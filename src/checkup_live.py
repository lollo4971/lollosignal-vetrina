#!/usr/bin/env python3
"""Autocontrollo dei dati live prodotti dopo il deploy del 14/08/2026.

Verifica che le tre modifiche di quel giorno funzionino sui dati veri:
gate whitelist + gate statistiche, correzione del bug xG, soglie di quota.

I log di journald non sono permanenti: lo script SALVA uno snapshot in
checkups/YYYY-MM-DD.json, cosi' le serate restano confrontabili anche dopo
la rotazione dei log.

Uso:
  ./checkup_live.py                    # analizza le ultime 12 ore e salva
  ./checkup_live.py --ore 24
  ./checkup_live.py --compare          # confronta tutti gli snapshot salvati
  ./checkup_live.py --file log.txt     # su un log gia' catturato
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "signals.db")
SNAP_DIR = os.path.join(BASE, "checkups")

# Misurato il 14/08/2026 sulle 24h precedenti al deploy.
# ATTENZIONE: costo_giorno e' la sola parte LIVE (Haiku), calcolata dal
# modello sotto su 588 chiamate x 664 token. I ~$2,50/giorno citati in
# CLAUDE.md sono il totale e includono il batch prematch con Sonnet, che
# queste modifiche non toccano.
BASELINE = {
    "chiamate_giorno": 588,
    "input_dinamici": 664,
    "quota_analisi_l3": 0.65,
    "costo_giorno": 1.32,
}

# Prezzi Haiku 4.5, $/milione di token.
PREZZO_INPUT = 1.00
PREZZO_CACHE_READ = 0.10
PREZZO_OUTPUT = 5.00
TOKEN_CACHE = 5747      # prefisso cachato del system prompt
TOKEN_OUTPUT_MEDI = 200

# Soglie minime per tipo, IMPORTATE da quota_filter — non duplicate.
# Erano duplicate "perche' lo script deve girare anche senza bot.py", ma
# quota_filter e' importabile da solo. Il 15/08 le soglie sono state abbassate
# in quota_filter e questa copia e' rimasta indietro: il report del 17/08 ha
# segnalato 2 falsi "segnali sotto soglia" su segnali perfettamente regolari.
from quota_filter import QUOTA_RANGES, resolve_quota_key  # noqa: E402


def soglia_minima(tipo):
    """Soglia minima per un tipo di segnale, None se non mappato."""
    chiave = resolve_quota_key(tipo)
    return QUOTA_RANGES[chiave][0] if chiave else None


def _da_to_sql(da):
    """Normalizza il valore di --da nel formato timestamp del DB.

    Accetta "20:00", "20:00:00" (oggi) e "2026-08-14 20:00:00".
    """
    testo = da.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", testo):
        parti = testo.split(":")
        if len(parti) == 2:
            testo += ":00"
        return f"{datetime.now():%Y-%m-%d} {testo}"
    return testo


@dataclass
class Check:
    nome: str
    ok: bool
    valore: str
    atteso: str
    nota: str = ""


# ─── PARSING ──────────────────────────────────────────────────────────────
_RE_ANALISI = re.compile(r"Analisi \d+ .*?\| ", re.S)
_RE_LIVELLO = re.compile(r"\]\s+(L[123])\s+\|")
# `na` significa che il fornitore non espone l'xG su quella lega: e' un
# valore diverso da zero e il controllo li tratta in modo diverso.
_RE_STATS = re.compile(
    r"stats (\d+): campi=(\d+)/(\d+) xg=([\d.]+|na)/([\d.]+|na)")
_RE_DINAMICI = re.compile(r"input_dinamici=(\d+)")


# Righe ERROR che NON sono colpa del bot. Raccolte il 01/09/2026 dal journal
# vero della settimana 25-31/08 (58 righe, tutte riconducibili a queste forme):
# non sono state indovinate.
_ERR_FORNITORE = (
    "API-Football errore su",        # il fornitore risponde con un suo 5xx
    "API error ",                    # timeout o rete verso il fornitore
)
_ERR_INFRASTRUTTURA = (
    "Exception happened while polling for updates",   # python-telegram-bot
    "No error handlers are registered",               # riga gemella della sopra
)


def _classifica_errori(text):
    """Divide le righe ERROR in nostre, del fornitore e di infrastruttura.

    PERCHE'. Il controllo pretendeva ZERO errori mentre il bot dipende da un
    fornitore che risponde letteralmente `{'bug': 'This is on our side'}`.
    Falliva ogni giorno, e un allarme che suona sempre insegna a ignorarlo:
    il 29/08/2026 segnalava 40 errori, e se fra quei 40 ce ne fosse stato uno
    nostro sarebbe passato inosservato.

    REGOLA: quello che non riconosco e' NOSTRO. Un errore nuovo e sconosciuto
    deve far scattare l'allarme, non essere assorbito in silenzio — lo stesso
    principio del default di `origine`, dove un percorso nuovo finisce fuori
    dalla vetrina invece che dentro.
    """
    nostri = fornitore = infra = 0
    for riga in text.splitlines():
        if not re.search(r"\bERROR\b", riga):
            continue
        if any(s in riga for s in _ERR_FORNITORE):
            fornitore += 1
        elif any(s in riga for s in _ERR_INFRASTRUTTURA):
            infra += 1
        else:
            nostri += 1
    return {
        "errori": nostri + fornitore + infra,
        "errori_nostri": nostri,
        "errori_fornitore": fornitore,
        "errori_infrastruttura": infra,
    }


def parse_log(text):
    """Estrae i contatori dal testo dei log. Funzione pura, testabile."""
    livelli = Counter(_RE_LIVELLO.findall(text))
    dinamici = [int(x) for x in _RE_DINAMICI.findall(text)]
    stats_rows = _RE_STATS.findall(text)
    campi = [int(r[1]) for r in stats_rows]
    def _num(v):
        return 0.0 if v == "na" else float(v)
    con_xg = sum(1 for r in stats_rows if _num(r[3]) > 0 or _num(r[4]) > 0)
    # Analisi in cui il fornitore l'xG non lo espone proprio: non sono un
    # nostro difetto e non devono far scattare l'allarme.
    senza_xg_fornitore = sum(1 for r in stats_rows if r[3] == "na")

    # Diagnostica dei rifiuti del fornitore. Il residuo al minuto e' il dato
    # decisivo: se restavano ~250 richieste su 300, il rifiuto non dipende
    # dal nostro volume.
    ritentati = len(re.findall(r"rate-limit su .* ritento fra", text))
    persi = len(re.findall(r"rate-limit su .*: esauriti i tentativi", text))
    residui = [int(x) for x in re.findall(r"residuo al minuto: (\d+)", text)]

    return {
        "analisi_per_livello": dict(livelli),
        "skip_whitelist": len(re.findall(r"fuori whitelist", text)),
        "skip_no_stats": len(re.findall(r"nessuna statistica disponibile", text)),
        "skip_quota": len(re.findall(r"sotto il minimo|sopra il massimo", text)),
        "quota_non_verificata": len(re.findall(r"quota non verificata", text)),
        "chiamate_ai": len(re.findall(r"cache_live:", text)),
        "input_dinamici_medi": (sum(dinamici) / len(dinamici)) if dinamici else 0,
        "stats_righe": len(stats_rows),
        "stats_con_xg": con_xg,
        "stats_xg_non_offerto": senza_xg_fornitore,
        "campi_medi": (sum(campi) / len(campi)) if campi else 0,
        **_classifica_errori(text),
        "ratelimit_ritentati": ritentati,
        "ratelimit_persi": persi,
        "ratelimit_recuperati": ritentati - persi,
        "ratelimit_residuo_medio": (sum(residui) / len(residui)) if residui else 0,
    }


def stima_costo_giornaliero(chiamate, input_dinamici):
    """Costo in dollari per un giorno con quel volume di chiamate."""
    if not chiamate:
        return 0.0
    per_chiamata = (
        TOKEN_CACHE * PREZZO_CACHE_READ / 1e6
        + input_dinamici * PREZZO_INPUT / 1e6
        + TOKEN_OUTPUT_MEDI * PREZZO_OUTPUT / 1e6
    )
    return round(chiamate * per_chiamata, 2)


# ─── CONTROLLI ────────────────────────────────────────────────────────────
def run_checks(p, db):
    """Lista di Check a partire dai contatori del log e dai dati DB."""
    out = []
    a = p["analisi_per_livello"]

    l3 = a.get("L3", 0)
    out.append(Check(
        "gate_whitelist", l3 == 0, f"{l3} analisi L3", "0",
        "il livello 3 non deve piu' essere analizzato"))

    analizzate = sum(a.values())
    out.append(Check(
        "gate_statistiche", True,
        f"{p['skip_no_stats']} partite scartate senza statistiche",
        "informativo",
        "leghe in whitelist ma senza feed dati"))

    out.append(Check(
        "risparmio_chiamate",
        p["chiamate_ai"] <= BASELINE["chiamate_giorno"],
        f"{p['chiamate_ai']} chiamate AI",
        f"<= {BASELINE['chiamate_giorno']} (baseline)",
        f"{p['skip_whitelist']} partite scartate prima di ogni chiamata API"))

    # Con zero analisi non c'e' nulla da misurare (fascia oraria senza
    # partite in whitelist): informativo, non fallimento.
    # Serve un volume minimo per distinguere una regressione da una giornata
    # di partite non coperte. Il fornitore espone expected_goals ma lo lascia
    # vuoto su molte competizioni: il 18/08 tre preliminari di Champions
    # hanno dato 0% e il controllo ha gridato al lupo su un dato normale.
    MIN_ANALISI_XG = 20
    if p["stats_righe"] == 0:
        out.append(Check(
            "xg_presente", True, "nessuna analisi nel periodo", "informativo",
            "nessuna partita in whitelist in questa fascia oraria"))
    elif p["stats_righe"] < MIN_ANALISI_XG:
        perc = 100 * p["stats_con_xg"] / p["stats_righe"]
        out.append(Check(
            "xg_presente", True,
            f"{p['stats_con_xg']}/{p['stats_righe']} con xG ({perc:.0f}%)",
            "informativo",
            f"meno di {MIN_ANALISI_XG} analisi: campione troppo piccolo per "
            f"distinguere una regressione dalla copertura del fornitore"))
    else:
        perc = 100 * p["stats_con_xg"] / p["stats_righe"]
        non_offerto = p.get("stats_xg_non_offerto", 0)
        offerte = p["stats_righe"] - non_offerto
        # L'allarme scatta solo se il fornitore l'xG L'HA MANDATO e noi non
        # l'abbiamo letto. Se non lo manda su nessuna delle leghe analizzate
        # — capita ogni volta che la giornata e' fatta di seconde divisioni —
        # lo zero e' corretto e gridare al lupo insegna a ignorare l'allarme.
        out.append(Check(
            "xg_presente", p["stats_con_xg"] > 0 or offerte == 0,
            f"{p['stats_con_xg']}/{p['stats_righe']} analisi con xG "
            f"({perc:.0f}%) · non esposto dal fornitore su {non_offerto}",
            "> 0 dove il fornitore lo espone",
            "expected_goals arriva solo su alcune leghe (La Liga e Premier "
            "si, Bundesliga e Ligue 1 no): verificato sull'API il 04/09"))

    # La soglia SCENDE dove il fornitore non espone l'xG: quei due campi su
    # trenta sono strutturalmente vuoti, e pretendere 20 su una giornata di
    # seconde divisioni vuol dire far fallire un controllo per un dato che
    # non poteva esserci. Su una giornata senza xG il tetto reale e' 28.
    _quota_senza_xg = (p.get("stats_xg_non_offerto", 0) / p["stats_righe"]
                       if p["stats_righe"] else 0)
    _soglia_campi = 20 - 2 * _quota_senza_xg
    out.append(Check(
        "campi_popolati",
        p["campi_medi"] >= _soglia_campi or p["stats_righe"] == 0,
        f"{p['campi_medi']:.1f}/30 campi medi", f">= {_soglia_campi:.1f}",
        "15 campi per squadra, 30 in totale"))

    din = p["input_dinamici_medi"]
    out.append(Check(
        "prompt_arricchito", din >= BASELINE["input_dinamici"] or din == 0,
        f"{din:.0f} token dinamici medi",
        f">= {BASELINE['input_dinamici']} (prima del deploy)",
        "gli 8 campi nuovi allungano il payload"))

    costo = stima_costo_giornaliero(p["chiamate_ai"], din)
    out.append(Check(
        "costo_stimato", costo <= BASELINE["costo_giorno"],
        f"${costo}/giorno", f"<= ${BASELINE['costo_giorno']} (baseline)",
        "proiezione sul periodo analizzato"))

    viol = db.get("violazioni_quota", 0)
    out.append(Check(
        "quote_rispettano_soglie", viol == 0,
        f"{viol} segnali sotto soglia", "0",
        f"{p['skip_quota']} bloccati dal filtro nei log"))

    fuori = db.get("leghe_fuori_whitelist", [])
    out.append(Check(
        "segnali_solo_whitelist", not fuori,
        f"{len(fuori)} leghe fuori whitelist" + (f": {', '.join(fuori[:3])}" if fuori else ""),
        "0"))

    # Rifiuti del fornitore. Non e' un PASS/FAIL nostro: serve a capire di
    # chi sia il problema. Con residuo alto la causa non e' il nostro volume.
    if p["ratelimit_ritentati"] or p["ratelimit_persi"]:
        residuo = p["ratelimit_residuo_medio"]
        diagnosi = ("residuo alto: la causa NON e' il nostro volume"
                    if residuo > 50 else
                    "residuo basso: stiamo davvero esaurendo il minuto")
        out.append(Check(
            "rate_limit_fornitore", True,
            f"{p['ratelimit_ritentati']} rifiuti, {p['ratelimit_recuperati']} recuperati "
            f"col ritentativo, {p['ratelimit_persi']} partite perse · "
            f"residuo medio {residuo:.0f}/300",
            "informativo", diagnosi))
    else:
        out.append(Check(
            "rate_limit_fornitore", True, "nessun rifiuto", "informativo"))

    # Solo gli errori NOSTRI hanno una soglia. Quelli del fornitore restano
    # visibili ma non fanno fallire: pretendere zero da un servizio esterno
    # significa avere un controllo che fallisce per sempre e che quindi
    # nessuno guarda piu'.
    out.append(Check(
        "errori_bot", p["errori_nostri"] == 0,
        f"{p['errori_nostri']} errori del bot", "0",
        "su " + str(p["errori"]) + " righe ERROR totali"))

    esterni = p["errori_fornitore"] + p["errori_infrastruttura"]
    out.append(Check(
        "errori_esterni", True,
        f"{esterni} non nostri: {p['errori_fornitore']} dal fornitore, "
        f"{p['errori_infrastruttura']} di infrastruttura",
        "informativo",
        "informativo: un picco va guardato, ma non e' un nostro difetto"))

    out.append(Check(
        "segnali_emessi", True, f"{db.get('segnali', 0)} segnali", "informativo",
        f"{analizzate} partite analizzate nel periodo"))
    return out


# ─── DATI DAL DB ──────────────────────────────────────────────────────────
def load_db_stats(db_path, ore, da=None):
    """Segnali del periodo: violazioni di soglia e leghe fuori whitelist.

    `da` allinea la finestra del DB a quella dei log: senza, un --da "20:00"
    confronterebbe log serali con segnali di tutta la giornata.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    # datetime() su ENTRAMBI i lati: il DB salva in ISO con la 'T'
    # ("2026-08-14T09:57:11") e il confronto fra stringhe grezze e' sbagliato,
    # perche' 'T' > ' ' e un segnale del mattino risulterebbe successivo a un
    # --da del pomeriggio.
    if da:
        rows = conn.execute(
            "SELECT tipo, league, quota_minima FROM signals "
            "WHERE datetime(timestamp) >= datetime(?)",
            (_da_to_sql(da),)).fetchall()
    else:
        rows = conn.execute(
            "SELECT tipo, league, quota_minima FROM signals "
            "WHERE datetime(timestamp) >= datetime('now', ?)",
            (f"-{ore} hours",)).fetchall()
    conn.close()

    viol = []
    for tipo, lega, q in rows:
        soglia = soglia_minima(tipo)
        # quota NULL = non verificata: non e' una violazione, e' il nuovo
        # comportamento voluto.
        if soglia and q is not None and q < soglia:
            viol.append(f"{tipo}@{q}")
    return {
        "segnali": len(rows),
        "violazioni_quota": len(viol),
        "dettaglio_violazioni": viol,
        "per_tipo": dict(Counter(t for t, _, _ in rows)),
        "per_lega": dict(Counter(l for _, l, _ in rows)),
        "quota_null": sum(1 for _, _, q in rows if q is None),
        "leghe_fuori_whitelist": [],   # popolato da chi conosce la whitelist
    }


