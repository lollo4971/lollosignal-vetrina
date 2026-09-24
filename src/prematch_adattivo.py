"""Selezione adattiva delle partite prematch e calcolo dei sette mercati.

REGOLA DI PROGETTO, dalle misure del 19/08/2026 su 59.901 partite:
il modello statistico per i mercati di FORMA (chi vince, quale punteggio,
anche nel primo tempo: batte la climatologia di lega), lo storico di lega
per quelli di LIVELLO (quanti gol: Over 2.5 t=+3,93, GG t=+4,06 e Over di
primo tempo, dove il modello e' misurato PEGGIO della semplice media).
Usare il modello sui totali peggiorerebbe i pronostici.
"""
import logging
import sqlite3
from collections import Counter

log = logging.getLogger(__name__)

_cache_tassi = {}

SOGLIA_MINIMA = 200  # sotto, il tasso e' troppo rumoroso per essere pubblicato


def tassi_lega(path, league_id):
    """Tassi storici di una lega: quanti gol, non quale risultato.

    league_id=None calcola i tassi GLOBALI su tutto l'archivio.

    None se la lega ha meno di SOGLIA_MINIMA partite o l'archivio non e'
    leggibile. Il docstring lo prometteva dalla Task 1 ma il controllo
    mancava: aggiunto il 19/08/2026, prima avrebbe pubblicato un
    over25 calcolato anche su un pugno di partite.
    """
    chiave = (path, league_id)
    if chiave in _cache_tassi:
        return _cache_tassi[chiave]
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        log.error(f"tassi_lega: archivio non leggibile: {e}")
        return None
    try:
        if league_id is None:
            # None = tassi globali su tutto l'archivio (usati come termine
            # di paragone da impronta_lega quando manca altro).
            righe = conn.execute(
                "SELECT ft_home, ft_away, ht_home, ht_away FROM partite").fetchall()
        else:
            righe = conn.execute(
                "SELECT ft_home, ft_away, ht_home, ht_away FROM partite "
                "WHERE league_id=?", (league_id,)).fetchall()
    except sqlite3.Error as e:
        log.error(f"tassi_lega {league_id}: {e}")
        return None
    finally:
        conn.close()

    if not righe or len(righe) < SOGLIA_MINIMA:
        _cache_tassi[chiave] = None
        return None

    n = len(righe)
    over = sum(1 for fh, fa, _, _ in righe if fh + fa > 2.5)
    gg = sum(1 for fh, fa, _, _ in righe if fh >= 1 and fa >= 1)
    gol = sum(fh + fa for fh, fa, _, _ in righe)

    conht = [(hh, ha) for _, _, hh, ha in righe if hh is not None and ha is not None]
    n_ht = len(conht)
    ht05 = sum(1 for hh, ha in conht if hh + ha > 0.5) / n_ht if n_ht else 0.0
    ht15 = sum(1 for hh, ha in conht if hh + ha > 1.5) / n_ht if n_ht else 0.0

    conta = Counter(f"{fh}-{fa}" for fh, fa, _, _ in righe)
    top5 = [(r, c / n) for r, c in conta.most_common(5)]

    ris = {"over25": over / n, "gg": gg / n, "ht_over05": ht05,
           "ht_over15": ht15, "n": n, "top5": top5, "gol_medi": gol / n}
    _cache_tassi[chiave] = ris
    return ris


from modello_storico import (  # noqa: E402
    lambde, matrice_primo_tempo, matrice_punteggi, prob_1x2, prob_gg, prob_over,
)

_DOPPIE = {"1X": ("1", "X"), "12": ("1", "2"), "X2": ("X", "2")}


def _esito(x, y):
    return "1" if x > y else ("2" if y > x else "X")


def _matrice_secondo_tempo(lam_h, lam_a, quota_pt, rho):
    """La matrice dei gol del secondo tempo usata dalla congiunta HT/FT:
    i lambda pieni scalati sulla quota di gol NON ANCORA GIOCATA al 45'
    (1 - quota_pt, il "resto").

    Isolata in una funzione propria perche' un test che verificasse solo
    l'output finale di `prob_dc_ht_ft` non distingueva questa formula da
    'resto = quota_pt': entrambe le versioni ricadevano dentro la
    tolleranza del test (misurato il 19/08/2026 in code review — vedi
    test_gol_attesi_secondo_tempo_su_1_meno_quota_pt). Qui si puo'
    verificare direttamente che i gol attesi valgano
    (lam_h + lam_a) * (1 - quota_pt), non un suo effetto indiretto.
    """
    resto = max(0.0, 1.0 - quota_pt)
    return matrice_punteggi(lam_h * resto, lam_a * resto, rho, max_gol=6)


