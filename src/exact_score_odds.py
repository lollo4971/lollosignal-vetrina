"""Raccolta quote del mercato Exact Score (id=10) di API-Football.

Modulo isolato: NON fa rete. Riceve la risposta /odds gia' scaricata da
match_data.fetch_prematch_odds, quindi non costa chiamate API aggiuntive.

ATTENZIONE: il mercato si chiama "Exact Score" (id 10). "Correct Score"
esiste ma indica primo tempo (id 31) e secondo tempo (id 62).

Spec: docs/superpowers/specs/2026-08-14-exact-score-odds-design.md
"""

import os
import json
import logging
import sqlite3
import statistics

# Nella vetrina i percorsi sono relativi al repository (in produzione: /opt/football-bot).
_RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


log = logging.getLogger(__name__)

DB_PATH = os.path.join(_RADICE, "signals.db")
EXACT_SCORE_BET_ID = 10
REF_BOOKMAKER = "1xBet"


def init_exact_score_tables():
    """Crea la tabella del listino e aggiunge le 3 colonne permanenti.
    Idempotente: segue il pattern di migrazione di match_data.py:41-45."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS exact_score_ladder(
        fixture_id  INTEGER,
        score       TEXT,
        odd_1xbet   REAL,
        odd_med     REAL,
        odd_min     REAL,
        odd_max     REAL,
        n_bk        INTEGER,
        captured_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(fixture_id, score))""")
    for coldef in ("odd_pred REAL", "odd_real REAL", "odds_json TEXT"):
        name = coldef.split()[0]
        try:
            conn.execute(f"SELECT {name} FROM prematch_predictions LIMIT 1")
        except sqlite3.OperationalError:
            # Stesso pattern difensivo di match_data.py:43-47: l'ALTER puo' fallire
            # per DB bloccato o colonna gia' aggiunta da un processo concorrente
            # (daily_prematch.py). Non deve mai impedire l'avvio del bot.
            try:
                conn.execute(f"ALTER TABLE prematch_predictions ADD COLUMN {coldef}")
                log.info(f"Migrazione: aggiunta colonna {name} a prematch_predictions")
            except sqlite3.OperationalError as e:
                log.warning(f"Migrazione {name} fallita (probabilmente già presente): {e}")
    conn.commit()
    conn.close()


def normalize_score(value):
    """'2:1' -> '2-1'. None se il formato non e' N:N o N-N."""
    if value is None:
        return None
    parts = str(value).strip().replace(":", "-").split("-")
    if len(parts) != 2:
        return None
    try:
        return f"{int(parts[0].strip())}-{int(parts[1].strip())}"
    except ValueError:
        return None


