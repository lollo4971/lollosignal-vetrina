"""Selezione a valore: le 6-10 partite pubblicate al posto delle dieci.

PERCHE' (19/09/2026, decisione dell'utente). Le dieci erano «prime per
livello poi orario»: nei giorni di coppa usciva la composizione peggiore
misurata (44,8% sull'1X2 contro il 61,9% dei campionati veri) e il valore
rispetto alle quote non contava nulla. Qui si ordina per uno score che
combina:

    score = W_EDGE·clip(edge_max) + W_LEGA·affidabilita
          + W_LEGG·leggibilita   + W_DATI·completezza

- edge_max: il migliore fra 1X2/GG/Over-Under 2.5, con probabilita' del
  MODELLO (1X2) e dello storico di lega (GG, O/U) contro la quota di
  riferimento dell'ultima fotografia (quote_prematch_storico: 1xBet,
  mediana come ripiego). Un mercato senza quota non concorre.
- affidabilita: calibrazione per lega dei pronostici gia' verificati
  (1 − |hit − prob dichiarata| sull'1X2), neutra 0,5 sotto N_MIN_LEGA.
- leggibilita: il punteggio adattivo esistente, normalizzato sul giorno.
- completezza: frazione dei dati disponibili, calcolata SOLO sui primi
  N_COMPLETEZZA candidati (per il resto neutra): su tutto l'universo
  costerebbe 150-300 chiamate al giorno.

ROLLBACK CON UNA VARIABILE: SELEZIONE_PUBBLICATA (env o default qui
sotto). Con "dieci" il bot pubblica come prima e la selezione a valore
resta calcolabile a mano. Le dieci e le sei restano comunque calcolate
ogni giorno come OMBRA e registrate in `selezioni_giorno`: il confronto
e' /confronto, mai la memoria.

COSTO: modello e quote gia' pagati (storico.db + fotografia 08:50);
in piu' ~40-80 chiamate/giorno per la completezza dei finalisti e le
schede AI delle ombre non sovrapposte (~4-7 Sonnet).

Test: test_selezione_valore.py.
"""
import logging
import os
import sqlite3
from datetime import datetime

# Nella vetrina i percorsi sono relativi al repository (in produzione: /opt/football-bot).
_RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


log = logging.getLogger(__name__)

DB = os.path.join(_RADICE, "signals.db")
STORICO = os.path.join(_RADICE, "storico.db")

# ── Parametri (tutti modificabili) ──────────────────────────────────────────
W_EDGE, W_LEGA, W_LEGG, W_DATI = 0.45, 0.25, 0.20, 0.10
# Tetto abbassato da 0.30 a 0.10 il 21/09/2026, dopo la prima giornata
# reale: l'edge MEDIO dichiarato era +33,2%, impossibile su mercati dove
# il banco tiene il 5-8%. Un edge cosi' non misura l'errore del banco, ma
# la distanza della NOSTRA stima dalla sua — e su quella distanza ha
# ragione quasi sempre lui (misura del 24/08: «cercare il massimo valore
# seleziona i propri errori»). Oltre il 10% non si compra piu' punteggio.
CLIP_EDGE = (-0.10, 0.10)
EDGE_PUBB = 0.03            # sotto, la partita esce «senza valore»
MIN_PUBB, MAX_PUBB = 6, 10
MAX_PER_FASCIA = 4          # per fascia oraria di ORE_FASCIA ore
ORE_FASCIA = 2
N_MIN_LEGA = 30             # sotto, affidabilita' neutra 0,5
N_COMPLETEZZA = 20          # completezza solo sui primi N per score
# Sotto questa probabilita' la scelta di valore non si gioca: il primo
# dry-run (19/09) proponeva «X al 16%, quota 7.65» — e' il «lift» gia'
# misurato morto il 07/09 (1,9% di centri, sei volte peggio di una
# costante): l'edge sui casi rari e' rumore amplificato, non valore.
# ALZATA da 0.25 a 0.40 il 21/09/2026: nella prima giornata reale SETTE
# scelte su dieci erano segni a quota 3,2-5,5, cioe' di nuovo quella
# zona. 2 centri su 10 (attesi 4,04) e resa −43%.
PROB_MIN_VALORE = 0.40
# L'interruttore del rollback: "valore" pubblica questa selezione,
# "dieci" torna al comportamento precedente. Niente altro da toccare.
SELEZIONE_PUBBLICATA = os.getenv("SELEZIONE_PUBBLICATA", "valore")