def prob_dc_ht_ft(mat_ht, lam_h, lam_a, quota_pt, rho):
    """Congiunta fra doppia chance all'intervallo ed esito finale.

    Si combina il punteggio al 45' con i gol del secondo tempo, questi
    ultimi con intensita' pari alla quota di gol non ancora giocata.

    APPROSSIMAZIONE DICHIARATA: si assume che i gol del secondo tempo non
    dipendano dal parziale. Non e' vero — chi conduce all'intervallo cambia
    atteggiamento — ed e' lo stesso limite gia' documentato per
    matrice_da_minuto. Va tenuto presente leggendo questi numeri.
    """
    mat_2t = _matrice_secondo_tempo(lam_h, lam_a, quota_pt, rho)
    out = {f"{d}/{e}": 0.0 for d in _DOPPIE for e in ("1", "X", "2")}
    for (h1, a1), p1 in mat_ht.items():
        if p1 <= 0:
            continue
        e_ht = _esito(h1, a1)
        doppie = [d for d, membri in _DOPPIE.items() if e_ht in membri]
        for (dh, da), p2 in mat_2t.items():
            if p2 <= 0:
                continue
            e_ft = _esito(h1 + dh, a1 + da)
            for d in doppie:
                out[f"{d}/{e_ft}"] += p1 * p2
    return out


SOGLIA_VINCOLO_HT = 0.90  # sopra, il primo tempo non sta restringendo niente


def _dc_ht_ft_informative(dc, p1x2):
    """Le doppie chance 1°T + finale che restringono davvero l'esito.

    STORIA (19/08/2026): il primo criterio confrontava la probabilita'
    della combinata con la secca sullo stesso esito e la scartava se non
    la superava di 5 punti. Era impossibile per costruzione: la combinata
    e' l'intersezione con un evento di primo tempo, quindi
    P(DC ∩ esito) <= P(esito) SEMPRE (identita' di probabilita', mai il
    contrario) — il filtro scartava tutto, sempre, su ogni partita.

    Criterio corretto: non "quanto vale" ma "quanto RESTRINGE". Il
    rapporto P(DC ∩ esito) / P(esito) e' la frazione delle volte in cui,
    quando esce quell'esito finale, e' successo anche quello scenario di
    primo tempo. Vicino a 1 = il primo tempo non aggiunge informazione
    (quello scenario capita quasi sempre insieme a quell'esito comunque);
    si scarta sopra SOGLIA_VINCOLO_HT. Fra le tre doppie chance (1X, 12,
    X2) che possono accompagnare lo stesso esito finale se ne tiene una
    sola, la piu' probabile — le altre due sono varianti dello stesso
    scenario. Al massimo due righe in tutto, su esiti finali diversi.

    Ritorna una lista di (etichetta, probabilita, rapporto).
    """
    migliore_per_esito = {}
    for etichetta, p in dc.items():
        esito = etichetta.split("/")[1]
        attuale = migliore_per_esito.get(esito)
        if attuale is None or p > attuale[1]:
            migliore_per_esito[esito] = (etichetta, p)

    informative = []
    for esito, (etichetta, p) in migliore_per_esito.items():
        secco = p1x2.get(esito, 0.0)
        rapporto = p / secco if secco > 0 else 1.0
        if rapporto <= SOGLIA_VINCOLO_HT:
            informative.append((etichetta, p, rapporto))

    informative.sort(key=lambda t: -t[1])
    return informative[:2]


