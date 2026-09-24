"""L'avvertenza di legge, in un posto solo.

PERCHE' UN MODULO SUO. Il testo esce in due mondi che non si parlano: le
immagini (`immagine_esiti.py` e le altre due, tenute FUORI da bot.py di
proposito, perche' un errore di Pillow non deve sfiorare il ciclo live) e i
messaggi Telegram (`bot.py`). Nessuno dei due puo' importare l'altro:
importare bot.py in uno script di disegno vorrebbe dire far partire diecimila
righe e uno scheduler per stampare una scritta.

Un file di due costanti che entrambi importano risolve la cosa che conta
davvero: **quando dopo la consulenza legale questo testo cambiera', deve
cambiare in tutti i posti insieme.** Due copie che divergono su
un'avvertenza legale sono peggio di nessuna avvertenza, perche' nessuno sa
piu' quale delle due e' quella vigente.

Scritta il 09/09/2026 su indicazione dell'utente, dopo un parere legale.
La parte obbligatoria — 18+, dipendenza patologica, gioco responsabile —
c'era gia' e non dipende da nessun parere. Quello che si e' aggiunto e' la
dichiarazione di COSA E' il prodotto, ed e' vera: LolloSignal e'
letteralmente un programma che elabora statistiche.

NIENTE MARKDOWN QUI DENTRO. Il testo viaggia anche in messaggi Telegram
inviati con parse_mode="Markdown": un underscore o un asterisco liberi
farebbero rifiutare l'invio con «Can't parse entities» — successo 38 volte
fra il 02 e il 24/08/2026. C'e' un test.
"""

AVVERTENZA = (
    "LolloSignal è un software di intelligenza artificiale che elabora "
    "analisi statistiche e storiche sulle performance sportive a scopo "
    "puramente informativo e di intrattenimento. Non fornisce consigli di "
    "gioco, non costituisce invito al betting né promuove il gioco "
    "d'azzardo. Le quote riportate sono ricavate da servizi API a "
    "pagamento e non sono espressione di alcun bookmaker. "
    "18+ · Il gioco può causare dipendenza patologica. "
    "Gioca responsabilmente.")

# Versione corta per i messaggi che ne portano gia' molte di righe. NON e'
# un'alternativa a piacere: la lunga sta sulle immagini e sui messaggi
# isolati, questa sui segnali live, che arrivano tre o quattro volte al
# giorno e con la lunga diventerebbero illeggibili. Entrambe contengono la
# parte obbligatoria per intero.
AVVERTENZA_BREVE = (
    "Analisi statistica automatica a scopo informativo. Non è un consiglio "
    "di gioco. Quote da servizi API a pagamento, non espressione di alcun "
    "bookmaker. 18+ · Il gioco può causare dipendenza patologica. "
    "Gioca responsabilmente.")