# Mappa nome→league_id per le righe storiche di prematch_predictions
# (la colonna league_id esiste dal 19/09/2026; prima c'era solo il nome).
LEGHE_NOME = {
    "Serie A": 135, "Serie B": 136, "Premier League": 39,
    "Championship": 40, "La Liga": 140, "Segunda": 141,
    "Ligue 1": 61, "Ligue 2": 62, "Bundesliga": 78,
    "2. Bundesliga": 79, "Eredivisie": 88, "Eerste Divisie": 89,
    "UEFA Champions League": 2, "UEFA Europa League": 3,
    "UEFA Europa Conference League": 848,
}


def clip(x, lo=CLIP_EDGE[0], hi=CLIP_EDGE[1]):
    return max(lo, min(hi, x))


def score_partita(edge, affidabilita, leggibilita, completezza):
    """La formula, coi pesi in testa al modulo.

    edge=None (nessuna quota) vale il PAVIMENTO del clip, non un neutro:
    senza quota il valore non e' dimostrabile, e una partita senza quote
    non deve battere una con un edge vero solo perche' il buio non
    penalizza."""
    e = clip(edge) if edge is not None else CLIP_EDGE[0]
    return (W_EDGE * e + W_LEGA * affidabilita
            + W_LEGG * leggibilita + W_DATI * completezza)


def edge_partita(mercati, quote_fix):
    """Il miglior valore fra i mercati candidati, o None senza quote.

    mercati: il dict di prematch_adattivo.mercati_partita (1x2 dal
    modello; over25/gg = tassi storici di lega, regola forma/livello).
    quote_fix: {(mercato, esito): quota} dall'ultima fotografia.
    UNDER e NG sono il complemento: P = 1 − P(OVER)/P(GG).
    """
    candidati = []
    p1 = mercati.get("1x2") or {}
    for segno in ("1", "X", "2"):
        p, q = p1.get(segno), quote_fix.get(("1X2", segno))
        if p and q:
            candidati.append((p * q - 1, "1X2", segno, p, q))
    po = mercati.get("over25")
    if po:
        q = quote_fix.get(("OVER25", "OVER"))
        if q:
            candidati.append((po * q - 1, "OVER25", "OVER", po, q))
        q = quote_fix.get(("OVER25", "UNDER"))
        if q:
            candidati.append(((1 - po) * q - 1, "OVER25", "UNDER", 1 - po, q))
    pg = mercati.get("gg")
    if pg:
        q = quote_fix.get(("GG", "GG"))
        if q:
            candidati.append((pg * q - 1, "GG", "GG", pg, q))
        q = quote_fix.get(("GG", "NG"))
        if q:
            candidati.append(((1 - pg) * q - 1, "GG", "NG", 1 - pg, q))
    candidati = [c for c in candidati if c[3] >= PROB_MIN_VALORE]
    if not candidati:
        return None
    edge, mercato, esito, prob, quota = max(candidati)
    return {"edge": edge, "mercato": mercato, "esito": esito,
            "prob": prob, "quota_rif": quota}


def esito_scelta(mercato, esito, score_ft):
    """VINTO/PERSO della scelta di valore dal punteggio finale."""
    try:
        h, a = (int(x) for x in score_ft.split("-"))
    except (AttributeError, ValueError):
        return None
    if mercato == "1X2":
        segno = "1" if h > a else ("2" if a > h else "X")
        return "VINTO" if esito == segno else "PERSO"
    if mercato == "OVER25":
        over = h + a >= 3
        return "VINTO" if (esito == "OVER") == over else "PERSO"
    if mercato == "GG":
        gg = h > 0 and a > 0
        return "VINTO" if (esito == "GG") == gg else "PERSO"
    return None