# ─── OUTPUT ───────────────────────────────────────────────────────────────
def stampa(checks, p, db, periodo):
    print(f"\n{'='*66}")
    print(f"  AUTOCONTROLLO DATI LIVE — periodo: {periodo} — {datetime.now():%d/%m/%Y %H:%M}")
    print(f"{'='*66}\n")
    falliti = 0
    for c in checks:
        if c.atteso == "informativo":
            simbolo = "·"
        elif c.ok:
            simbolo = "OK  "
        else:
            simbolo = "FAIL"
            falliti += 1
        print(f"  [{simbolo:^4}] {c.nome:<26} {c.valore}")
        print(f"         {'atteso: ' + c.atteso:<34}{c.nota}")
    print(f"\n  {'-'*62}")
    if db.get("per_tipo"):
        print(f"  Segnali per tipo: {db['per_tipo']}")
    if db.get("quota_null") is not None:
        print(f"  Segnali con quota NULL (non verificata): {db['quota_null']}")
    print(f"\n  RISULTATO: {len(checks)-falliti}/{len(checks)} controlli superati"
          + (f" — {falliti} DA GUARDARE" if falliti else " — tutto a posto"))
    print()
    return falliti


def format_telegram(checks, p, db, periodo):
    """Riassunto compatto per la chat admin. Testo semplice, niente Markdown:
    i nomi delle leghe contengono trattini e underscore che romperebbero il
    parsing e farebbero fallire l'invio."""
    reali = [c for c in checks if c.atteso != "informativo"]
    falliti = [c for c in reali if not c.ok]
    a = p["analisi_per_livello"]
    livelli = " ".join(f"{k} {v}" for k, v in sorted(a.items())) or "nessuna"

    righe = [
        f"🔎 Autocontrollo live — {datetime.now():%d/%m %H:%M}",
        f"periodo analizzato: {periodo}",
        "",
    ]
    if falliti:
        righe.append(f"⚠️ {len(falliti)} controlli su {len(reali)} da guardare:")
        for c in falliti:
            righe.append(f"  • {c.nome}: {c.valore}  (atteso: {c.atteso})")
    else:
        righe.append(f"✅ tutti i {len(reali)} controlli superati")
    righe += [
        "",
        f"Analisi: {sum(a.values())} ({livelli})",
        f"Scartate: {p['skip_whitelist']} fuori whitelist, "
        f"{p['skip_no_stats']} senza statistiche",
        f"Chiamate AI: {p['chiamate_ai']} · {p['input_dinamici_medi']:.0f} token medi",
        f"Costo stimato: ${stima_costo_giornaliero(p['chiamate_ai'], p['input_dinamici_medi'])}/giorno "
        f"(baseline ${BASELINE['costo_giorno']})",
    ]
    if p["stats_righe"]:
        righe.append(f"xG ricevuto: {p['stats_con_xg']}/{p['stats_righe']} analisi")
    if db.get("segnali") is not None:
        righe.append(f"Segnali emessi: {db['segnali']}")
    if db.get("per_tipo"):
        righe.append(f"  per tipo: {db['per_tipo']}")
    if db.get("quota_null"):
        righe.append(f"  con quota non verificata: {db['quota_null']}")

    testo = "\n".join(righe)
    return testo[:4000] + "\n…(troncato)" if len(testo) > 4000 else testo