# ─── Gruppi «Ris.Esatto MultiEsiti 4» ────────────────────────────────────────
# La partizione del bookmaker (Planetwin365), letta da schermate reali e
# verificata identica su sette partite: sette gruppi che coprono TUTTI i
# punteggi possibili, ognuno con una quota unica, una posta sola invece di
# quattro schedine separate.
#
# Sommare le celle della matrice del modello e' aritmetica su un numero gia'
# calcolato: costo zero, nessuna chiamata in piu'.
#
# Il margine del banco misurato il 21/08/2026 su prezzi veri e' del 21,6%
# (stabile fra 20,5% e 22,9%) ma distribuito in modo MOLTO disuguale fra i
# gruppi: 12,5% su «casa di misura», 18,8% su «ospite di misura», 22,1% su
# «pochi gol», fino al 59,5% di «casa 4+» e all'84,6% di «ospite 4+». I due
# «di misura» sono gli unici dove il margine lascia spazio: e' l'unica cosa
# che rende la riga azionabile invece che decorativa, quindi il messaggio la
# segnala. Il nostro modello stima i gruppi meglio del mercato (log loss
# 1,5324 contro 1,5630) ma il vantaggio NON copre il margine medio.
GRUPPI = (
    ("pochi gol",        ("0-0", "1-1", "0-1", "1-0")),
    ("casa di misura",   ("2-0", "2-1", "3-0", "3-1")),
    ("ospite di misura", ("0-2", "1-2", "0-3", "1-3")),
    ("pari alti",        ("2-2", "2-3", "3-2", "3-3")),
    ("casa 4+",          ("4-0", "4-1", "4-2", "4-3")),
    ("ospite 4+",        ("0-4", "1-4", "2-4", "3-4")),
)
ALTRO = "altro"   # il settimo: 4-4 e qualunque punteggio piu' alto
GRUPPI_DI_MISURA = ("casa di misura", "ospite di misura")

_DA_PUNTEGGIO = {ris: et for et, membri in GRUPPI for ris in membri}

# Come li scrive la lavagna di Planetwin365. NON il trattino: i punteggi ne
# contengono gia' uno e "2-0 - 2-1 - 3-0 - 3-1" e' illeggibile.
SEPARATORE_PUNTEGGI = " / "
_ALTRO_STAMPATO = "4-4 e oltre"


def punteggi_gruppo(etichetta):
    """I quattro punteggi del gruppo, come si stampano.

    L'etichetta («casa di misura») resta il nome INTERNO: e' la chiave del
    registro `gruppi_pronostico` e non cambia. Quello che l'abbonato legge
    sono i punteggi, perche' con «casa di misura» non ci si gioca niente:
    sulla lavagna del bookmaker il gruppo e' identificato dai punteggi.

    Per il settimo gruppo (ALTRO) i quattro punteggi non esistono — e' un
    residuo aperto — e si dichiara com'e' fatto.
    """
    for et, membri in GRUPPI:
        if et == etichetta:
            return SEPARATORE_PUNTEGGI.join(membri)
    return _ALTRO_STAMPATO if etichetta == ALTRO else ""


def gruppo_di(punteggio):
    """L'etichetta del gruppo che contiene quel punteggio.

    Tutto cio' che non e' esplicitamente elencato finisce in ALTRO: e' il
    settimo gruppo del banco («4-4 / ALTRO»), quindi la partizione e'
    completa per costruzione e nessun punteggio, per quanto assurdo, resta
    senza gruppo.

    Accetta sia "2-1" (forma del DB) sia "2:1" (forma dell'API odds): la
    stessa asimmetria che aveva gia' morso su exact_score_odds.
    """
    return _DA_PUNTEGGIO.get((punteggio or "").strip().replace(":", "-"), ALTRO)


def prob_gruppi(matrice):
    """Probabilita' di ogni gruppo: la somma delle sue celle."""
    out = {et: 0.0 for et, _ in GRUPPI}
    out[ALTRO] = 0.0
    for (h, a), p in matrice.items():
        out[gruppo_di(f"{h}-{a}")] += p
    return out


def gruppi_top(matrice, n=2):
    """I primi n gruppi per probabilita', dal piu' probabile in giu'.

    Due e non uno: il secondo gruppo sta spesso intorno al 25% e serve a
    capire quanto e' netta la scelta.
    """
    return sorted(prob_gruppi(matrice).items(), key=lambda kv: -kv[1])[:n]


