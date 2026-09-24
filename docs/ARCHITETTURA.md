# Architettura

Il sistema gira su una VPS Linux come servizio `systemd`, con timer separati per i
lavori che non devono poter fermare il ciclo live.

## Componenti

| Parte | Tecnologia | Note |
|---|---|---|
| Bot e scheduler | Python 3.12, `python-telegram-bot`, APScheduler | un processo, riavvio automatico |
| Dati calcistici | API-Football | budget di 7.500 chiamate/giorno, cache con scadenza per tipo di dato |
| AI live | Claude Haiku | ~95% delle chiamate, prompt di sistema in cache (~5.700 token) |
| AI pre-partita | Claude Sonnet | una scheda per partita, cache per partita e giorno |
| Modello statistico | Dixon-Coles su `storico.db` | 44 leghe × 5 stagioni, rigenerabile dall'API |
| Database | SQLite (`signals.db`, `storico.db`, `ombra.db`) | database separati per ruolo |
| Immagini | Pillow | script fuori dal processo principale |
| Autocontrollo | `checkup_live.py` (timer 23:30) | report serale all'amministratore |

## Il percorso di un segnale live

1. **Acquisizione.** Elenco delle partite in corso (cache 60 s), poi per le partite in
   whitelist statistiche, eventi e quote. La frequenza è adattiva: ogni **8 minuti**
   nella fase calda (45'-80'), ogni **16** nella fredda, subito se un evento (rosso,
   rigore, VAR) segna la partita come prioritaria.
2. **Lettura.** L'AI riceve un payload con statistiche, eventi, quote, forma e contesto
   di lega, e propone un segnale con una confidenza.
3. **Tre cancelli**, tutti in codice e non nel prompt:
   - **finestra temporale**: ogni fascia di minuti ammette solo certi tipi;
   - **convergenza dei dati** (`live_data.py`): due indicatori concordi *nella
     direzione del segnale* permettono una confidenza più bassa, ma non aprono le
     finestre chiuse né aggirano il prezzo;
   - **prezzo minimo** (`quota_filter.py`): la soglia più severa fra quella statica e
     quella ricavata dal win rate degli ultimi 180 giorni.
4. **Veto del modello** (`veto_modello.py`): dove il modello ha una stima e il mercato
   una quota, il segnale passa solo se `probabilità × quota ≥ 1,10`. Se non può
   giudicare, lascia passare.
5. **Emissione e registro.** Il messaggio parte e il contesto di emissione viene
   salvato, incluso il confronto modello/AI/mercato della modalità ombra.
6. **Verifica.** Una funzione pura, `verify_outcome`, decide l'esito di ogni tipo di
   segnale sulla timeline degli eventi. Ogni notte l'audit la rilancia e corregge il
   database.

## Scelte di robustezza

- **Chi non riconosce un errore lo considera proprio.** L'autocontrollo separa gli
  errori del fornitore e di rete da quelli del codice, ma tutto ciò che non sa
  classificare lo tratta come difetto nostro e dà l'allarme.
- **Default prudenti.** Una pubblicazione nuova che dimentica di dichiarare l'origine
  finisce *fuori* dalle statistiche pubblicate, non dentro.
- **Un solo posto per ogni verità.** Prezzi, avvertenza legale e versione hanno ognuno
  una sola fonte. Due copie di un'avvertenza che divergono sono peggio di nessuna.
- **Gli invii non sollevano mai eccezioni.** Nei canali pubblici si fa un solo
  tentativo: un buco si riempie a mano, un doppione pubblico resta.
- **Scritture condizionate.** L'audit aggiorna con `WHERE id=? AND esito=?`, così una
  modifica concorrente non viene sovrascritta.
- **Ritorno indietro con una variabile.** Le funzioni nuove hanno un interruttore unico
  (es. `SELEZIONE_PUBBLICATA`) e un ripiego automatico se i loro dati mancano.
