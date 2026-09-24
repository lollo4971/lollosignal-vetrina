"""Quote del mercato «HT/FT Double» (Primo Tempo / Finale), id 7.

PERCHE' ESISTE. E' il mercato su cui l'utente gioca davvero, e le sue quote
non erano salvate da nessuna parte. La retention di API-Football su `/odds`
e' di **7 giorni**: quello che non si prende oggi non si prende piu'. E'
lo stesso buco che ha lasciato 856 pronostici senza ROI sul risultato esatto
e che il 26/08/2026 ha richiesto la colonna `quota_banco` per i gruppi.

COSTO API ZERO: riusa la risposta `/odds` gia' scaricata da
`match_data.fetch_prematch_odds`, esattamente come `exact_score_odds`.

DA SAPERE PRIMA DI TOCCARLO:
- il mercato si filtra per **id = 7**, non per nome. Stessa trappola gia'
  vista su Exact Score, dove «Correct Score» esiste ma indica il primo tempo;
- l'API restituisce nove valori con etichette `Home/Draw`, il progetto usa le
  celle `1/X`. La conversione sta in `CELLE`, in un punto solo: se le due
  notazioni divergessero, quote e statistiche parlerebbero di cose diverse;
- il campo `odd` e' una **stringa**;
- bookmaker di riferimento **1xBet** (conto reale dell'utente), mediana come
  ripiego. Stessa scelta di `exact_score_odds`.

Le nove celle permettono di ricostruire qualunque mercato combinato — P(A),
P(B), P(C), X/X — con `combined()`, che fa il dutching.

Misure di riferimento (28/08/2026, 57.424 partite di `storico.db`):
P(A) 30,8% · P(B) 17,3% · P(C) 13,5% · X/X 15,0% · 1/1 26,7%.
"""
import json
import logging
import os
import sqlite3
import statistics

# Nella vetrina i percorsi sono relativi al repository (in produzione: /opt/football-bot).
_RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


log = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", os.path.join(_RADICE, "signals.db"))

HTFT_BET_ID = 7
REF_BOOKMAKER = "1xBet"

# Etichetta API → cella del progetto. UNICO punto di conversione.
CELLE = {
    "Home/Home": "1/1", "Home/Draw": "1/X", "Home/Away": "1/2",
    "Draw/Home": "X/1", "Draw/Draw": "X/X", "Draw/Away": "X/2",
    "Away/Home": "2/1", "Away/Draw": "2/X", "Away/Away": "2/2",
}

# «Il primo tempo non decide»: le quattro celle in cui l'esito
# all'intervallo non e' quello finale. Definizione usata in tutta l'analisi.
CELLE_A = ("X/1", "X/2", "1/2", "2/1")
CELLE_B = ("X/1", "2/1")      # X2 primo tempo → 1 finale
CELLE_C = ("X/2", "1/2")      # 1X primo tempo → 2 finale


def init_htft_tables():
    """Crea la tabella. Idempotente: gira a ogni avvio (Restart=always)."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS htft_odds(
        fixture_id  INTEGER,
        cella       TEXT,
        odd_ref     REAL,
        odd_med     REAL,
        odd_min     REAL,
        odd_max     REAL,
        n_bk        INTEGER,
        captured_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(fixture_id, cella))""")
    conn.commit()
    conn.close()


def _agg(valori):
    if not valori:
        return None
    return {"med": round(statistics.median(valori), 2),
            "min": min(valori), "max": max(valori), "n": len(valori)}