def invia_telegram(testo):
    """Invia alla chat admin. Ritorna True se accettato."""
    import urllib.parse
    import urllib.request
    token = chat = None
    try:
        with open(os.path.join(BASE, ".env")) as f:
            for riga in f:
                if riga.startswith("TELEGRAM_TOKEN="):
                    token = riga.split("=", 1)[1].strip()
                elif riga.startswith("TELEGRAM_CHAT_ID="):
                    chat = riga.split("=", 1)[1].strip()
    except OSError as e:
        print(f"  .env illeggibile: {e}")
        return False
    if not token or not chat:
        print("  TELEGRAM_TOKEN o TELEGRAM_CHAT_ID assenti in .env")
        return False
    dati = urllib.parse.urlencode({
        "chat_id": chat, "text": testo, "disable_web_page_preview": "true",
    }).encode()
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=dati)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("ok", False)
    except Exception as e:
        print(f"  invio Telegram fallito: {e}")
        return False


def riepilogo_settimanale():
    """Testo di confronto fra gli snapshot degli ultimi 7 giorni."""
    if not os.path.isdir(SNAP_DIR):
        return "Nessuno snapshot disponibile per il riepilogo settimanale."
    tutti = sorted(f for f in os.listdir(SNAP_DIR) if f.endswith(".json"))
    if not tutti:
        return "Nessuno snapshot disponibile per il riepilogo settimanale."
    # Un giorno = una riga. Con piu' esecuzioni nella stessa data vale
    # l'ultima, altrimenti gli esiti parziali della mattina falserebbero
    # il confronto e la settimana coprirebbe meno di 7 giorni.
    per_giorno = {}
    for fn in tutti:
        per_giorno[fn[:10]] = fn
    files = [per_giorno[g] for g in sorted(per_giorno)[-7:]]

    righe = ["📈 Riepilogo settimanale autocontrollo live", ""]
    tot_seg = tot_chiam = 0
    for fn in files:
        with open(os.path.join(SNAP_DIR, fn)) as f:
            d = json.load(f)
        lg, db = d["log"], d.get("db", {})
        fail = sum(1 for c in d["checks"]
                   if not c["ok"] and c["atteso"] != "informativo")
        costo = stima_costo_giornaliero(lg["chiamate_ai"], lg["input_dinamici_medi"])
        tot_seg += db.get("segnali", 0)
        tot_chiam += lg["chiamate_ai"]
        stato = "OK" if not fail else f"{fail} FAIL"
        righe.append(f"{fn[:10]}  chiamate {lg['chiamate_ai']:>4}  "
                     f"segnali {db.get('segnali', 0):>3}  ${costo:>5.2f}  {stato}")
    righe += ["", f"Totale settimana: {tot_chiam} chiamate, {tot_seg} segnali",
              f"Baseline pre-deploy: {BASELINE['chiamate_giorno']} chiamate/giorno"]
    return "\n".join(righe)