def mercati_partita(par, rho, quota_pt, home_id, away_id, tassi):
    """I sette mercati di una partita.

    Forma dal modello, livello dallo storico: vedi la regola in testa al
    modulo. Ma la regola va applicata per GRANDEZZA (Over 2.5, GG, gol del
    1°T dallo storico; tutto il resto dal modello), non per riga: usare i
    lambda grezzi del modello per costruire le matrici di risultato esatto
    farebbe trapelare dentro quelle righe il livello-gol del modello, che
    e' proprio cio' che la regola voleva escludere (bug misurato il
    19/08/2026: 'Over 0.5 primo tempo' storico al 69,9% contro 'Risultato
    1°T 0-0' del modello al 26,5%, due numeri sulla stessa grandezza che
    si contraddicevano fino a 30 punti su altre partite).

    Soluzione: i lambda del modello vengono riscalati sul livello di gol
    della lega (tassi['gol_medi']) PRIMA di costruire qualunque matrice.
    Il rapporto lam_h/lam_a — la FORMA, cio' che il modello sa fare bene —
    resta quello del modello; la somma lam_h+lam_a — il LIVELLO — diventa
    quella storica di lega. Un'unica fonte di livello, non una per riga.
    """
    lam_h, lam_a = lambde(par, home_id, away_id)
    attesi = lam_h + lam_a
    k = tassi["gol_medi"] / attesi if attesi > 0 else 1.0
    lam_h, lam_a = lam_h * k, lam_a * k

    mat_ft = matrice_punteggi(lam_h, lam_a, rho)
    mat_ht = matrice_primo_tempo(lam_h, lam_a, quota_pt, rho)

    p1x2 = prob_1x2(mat_ft)
    esatto_ft = sorted(mat_ft.items(), key=lambda kv: -kv[1])[:3]
    esatto_ht = sorted(mat_ht.items(), key=lambda kv: -kv[1])[:2]
    dc = prob_dc_ht_ft(mat_ht, lam_h, lam_a, quota_pt, rho)
    dc_top = _dc_ht_ft_informative(dc, p1x2)

    return {
        "1x2": p1x2,
        "esatto_ft": [(f"{h}-{a}", p) for (h, a), p in esatto_ft],
        "over25": tassi["over25"],
        "gg": tassi["gg"],
        "ht_over05": tassi["ht_over05"],
        "ht_over15": tassi["ht_over15"],
        "esatto_ht": [(f"{h}-{a}", p) for (h, a), p in esatto_ht],
        "dc_ht_ft": dc_top,
        "gruppi": gruppi_top(mat_ft),
        "_matrice_ft": mat_ft,
        "_matrice_ht": mat_ht,
        "_lambda": (lam_h, lam_a),
    }


_cache_parametri = {}

MINIMO_PARTITE_LEGA = 400   # sotto, lo stimatore non ha di che convergere


def parametri_lega(path, league_id):
    """(parametri, rho, quota_gol_1ºT) della lega, o None se non si puo'.

    None — cioe' "su questa lega non si pronostica" — nei tre casi in cui il
    modello e' misurato peggio del non fare niente o non e' stimabile:
    coppa a eliminazione (`e_coppa`, criterio della mediana presenze per
    squadra, non una lista di id), archivio troppo corto
    (< MINIMO_PARTITE_LEGA), archivio non leggibile.

    Estratta il 21/08/2026 dal corpo di `costruisci_selezione`, che era
    l'unico posto dove esisteva: adesso la stessa stima serve anche la riga
    dei pronostici agli abbonati. La cache e' per processo e per lega —
    `stima_parametri` gira 60 iterazioni su migliaia di partite, e le dieci
    del batch delle 09:00 pescano da poche leghe: senza cache si
    rifarebbe lo stesso conto dieci volte.
    """
    from modello_storico import (quota_gol_primo_tempo, stima_parametri,
                                 stima_rho)
    from storico_db import leggi_partite
    from valida_modello import e_coppa

    chiave = (path, league_id)
    if chiave in _cache_parametri:
        return _cache_parametri[chiave]
    try:
        storiche = leggi_partite(path, league_id)
    except sqlite3.Error as e:
        log.error(f"parametri_lega {league_id}: archivio non leggibile: {e}")
        return None
    if len(storiche) < MINIMO_PARTITE_LEGA or e_coppa(storiche):
        _cache_parametri[chiave] = None
        return None
    par = stima_parametri(storiche)
    ris = (par, stima_rho(storiche[-MINIMO_PARTITE_LEGA:], par),
           quota_gol_primo_tempo(storiche))
    _cache_parametri[chiave] = ris
    return ris


def _mercati_di_partita(path, league_id, home_id, away_id):
    """I mercati del modello per una partita qualunque, o None.

    None quando la lega non e' pronosticabile (coppa, archivio corto) o una
    delle due squadre non e' nell'archivio: `lambde` la tratterebbe come
    una squadra media, e un pronostico inventato e' peggio di nessun
    pronostico. Non solleva: chi la chiama sta componendo un messaggio.
    """
    try:
        tassi = tassi_lega(path, league_id)
        if not tassi or tassi["n"] < MINIMO_PARTITE_LEGA:
            return None
        p = parametri_lega(path, league_id)
        if not p:
            return None
        par, rho, qpt = p
        if home_id not in par["attacco"] or away_id not in par["attacco"]:
            return None
        return mercati_partita(par, rho, qpt, home_id, away_id, tassi)
    except Exception as e:
        log.error(f"mercati_di_partita {league_id} {home_id}-{away_id}: {e}")
        return None


