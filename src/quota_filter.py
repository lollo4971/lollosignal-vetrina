"""Filtro quote minime per i segnali LIVE.

NON si applica al prematch.

Soglie decise il 14/08/2026 sulla base dell'analisi ROI dello storico
(480 segnali, aprile-agosto 2026). Il filtro alza il prezzo minimo
accettato, non migliora la selezione: sui CHI_SEGNA il winrate resta
33,3% sopra e sotto soglia. Serve a non giocare a quote che non ripagano
il rischio, non a scegliere meglio.

OVER_2.5 e' volutamente piu' permissivo (1.60) degli altri OVER: e' l'unico
tipo il cui intervallo di confidenza sta interamente sopra il 50% e con la
soglia piena sarebbe sceso al 9% del volume, troppo poco per misurarlo.
"""

import os
import sqlite3

# Nella vetrina i percorsi sono relativi al repository (in produzione: /opt/football-bot).
_RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Floor globale gia' applicato in pre_publish_check (bot.py).
MIN_QUOTA_ASSOLUTA = 1.40

# Minimi abbassati di ~0.10 il 15/08 su richiesta: piu' segnali, filtro
# comunque attivo. Il floor assoluto resta MIN_QUOTA_ASSOLUTA.
# I massimi sono saliti a 5.00 sugli OVER: il 15/08 erano stati bocciati un
# OVER_1.5 a 5.00 e un OVER_2.5 a 4.33, cioe' proprio i casi di valore.
QUOTA_RANGES = {
    "OVER_0.5":           (1.65, 5.00),
    "OVER_1.5":           (1.65, 5.00),
    "OVER_2.5":           (1.50, 5.00),   # protetto, vedi docstring
    "OVER_3.5":           (1.75, 5.00),
    "GG":                 (1.50, 3.00),
    "CHI_SEGNA_PROSSIMO": (1.70, 3.50),
    "RIBALTONE":          (2.50, 8.00),
    # Primo tempo: mercato diverso, prezzi diversi. Un Over 0.5 vale 1.04
    # sui 90 minuti e circa 1.70 sul solo primo tempo al 6'.
    "OVER_0.5_PT":        (1.55, 4.50),
    "OVER_1.5_PT":        (1.80, 8.00),
    "OVER_2.5_PT":        (2.50, 15.00),
}

# Tipi con varianti a suffisso: CHI_SEGNA_PROSSIMO_CASA, RIBALTONE_OSPITE...
_PREFIX_KEYS = ("CHI_SEGNA_PROSSIMO", "RIBALTONE")

# Linea OVER non prevista: si applica la soglia piu' severa invece di
# lasciarla passare senza filtro. E' la falla che la vecchia chiave
# "OVER_N5" apriva.
_OVER_FALLBACK = "OVER_3.5"
_OVER_PT_FALLBACK = "OVER_2.5_PT"


def correct_over_type(tipo, gol_casa, gol_ospite):
    """Allinea la linea OVER al punteggio, CONSERVANDO il suffisso _PT.

    Il bug del 15/08: la riscrittura buttava via il _PT, quindi un segnale
    sul primo tempo veniva poi prezzato con il mercato dei 90 minuti.
    """
    if not tipo or not tipo.startswith("OVER_"):
        return tipo
    pt = tipo.endswith("_PT")
    return f"OVER_{gol_casa + gol_ospite}.5" + ("_PT" if pt else "")


# ─── Soglie derivate dal win rate misurato (21/09/2026) ─────────────────────
# Le soglie qui sopra sono state decise a tavolino nell'agosto 2026. Ma il
# prezzo che serve per andare in pari non e' un'opinione: e' 1/winrate.
# Misurato sui segnali veri:
#     OVER 2.5  65,6% -> pareggio 1,52 · mercato 1,70-1,90  giocabile
#     OVER 0.5  60,0% -> pareggio 1,67 · mercato ~1,20      no
#     CHI_SEGNA 35,7% -> pareggio 2,80 · mercato 1,80-2,50  no
# La regola dell'espulsione emetteva CHI_SEGNA a 1,80 fissi: perdente per
# costruzione. Ora la soglia si calcola, e si aggiorna da sola.
DB_SEGNALI = os.path.join(_RADICE, "signals.db")
CAMPIONE_MINIMO_SOGLIA = 30   # sotto, si tiene la soglia statica
MARGINE_SICUREZZA = 0.07      # 7% sopra il pareggio: il banco non regala
SOGLIA_MASSIMA = 6.00         # oltre, il tipo sarebbe spento da un numero
GIORNI_FINESTRA = 180