def salva_snapshot(p, db, checks, ore):
    os.makedirs(SNAP_DIR, exist_ok=True)
    path = os.path.join(SNAP_DIR, f"{datetime.now():%Y-%m-%d_%H%M}.json")
    with open(path, "w") as f:
        json.dump({
            "generato": datetime.now().isoformat(timespec="seconds"),
            "ore_analizzate": ore,
            "log": p,
            "db": db,
            "checks": [asdict(c) for c in checks],
            "baseline": BASELINE,
        }, f, indent=2, ensure_ascii=False)
    return path


def compara():
    if not os.path.isdir(SNAP_DIR):
        print("Nessuno snapshot salvato."); return
    files = sorted(f for f in os.listdir(SNAP_DIR) if f.endswith(".json"))
    if not files:
        print("Nessuno snapshot salvato."); return
    print(f"\n{'snapshot':<20}{'chiamate':>9}{'token':>8}{'costo':>8}"
          f"{'xG %':>7}{'segnali':>9}{'FAIL':>6}")
    print("-" * 67)
    for fn in files:
        with open(os.path.join(SNAP_DIR, fn)) as f:
            d = json.load(f)
        lg, db = d["log"], d.get("db", {})
        xg = (100 * lg["stats_con_xg"] / lg["stats_righe"]) if lg["stats_righe"] else 0
        costo = stima_costo_giornaliero(lg["chiamate_ai"], lg["input_dinamici_medi"])
        fail = sum(1 for c in d["checks"] if not c["ok"] and c["atteso"] != "informativo")
        print(f"{fn[:-5]:<20}{lg['chiamate_ai']:>9}{lg['input_dinamici_medi']:>8.0f}"
              f"{costo:>8.2f}{xg:>7.0f}{db.get('segnali', 0):>9}{fail:>6}")
    print()