def gruppi_partita(path, league_id, home_id, away_id):
    """I due gruppi piu' probabili di una partita qualunque, o None.

    Stessi None di `_mercati_di_partita`. Non solleva.
    """
    m = _mercati_di_partita(path, league_id, home_id, away_id)
    return m["gruppi"] if m else None


def prob_gruppi_partita(path, league_id, home_id, away_id):
    """La probabilita' di TUTTI e sette i gruppi, come dizionario, o None.

    Serve alla scheda degli abbonati, che dal 21/08/2026 non mostra il
    gruppo piu' probabile ma quello che CONTIENE il risultato esatto gia'
    stampato nella riga sopra: quel gruppo puo' essere il terzo o il quarto
    del modello (misurato su 499 pronostici: primo o secondo nell'83% dei
    casi, terzo nel 12%, quarto nel 4,6%), quindi i primi due non bastano.

    La probabilita' che si stampa resta quella VERA di quel gruppo: si
    sceglie per coerenza, non si riscala niente. Stessi None di
    `_mercati_di_partita`. Non solleva.
    """
    m = _mercati_di_partita(path, league_id, home_id, away_id)
    return prob_gruppi(m["_matrice_ft"]) if m else None


# Pesi della spec. Ogni componente ha un fondamento misurato: vedi
# docs/superpowers/specs/2026-08-19-prematch-adattivo-design.md
# 'mese' e' stato tolto il 19/08/2026: tutte le partite di una giornata
# hanno lo stesso mese, quindi non discriminava nulla nella selezione fra
# partite (era 0,08 di budget speso per un no-op). fattore_mese resta nel
# modulo, non usato qui, per un eventuale uso futuro come soglia assoluta.
PESI = {"concentrazione": 0.40, "coerenza": 0.33, "impronta": 0.15,
        "serie_over": 0.12}

# Gol per partita misurati per mese su 59.901 partite (2021-2025).
# Agosto 2,93 contro marzo 2,59: quasi otto punti di escursione che il bot
# oggi ignora del tutto.
_GOL_MESE = {1: 2.64, 2: 2.63, 3: 2.59, 4: 2.71, 5: 2.83, 6: 2.70,
             7: 2.70, 8: 2.93, 9: 2.80, 10: 2.74, 11: 2.73, 12: 2.68}
_GOL_MEDIA = sum(_GOL_MESE.values()) / 12


def concentrazione(mercati):
    """Quanto la partita e' leggibile: somma dei tre punteggi piu' probabili.

    E' il fattore strutturale piu' forte per il risultato esatto: i primi
    cinque risultati coprono il 56% in Serie C e il 36% in FA Cup.
    """
    return min(sum(p for _, p in mercati.get("esatto_ft", [])), 1.0)


def coerenza(mercati):
    """Quanto la PARTITA e' decisa invece che a testa o croce.

    Corretto il 19/08/2026: la versione precedente leggeva over25/gg dai
    tassi di lega, che sono identici per tutte le partite dello stesso
    campionato — zero discriminazione dentro una lega, misurato su 37
    leghe. Ricostruita sulla matrice della partita (riscalata sul livello
    di lega, vedi mercati_partita), che e' per-partita.

    NOTA: prob_over/prob_gg qui sono usati SOLO come misura interna di
    quanto la partita e' sbilanciata, per ordinare la selezione — non
    sostituiscono il pronostico Over/GG pubblicato, che resta quello
    storico di lega. Non e' una violazione della regola forma/livello:
    quella regola riguarda cosa si PUBBLICA, non cosa si usa internamente
    per punteggiare.
    """
    m = mercati.get("_matrice_ft")
    if not m:
        return 0.0
    p1 = mercati.get("1x2", {})
    if not p1:
        return 0.0
    dominanza = max(p1.values()) - min(p1.values())  # quanto un esito stacca
    scarti = [abs(prob_over(m, 2.5) - 0.5), abs(prob_gg(m) - 0.5)]
    return min(0.5 * dominanza + 2 * sum(scarti) / len(scarti) * 0.5, 1.0)


