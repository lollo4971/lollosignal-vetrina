"""Il modello come VETO sui segnali live, non come proponente.

PERCHE' (22/09/2026). Fra le tre fonti misurate sulla modalita' ombra il
modello e' l'unica calibrata:

    modello  fascia 55-70%: dichiara 62,8% -> rende 60,0%   (scarto  -2,8)
    modello  fascia 40-55%: dichiara 47,1% -> rende 30,0%   (scarto -17,1)
    AI       fascia >70%:   dichiara 79,1% -> rende 41,0%   (scarto -38,0)

E sui 75 CHI_SEGNA nati dal cartellino rosso diceva 33,1% contro un esito
reale del 37,3%: aveva ragione, ma non veniva interpellato.

LA REGOLA, E PERCHE' NON E' LA CACCIA AL VALORE. Nel prematch scegliere
il massimo edge ha prodotto danni (misura del 24/08: «cercare il massimo
valore seleziona i propri errori»). Qui il modello **non propone nulla**:
guarda un segnale che qualcun altro ha gia' deciso e puo' solo dire «a
questo prezzo no». Togliere e' molto piu' sicuro che scegliere.

DOVE SI APPLICA. Solo sui tipi dove il modello e' misurato meglio
dell'AI. Gli OVER a 90 minuti rendono 53-66% e funzionano: la' il veto
non serve e allargarlo sarebbe una decisione da prendere sui dati, non
per simmetria.

Test: test_veto_modello.py.
"""
import logging

log = logging.getLogger(__name__)

# Margine sopra il pareggio. Non zero: anche il modello sbaglia — nella
# fascia 40-55% sovrastima di 17 punti — e un veto che lascia passare
# esattamente il pareggio non protegge da niente.
MARGINE_VETO = 0.10

# I tipi dove il modello ha voce. Prefissi, come in quota_filter.
TIPI_CON_VETO = ("CHI_SEGNA_PROSSIMO", "GG", "RIBALTONE", "OVER_0.5_PT")


def veto(tipo, prob_modello, quota_reale):
    """(passa, motivo). `passa=False` = il modello blocca il segnale.

    Passa sempre quando non puo' giudicare: nessuna stima (il modello non
    copre tutte le leghe — 40 righe su 148 nella modalita' ombra), nessuna
    quota, tipo fuori elenco. Un veto muto non deve diventare un divieto.
    """
    if not tipo or not any(tipo.startswith(p) for p in TIPI_CON_VETO):
        return True, "tipo senza veto del modello"
    try:
        p = float(prob_modello) if prob_modello is not None else None
        q = float(quota_reale) if quota_reale is not None else None
    except (TypeError, ValueError):
        return True, "valori non leggibili: nessun veto"
    if p is None or p <= 0:
        return True, "nessuna stima del modello: nessun veto"
    if q is None or q <= 0:
        return True, "quota assente: valore non calcolabile"
    atteso = p * q
    soglia = 1 + MARGINE_VETO
    if atteso >= soglia:
        return True, (f"modello {p:.0%} × quota {q:.2f} = {atteso:.2f} "
                      f"(≥ {soglia:.2f})")
    minima = soglia / p
    return False, (f"modello {p:.0%} × quota {q:.2f} = {atteso:.2f}: "
                   f"serve almeno {minima:.2f}")