def parse(raw):
    """Dalla risposta `/odds` alle nove celle: {cella: {ref, agg}}.

    `ref` e' la quota di 1xBet (None se quel bookmaker non quota la partita),
    `agg` mediana/min/max su tutti i bookmaker che la quotano.
    Non solleva mai: una risposta malformata vale zero celle.
    """
    per_cella = {}
    ref = {}
    try:
        for partita in raw or []:
            for bk in (partita or {}).get("bookmakers", []) or []:
                nome = (bk or {}).get("name")
                for bet in (bk or {}).get("bets", []) or []:
                    if (bet or {}).get("id") != HTFT_BET_ID:
                        continue
                    for v in bet.get("values", []) or []:
                        cella = CELLE.get(v.get("value"))
                        if not cella:
                            continue
                        try:
                            quota = float(v.get("odd"))
                        except (TypeError, ValueError):
                            continue
                        if quota <= 0:
                            continue
                        per_cella.setdefault(cella, []).append(quota)
                        if nome == REF_BOOKMAKER:
                            ref[cella] = quota
    except Exception as e:
        log.error(f"htft parse: {e}")
        return {}
    return {c: {"ref": ref.get(c), "agg": _agg(q)} for c, q in per_cella.items()}


def save(fixture_id, raw):
    """Salva le celle per una partita. Ritorna quante ne ha scritte.

    NON SOLLEVA MAI: sta dentro `fetch_prematch_odds`, che serve al prompt
    dell'AI. Se questo esplode, il pronostico non deve saltare.
    """
    try:
        celle = parse(raw)
        if not celle:
            return 0
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.executemany(
                "INSERT OR REPLACE INTO htft_odds"
                "(fixture_id,cella,odd_ref,odd_med,odd_min,odd_max,n_bk) "
                "VALUES(?,?,?,?,?,?,?)",
                [(fixture_id, c, v["ref"],
                  (v["agg"] or {}).get("med"), (v["agg"] or {}).get("min"),
                  (v["agg"] or {}).get("max"), (v["agg"] or {}).get("n"))
                 for c, v in celle.items()])
            conn.commit()
        finally:
            conn.close()
        n_ref = sum(1 for v in celle.values() if v["ref"] is not None)
        log.info(f"htft: fixture {fixture_id} — {len(celle)} celle "
                 f"({n_ref} da {REF_BOOKMAKER})")
        return len(celle)
    except Exception as e:
        log.error(f"htft save {fixture_id}: {e}")
        return 0


def get_cells(fixture_id):
    """{cella: quota} per una partita. 1xBet se c'e', mediana altrimenti."""
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            righe = conn.execute(
                "SELECT cella, odd_ref, odd_med FROM htft_odds WHERE fixture_id=?",
                (fixture_id,)).fetchall()
        finally:
            conn.close()
    except Exception as e:
        log.error(f"htft get_cells {fixture_id}: {e}")
        return {}
    out = {}
    for cella, ref, med in righe:
        q = ref if ref is not None else med
        if q:
            out[cella] = q
    return out


def combined(fixture_id, celle):
    """Quota combinata delle celle: `1 / Σ(1/quota)` — il dutching.

    E' quanto incassi giocando le celle a posta ripartita. NON e' la quota
    che il bookmaker espone sul mercato combinato («1X-2»), che prezza a
    parte e puo' differire.

    None se manca anche UNA sola cella: su tre celle invece di quattro la
    somma delle implicite e' piu' bassa e la quota risulterebbe piu' ALTA
    del vero — chi la legge si aspetterebbe un incasso che non arriva.
    """
    quote = get_cells(fixture_id)
    celle = tuple(celle or ())
    if not celle or any(c not in quote for c in celle):
        return None
    somma = sum(1.0 / quote[c] for c in celle)
    return (1.0 / somma) if somma > 0 else None


def cleanup(days=10):
    """Toglie le quote piu' vecchie di `days`. Ritorna quante righe.

    Il listino serve fino alla verifica della partita; dopo e' peso morto.
    Default 10 giorni: la partita si gioca entro 7 (retention API) e la
    verifica arriva la notte stessa.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            n = conn.execute(
                "DELETE FROM htft_odds WHERE captured_at < datetime('now',?)",
                (f"-{int(days)} days",)).rowcount
            conn.commit()
        finally:
            conn.close()
        return n
    except Exception as e:
        log.error(f"htft cleanup: {e}")
        return 0