def impronta_lega(tassi, tassi_globali):
    """Quanto la distribuzione della lega si scosta dalla media globale.

    Nasce dall'osservazione verificata sulla Championship: 2-1 e 1-2
    insieme valgono il 19,6% nel 2025 contro il 15,7% globale.

    Divisore portato da 0,10 a 0,25 il 19/08/2026: con 0,10 saturava a 1,0
    in 27 leghe su 37, appiattendo la componente.
    """
    glob = dict(tassi_globali.get("top5", []))
    scarto = sum(abs(p - glob.get(r, 0.0)) for r, p in tassi.get("top5", []))
    return min(scarto / 0.25, 1.0)


def fattore_mese(mese):
    """Quanto quel mese e' sopra o sotto la media annuale di gol."""
    return _GOL_MESE.get(int(mese), _GOL_MEDIA) / _GOL_MEDIA


def punteggio(mercati, tassi, tassi_globali, serie_over):
    """Punteggio di selezione fra 0 e 1. Piu' alto = piu' interessante.

    'mese' tolto dalla firma il 19/08/2026 insieme al peso corrispondente:
    vedi la nota su PESI.
    """
    comp = {
        "concentrazione": concentrazione(mercati),
        "coerenza": coerenza(mercati),
        "impronta": impronta_lega(tassi, tassi_globali),
        "serie_over": 1.0 if serie_over else 0.0,
    }
    return min(sum(PESI[k] * v for k, v in comp.items()), 1.0)


def quota_equa(p):
    """Da probabilita' a quota. Serve al confronto col bookmaker: se paga
    meno di questa, non c'e' valore."""
    try:
        if p is None or p <= 0:
            return "—"
        return f"{1.0 / p:.2f}"
    except (TypeError, ZeroDivisionError):
        return "—"


def _riga(etichetta, valore, p, w_et=20, w_val=10):
    # Campo etichetta a 20 (a 18 "Risultato 1º tempo", che e' lunga
    # esattamente 18, si attaccava al valore); campo quota a 8 (le quote
    # basse, es. "100.00", sono 6-7 caratteri e sballavano l'allineamento.
    # w_et/w_val si spostano solo per la riga dei gruppi, dove il VALORE e'
    # lungo ("ospite di misura", 16 caratteri): la somma dei due campi resta
    # 30, cosi' le colonne di percentuale e quota restano incolonnate con
    # tutte le altre righe della scheda.
    return f"{etichetta:<{w_et}}{valore:<{w_val}}{100 * p:>5.1f}%  {quota_equa(p):>8}"


def formatta_partita(nome_lega, casa, ospite, ora, mercati):
    """Le sette righe di una partita, testo semplice.

    Niente Markdown: i nomi delle squadre contengono apostrofi e trattini
    che romperebbero il parsing e farebbero fallire l'invio.
    """
    r = [f"{nome_lega} · {casa} – {ospite}   {ora}", "─" * 46]
    p1 = mercati["1x2"]
    scelta = max(p1, key=p1.get)
    r.append(_riga("1X2", scelta, p1[scelta]))
    for i, (ris, p) in enumerate(mercati["esatto_ft"]):
        r.append(_riga("Risultato esatto" if i == 0 else "", ris, p))
    # I due gruppi piu' probabili del mercato «Ris.Esatto MultiEsiti 4».
    # .get() e non [..]: se il calcolo e' fallito la partita esce lo stesso,
    # senza questa riga.
    #
    # Si stampano i PUNTEGGI, non l'etichetta (21/08/2026): «casa di misura»
    # e' il nome interno del gruppo, ma alla cassa si gioca "2-0 / 2-1 / 3-0
    # / 3-1" — con l'etichetta bisogna ricordarsi a memoria cosa contiene.
    # Il valore passa da 18 a 22 caratteri (i quattro punteggi ne occupano
    # 21): le due righe dei gruppi restano incolonnate fra loro ma stanno
    # quattro caratteri piu' a destra delle altre. E' il prezzo dei punteggi
    # per esteso, e si paga volentieri.
    #
    # La spia «margine basso» solo se e' il PRIMO gruppo a essere «di
    # misura»: sui prezzi veri del 21/08 si accendeva su 6 partite su 6
    # (quindi non diceva niente), guardando solo il primo su 1 su 6.
    for i, (et, p) in enumerate(mercati.get("gruppi", [])):
        nota = "  (margine basso)" if i == 0 and et in GRUPPI_DI_MISURA else ""
        r.append(_riga("MultiEsiti" if i == 0 else "", punteggi_gruppo(et), p,
                       w_et=12, w_val=22) + nota)
    r.append(_riga("Over 2.5", "", mercati["over25"]))
    r.append(_riga("GG", "", mercati["gg"]))
    r.append(_riga("Gol 1º tempo", "Over 0.5", mercati["ht_over05"]))
    r.append(_riga("", "Over 1.5", mercati["ht_over15"]))
    for i, (ris, p) in enumerate(mercati["esatto_ht"]):
        r.append(_riga("Risultato 1º tempo" if i == 0 else "", ris, p))
    for i, (et, p, rapporto) in enumerate(mercati["dc_ht_ft"]):
        esito = et.split("/")[1]
        nota = f"  ({100 * rapporto:.0f}% dei casi in cui esce {esito})"
        r.append(_riga("DC 1ºT + finale" if i == 0 else "", et, p) + nota)
    return "\n".join(r)