# ── Quote dall'ultima fotografia ────────────────────────────────────────────

def quote_del_giorno(db=DB):
    """{fixture_id: {(mercato, esito): quota}} dall'ULTIMA fotografia.

    Finestra a 2 giorni: la passata delle 23:55 fotografa domani, quella
    delle 08:50 rinfresca. Si tiene l'osservazione piu' recente per
    (fixture, mercato, esito) — stessa regola di sistema_x."""
    quote = {}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        righe = conn.execute(
            "SELECT fixture_id, mercato, esito, quota FROM "
            "quote_prematch_storico WHERE captured_at >= "
            "datetime('now', '-2 days') ORDER BY captured_at ASC").fetchall()
        conn.close()
        for fid, mercato, esito, q in righe:
            quote.setdefault(fid, {})[(mercato, esito)] = q
    except Exception as e:
        log.error(f"quote_del_giorno: {e}")
    return quote


# ── Affidabilita' per lega ──────────────────────────────────────────────────

def calcola_affidabilita(db=DB):
    """Calibrazione 1X2 per lega dai pronostici verificati; scrive la
    tabella affidabilita_lega e ritorna {league_id: score}.

    score = 1 − |hit_rate − prob_media_dichiarata|: premia chi mantiene
    quello che dichiara, non chi vince — la costante del progetto e' che
    la confidenza predice il winrate, e qui si misura proprio quanto.
    Le righe storiche senza league_id si mappano dal nome (LEGHE_NOME).
    """
    tab = {}
    try:
        conn = sqlite3.connect(db)
        casi = {}   # league_id -> [n, vinte, somma_prob]
        # league_id esiste solo dopo la migrazione del 19/09, e le righe
        # storiche restano NULL per sempre: senza colonna si legge il solo
        # nome e si mappa con LEGHE_NOME (primo dry-run: tabella mai nata
        # perche' la SELECT esplodeva prima della CREATE).
        try:
            righe = conn.execute(
                "SELECT league_id, league, ft_1x2_conf, esito_1x2 "
                "FROM prematch_predictions "
                "WHERE esito_1x2 IN ('VINTO','PERSO') "
                "AND ft_1x2_conf IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            righe = [(None, lega, conf, esito) for lega, conf, esito in
                     conn.execute(
                         "SELECT league, ft_1x2_conf, esito_1x2 "
                         "FROM prematch_predictions "
                         "WHERE esito_1x2 IN ('VINTO','PERSO') "
                         "AND ft_1x2_conf IS NOT NULL")]
        for lid, lega, conf, esito in righe:
            if lid is None:
                lid = next((v for nome, v in LEGHE_NOME.items()
                            if nome in (lega or "")), None)
            if lid is None:
                continue
            c = casi.setdefault(lid, [0, 0, 0.0])
            c[0] += 1
            c[1] += (esito == "VINTO")
            c[2] += conf / 100.0
        conn.execute(
            "CREATE TABLE IF NOT EXISTS affidabilita_lega("
            "league_id INTEGER PRIMARY KEY, n INTEGER, hit_rate REAL, "
            "prob_media REAL, score REAL, aggiornato TEXT)")
        for lid, (n, vinte, somma_p) in casi.items():
            if n < N_MIN_LEGA:
                continue
            hit, prob = vinte / n, somma_p / n
            score = max(0.0, min(1.0, 1.0 - abs(hit - prob)))
            tab[lid] = score
            conn.execute(
                "INSERT OR REPLACE INTO affidabilita_lega VALUES(?,?,?,?,?,?)",
                (lid, n, hit, prob, score,
                 datetime.now().strftime("%Y-%m-%d %H:%M")))
        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"calcola_affidabilita: {e}")
    return tab


def affidabilita_di(league_id, tab):
    return tab.get(league_id, 0.5)


# ── Completezza dati (solo finalisti) ───────────────────────────────────────