def _agg(values):
    """Aggrega una lista di quote. Stessa forma di match_data._agg_odds, senza spread."""
    if not values:
        return None
    return {"med": round(statistics.median(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "n": len(values)}


def parse_ladder(raw):
    """Estrae il mercato Exact Score dalla risposta /odds.
    Ritorna {"2-1": {"x1": float|None, "agg": {...}|None}}. {} se assente."""
    if not raw:
        return {}
    per_score = {}
    ref = {}
    for entry in raw:
        for bk in entry.get("bookmakers", []):
            bk_name = bk.get("name", "")
            for bet in bk.get("bets", []):
                if bet.get("id") != EXACT_SCORE_BET_ID:
                    continue
                for v in bet.get("values", []):
                    score = normalize_score(v.get("value"))
                    if not score:
                        continue
                    try:
                        odd = float(v.get("odd"))
                    except (TypeError, ValueError):
                        continue
                    per_score.setdefault(score, []).append(odd)
                    if bk_name == REF_BOOKMAKER:
                        ref[score] = odd
    return {s: {"x1": ref.get(s), "agg": _agg(o)} for s, o in per_score.items()}


def save_ladder(fixture_id, raw):
    """Salva il listino per una fixture. Ritorna il numero di punteggi salvati."""
    ladder = parse_ladder(raw)
    if not ladder:
        log.info(f"exact_score: nessun listino per fixture {fixture_id}")
        return 0
    conn = sqlite3.connect(DB_PATH)
    conn.executemany(
        "INSERT OR REPLACE INTO exact_score_ladder"
        "(fixture_id,score,odd_1xbet,odd_med,odd_min,odd_max,n_bk) "
        "VALUES(?,?,?,?,?,?,?)",
        [(fixture_id, s, v["x1"],
          (v["agg"] or {}).get("med"), (v["agg"] or {}).get("min"),
          (v["agg"] or {}).get("max"), (v["agg"] or {}).get("n"))
         for s, v in ladder.items()])
    conn.commit()
    conn.close()
    n_ref = sum(1 for v in ladder.values() if v["x1"] is not None)
    log.info(f"exact_score: fixture {fixture_id} — {len(ladder)} punteggi ({n_ref} da {REF_BOOKMAKER})")
    return len(ladder)


def get_odd(fixture_id, score):
    """Quota di un punteggio dal listino. Preferisce 1xBet, ripiega sulla mediana.
    None se il listino o il punteggio non ci sono."""
    score = normalize_score(score)
    if not score:
        return None
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT odd_1xbet,odd_med,odd_min,odd_max,n_bk FROM exact_score_ladder "
        "WHERE fixture_id=? AND score=?", (fixture_id, score)).fetchone()
    conn.close()
    if not row:
        return None
    x1, med, mn, mx, n = row
    odd, src = (x1, "1xbet") if x1 is not None else (med, "med")
    if odd is None:
        return None
    return {"odd": odd, "src": src,
            "agg": {"med": med, "min": mn, "max": mx, "n": n}}


def combined_odd(fixture_id, scores):
    """Quota combinata di piu' punteggi: 1 / Σ(1/quota).

    E' il "dutching": quanto incassi giocando i punteggi a posta ripartita.
    Serve per il gruppo «Ris.Esatto MultiEsiti 4», che sono quattro punteggi
    con una posta sola.

    NON e' la quota del mercato MultiEsiti di Planetwin365: quella dall'API
    non si legge — la partizione e' stata ricavata da schermate, e i suoi
    margini variano dal 12,5% all'84,6% da gruppo a gruppo (misurato 21/08).
    Questa e' una quota vera e giocabile, ma su un altro banco.

    None se anche UN SOLO punteggio non e' quotato. Su tre punteggi invece
    che quattro la somma delle implicite e' piu' bassa, quindi la quota
    verrebbe piu' ALTA del vero: chi la legge si aspetterebbe un incasso che
    non arrivera' mai. Meglio nessuna quota che una gonfiata.
    """
    scores = [normalize_score(s) for s in (scores or ())]
    if not scores or not all(scores):
        return None
    conn = sqlite3.connect(DB_PATH)
    try:
        righe = conn.execute(
            f"SELECT score, odd_1xbet, odd_med FROM exact_score_ladder "
            f"WHERE fixture_id=? AND score IN ({','.join('?' * len(scores))})",
            [fixture_id, *scores]).fetchall()
    finally:
        conn.close()
    # Stessa preferenza di get_odd: 1xBet (conto reale), mediana come ripiego.
    # `if q` scarta anche lo zero, che farebbe esplodere la divisione.
    quote = {}
    for s, x1, med in righe:
        q = x1 if x1 is not None else med
        if q:
            quote[s] = q
    if len(quote) < len(set(scores)):
        return None
    somma = sum(1.0 / quote[s] for s in scores)
    return (1.0 / somma) if somma > 0 else None


def save_pred_odd(fixture_id, score):
    """Scrive odd_pred (snapshot delle 09:00). Ritorna la quota o None.
    NON viene mai riscritta da collapse(): e' il prezzo disponibile alla pubblicazione."""
    r = get_odd(fixture_id, score)
    if not r:
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE prematch_predictions SET odd_pred=? WHERE fixture_id=?",
                 (r["odd"], fixture_id))
    conn.commit()
    conn.close()
    return r["odd"]


def get_stored_pred_odd(fixture_id):
    """Legge odd_pred dalla colonna permanente (utile dopo il collasso del listino)."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT odd_pred FROM prematch_predictions WHERE fixture_id=?",
                       (fixture_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def collapse(fixture_id, pred, real):
    """Alla verifica: scrive odd_real e odds_json, poi CANCELLA il listino.
    odd_pred NON viene toccata (resta lo snapshot delle 09:00).
    Ritorna {"pred": float|None, "real": float|None}."""
    r_pred = get_odd(fixture_id, pred)
    r_real = get_odd(fixture_id, real)
    payload = {
        "pred": {"score": normalize_score(pred),
                 "odd": (r_pred or {}).get("odd"),
                 "src": (r_pred or {}).get("src"),
                 "agg": (r_pred or {}).get("agg")},
        "real": {"score": normalize_score(real),
                 "odd": (r_real or {}).get("odd"),
                 "src": (r_real or {}).get("src"),
                 "agg": (r_real or {}).get("agg")},
    }
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE prematch_predictions SET odd_real=?, odds_json=? WHERE fixture_id=?",
                 ((r_real or {}).get("odd"), json.dumps(payload), fixture_id))
    conn.execute("DELETE FROM exact_score_ladder WHERE fixture_id=?", (fixture_id,))
    conn.commit()
    conn.close()
    return {"pred": (r_pred or {}).get("odd"), "real": (r_real or {}).get("odd")}


def cleanup(days=4):
    """Elimina i listini orfani (partite mai verificate). Ritorna le righe rimosse."""
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("DELETE FROM exact_score_ladder "
                     "WHERE captured_at < datetime('now', ?)", (f"-{days} days",)).rowcount
    conn.commit()
    conn.close()
    if n:
        log.info(f"exact_score cleanup: {n} righe di listino rimosse (>{days} giorni)")
    return n
