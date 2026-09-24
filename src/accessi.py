"""Policy accessi a due stati.

Decisa il 05/06/2026, implementata il 16/08/2026.

Il bug del 04/06: un abbonato scaduto finiva in `blocked_users`, la stessa
tabella dei bannati. Ne seguivano due guai — chi rinnovava restava murato
fuori perche' nessuno lo toglieva da li', e non si distingueva piu' chi era
semplicemente scaduto da chi aveva violato le regole.

I due stati hanno natura diversa:
  SCADUTO  automatico a fine abbonamento, REVERSIBILE pagando
  BANNATO  solo manuale, per violazione; riammissione a giudizio dell'admin

Da qui la scelta di fondo: "scaduto" NON si memorizza, si ricava da
`expires`. `blocked_users` resta solo per i ban. Cosi' il secondo bug non
va corretto, sparisce: rinnovare riporta ad attivo senza dover sbloccare
niente.
"""
from datetime import datetime, timedelta

STATO_ATTIVO = "attivo"
STATO_SCADUTO = "scaduto"
STATO_BANNATO = "bannato"
STATO_SCONOSCIUTO = "sconosciuto"

# Formato canonico. In DB ne convivono due ('2026-07-20T21:27:58.050288' e
# '2027-04-19 23:14:01') e confrontarli come stringhe e' sbagliato: 'T' viene
# dopo lo spazio, quindi un orario del mattino risulta successivo a uno della
# sera dello stesso giorno.
FORMATO = "%Y-%m-%d %H:%M:%S"


def _parse(value):
    """datetime da qualunque forma usata in DB, None se illeggibile."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    testo = str(value).strip()
    if not testo:
        return None
    try:
        return datetime.fromisoformat(testo)
    except ValueError:
        return None


def normalize_expires(value):
    """Scadenza nel formato canonico, None se non interpretabile."""
    dt = _parse(value)
    return dt.strftime(FORMATO) if dt else None


def is_expired(expires, now=None):
    """True se la scadenza e' passata. expires assente = nessuna scadenza."""
    dt = _parse(expires)
    if dt is None:
        return False
    return dt < (now or datetime.now())


def renewal_expires(expires, days, now=None):
    """Nuova scadenza dopo un rinnovo di `days` giorni.

    Si parte dalla piu' avanzata fra scadenza attuale e oggi:
      - scaduto da tempo -> riparte da oggi, non perde i giorni in mezzo
      - ancora attivo    -> si estende dalla scadenza, non perde i residui

    La formula precedente, `datetime(expires, '+N days')`, partiva sempre
    dalla vecchia scadenza: chi rinnovava dopo mesi poteva restare scaduto
    anche dopo aver pagato.
    """
    if days <= 0:
        raise ValueError(f"giorni di rinnovo non validi: {days}")
    adesso = now or datetime.now()
    attuale = _parse(expires)
    base = max(attuale, adesso) if attuale else adesso
    return (base + timedelta(days=days)).strftime(FORMATO)


def stato_accesso(expires, banned, now=None, esiste=True):
    """Stato di accesso di un utente. Accede SOLO chi risulta attivo.

    Il ban prevale su tutto: e' una sanzione, non dipende dal pagamento.
    """
    if banned:
        return STATO_BANNATO
    if not esiste:
        return STATO_SCONOSCIUTO
    return STATO_SCADUTO if is_expired(expires, now) else STATO_ATTIVO