def completezza_da_dati(pdata, quote_fix):
    """Frazione dei sei blocchi di dati disponibili."""
    campi = [bool((pdata or {}).get("home_form")),
             bool((pdata or {}).get("away_form")),
             bool((pdata or {}).get("prematch_odds")),
             ("1X2", "1") in quote_fix,
             ("OVER25", "OVER") in quote_fix,
             ("GG", "GG") in quote_fix]
    return sum(campi) / len(campi)


# ── Selezione ───────────────────────────────────────────────────────────────

def seleziona(candidati):
    """Dai candidati arricchiti (score, edge, ora_locale) alle scelte.

    1) per score, tutte quelle con edge >= EDGE_PUBB, fino a MAX_PUBB;
    2) se meno di MIN_PUBB, si completa con le migliori per score,
       marcate senza_valore;
    3) mai piu' di MAX_PER_FASCIA per fascia di ORE_FASCIA ore: le
       eccedenti scalano alla successiva in classifica;
    4) l'elenco finale torna in ordine di orario, come si legge.
    """
    ordinati = sorted(candidati, key=lambda c: -c["score"])
    presi, per_fascia = [], {}

    def _fascia(c):
        try:
            return int(c["ora_locale"][:2]) // ORE_FASCIA
        except (TypeError, ValueError):
            return -1

    def _riempi(filtro, tetto, rispetta_fascia=True):
        for c in ordinati:
            if len(presi) >= tetto:
                return
            if c in presi or not filtro(c):
                continue
            f = _fascia(c)
            if rispetta_fascia and per_fascia.get(f, 0) >= MAX_PER_FASCIA:
                continue
            presi.append(c)
            per_fascia[f] = per_fascia.get(f, 0) + 1

    con_valore = lambda c: c.get("edge") is not None and c["edge"] >= EDGE_PUBB
    _riempi(con_valore, MAX_PUBB)
    if len(presi) < MIN_PUBB:
        # Il PAVIMENTO vince sul tetto di fascia (21/09/2026): quel giorno
        # le uniche sei partite disponibili erano tutte alle 20:30 e ne
        # sono uscite QUATTRO, perche' il tetto bloccava il riempimento.
        # La deroga vale solo qui, per arrivare al minimo: la prima
        # passata rispetta le fasce, altrimenti la vetrina tornerebbe
        # tutta di sera — il difetto misurato sulla terza slide il 03/09.
        _riempi(lambda c: True, MIN_PUBB, rispetta_fascia=False)
    for c in presi:
        c["senza_valore"] = not con_valore(c)
    presi.sort(key=lambda c: c["ora_locale"])
    return presi


def riga_valore(c):
    """La riga 💰 della scheda pubblicata."""
    if c.get("senza_valore"):
        return "💰 Valore: nessuno alle quote attuali"
    qmin = (1 + EDGE_PUBB) / c["prob"] if c.get("prob") else 0
    return (f"💰 Valore: {c['mercato']} {c['esito_scelto']} · "
            f"prob {c['prob']:.0%} · quota rif {c['quota_rif']:.2f} · "
            f"edge {c['edge']:+.0%} · quota minima {qmin:.2f}")


# ── Il giro completo del mattino ────────────────────────────────────────────

def candidate_senza_modello(fixtures, con_modello):
    """Le partite che il modello non sa stimare, come candidate comunque.

    PERCHE' (22/09/2026, richiesta dell'utente sulle nazionali UEFA).
    `candidate_del_giorno` tiene solo le leghe con un modello, e
    `parametri_lega` ne chiede 400 partite di storico: la Nations League
    ne ha 343, le qualificazioni 200, l'Europeo 46. Nel periodo delle
    nazionali quelle sono le UNICHE partite in campo (104 fra il 24/09 e
    il 20/10), e la selezione sarebbe uscita vuota.

    Entrano senza stima: niente edge (la riga del valore dira' «nessuno»,
    non un numero inventato) e leggibilita' neutra, mentre affidabilita'
    di lega e completezza dei dati lavorano normalmente. Restano sotto
    una partita con modello, ed e' corretto — su di loro sappiamo meno.

    Non solleva su una fixture malformata: la salta e basta.
    """
    from zoneinfo import ZoneInfo
    fuori = []
    for f in fixtures:
        try:
            fid = f["fixture"]["id"]
            if fid in con_modello:
                continue
            try:
                kick = datetime.fromisoformat(
                    f["fixture"]["date"].replace("Z", "+00:00"))
                ora = kick.astimezone(ZoneInfo("Europe/Rome")).strftime("%H:%M")
            except Exception:
                ora = f["fixture"]["date"][11:16]
            fuori.append({
                "fixture_id": fid,
                "league_id": f["league"]["id"],
                "data": f["fixture"]["date"][:10],
                "lega": f["league"]["name"],
                "casa": f["teams"]["home"]["name"],
                "ospite": f["teams"]["away"]["name"],
                "ora": ora,
                "mercati": {},
                "punteggio": None,
                "senza_modello": True,
            })
        except Exception:
            continue
    return fuori


