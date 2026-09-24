"""Le due costanti del flusso abbonamenti, condivise fra bot e immagini.

PERCHE' UN MODULO E NON DUE RIGHE IN bot.py. Le stesse costanti servono al
richiamo in coda alle didascalie del canale (`immagine_esiti.RICHIAMO`), e
gli script delle immagini stanno FUORI da bot.py di proposito — importarlo
per leggere due numeri vorrebbe dire far partire diecimila righe e uno
scheduler. Stesso schema di `avvertenza.py`: una fonte sola, importata da
entrambi i mondi. bot.py le importa accanto a `PIANI`, che resta l'unico
posto dei prezzi.

PROVA_GIORNI — la durata della prova gratuita. Il numero compare nei
bottoni, nei messaggi, nel richiamo del gruppo e nei documenti: cambiarlo
qui li cambia tutti insieme.

PAGAMENTI_ATTIVI — L'UNICO INTERRUTTORE del flusso di vendita (11/09/2026).
Con False:
  - a fine prova l'utente riceve solo «prova terminata», senza bottoni;
  - vip:request risponde «iscrizioni al momento chiuse»;
  - il richiamo in coda a esiti e didascalie sparisce.
Con True tutto il flusso e' aperto: prova, scelta piano, PayPal, conferma.

SOSTITUISCE il cancello a data del 09/09 (`APERTURA_VIP` 01/11): la prova
da 15 giorni attivata a settembre scade PRIMA di novembre, e chi finisce la
prova deve poter pagare — le due cose non potevano convivere. La decisione
di quando aprire resta all'utente, ma ora e' un interruttore esplicito
invece di una data.
"""

PROVA_GIORNI = 15
PAGAMENTI_ATTIVI = True
