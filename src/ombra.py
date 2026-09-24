# ombra.py
"""Modalita' ombra del modello statistico storico.

Confronta, per ogni segnale live inviato, la probabilita' del modello
statistico (modello_storico.py, validato su 7.492 partite) con la
confidenza dell'AI e la quota di mercato. Scrive il confronto in un
database SEPARATO (`ombra.db`, non `signals.db`): stessa ragione per cui
`storico.db` e' separato (vedi storico_db.py) — i dati sperimentali non
devono ne' rischiare lock concorrenti sul database di produzione ne'
finire nei backup che contengono chat_id e codici degli abbonati.

REGOLA ASSOLUTA: questo modulo non deve MAI poter cambiare o bloccare un
segnale. `registra` intercetta qualunque eccezione al proprio interno e non
la rilancia mai: se il modello esplode, il bot deve comportarsi come se la
modalita' ombra non esistesse. bot.py, dal canto suo, avvolge comunque ogni
chiamata in un try/except (difesa in profondita', non fiducia cieca in
questo modulo).

`registra` e' sincrona, chiamata da bot.py DOPO che il segnale e' gia'
stato inviato su Telegram (send_msg avviene prima di save_signal in
entrambi i punti di chiamata): un rallentamento qui non ritarda mai la
consegna del messaggio. Deliberatamente NON e' su un thread separato: in
CPython il GIL fa si' che un thread non renda il lavoro CPU-bound (il fit
del modello) davvero non-bloccante, lo spalma soltanto, aggiungendo una
classe di concorrenza sqlite in piu' senza un guadagno reale. La cache dei
parametri viene invece scaldata una sola volta, a monte, con
`scalda_cache()` chiamata da bot.py:init_db() prima che parta il polling
live: cosi' il costo del fit a freddo (fino a alcune centinaia di ms sulle
leghe piu' popolate) non lo paga mai un segnale vero.

Nessuna dipendenza nuova: solo libreria standard + modello_storico/storico_db
gia' presenti nel progetto.
"""
import logging
import os
import re
import sqlite3
import time
from datetime import datetime

from modello_storico import (
    lambde, matrice_da_minuto, prob_gg, prob_over,
    quota_gol_primo_tempo, stima_parametri, stima_rho,
)
from storico_db import PERCORSO_DB, leggi_partite

log = logging.getLogger(__name__)

# Database separato da signals.db — vedi il motivo nel docstring del modulo.
PERCORSO_OMBRA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ombra.db")

# Sotto questa soglia di partite il fit non e' abbastanza affidabile da
# usare: meglio nessun numero che un numero rumoroso.
_MIN_PARTITE = 100

# Cache dei parametri per lega: {league_id: (timestamp, parametri, rho, quota_pt)}.
# stima_parametri su ~1500 partite costa ~10ms, non e' un problema di per se',
# ma non ha senso rifarlo ad ogni segnale quando il campione storico cambia
# al piu' una volta al giorno (lo scarica scarica_storico.py).
_cache = {}
_CACHE_TTL_SECONDI = 24 * 60 * 60

_RE_OVER = re.compile(r"^OVER_(\d+(?:\.\d+)?)(_PT)?$")