def selezione_del_giorno(fixtures, path_storico=STORICO, db=DB,
                         headers=None):
    """Dalle fixture del giorno alle scelte pubblicabili.

    Ritorna [{fixture, fixture_id, home, away, league_id, ora_locale,
    score, edge, mercato, esito_scelto, prob, quota_rif, senza_valore,
    leggibilita, completezza}]. Vuota se qualcosa di grosso manca
    (fotografia quote assente, storico rotto): il chiamante DEVE avere
    un ripiego — la pubblicazione del mattino non puo' saltare.
    """
    from zoneinfo import ZoneInfo
    from prematch_adattivo import candidate_del_giorno

    # SCUDO ANTI-TEST (lezione delle 44 mail del 15/09): decine di test
    # pilotano send_daily_header con partite finte, ma questo giro legge
    # e SCRIVE il signals.db vero (affidabilita_lega). Sotto unittest e
    # senza un db esplicito si esce a vuoto: il chiamante ripiega sulle
    # dieci, che e' cio' che quei test esercitano.
    import sys as _sys
    if "unittest" in _sys.modules and db == DB:
        return []

    per_fid = {f["fixture"]["id"]: f for f in fixtures}
    cands = candidate_del_giorno(fixtures, path_storico)
    # Le partite che il modello non sa stimare entrano comunque
    # (22/09/2026, nazionali UEFA): senza stima, non senza analisi.
    senza = candidate_senza_modello(fixtures, {c["fixture_id"] for c in cands})
    if senza:
        log.info(f"selezione_valore: {len(senza)} candidate senza modello "
                 f"(leghe fuori dallo storico o sotto la soglia)")
    cands = cands + senza
    if not cands:
        log.warning("selezione_valore: zero candidati")
        return []
    quote = quote_del_giorno(db)
    aff = calcola_affidabilita(db)

    scarti = {"senza_quote_1x2": 0}
    punteggi = [c["punteggio"] for c in cands if c.get("punteggio") is not None]
    p_min, p_max = (min(punteggi), max(punteggi)) if punteggi else (0.0, 0.0)

    arricchiti = []
    for c in cands:
        fid = c["fixture_id"]
        qf = quote.get(fid, {})
        if ("1X2", "1") not in qf:
            scarti["senza_quote_1x2"] += 1
            continue
        e = edge_partita(c["mercati"], qf)
        f = per_fid.get(fid)
        try:
            kick = datetime.fromisoformat(
                f["fixture"]["date"].replace("Z", "+00:00"))
            ora_locale = kick.astimezone(ZoneInfo("Europe/Rome")).strftime("%H:%M")
        except Exception:
            ora_locale = c.get("ora") or "00:00"
        # Senza modello non c'e' un punteggio di leggibilita': vale il
        # neutro, cosi' la partita non viene ne' premiata ne' punita da
        # una grandezza che su di lei non esiste.
        legg = 0.5 if c.get("punteggio") is None else (
            (c["punteggio"] - p_min) / (p_max - p_min)
            if p_max > p_min else 0.5)
        riga = {
            "fixture": f, "fixture_id": fid,
            "home": c["casa"], "away": c["ospite"],
            "league_id": c["league_id"], "ora_locale": ora_locale,
            "leggibilita": legg, "completezza": 0.5,
            "quote_fix": qf,
            "affidabilita": affidabilita_di(c["league_id"], aff),
        }
        if e:
            riga.update(edge=e["edge"], mercato=e["mercato"],
                        esito_scelto=e["esito"], prob=e["prob"],
                        quota_rif=e["quota_rif"])
        else:
            riga.update(edge=None, mercato=None, esito_scelto=None,
                        prob=None, quota_rif=None)
        riga["score"] = score_partita(riga["edge"], riga["affidabilita"],
                                      legg, riga["completezza"])
        arricchiti.append(riga)

    log.info(f"selezione_valore: {len(arricchiti)} candidati, "
             f"scartati {scarti['senza_quote_1x2']} senza quote 1X2 "
             f"su {len(cands)} col modello")
    if not arricchiti:
        return []

    # Completezza vera solo sui primi N per score: sul resto e' neutra.
    if headers:
        migliori = sorted(arricchiti, key=lambda c: -c["score"])[:N_COMPLETEZZA]
        for c in migliori:
            try:
                import match_data as mdata
                f = c["fixture"]
                pdata = mdata.collect_prematch_data_cached(
                    c["fixture_id"], f["teams"]["home"]["id"],
                    f["teams"]["away"]["id"], c["league_id"],
                    f["league"].get("season", 2025), headers)
                c["completezza"] = completezza_da_dati(pdata, c["quote_fix"])
            except Exception as e:
                log.warning(f"completezza {c['fixture_id']}: {e}")
            c["score"] = score_partita(c["edge"], c["affidabilita"],
                                       c["leggibilita"], c["completezza"])

    return seleziona(arricchiti)


