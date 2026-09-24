"""Coefficienti UEFA per club: il dato in piu' per i pronostici di coppa.

PERCHE' (17/09/2026). Il modello statistico non entra nelle coppe europee
(misurato peggio della climatologia, vedi valida_modello) e l'AI, senza
precedenti diretti e con la «forma» presa da campionati di livello
diverso, si appoggia quasi solo alle quote. Il coefficiente UEFA e' il
criterio con cui la UEFA compone le fasce del sorteggio: misura la forza
strutturale in Europa. Lo si da' all'AI SOLO per UCL/UEL/UECL e lo si
registra accanto al pronostico per misurarne l'effetto fra un mese.

FONTE: data/coefficienti_uefa_2026_27_ids.csv — 108 squadre (36 per
competizione), gia' allineate ai team_id API-Football il 17/09/2026
(106 automatiche + Bayern München id 157 e St. Truiden id 735, unici
candidati nelle rispettive fasi campionato). Le qualificazioni restano
fuori da sole: chi e' uscito ai preliminari non e' nel file.

REGOLE:
- il cancello e' il league_id della PARTITA (2/3/848), non la tabella:
  Getafe-Real Madrid in Liga non ha la riga anche se entrambe sono qui;
- 0 o 2+ candidati nell'abbinamento nomi NON sono un abbinamento
  («le correggo a mano, non tirare a indovinare»);
- file mancante -> WARNING una volta e il bot continua come oggi;
- il «fascia X di N» viene dai dati (UCL/UEL 4 urne, Conference 6),
  non da una costante.

Test: test_coefficienti_uefa.py.
"""
import os
import csv
import logging
import unicodedata

# Nella vetrina i percorsi sono relativi al repository (in produzione: /opt/football-bot).
_RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


log = logging.getLogger(__name__)

CSV_IDS = os.path.join(_RADICE, "data/coefficienti_uefa_2026_27_ids.csv")

# league_id API-Football delle tre fasi campionato UEFA.
COPPE_UEFA = {2: "UCL", 3: "UEL", 848: "UECL"}

_FRASE_LETTURA = ("In coppa i precedenti diretti e la forma nel campionato "
                  "nazionale valgono poco; il coefficiente pesa piu' della "
                  "forma recente quando il rapporto supera 3:1.")


def norm(s):
    """Minuscole, senza accenti, senza punteggiatura: la base del match."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join("".join(c if c.isalnum() or c == " " else " "
                            for c in s.lower()).split())


def abbina(alias, club, candidati):
    """team_id abbinato, o None. candidati = [(team_id, nome_api)].

    Tre passate in ordine di fiducia: alias esatto, club esatto,
    contenimento. Ogni passata deve dare UN candidato: zero o piu' di uno
    non sono un abbinamento — si segnala, mai si indovina.
    """
    na, nc = norm(alias), norm(club)
    prove = (lambda n: n == na, lambda n: n == nc,
             lambda n: na in n or n in na or nc in n or n in nc)
    for prova in prove:
        trovati = [tid for tid, nome in candidati if prova(norm(nome))]
        if trovati:
            return trovati[0] if len(trovati) == 1 else None
    return None


_tabella = None
_avvisato = False


def carica(percorso=CSV_IDS):
    """dict team_id -> {club, competizione, fascia, coefficiente,
    fasce_tot}. Cache di processo sul percorso di default; file mancante
    o rotto -> {} con UN warning, il bot continua come oggi."""
    global _tabella, _avvisato
    if percorso == CSV_IDS and _tabella is not None:
        return _tabella
    tab = {}
    try:
        with open(percorso, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if not r.get("team_id"):
                    continue
                tab[int(r["team_id"])] = {
                    "club": r["club"],
                    "competizione": r["competizione"],
                    "fascia": int(r["fascia"]),
                    "coefficiente": float(r["coefficiente"]),
                }
        fasce_tot = {}
        for d in tab.values():
            fasce_tot[d["competizione"]] = max(
                fasce_tot.get(d["competizione"], 0), d["fascia"])
        for d in tab.values():
            d["fasce_tot"] = fasce_tot[d["competizione"]]
    except Exception as e:
        if not _avvisato:
            log.warning(f"coefficienti UEFA non caricati ({e}): "
                        f"i pronostici di coppa proseguono senza")
            _avvisato = True
        tab = {}
    if percorso == CSV_IDS and tab:
        _tabella = tab
    return tab


def _dati_coppia(league_id, home_id, away_id, nomi=None):
    """(dati_casa, dati_ospite) se la partita e' di coppa UEFA ed entrambe
    sono in tabella, altrimenti None — con l'INFO dei non abbinati."""
    if league_id not in COPPE_UEFA:
        return None
    t = carica()
    dc, do = t.get(home_id), t.get(away_id)
    if dc and do:
        return dc, do
    if t:                          # tabella carica ma squadra assente
        etichette = nomi or (home_id, away_id)
        chi = []
        if not dc:
            chi.append(str(etichette[0]))
        if not do:
            chi.append(str(etichette[1]))
        log.info(f"coefficienti UEFA: non in tabella {', '.join(chi)} "
                 f"({COPPE_UEFA[league_id]})")
    return None


def _formatta_rapporto(a, b):
    """«15:1» sopra il 3 (il decimale li' e' rumore), «2.3:1» sotto,
    dove la frase di lettura ha bisogno della precisione."""
    r = max(a, b) / min(a, b) if min(a, b) > 0 else 0
    testo = f"{r:.0f}" if r >= 3 else f"{r:.1f}".rstrip("0").rstrip(".")
    return f"{testo}:1"


def riga_prompt(league_id, home_id, away_id, nomi=None):
    """La riga per il prompt dell'AI, o None se non spetta.

    None nei tre casi: non e' una coppa UEFA, tabella assente, una delle
    due squadre non abbinata (con log INFO per vedere chi manca).
    """
    coppia_dati = _dati_coppia(league_id, home_id, away_id, nomi)
    if not coppia_dati:
        return None
    dc, do = coppia_dati
    return (f"Coefficiente UEFA (forza strutturale in Europa, base delle "
            f"fasce del sorteggio): "
            f"{dc['club']} {dc['coefficiente']:.1f} "
            f"(fascia {dc['fascia']} di {dc['fasce_tot']}) · "
            f"{do['club']} {do['coefficiente']:.1f} "
            f"(fascia {do['fascia']} di {do['fasce_tot']}). "
            f"Rapporto {_formatta_rapporto(dc['coefficiente'], do['coefficiente'])}.\n"
            f"{_FRASE_LETTURA}")


def coppia(league_id, home_id, away_id):
    """(coeff_casa, coeff_ospite, fascia_casa, fascia_ospite) per il
    registro, o quattro None se la riga non spetta."""
    coppia_dati = _dati_coppia(league_id, home_id, away_id)
    if not coppia_dati:
        return (None, None, None, None)
    dc, do = coppia_dati
    return (dc["coefficiente"], do["coefficiente"],
            dc["fascia"], do["fascia"])