_cache_soglie = {}


def svuota_cache_soglie():
    """Per i test e per il ricalcolo quotidiano."""
    _cache_soglie.clear()


def _winrate_tipo(tipo, db):
    """(vinti, totale) del tipo negli ultimi GIORNI_FINESTRA giorni."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        r = conn.execute(
            "SELECT COUNT(*), SUM(esito='VINTO') FROM signals "
            "WHERE tipo=? AND esito IN ('VINTO','PERSO') "
            "AND timestamp > datetime('now', ?)",
            (tipo, f"-{GIORNI_FINESTRA} days")).fetchone()
        return (r[1] or 0), (r[0] or 0)
    finally:
        conn.close()


def soglia_minima(tipo, db=DB_SEGNALI):
    """La quota minima per questo tipo: la piu' SEVERA fra quella statica
    e quella che il win rate misurato impone.

    None se il tipo non e' mappato (come resolve_quota_key).

    Non si allenta mai sotto la statica: rendere il filtro piu' largo
    sulla base di qualche decina di casi e' il modo classico di farsi
    male. E qualunque guaio (DB assente, tabella diversa) ricade sulla
    statica, mai su nessun filtro.
    """
    key = resolve_quota_key(tipo)
    if key is None:
        return None
    statica = QUOTA_RANGES[key][0]
    if (tipo, db) in _cache_soglie:
        return _cache_soglie[(tipo, db)]
    soglia = statica
    try:
        vinti, n = _winrate_tipo(tipo, db)
        if n >= CAMPIONE_MINIMO_SOGLIA and vinti > 0:
            pareggio = n / vinti                       # 1 / winrate
            dal_dato = pareggio * (1 + MARGINE_SICUREZZA)
            soglia = min(max(statica, round(dal_dato, 2)), SOGLIA_MASSIMA)
    except Exception:
        soglia = statica
    _cache_soglie[(tipo, db)] = soglia
    return soglia


def resolve_quota_key(tipo):
    """Chiave di QUOTA_RANGES per un tipo di segnale, o None se non mappato."""
    if not tipo:
        return None
    if tipo in QUOTA_RANGES:
        return tipo
    for key in _PREFIX_KEYS:
        if tipo.startswith(key):
            return key
    if tipo.startswith("OVER_"):
        return _OVER_PT_FALLBACK if tipo.endswith("_PT") else _OVER_FALLBACK
    return None


def check_quota_range(tipo, real_quota, db=DB_SEGNALI):
    """Verifica se la quota REALE di mercato e' nel range accettabile.

    Ritorna (ok: bool, reason: str).

    Da chiamare solo con una quota di mercato verificata. Se manca, il
    segnale passa marcato 'quota non verificata': il chiamante deve
    salvare NULL in signals.quota_minima, mai un valore inventato.
    """
    if not real_quota:
        return True, "quota non verificata"

    key = resolve_quota_key(tipo)
    if key is None:
        return True, "tipo non mappato"

    lo, hi = QUOTA_RANGES[key]
    # La soglia vera e' la piu' severa fra statica e quella imposta dal
    # win rate misurato del tipo (21/09/2026).
    dinamica = soglia_minima(tipo, db) or lo
    if real_quota < dinamica:
        motivo = (f"quota {real_quota} sotto il minimo {dinamica} per {key}"
                  + (f" (dal winrate misurato)" if dinamica > lo else ""))
        return False, motivo
    if real_quota < lo:
        return False, f"quota {real_quota} sotto il minimo {lo} per {key}"
    if real_quota > hi:
        return False, f"quota {real_quota} sopra il massimo {hi} per {key}"
    return True, "in range"