# ── Registro e confronto ────────────────────────────────────────────────────

def _init_registro(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS selezioni_giorno(
        data TEXT NOT NULL, origine TEXT NOT NULL,
        fixture_id INTEGER NOT NULL, posizione INTEGER,
        home TEXT, away TEXT, league_id INTEGER,
        edge REAL, mercato TEXT, esito_scelto TEXT, prob REAL,
        quota_rif REAL, quota_minima REAL, score REAL,
        senza_valore INTEGER,
        PRIMARY KEY(data, origine, fixture_id))""")


def registra_selezioni(data, origine, righe, db=DB):
    """Scrive l'appartenenza di un set del giorno (valore/dieci/sei).

    E' il registro che rende possibile /confronto: gruppi_pronostico ha
    fixture_id come PRIMARY KEY e non puo' tenere la stessa partita sotto
    due origini — la lezione della sovrapposizione sei∩dieci ricostruita
    dall'export Telegram. Non solleva mai."""
    try:
        conn = sqlite3.connect(db)
        try:
            _init_registro(conn)
            for pos, c in enumerate(righe, start=1):
                prob = c.get("prob")
                qmin = (1 + EDGE_PUBB) / prob if prob else None
                conn.execute(
                    "INSERT OR REPLACE INTO selezioni_giorno "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (data, origine, c["fixture_id"], pos,
                     c.get("home"), c.get("away"), c.get("league_id"),
                     c.get("edge"), c.get("mercato"), c.get("esito_scelto"),
                     prob, c.get("quota_rif"), qmin, c.get("score"),
                     1 if c.get("senza_valore") else 0))
            conn.commit()
            return len(righe)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"registra_selezioni {origine}: {e}")
        return 0


