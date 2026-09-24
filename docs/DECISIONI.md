# Decisioni prese sui dati

Una selezione dal registro del progetto. Ognuna ha la stessa forma: un'idea, una
misura, una decisione. Molte idee non hanno retto alla misura, e anche quelle sono
documentate: sapere cosa non funziona è metà del lavoro.

## Il ribaltone dopo il 75' non esiste

**Idea:** aprire i segnali «ribaltone» anche fra il 70' e l'80'.
**Misura:** su 172 partite, 1 ribaltone su 13 fra il 60' e il 75' e **zero su 11**
dopo il 75'. Il criterio del «dominio statistico» non discriminava: 11,3% di ribaltoni
fra le squadre dominanti contro 14,6% fra le altre.
**Decisione:** finestra chiusa, con un test che la difende. Quando, mesi dopo, un
nuovo strumento (il veto del modello) sembrava renderla sicura, il test ha bocciato la
riapertura. Aveva ragione: uno strumento nuovo protegge ciò che è già ammesso, non
autorizza a disfare una misura.

## La confidenza dell'AI è quasi una costante

**Misura:** confronto su 20 partite vere, stesso input a due modelli. Haiku dichiara
**76 in 9 segnali su 10**; Sonnet distribuisce fra 62 e 78. Due finestre chiedevano
80: chiuse per costruzione.
**Decisione:** la confidenza da sola non seleziona nulla. La regola «due indicatori
concordi», che prima stava solo nel prompt, è stata portata nel codice come via
alternativa. La prima taratura a occhio faceva convergere l'Over nell'**89%** dei casi,
cioè una porta spalancata. Le soglie sono state ricavate dall'80° percentile di 4.281
rilevazioni reali.

## Il prezzo di pareggio non è un'opinione

**Misura:** con un win rate del 35,7%, un segnale serve solo a quota ≥ 2,80. Il
mercato ne offriva 1,80-2,50.
**Decisione:** soglia di prezzo per tipo = la più severa fra quella statica e
`(1/winrate) × (1+margine)` sugli ultimi 180 giorni. Non si allenta mai sotto la
statica: un win rate alto su poche decine di casi non deve aprire il filtro.

## Un segnale che nasce da un evento rende meno di uno che nasce dai dati

**Misura:** nella modalità ombra 75 segnali «prossimo marcatore» su 76 nascevano da
un'espulsione, con un win rate del **37,3%** contro il 55% che la quota richiedeva. Il
modello, dove aveva una stima, diceva 33,1%.
**Decisione:** il cartellino rosso non emette più: *innesca* un'analisi immediata, e
il segnale, se esce, passa dagli stessi cancelli di tutti gli altri.

## Un terzo modello sui tiri: provato e scartato

**Misura:** 14.432 rilevazioni al minuto su 2.874 partite. Per «arriverà un gol?» la
traiettoria dei tiri non aggiunge nulla a minuto e punteggio. Per «chi lo segna?» sì
(+3,2% di log loss), ma l'AI lo cattura già: nei disaccordi l'AI ha ragione 9 volte
su 14, il modello 2.
**Decisione:** non innestato. Un modello utile deve usare dati che l'AI non vede.

## Il risultato esatto del primo tempo non contiene informazione

**Misura:** fuori campione su 11.599 primi tempi, il modello indovina 3.382 volte.
La costante «0-0» indovina **3.382 volte**. Le 758 deviazioni da 0-0 guadagnano 187
centri e ne perdono 187.
**Decisione:** tolto dalla pubblicazione. Resta misurato nel pannello interno.

## Cercare il «massimo valore» seleziona i propri errori

**Misura:** alla prima giornata reale la selezione a valore dichiarava un vantaggio
medio del **+33%**, impossibile su mercati dove il banco trattiene il 5-8%. Quel numero
misurava la distanza della *nostra* stima dal mercato, non un errore del mercato.
Risultato: 2 centri su 10 contro 4 attesi.
**Decisione:** probabilità minima 40% e tetto al contributo del vantaggio (dal 30% al
10%). Un vantaggio oltre il 10% è un sintomo, non un'occasione.

## Un difetto che toglieva sempre le partite migliori

**Misura:** la vetrina del mattino perdeva 3-6 partite in alcuni giorni. Non a caso:
erano quelle aperte la sera prima da chi sfogliava il menu, cioè le partite più
attraenti, dove il sistema rende **61,9% contro il 44%** delle divisioni minori. Il win
rate pubblicato risultava più basso del vero.
**Causa:** la promozione «richiesta → pubblicata» stava sul ramo della cache che non
viene mai percorso in quel caso. Il test che doveva coprirla forzava uno scenario che
in produzione non capita mai.
**Decisione:** correzione sul ramo giusto, riparazione delle righe storiche con
backup, e un test costruito sullo scenario reale.

## La selezione delle partite pubbliche non guarda la confidenza

**Misura:** scegliere per orario sembra neutro, ma le partite di richiamo si giocano la
sera: 0,9 partite importanti in vetrina contro 2,4 riservate. Una partita per fascia
oraria porta il rapporto a 30% contro 34%.
**Decisione:** una per fascia oraria, scartando i doppioni per forma della scheda, mai
per confidenza o campionato. Scegliere le partite «sicure» mostrerebbe un sistema
migliore di quello reale. Un test cade se la selezione inizia a guardarle.