_LIMITE_CORPO = 4000  # margine sotto i 4096 di Telegram; alzato da 3900 il
                       # 19/08/2026 dopo che la riga DC ha allungato le schede

_TESTA = ("🧪 SELEZIONE ADATTIVA — in valutazione\n"
          "Criterio sperimentale, non sostituisce i pronostici del gruppo.\n"
          "La quota accanto e' quella EQUA: se il bookmaker paga meno,\n"
          "non c'e' valore.\n")


def formatta_messaggi(partite):
    """Il secondo messaggio delle 09:00, solo per l'admin: una o piu' parti.

    Il taglio e' per PARTITA INTERA, non per carattere: tagliare a
    carattere fisso (bug misurato il 19/08/2026 con nomi realistici tipo
    "UEFA Champions League", che portavano il messaggio a 4012 caratteri
    con il taglio a meta' delle righe della sesta partita) lascia schede
    monche e incoerenti.

    Fino al 21/08/2026 era un messaggio SOLO, e le partite che non
    entravano venivano buttate via dichiarandolo ("…e altre N partite
    omesse"). Con la riga MultiEsiti la scheda passa da 634 a 751
    caratteri: sei partite fanno 4506 caratteri contro i 4096 di Telegram,
    quindi con un messaggio solo la sesta partita sarebbe SEMPRE persa.
    Adesso si spezza in piu' parti — nessuna partita viene scartata e
    nessuna scheda viene tagliata a meta'.
    """
    if not partite:
        return [_TESTA + "\nNessuna partita adatta oggi."]

    schede = [formatta_partita(p["lega"], p["casa"], p["ospite"], p["ora"], p["mercati"])
              for p in partite]

    # Si riserva in ogni parte lo spazio della testa piena, che e' la piu'
    # lunga delle intestazioni: cosi' il conto non puo' sbagliare per difetto.
    riservato = len(_TESTA) + 1
    blocchi, corrente, lunghezza = [], [], riservato
    for scheda in schede:
        aggiunta = len(scheda) + (2 if corrente else 0)  # "\n\n" di separazione
        if corrente and lunghezza + aggiunta > _LIMITE_CORPO:
            blocchi.append(corrente)
            corrente, lunghezza, aggiunta = [], riservato, len(scheda)
        lunghezza += aggiunta
        corrente.append(scheda)
    if corrente:
        blocchi.append(corrente)

    n = len(blocchi)
    parti = []
    for i, blocco in enumerate(blocchi):
        if i == 0:
            capo = _TESTA if n == 1 else f"{_TESTA}(parte 1 di {n})\n"
        else:
            capo = f"🧪 SELEZIONE ADATTIVA — parte {i + 1} di {n}\n"
        parti.append(f"{capo}\n" + "\n\n".join(blocco))
    return parti


def scegli_sei(candidate, n=6, max_per_lega=2):
    """Le n partite col punteggio piu' alto, una sola volta ciascuna, con
    diversificazione fra campionati.

    Sei partite DIVERSE: due mercati della stessa partita non sono
    indipendenti e in una multipla si trascinano a vicenda. Vale, piu'
    debolmente, anche fra partite della STESSA lega: Over 2.5, GG e i gol
    del 1°T vengono dallo stesso tasso storico di lega (per costruzione,
    regola forma/livello) — quattro partite della stessa lega hanno schede
    quasi sovrapponibili su tre mercati su sette, poco utili per un
    sistema multiplo (misurato il 19/08/2026: 4 partite MLS su 6 nella
    prima selezione reale, identiche su Over/GG/HT).

    Al massimo max_per_lega partite per campionato. Se dopo il vincolo non
    si arriva a n, si completa con le migliori rimaste ignorando il
    limite: meglio n partite con qualche ripetizione di lega che meno di n.
    """
    viste = set()
    ordinate = []
    for c in sorted(candidate, key=lambda x: -x.get("punteggio", 0)):
        fid = c.get("fixture_id")
        if fid in viste:
            continue
        viste.add(fid)
        ordinate.append(c)

    fuori = []
    conta_lega = {}
    for c in ordinate:
        lega = c.get("lega")
        if conta_lega.get(lega, 0) >= max_per_lega:
            continue
        fuori.append(c)
        conta_lega[lega] = conta_lega.get(lega, 0) + 1
        if len(fuori) >= n:
            return fuori

    scelti = {c.get("fixture_id") for c in fuori}
    for c in ordinate:
        if c.get("fixture_id") in scelti:
            continue
        fuori.append(c)
        if len(fuori) >= n:
            break
    return fuori


