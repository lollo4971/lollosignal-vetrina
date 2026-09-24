"""Archivio storico dei risultati: database SEPARATO da signals.db.

Separato di proposito: sono dati pubblici e rigenerabili, non vanno a
gonfiare i backup di signals.db che contengono chat_id e codici degli
abbonati, e un archivio corrotto non puo' toccare la produzione.
"""
import os
import sqlite3

PERCORSO_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storico.db")

_CAMPI = ("fixture_id", "league_id", "season", "data", "home_id", "away_id",
          "home_nome", "away_nome", "ht_home", "ht_away", "ft_home", "ft_away")


def init_storico(path=PERCORSO_DB):
    conn = sqlite3.connect(path)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS partite (
            fixture_id INTEGER PRIMARY KEY,
            league_id  INTEGER NOT NULL,
            season     INTEGER NOT NULL,
            data       TEXT    NOT NULL,
            home_id    INTEGER NOT NULL,
            away_id    INTEGER NOT NULL,
            home_nome  TEXT,
            away_nome  TEXT,
            ht_home    INTEGER,
            ht_away    INTEGER,
            ft_home    INTEGER NOT NULL,
            ft_away    INTEGER NOT NULL)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lega_stagione ON partite(league_id, season)")
        conn.commit()
    finally:
        conn.close()


def salva_partite(path, partite):
    """Inserisce, ignorando i duplicati. Scarta le partite senza risultato."""
    valide = [p for p in partite
              if p.get("ft_home") is not None and p.get("ft_away") is not None]
    if not valide:
        return 0
    conn = sqlite3.connect(path)
    try:
        cur = conn.executemany(
            f"INSERT OR IGNORE INTO partite ({','.join(_CAMPI)}) "
            f"VALUES ({','.join('?' * len(_CAMPI))})",
            [tuple(p.get(c) for c in _CAMPI) for p in valide])
        n = cur.rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def leggi_partite(path, league_id, escludi_stagione=None):
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        if escludi_stagione is None:
            rows = conn.execute("SELECT * FROM partite WHERE league_id=? ORDER BY data",
                                (league_id,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM partite WHERE league_id=? AND season<>? ORDER BY data",
                (league_id, escludi_stagione)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
