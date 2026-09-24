"""Il profilo storico di una lega, per il prompt prematch dell'AI.

PERCHE' (17/09/2026, richiesta dell'utente). Le leghe hanno caratteri
misurati e stabili — Eerste Divisie 3,08 gol/partita e 61% di Over 2.5,
Segunda 2,37 e 43%; pareggi al 31,8% in Serie B contro il 22,4% in
Olanda — ma l'AI non li riceveva: doveva ricordarseli dalla cultura
generale, vaga sulle seconde divisioni. Ora li legge da storico.db
(5 stagioni, zero API, zero costo).

REGOLE:
- SOLO campionati: per le coppe c'e' gia' la riga dei coefficienti UEFA,
  e i tassi storici di una coppa mischiano preliminari e fasi finali;
  il criterio e' `valida_modello.e_coppa`, lo stesso del modello.
- Sotto MINIMO_PARTITE_LEGA (400) niente profilo: un tasso su poche
  partite e' rumore travestito da carattere.
- Ogni guaio (archivio assente, lega ignota) -> None, mai un'eccezione:
  la scheda esce come oggi, senza la riga.

Test: test_profilo_lega.py.
"""
import os
import logging

# Nella vetrina i percorsi sono relativi al repository (in produzione: /opt/football-bot).
_RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


log = logging.getLogger(__name__)

STORICO = os.path.join(_RADICE, "storico.db")

_cache = {}


def profilo(league_id, path=STORICO):
    """dict {gol_medi, over25, gg, ht_over05, pareggi, n} o None.

    Cache di processo per (path, lega): tassi_lega rilegge migliaia di
    righe, e il batch chiede la stessa lega piu' volte al giorno.
    """
    chiave = (path, league_id)
    if chiave in _cache:
        return _cache[chiave]
    try:
        from prematch_adattivo import MINIMO_PARTITE_LEGA, tassi_lega
        from storico_db import leggi_partite
        from valida_modello import e_coppa

        partite = leggi_partite(path, league_id)
        if len(partite) < MINIMO_PARTITE_LEGA or e_coppa(partite):
            _cache[chiave] = None
            return None
        t = tassi_lega(path, league_id)
        ris = {
            "gol_medi": t["gol_medi"],
            "over25": t["over25"],
            "gg": t["gg"],
            "ht_over05": t["ht_over05"],
            "pareggi": sum(1 for r in partite
                           if r["ft_home"] == r["ft_away"]) / len(partite),
            "n": len(partite),
        }
        _cache[chiave] = ris
        return ris
    except Exception as e:
        log.warning(f"profilo_lega {league_id}: {e}")
        _cache[chiave] = None
        return None


def riga_prompt(league_id, path=STORICO):
    """Le due righe per il prompt dell'AI, o None se non spettano."""
    p = profilo(league_id, path)
    if not p:
        return None
    return (f"PROFILO LEGA (storico 5 stagioni, {p['n']} partite): "
            f"media gol {p['gol_medi']:.1f} · "
            f"Over 2.5 {p['over25']:.0%} · GG {p['gg']:.0%} · "
            f"gol nel 1ºT {p['ht_over05']:.0%} · "
            f"pareggi {p['pareggi']:.0%}\n"
            f"Questi sono i tassi di base della lega: ancora i pronostici "
            f"Over/GG/1X2 a questi valori, la forma recente li sposta poco.")