def init_ombra(path):
    """Crea la tabella confronto_modello nel database ombra (`path`, di
    norma PERCORSO_OMBRA — mai signals.db), se non gia' presente.

    Chiamata da bot.py:init_db() dopo le altre CREATE TABLE, sempre dentro un
    try/except lato bot.py: un guasto qui non deve impedire l'avvio del bot.
    """
    conn = sqlite3.connect(path)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS confronto_modello(
            signal_id INTEGER PRIMARY KEY,
            fixture_id INTEGER,
            league_id INTEGER,
            tipo TEXT,
            minuto INTEGER,
            punteggio TEXT,
            prob_modello REAL,
            conf_ai INTEGER,
            quota_mercato REAL,
            prob_mercato REAL,
            esito TEXT,
            creato_il TEXT)""")
        conn.commit()
    finally:
        conn.close()


def _parametri_lega(league_id, path_storico=None):
    """Parametri del modello per una lega, con cache di 24 ore.

    Ritorna (parametri, rho, quota_pt) o None se lo storico non ha
    abbastanza partite per quella lega (fit inaffidabile).
    """
    path_storico = path_storico or PERCORSO_DB
    ora = time.time()
    voce = _cache.get(league_id)
    if voce is not None and (ora - voce[0]) < _CACHE_TTL_SECONDI:
        return voce[1], voce[2], voce[3]

    partite = leggi_partite(path_storico, league_id)
    if len(partite) < _MIN_PARTITE:
        # Dati insufficienti ora: se c'era una cache precedente (anche
        # scaduta) e' comunque meglio di niente. Altrimenti None.
        if voce is not None:
            return voce[1], voce[2], voce[3]
        return None

    parametri = stima_parametri(partite)
    rho = stima_rho(partite[-500:], parametri)
    quota_pt = quota_gol_primo_tempo(partite)
    _cache[league_id] = (ora, parametri, rho, quota_pt)
    return parametri, rho, quota_pt


def prob_del_modello(league_id, home_id, away_id, tipo, minuto, gol_casa, gol_ospite,
                      path_storico=None):
    """Probabilita' del modello statistico per il tipo di segnale dato.

    Ritorna None se non calcolabile: storico insufficiente, tipo non
    riconosciuto, o qualunque valore di input incoerente. Non solleva mai:
    e' pensata per essere chiamata anche con dati sporchi (vedi `registra`).
    """
    try:
        risultato = _parametri_lega(league_id, path_storico)
        if risultato is None:
            return None
        parametri, rho, quota_pt = risultato
        lam_h, lam_a = lambde(parametri, home_id, away_id)

        if tipo == "GG":
            matrice = matrice_da_minuto(lam_h, lam_a, minuto, gol_casa, gol_ospite,
                                         rho, quota_pt=quota_pt)
            return prob_gg(matrice)

        m_over = _RE_OVER.match(tipo) if isinstance(tipo, str) else None
        if m_over:
            linea = float(m_over.group(1))
            e_primo_tempo = m_over.group(2) is not None
            if e_primo_tempo:
                # Il minuto deve essere strettamente prima del 45': oltre,
                # "entro il 45'" e' un evento gia' deciso (0.0 o 1.0), un
                # numero che in una log-loss futura manderebbe a +-infinito
                # se sbagliato. Meglio nessun numero.
                if minuto is None or minuto >= 45:
                    return None
                # Orizzonte 45' invece di 90'. lam_h/lam_a sono i gol attesi
                # sull'INTERA partita: il budget dell'intero primo tempo e'
                # lam_h*quota_pt (non lam_h). Si scalano prima i lambda a
                # "gol attesi nei 45 minuti di primo tempo", POI si applica
                # lo stesso trucco — raddoppiare il minuto passato con
                # quota_pt=None, cosi' (90-2*minuto)/90 = (45-minuto)/45 —
                # per prendere solo la frazione di quel budget non ancora
                # giocata. Senza lo scaling per quota_pt si comprime l'intero
                # budget di partita (90') dentro 45', overstimando
                # sistematicamente (misurato: x2,25 su Premier League).
                matrice = matrice_da_minuto(lam_h * quota_pt, lam_a * quota_pt, 2 * minuto,
                                             gol_casa, gol_ospite, rho, quota_pt=None)
            else:
                matrice = matrice_da_minuto(lam_h, lam_a, minuto, gol_casa, gol_ospite,
                                             rho, quota_pt=quota_pt)
            return prob_over(matrice, linea)

        if tipo in ("CHI_SEGNA_PROSSIMO_CASA", "CHI_SEGNA_PROSSIMO_OSPITE"):
            totale = lam_h + lam_a
            if totale <= 0:
                return None
            # lam_h/(lam_h+lam_a) e' la probabilita' che, DATO che arriva
            # un altro gol, sia della casa (si semplifica nel rapporto: il
            # fattore tempo-residuo moltiplica entrambe le squadre allo
            # stesso modo). Ma l'esito del segnale (CLAUDE.md: "PERSO se
            # assente o di altra squadra") richiede che il gol arrivi
            # DAVVERO: va moltiplicata per P(almeno un altro gol nel tempo
            # restante), altrimenti si sovrastima via via che il tempo
            # residuo si riduce (misurato: fino a 37 punti percentuali
            # all'80'). Quella probabilita' si legge dalla stessa matrice
            # gia' usata per Over/GG: 1 meno la massa sul punteggio attuale
            # (nessun gol ulteriore = punteggio invariato).
            matrice = matrice_da_minuto(lam_h, lam_a, minuto, gol_casa, gol_ospite,
                                         rho, quota_pt=quota_pt)
            p_almeno_un_gol = 1.0 - matrice.get((gol_casa, gol_ospite), 0.0)
            quota_casa = lam_h / totale
            return p_almeno_un_gol * (quota_casa if tipo.endswith("CASA") else 1.0 - quota_casa)

        if tipo in ("RIBALTONE_CASA", "RIBALTONE_OSPITE"):
            # Limite noto: approssima "la squadra e' avanti a fine partita",
            # non il vero evento di verify_outcome (sorpasso in QUALSIASI
            # istante della timeline, valido anche se poi l'avversario
            # ripareggia). Senza cronologia gol storica (stesso limite
            # documentato in modello_storico.matrice_da_minuto) non si puo'
            # fare di meglio: questo tende a SOTTOSTIMARE l'evento vero,
            # perche' ignora i sorpassi temporanei poi ripareggiati.
            if gol_casa is None or gol_ospite is None:
                return None
            e_casa = tipo == "RIBALTONE_CASA"
            # La squadra indicata deve essere davvero in svantaggio ORA:
            # altrimenti "probabilita' di sorpasso" non ha senso (su
            # RIBALTONE_CASA chiamato sull'1-0 darebbe P(vittoria casa),
            # un numero alto e privo di senso, non un errore del modello).
            if e_casa and not (gol_casa < gol_ospite):
                return None
            if not e_casa and not (gol_ospite < gol_casa):
                return None
            matrice = matrice_da_minuto(lam_h, lam_a, minuto, gol_casa, gol_ospite,
                                         rho, quota_pt=quota_pt)
            if e_casa:
                return sum(v for (x, y), v in matrice.items() if x > y)
            return sum(v for (x, y), v in matrice.items() if y > x)

        return None
    except Exception:
        # Qualunque input sporco (None, tipi incoerenti, lega inesistente)
        # deve tradursi in "nessun numero", mai in un'eccezione che risale
        # al chiamante.
        return None


def registra(path, signal_id, fixture_id=None, league_id=None, home_id=None, away_id=None,
             tipo=None, minuto=None, gol_casa=None, gol_ospite=None,
             conf_ai=None, quota_mercato=None):
    """Scrive una riga di confronto ombra in confronto_modello.

    NON SOLLEVA MAI: qualunque errore (database assente o non inizializzato,
    valori nulli, tipo sconosciuto, quota incoerente) viene solo loggato.
    Questa e' la funzione che bot.py chiama dal flusso reale di invio dei
    segnali: deve essere innocua per costruzione, non solo per convenzione.

    Ritorna True se la riga e' stata scritta, False in ogni altro caso.
    """
    try:
        prob_modello = None
        if None not in (league_id, home_id, away_id, tipo, minuto, gol_casa, gol_ospite):
            prob_modello = prob_del_modello(league_id, home_id, away_id, tipo,
                                             minuto, gol_casa, gol_ospite)

        prob_mercato = None
        if quota_mercato is not None:
            try:
                q = float(quota_mercato)
                if q > 0:
                    prob_mercato = 1.0 / q
            except (TypeError, ValueError):
                prob_mercato = None

        punteggio = (f"{gol_casa}-{gol_ospite}"
                     if gol_casa is not None and gol_ospite is not None else None)

        conn = sqlite3.connect(path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO confronto_modello "
                "(signal_id, fixture_id, league_id, tipo, minuto, punteggio, "
                "prob_modello, conf_ai, quota_mercato, prob_mercato, esito, creato_il) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?)",
                (signal_id, fixture_id, league_id, tipo, minuto, punteggio,
                 prob_modello, conf_ai, quota_mercato, prob_mercato,
                 datetime.now().isoformat()))
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception as e:
        try:
            log.warning(f"Ombra: registra fallita per signal_id={signal_id}: {e}")
        except Exception:
            pass
        return False


def scalda_cache(path_storico=None, league_ids=None):
    """Pre-calcola (e mette in cache) i parametri per un elenco di leghe.

    Va chiamata UNA VOLTA all'avvio del bot (bot.py:init_db()), PRIMA che
    parta il polling live: cosi' `registra`, che gira sincrona dentro
    `save_signal`, trova quasi sempre la cache calda (~3-4ms) invece di
    pagare un fit a freddo (misurato fino a ~470ms sulle leghe piu'
    popolate) nel mezzo del ciclo dei segnali.

    Se una lega fallisce la salta e continua: non deve mai impedire
    l'avvio del bot. Se `league_ids` non e' dato, scalda tutte le leghe
    presenti nello storico. Ritorna il numero di leghe scaldate con successo.
    """
    path_storico = path_storico or PERCORSO_DB
    if league_ids is None:
        try:
            conn = sqlite3.connect(f"file:{path_storico}?mode=ro", uri=True)
            try:
                league_ids = [r[0] for r in conn.execute(
                    "SELECT DISTINCT league_id FROM partite").fetchall()]
            finally:
                conn.close()
        except Exception as e:
            log.warning(f"Ombra: impossibile elencare le leghe da scaldare: {e}")
            return 0
    n_ok = 0
    for lid in league_ids:
        try:
            if _parametri_lega(lid, path_storico) is not None:
                n_ok += 1
        except Exception as e:
            log.warning(f"Ombra: scaldamento cache fallito per lega {lid}: {e}")
    return n_ok