def serie_over_recente(path, team_id, n=3):
    """True se le ultime n partite della squadra sono finite Over 2.5.

    Bonus misurato: dopo tre Over consecutivi il successivo e' Over al
    57,5% contro il 53,6% previsto dal modello (+3,9 punti, t=+2,71).
    """
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        righe = conn.execute(
            "SELECT ft_home + ft_away FROM partite "
            "WHERE home_id=? OR away_id=? ORDER BY data DESC LIMIT ?",
            (team_id, team_id, n)).fetchall()
    except sqlite3.Error:
        return False
    finally:
        conn.close()
    return len(righe) == n and all(r[0] > 2.5 for r in righe)


def costruisci_selezione(fixtures, path_storico):
    """Dalle fixture API alle sei partite pronte da formattare.

    Dal 19/09/2026 il corpo sta in `candidate_del_giorno`, che la
    selezione a valore riusa per avere TUTTI i candidati col modello e il
    punteggio, non solo i sei scelti. Qui il comportamento e' invariato.

    Salta le leghe senza abbastanza storico e le coppe: su quelle il
    modello e' misurato peggio del non fare niente (t=+4,54 sull'1X2).

    Corretto il 19/08/2026: la prima versione dichiarava di saltare le
    coppe ma non lo faceva — la prova su dati veri aveva messo in testa
    alla selezione una partita di Champions League, cioe' proprio dove il
    modello e' peggio della climatologia su tutti e tre i mercati. Ora usa
    `valida_modello.e_coppa`, lo stesso criterio della validazione:
    mediana delle presenze per squadra sotto 15 -> coppa (niente liste di
    id cablate, che si disallineano in silenzio se un torneo cambia
    formato). Sulle coppe lo stimatore non converge perche' troppe
    squadre hanno poche partite (eliminazione diretta, non girone).
    """
    return scegli_sei(candidate_del_giorno(fixtures, path_storico))


def candidate_del_giorno(fixtures, path_storico):
    """Tutti i candidati del giorno col modello: la lista PRIMA del taglio.

    Estratta da costruisci_selezione il 19/09/2026 per la selezione a
    valore, che ha bisogno dell'universo intero e non delle sei scelte.
    """
    globali = tassi_lega(path_storico, None) or {}
    candidate = []
    for f in fixtures:
        try:
            lid = f["league"]["id"]
            tassi = tassi_lega(path_storico, lid)
            if not tassi or tassi["n"] < MINIMO_PARTITE_LEGA:
                continue
            # La stima (e la sua cache, e l'esclusione delle coppe) sta in
            # parametri_lega dal 21/08/2026: la condivide con la riga dei
            # pronostici agli abbonati, che deve escludere esattamente le
            # stesse leghe con lo stesso criterio.
            p = parametri_lega(path_storico, lid)
            if not p:
                continue
            par, rho, qpt = p
            hid = f["teams"]["home"]["id"]
            aid = f["teams"]["away"]["id"]
            merc = mercati_partita(par, rho, qpt, hid, aid, tassi)
            serie = (serie_over_recente(path_storico, hid)
                     or serie_over_recente(path_storico, aid))
            candidate.append({
                "fixture_id": f["fixture"]["id"],
                # league_id e data non si stampano: servono a registrare la
                # selezione su gruppi_pronostico, che senza non e' misurabile.
                "league_id": lid,
                "data": f["fixture"]["date"][:10],
                "lega": f["league"]["name"],
                "casa": f["teams"]["home"]["name"],
                "ospite": f["teams"]["away"]["name"],
                "ora": f["fixture"]["date"][11:16],
                "mercati": merc,
                "punteggio": punteggio(merc, tassi, globali or tassi, serie),
            })
        except Exception as e:
            log.error(f"costruisci_selezione, fixture saltata: {e}")
    return candidate