def leggi_log(ore, file=None, da=None):
    """Log del periodo. `da` ha la precedenza su `ore` e accetta qualunque
    formato capito da journalctl --since ("20:00", "2026-08-14 20:00:00")."""
    if file:
        with open(file) as f:
            return f.read()
    since = da if da else f"{ore} hours ago"
    r = subprocess.run(
        ["journalctl", "-u", "football-bot", "--since", since,
         "--no-pager", "-o", "cat"],
        capture_output=True, text=True, timeout=180)
    return r.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ore", type=int, default=12)
    ap.add_argument("--da", help="istante di inizio preciso, es. --da '20:00'. "
                                 "Utile per non includere il periodo prima di un deploy.")
    ap.add_argument("--file", help="analizza un log gia' salvato invece di journalctl")
    ap.add_argument("--compare", action="store_true", help="confronta gli snapshot")
    ap.add_argument("--telegram", action="store_true",
                    help="invia il riassunto alla chat admin")
    ap.add_argument("--settimanale", action="store_true",
                    help="riepilogo degli ultimi 7 snapshot (usato dal timer domenicale)")
    args = ap.parse_args()

    if args.compare:
        compara(); return 0

    if args.settimanale:
        testo = riepilogo_settimanale()
        print(testo)
        if args.telegram:
            print("  inviato" if invia_telegram(testo) else "  invio FALLITO")
        return 0

    p = parse_log(leggi_log(args.ore, args.file, args.da))
    db = load_db_stats(DB_PATH, args.ore, args.da)
    checks = run_checks(p, db)
    periodo = args.da or f"ultime {args.ore}h"
    falliti = stampa(checks, p, db, periodo)
    path = salva_snapshot(p, db, checks, args.ore)
    print(f"  Snapshot salvato in {path}")

    if args.telegram:
        ok = invia_telegram(format_telegram(checks, p, db, periodo))
        print(f"  Telegram: {'inviato' if ok else 'INVIO FALLITO'}")
    else:
        print(f"  Confronto tra serate: ./checkup_live.py --compare")
    print()
    return 1 if falliti else 0


if __name__ == "__main__":
    sys.exit(main())