def confronto(giorni=30, db=DB):
    """Il testo del confronto fra le origini, per l'admin.

    Esiti dal DB gia' verificato (prematch_predictions): 1X2 dell'AI per
    tutte le origini; per 'valore' anche il mercato scelto, ricalcolato
    dal risultato reale, e il ROI simulato a 1 € sulla quota di
    riferimento. Zero chiamate API."""
    r = [f"📊 *CONFRONTO SELEZIONI — ultimi {giorni} giorni*"]
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        origini = [x[0] for x in conn.execute(
            "SELECT DISTINCT origine FROM selezioni_giorno "
            "WHERE data >= date('now', ?)", (f"-{giorni} days",))]
        for origine in sorted(origini):
            righe = conn.execute(
                "SELECT s.mercato, s.esito_scelto, s.prob, s.quota_rif, "
                "p.esito_1x2, p.risultato_reale, p.ft_1x2_conf "
                "FROM selezioni_giorno s "
                "LEFT JOIN prematch_predictions p "
                "ON p.fixture_id = s.fixture_id "
                "WHERE s.data >= date('now', ?) AND s.origine = ?",
                (f"-{giorni} days", origine)).fetchall()
            verificate = [x for x in righe if x[4] in ("VINTO", "PERSO")]
            n = len(verificate)
            etichetta = origine if origine == "valore" else f"{origine} (ombra)"
            if not n:
                r.append(f"\n*{etichetta}*: nessuna partita verificata")
                continue
            v1 = sum(1 for x in verificate if x[4] == "VINTO")
            conf_media = (sum(x[6] or 0 for x in verificate) / n) / 100.0
            r.append(f"\n*{etichetta}* — {n} partite")
            r.append(f"  1X2 {v1 / n:.0%} ({v1}/{n}) · "
                     f"dichiarato {conf_media:.0%}")
            con_mercato = [x for x in verificate if x[0] and x[5]]
            if con_mercato:
                vinte, roi = 0, 0.0
                for mercato, esito, prob, quota, _, reale, _ in con_mercato:
                    e = esito_scelta(mercato, esito, reale)
                    if e == "VINTO":
                        vinte += 1
                        roi += (quota or 1) - 1
                    elif e == "PERSO":
                        roi -= 1
                nm = len(con_mercato)
                r.append(f"  mercato di valore {vinte / nm:.0%} "
                         f"({vinte}/{nm}) · ROI {roi / nm:+.0%} "
                         f"a 1 € sulla quota rif")
        conn.close()
    except Exception as e:
        r.append(f"(confronto non calcolabile: {e})")
    return "\n".join(r)


# ── CLI: dry-run ────────────────────────────────────────────────────────────

def _dry_run(data_str=None):
    import requests
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_RADICE, ".env"))
    from bot import LEAGUE_LEVEL_1, LEAGUE_LEVEL_2   # solo da CLI, mai a import

    if data_str is None:
        data_str = datetime.now().strftime("%Y-%m-%d")
    H = {"x-rapidapi-key": os.getenv("API_FOOTBALL_KEY"),
         "x-rapidapi-host": "v3.football.api-sports.io"}
    js = requests.get("https://v3.football.api-sports.io/fixtures",
                      params={"date": data_str}, headers=H, timeout=30).json()
    livelli = LEAGUE_LEVEL_1 | LEAGUE_LEVEL_2
    universo = [f for f in (js.get("response") or [])
                if f["league"]["id"] in livelli
                and f["fixture"]["status"]["short"] in ("NS", "TBD")]
    print(f"{data_str}: {len(universo)} partite in whitelist da giocare")
    scelte = selezione_del_giorno(universo, headers=H)
    if not scelte:
        print("NESSUNA SCELTA (fotografia quote assente? storico rotto?) "
              "— il bot ripiegherebbe sulle dieci cronologiche")
        return
    print(f"\nSELEZIONE A VALORE — {len(scelte)} partite:")
    for c in scelte:
        print(f"  {c['ora_locale']}  {c['home']} - {c['away']}  "
              f"[lega {c['league_id']}]")
        print(f"         score {c['score']:.3f} · aff {c['affidabilita']:.2f}"
              f" · legg {c['leggibilita']:.2f} · dati {c['completezza']:.2f}")
        print(f"         {riga_valore(c)}")


if __name__ == "__main__":
    import sys
    if "--dry-run" in sys.argv:
        d = None
        if "--data" in sys.argv:
            d = sys.argv[sys.argv.index("--data") + 1]
        _dry_run(d)
    else:
        print("uso: python3 -m selezione_valore --oggi --dry-run "
              "[--data YYYY-MM-DD]")
