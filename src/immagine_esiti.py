"""Immagine quadrata con gli esiti di una giornata, per Instagram.

PERCHE'. Instagram non ha post di testo: ogni pubblicazione e' un'immagine.
Gli esiti che il bot manda al gruppo Telegram sono testo, quindi per
pubblicarli fuori vanno disegnati.

SCELTE, e sono scelte non dettagli:

- **Il pronostico e' al centro, il risultato di fianco.** La prima versione
  mostrava il risultato finale e un pallino verde: era una nostra
  affermazione, non una prova. Chi guarda deve poter fare il confronto da
  solo, e per farlo deve leggere cosa aveva detto il bot PRIMA. Il testo e'
  il pronostico, il colore e' l'esito, il segno ✓/✗ lo ripete per chi non
  distingue i colori.
- **I nomi non si accorciano tagliandoli.** «Real Sociedad II» tagliato a
  quindici caratteri diventa «Real Sociedad I», che e' un'altra squadra: un
  dato falso in un'immagine pubblica. Se non ci sta, prima rimpicciolisce il
  carattere, e solo all'ultimo mette i puntini (`_corto`).
- **Niente loghi ne' stemmi delle squadre.** Sono marchi registrati. I nomi
  si possono usare — e' uso descrittivo di un fatto — il simbolo no.
- **Il tasso storico sta accanto a quello del giorno.** Una giornata sola non
  descrive niente: il 31/08 l'1X2 ha fatto 9 su 10, contro una media storica
  del 51%. Pubblicare solo il 90% sarebbe vero e ingannevole insieme, ed e'
  esattamente il trucco che rende i pronosticatori inaffidabili. Il confronto
  e' l'unica cosa che rende la pubblicazione onesta.
- **Nessuna promessa di vincita.** I ROI misurati sono negativi alle quote di
  mercato.
- **1080x1080**: il formato del feed. Testo grande, poche righe: si guarda su
  un telefono, in due secondi.

Uso:
    python3 immagine_esiti.py [YYYY-MM-DD] [--out percorso.png]
Senza data, prende ieri.
"""
import os
import sqlite3
import sys
from datetime import date, timedelta

from PIL import (Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont)

# Nella vetrina i percorsi sono relativi al repository (in produzione: /opt/football-bot).
_RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


DB = os.getenv("DB_PATH", os.path.join(_RADICE, "signals.db"))
FONT_DIR = "/usr/share/fonts/truetype/dejavu"
LATO = 1080
# ALTEZZA — 4:5, il formato piu' alto che Instagram accetta nel feed.
# Era 1:1 fino al 09/09/2026: la seconda slide sforava di 96 px sul piede
# e il margine era gia' di soli 10 px prima di aggiungere il pannello del
# mese. Un quadrato non ha piu' spazio da dare.
#
# LE TRE SLIDE DEVONO AVERE LO STESSO RAPPORTO: in un carosello Instagram
# ritaglia tutte sul formato della PRIMA. Cambiarne una sola taglierebbe le
# altre due.
ALT = 1350

# ── il pavimento ─────────────────────────────────────────────────────────
# Sotto questa y c'e' solo il piede: tre righe di testo piu' la firma. Il
# contenuto non ci scrive MAI sopra — si adatta, e se non basta si mostra
# meno roba.
#
# PERCHE' UN PAVIMENTO E NON SOLO UN FOGLIO PIU' GRANDE. Il 4:5 regala 270
# px, e oggi bastano. Ma il difetto del 09/09/2026 non era la mancanza di
# spazio: erano posizioni fisse sotto contenuto variabile. Con quel
# meccanismo intatto il foglio piu' grande sposta solo la data della
# prossima rottura.
# PIEDE e PAVIMENTO NON SONO PIU' NUMERI SCRITTI A MANO: si ricavano dal
# testo vero dell'avvertenza, piu' in basso, dopo che `avvolgi` esiste.
#
# Il 09/09/2026 l'avvertenza e' cambiata due volte in un'ora — prima da una
# riga a quattro, poi a cinque con la provenienza delle quote — e ogni volta
# il piede si allargava. Con i numeri a mano ogni modifica del testo richiede
# di ritararli, e il giorno in cui qualcuno se ne dimentica il contenuto
# finisce sopra l'avvertenza: e' esattamente il difetto da cui e' nato tutto.
# Adesso allungare il testo sposta tutto il resto da solo.

# Quanti risultati esatti si elencano nella seconda slide. Erano tre per
# scelta editoriale, e per caso erano anche il massimo che ci stava.
MAX_ESATTI = 3


def elenco_che_ci_sta(y, quante, passo_max, passo_min, coda=0,
                      pavimento=None):
    """(righe da mostrare, passo in px) per restare sopra il pavimento.

    L'ORDINE DEI DUE RIMEDI CONTA. Prima si STRINGE il passo: togliere una
    partita e' una perdita di informazione, avvicinare due righe no. Solo
    quando il passo scenderebbe sotto `passo_min` — che e' una soglia di
    leggibilita', non un numero estetico — si MOSTRANO MENO RIGHE.

    `coda` e' lo spazio che serve DOPO l'elenco: altri pannelli, i totali.
    Ignorarla e' esattamente il difetto del 09/09: l'elenco ci stava, quello
    che veniva dopo no.

    Chi chiama deve dire quante ne restano fuori — `quante - risultato`.
    Terza volta che serve questa regola: la sesta partita del prematch
    adattivo spariva col log che diceva «6 inviate» (19-21/08), e la ricerca
    per paese troncava i campionati senza dirlo (07/09).

    Non torna mai numeri negativi: quando il contenuto e' gia' oltre il
    pavimento — il caso del 09/09 — un passo negativo farebbe risalire le
    righe verso l'alto invece di fermarle.
    """
    # Il pavimento si risolve QUI e non come valore di default: dipende
    # dalla lunghezza dell'avvertenza, che e' definita piu' in basso.
    if pavimento is None:
        pavimento = PAVIMENTO
    if quante <= 0:
        return 0, passo_max
    spazio = max(0, pavimento - y - coda)
    passo = min(passo_max, spazio // quante)
    if passo >= passo_min:
        return quante, passo
    return max(0, min(quante, spazio // passo_min)), passo_min


SFONDO = (10, 19, 15)          # verde molto scuro: erba di notte
PANNELLO = (20, 32, 26)
TESTO = (236, 239, 244)
TENUE = (138, 148, 166)
VERDE = (61, 194, 122)
ROSSO = (232, 87, 87)
ORO = (232, 178, 63)


def _corto(nome, massimo=17):
    """Accorcia un nome squadra solo se necessario, e senza cambiarlo.

    Tagliare «Real Sociedad II» a «Real Sociedad I» produce il nome di
    un'altra squadra: se non ci sta, si mettono i puntini.
    """
    nome = (nome or "").strip()
    return nome if len(nome) <= massimo else nome[:massimo - 1].rstrip() + "…"


def _f(nome, size):
    return ImageFont.truetype(os.path.join(FONT_DIR, nome), size)


SFONDO_FOTO = os.path.join(_RADICE, "assets/sfondo_stadio.jpg")


def _sfondo_foto(larg, alt, sfoca=12, scuro=0.42, sat=0.95):
    """Lo stadio vero, trattato perche' ci si possa scrivere sopra.

    QUATTRO PASSAGGI, e ognuno risolve un problema che si e' visto provando:

    1. **Ritaglio dal BASSO.** Li' c'e' il campo; sopra ci sono il tabellone
       con «GOAL!» e i led con «STADIUM ATMOSPHERE», cioe' testo inventato.
       Su un profilo che vende dati verificati, uno sfondo con scritte finte
       e' la cosa che stona di piu'.
    2. **Sfocatura.** Una foto di stadio nitida dietro del testo lo rende
       illeggibile: troppe linee, troppi contrasti locali.
    3. **Spegnimento delle sole zone chiare.** Il problema non era la
       luminosita' media ma la MACCHIA dei riflettori, che cadeva dietro una
       colonna di numeri e la mangiava. Scurire tutto per colpa di una zona
       avrebbe buttato via il resto: si misura la luminosita', si tiene solo
       cio' che supera la soglia, si sfuma e si scurisce li'.
    4. **Sfumatura in basso.** L'erba illuminata sta dove vanno le righe
       piccole del piede, e il testo tenue ci spariva sopra.
    """
    f = Image.open(SFONDO_FOTO).convert("RGB")
    k = max(larg / f.width, alt / f.height)
    f = f.resize((int(f.width * k), int(f.height * k)), Image.LANCZOS)
    x = int((f.width - larg) / 2)
    f = f.crop((x, f.height - alt, x + larg, f.height))
    f = f.filter(ImageFilter.GaussianBlur(sfoca * larg / 1080))
    f = ImageEnhance.Color(f).enhance(sat)
    f = Image.blend(f, Image.new("RGB", (larg, alt), (0, 0, 0)), scuro)

    troppo = f.convert("L").point(lambda v: 0 if v < 70 else min(255, (v - 70) * 3))
    troppo = troppo.filter(ImageFilter.GaussianBlur(larg // 22))
    f = Image.composite(Image.new("RGB", (larg, alt), (14, 22, 20)), f, troppo)

    grad = Image.new("L", (1, alt))
    px = grad.load()
    for y in range(alt):
        t = y / (alt - 1)
        px[0, y] = 0 if t < 0.55 else int(215 * ((t - 0.55) / 0.45) ** 1.5)
    return Image.composite(Image.new("RGB", (larg, alt), (5, 10, 8)), f,
                           grad.resize((larg, alt)))


def sfondo_campo(larg, alt):
    """Lo sfondo comune alle quattro immagini.

    Usa la FOTO se c'e', altrimenti disegna il campo. Il ripiego non e'
    teorico: la foto e' un file caricato dall'utente, e su una macchina
    appena clonata potrebbe non esserci. Senza il ripiego le immagini non
    uscirebbero piu' — e nessuno se ne accorgerebbe fino alle 08:00.
    """
    if os.path.exists(SFONDO_FOTO):
        try:
            return _sfondo_foto(larg, alt)
        except Exception:
            pass                      # foto illeggibile: si disegna
    return _campo_disegnato(larg, alt)


def _campo_disegnato(larg, alt):
    """Il fondo comune a tutte le immagini: un campo visto di notte.

    PERCHE' NON UN COLORE PIATTO. Un rettangolo scuro uniforme e' il fondo di
    default di qualunque cosa generata da un programma, e si riconosce: non
    dice niente del prodotto e non si distingue da mille altre. Questo invece
    e' l'unico elemento che compare su OGNI immagine, quindi e' l'unica cosa
    che puo' diventare riconoscibile a colpo d'occhio.

    PERCHE' DISEGNATO E NON UNA FOTO. Una foto di stadio sarebbe piu' facile
    e piu' rischiosa: le immagini di stadi e partite hanno un proprietario, e
    qui si pubblica ogni giorno. La geometria del campo invece non e' di
    nessuno, e disegnata resta nitida a qualunque dimensione.

    TUTTO A BASSO CONTRASTO, di proposito. Il fondo deve farsi notare
    guardandolo e sparire mentre si legge: le righe stanno entro 4-5 punti di
    luminosita' dal fondo, la segnatura entro 16. Se si vedono bene, e'
    sbagliato.
    """
    img = Image.new("RGB", (larg, alt), SFONDO)
    d = ImageDraw.Draw(img)

    # righe di taglio dell'erba: la cosa che rende un prato un CAMPO
    bande = 9
    for i in range(bande):
        if i % 2:
            d.rectangle([larg * i // bande, 0, larg * (i + 1) // bande, alt],
                        fill=(13, 24, 19))

    # segnatura: cerchio di centro e linea mediana, tagliati dal bordo come
    # in un'inquadratura vera. Un campo intero e centrato sembrerebbe uno
    # schema tattico, non uno sfondo.
    linea = (25, 44, 34)
    sp = max(larg // 360, 2)
    cx, cy = int(larg * 0.72), int(alt * 0.60)
    r = int(min(larg, alt) * 0.42)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=linea, width=sp)
    d.ellipse([cx - sp * 4, cy - sp * 4, cx + sp * 4, cy + sp * 4], fill=linea)
    d.line([(0, cy), (larg, cy)], fill=linea, width=sp)
    # area di rigore che entra da sinistra
    ah, aw = int(alt * 0.30), int(larg * 0.22)
    d.rectangle([-10, cy - ah // 2, aw, cy + ah // 2], outline=linea, width=sp)

    # luce dei riflettori: un alone dall'alto, appena percepibile
    alone = Image.new("L", (larg, alt), 0)
    ImageDraw.Draw(alone).ellipse(
        [-larg * 0.3, -alt * 0.55, larg * 1.3, alt * 0.42], fill=120)
    img = Image.composite(Image.new("RGB", (larg, alt), (26, 42, 34)), img,
                          alone.filter(ImageFilter.GaussianBlur(larg // 6)))

    # angoli piu' scuri: da' profondita' e tiene l'occhio al centro
    ombra = Image.new("L", (larg, alt), 0)
    do = ImageDraw.Draw(ombra)
    passi = 60
    for i in range(passi):
        k = i / (passi - 1)
        m = int(min(larg, alt) * 0.5 * (1 - k))
        do.rounded_rectangle([m, m, larg - m, alt - m],
                             radius=int(min(larg, alt) * 0.3),
                             fill=int(70 + 185 * k))
    return Image.composite(img, Image.new("RGB", (larg, alt), (4, 9, 7)),
                           ombra.filter(ImageFilter.GaussianBlur(larg // 14)))


# Le due destinazioni, in un posto solo. Sono DIVERSE e non e' una svista:
# @LolloSignalLive e' il profilo Instagram, @LolloSignalCalcio e' il canale
# Telegram — "@LolloSignalLive" era gia' preso su Telegram.
INSTAGRAM = "@LolloSignalLive"
CANALE_TG = "t.me/LolloSignalCalcio"
BOT_TG = "t.me/LolloSignalLive_bot"

# La riga che porta all'abbonamento. Va in coda alle didascalie del canale,
# ed e' l'UNICO punto in cui un lettore del canale scopre che esiste qualcosa
# da comprare: fino al 03/09 la didascalia del prematch diceva «le altre 7
# agli abbonati» e poi lasciava il lettore in un vicolo cieco.
#
# Niente Markdown: le didascalie partono senza parse_mode, quindi
# l'underscore di LolloSignalLive_bot e' un underscore e basta. Telegram
# rende comunque cliccabile un t.me/ scritto in chiaro.
# Dall'11/09/2026 il richiamo punta alla PROVA GRATUITA (giorni da
# PROVA_GIORNI, mai scritti) e con PAGAMENTI_ATTIVI=False sparisce: si
# spegne la vendita, non il prodotto. Le costanti stanno in
# abbonamenti_config.py — stessa ragione di avvertenza.py: bot.py e le
# slide devono leggere lo STESSO valore senza potersi importare a vicenda.
# Niente prezzi qui: i post del canale non ne portano.
from abbonamenti_config import PAGAMENTI_ATTIVI, PROVA_GIORNI  # noqa: E402

RICHIAMO = (f"🎁 Prova gratis {PROVA_GIORNI} giorni, tutto il servizio: "
            f"/start su " + BOT_TG) if PAGAMENTI_ATTIVI else ""

# ── l'avvertenza in fondo a ogni slide ───────────────────────────────────
# Riscritta il 09/09/2026. Prima diceva solo «18+ · Il gioco puo' causare
# dipendenza · Gioca responsabilmente»: vero e insufficiente, perche' non
# diceva COSA E' il prodotto.
#
# Ora lo dichiara, ed e' una dichiarazione VERA — LolloSignal e'
# letteralmente un programma che elabora statistiche. Non e' un camuffamento
# lessicale: rinominare «Over 2.5» in «proiezione gol» lasciando tutto il
# resto uguale non cambierebbe cosa fa il prodotto, e un eufemismo evidente
# davanti a un'autorita' vale meno di niente. Questa invece aggiunge
# informazione al lettore.
#
# La parte obbligatoria (18+, dipendenza, gioco responsabile) resta identica:
# quella non dipende da nessun parere.
# Il testo NON sta piu' qui: vive in `avvertenza.py`, condiviso con i
# messaggi Telegram di bot.py. Due copie di un'avvertenza legale che
# divergono sono peggio di nessuna avvertenza — nessuno sa piu' quale
# delle due sia quella vigente, e dopo la consulenza cambiera'.
from avvertenza import AVVERTENZA  # noqa: E402

CORPO_AVVERTENZA = 17
INTERLINEA_AVVERTENZA = 21
INTERLINEA_NOTE = 28


def _larghezza(testo, corpo):
    return _f("DejaVuSans.ttf", corpo).getlength(testo)


def avvolgi(testo, larghezza, corpo):
    """Spezza il testo in righe che stanno in `larghezza` pixel.

    NON TRONCA MAI. Tagliare un'avvertenza legale a meta' frase e' peggio
    che non averla: si perde proprio la parte che la rende una
    dichiarazione. Se una singola parola non ci sta, esce lunga — meglio una
    riga che sborda di una parola inventata a meta'.
    """
    righe, riga = [], ""
    for parola in testo.split():
        prova = f"{riga} {parola}".strip()
        if riga and _larghezza(prova, corpo) > larghezza:
            righe.append(riga)
            riga = parola
        else:
            riga = prova
    if riga:
        righe.append(riga)
    return righe


# ── la geometria del fondo, RICAVATA dal testo vero ──────────────────────
# Quante righe occupa davvero l'avvertenza si sa solo misurandola con il
# font: dipende dalle parole, non da una stima. Da qui in giu' tutto
# discende, e allungare il testo di legge sposta il resto da solo.
RIGHE_AVVERTENZA = len(avvolgi(AVVERTENZA, LATO - 120, CORPO_AVVERTENZA))
ALT_PIEDE = 38 + RIGHE_AVVERTENZA * INTERLINEA_AVVERTENZA
Y_PIEDE = ALT - ALT_PIEDE - 26

# Le due o tre righe di spiegazione che ogni slide mette sopra il piede
# («il dato storico è accanto a quello del giorno», ecc.).
Y_NOTE = Y_PIEDE - 3 * INTERLINEA_NOTE - 16

# Il contenuto non arriva mai alle note: sotto il pavimento c'e' solo roba
# che deve esserci sempre.
PAVIMENTO = Y_NOTE
PIEDE = ALT - PAVIMENTO


def accuratezza(presi, n):
    """('90%', '9 su 10') — la percentuale e il suo denominatore.

    PERCHE' LA PERCENTUALE. «9/10» viene letto come una schedina centrata,
    ed e' l'interpretazione che la seconda slide esiste apposta per negare:
    la media e' 51%, non 90%. Un indice espresso in percentuale, accanto
    alla media storica, dice lo stesso fatto senza evocare una vincita.

    PERCHE' IL CONTEGGIO RESTA. Un 90% su dieci partite e' molto meno solido
    di un 90% su mille, e una percentuale senza denominatore sembra piu'
    autorevole di quanto sia. La percentuale fa da titolo, il conteggio sta
    sotto: nessuno dei due da solo e' onesto.
    """
    if not n:
        return "—", "nessuna partita"
    return f"{100 * presi / n:.0f}%", f"{presi} su {n}"


def piede(d, y):
    """Firma e avvertenza, identiche sulle tre slide.

    PERCHE' C'E' L'INDIRIZZO SCRITTO PER ESTESO. Instagram **non rende
    cliccabile** nessun link nella didascalia: l'unico link che si tocca sta
    in bio o nelle storie. Ma l'immagine e' la cosa che viaggia — viene
    screenshottata, rigirata, salvata — e un indirizzo scritto sopravvive
    dove un link non arriva. Chi la vede puo' digitarlo.

    Una funzione sola perche' le tre slide non divergano: se un giorno il
    canale cambiasse nome, tre piedi separati diventerebbero due indirizzi
    giusti e uno che porta nel vuoto.
    """
    grassetto = _f("DejaVuSans-Bold.ttf", 26)
    d.text((60, y), INSTAGRAM, font=grassetto, fill=ORO)
    larg = d.textlength(INSTAGRAM, font=grassetto)
    d.text((60 + larg + 16, y + 4), "· " + CANALE_TG,
           font=_f("DejaVuSans.ttf", 22), fill=TENUE)
    yy = y + 38
    for riga in avvolgi(AVVERTENZA, LATO - 120, CORPO_AVVERTENZA):
        d.text((60, yy), riga, font=_f("DejaVuSans.ttf", CORPO_AVVERTENZA),
               fill=TENUE)
        yy += INTERLINEA_AVVERTENZA


def carica_turno(turno, db_path=DB):
    """Le partite di un TURNO chiesto dall'admin, gia' verificate.

    Stessa forma di `carica_giornata` — stesse colonne, stesso ordine —
    perche' `disegna()` non deve sapere da dove arrivano: l'utente ha chiesto
    «stessa configurazione di quelle che fai la mattina alle 9», e il modo
    piu' solido di garantirlo e' usare la STESSA funzione di disegno.

    Lo storico in fondo resta quello complessivo (batch + turni): e' il
    curriculum del bot, non del singolo turno.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        righe = conn.execute(
            "SELECT home, away, risultato_reale, esito_1x2, esito_over25, "
            "esito_gg, esito_risultato, ft_1x2, ft_over25, ft_gg, "
            "risultato_ft "
            "FROM prematch_predictions "
            "WHERE turno=? AND esito_1x2 IS NOT NULL "
            "ORDER BY kickoff, id", (turno,)).fetchall()
        storico = conn.execute(
            "SELECT COUNT(*), SUM(esito_1x2='VINTO'), SUM(esito_over25='VINTO'), "
            "SUM(esito_gg='VINTO'), SUM(esito_risultato='VINTO') "
            "FROM prematch_predictions "
            "WHERE origine IN ('batch','turno','valore') AND esito_1x2 IS NOT NULL"
        ).fetchone()
    finally:
        conn.close()
    return righe, storico


def carica_giornata(giorno, db_path=DB):
    """Le partite verificate di quel giorno, solo batch (quelle pubblicate)."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        righe = conn.execute(
            "SELECT home, away, risultato_reale, esito_1x2, esito_over25, "
            "esito_gg, esito_risultato, ft_1x2, ft_over25, ft_gg, "
            "risultato_ft "
            "FROM prematch_predictions "
            "WHERE match_date=? AND origine IN ('batch','valore') AND esito_1x2 IS NOT NULL "
            "ORDER BY id", (giorno,)).fetchall()
        storico = conn.execute(
            "SELECT COUNT(*), SUM(esito_1x2='VINTO'), SUM(esito_over25='VINTO'), "
            "SUM(esito_gg='VINTO'), SUM(esito_risultato='VINTO') "
            "FROM prematch_predictions "
            # Lo storico e' il curriculum COMPLESSIVO: batch + turni chiesti
            # dall'admin, come deciso il 07/09. L'elenco sopra resta invece
            # solo del giorno.
            "WHERE origine IN ('batch','turno','valore') AND esito_1x2 IS NOT NULL"
        ).fetchone()
    finally:
        conn.close()
    return righe, storico


def disegna(giorno, righe, storico, out):
    img = sfondo_campo(LATO, ALT)
    d = ImageDraw.Draw(img)
    grassetto = lambda s: _f("DejaVuSans-Bold.ttf", s)
    normale = lambda s: _f("DejaVuSans.ttf", s)
    mono = lambda s: _f("DejaVuSansMono-Bold.ttf", s)

    g, m, a = giorno[8:10], giorno[5:7], giorno[:4]
    d.text((60, 52), "LOLLOSIGNAL", font=grassetto(34), fill=ORO)
    d.text((60, 96), f"Esiti del {g}/{m}/{a}", font=normale(30), fill=TENUE)

    # LA PARTE CHE CONTA: cosa aveva detto il bot.
    # Prima l'immagine mostrava solo il risultato e un pallino verde: era una
    # nostra affermazione, non una prova. Chi guarda deve poter fare il
    # confronto da solo, e per farlo deve vedere il pronostico.
    X_1X2, X_OVER, X_GG, X_RIS, X_FIN = 442, 522, 630, 742, 880
    d.text((60, 150), "PARTITA", font=grassetto(19), fill=TENUE)
    # centrata sull'INTERO blocco (1X2 -> risultato esatto): se resta a
    # sinistra, "RIS. ESATTO" sembra appartenere a "FINITA" e il confronto
    # fra pronostico e realta' si legge al contrario.
    _t = "SEGNALE ATTESO"
    _x = X_1X2 + (830 - X_1X2 - d.textlength(_t, font=grassetto(19))) / 2
    d.text((_x, 150), _t, font=grassetto(19), fill=ORO)
    d.text((X_FIN, 150), "FINITA", font=grassetto(19), fill=TENUE)
    d.text((X_1X2, 176), "1X2", font=normale(17), fill=TENUE)
    d.text((X_OVER, 176), "OVER 2.5", font=normale(17), fill=TENUE)
    d.text((X_GG, 176), "GG", font=normale(17), fill=TENUE)
    d.text((X_RIS, 176), "RIS. ESATTO", font=normale(17), fill=TENUE)
    d.line([(60, 202), (LATO - 60, 202)], fill=PANNELLO, width=2)

    ETICHETTA_1X2 = {"1": "1", "X": "X", "2": "2"}
    y = 214
    # CODA: quello che viene dopo l'elenco e che deve starci comunque —
    # lo stacco e il riquadro dei totali. E' il pezzo che il 09/09 nessuno
    # contava, e infatti l'elenco ci stava ma il resto no.
    CODA_TOTALI = 20 + 242
    quante, passo = elenco_che_ci_sta(y, len(righe), 42, 30, coda=CODA_TOTALI)
    fuori = len(righe) - quante
    f_pron, f_segno = mono(25), grassetto(21)
    for (home, away, fin, e1, eo, eg, er, p1, po, pg, pr) in righe[:quante]:
        nome = f"{_corto(home, 20)} – {_corto(away, 20)}"
        f_nome = normale(24)
        while d.textlength(nome, font=f_nome) > 370 and f_nome.size > 15:
            f_nome = normale(f_nome.size - 1)
        d.text((60, y + (24 - f_nome.size) // 2), nome, font=f_nome, fill=TESTO)

        # pronostico: il TESTO e' il pronostico, il COLORE e' l'esito, e il
        # segno accanto lo ripete per chi non distingue i colori.
        # Il risultato esatto sta ACCANTO a quello vero: e' il confronto piu'
        # immediato che ci sia, e resta leggibile anche quando e' sbagliato.
        for x, valore, esito in ((X_1X2, ETICHETTA_1X2.get(p1, p1 or "?"), e1),
                                 (X_OVER, po or "?", eo),
                                 (X_GG, pg or "?", eg),
                                 (X_RIS, pr or "?", er)):
            ok = esito == "VINTO"
            colore = VERDE if ok else ROSSO
            d.text((x, y), str(valore), font=f_pron, fill=colore)
            larg = d.textlength(str(valore), font=f_pron)
            d.text((x + larg + 7, y + 1), "✓" if ok else "✗",
                   font=f_segno, fill=colore)

        d.text((X_FIN, y), fin or "?", font=mono(25), fill=TESTO)
        y += passo

    # Niente tagli silenziosi: se qualcosa e' rimasto fuori si dice, come
    # gia' per la sesta partita del prematch adattivo e per i campionati
    # della ricerca per paese.
    if fuori:
        d.text((60, y + 4), f"e altre {fuori} partite",
               font=normale(21), fill=TENUE)
        y += 30

    # totali del giorno — sempre su TUTTE le partite verificate, anche
    # quelle non elencate: il conteggio e' il risultato della giornata, non
    # di quanto ci stava nel foglio.
    n = len(righe)
    v1 = sum(1 for r in righe if r[3] == "VINTO")
    vo = sum(1 for r in righe if r[4] == "VINTO")
    vg = sum(1 for r in righe if r[5] == "VINTO")
    vr = sum(1 for r in righe if r[6] == "VINTO")
    tot_st, s1, so, sg, sr = storico
    tot_st_txt = f"{tot_st} segnali"
    y += 20
    d.rounded_rectangle([48, y, LATO - 48, y + 242], 22, fill=PANNELLO)
    d.text((78, y + 22), "IERI", font=grassetto(24), fill=ORO)
    d.text((560, y + 22), f"STORICO · {tot_st_txt}", font=grassetto(24), fill=TENUE)

    yy = y + 64
    # Il risultato esatto e' l'ultima riga e ha il tasso piu' basso di tutti:
    # sta qui APPOSTA. La colonna nell'elenco e' quasi tutta rossa, e senza il
    # 12% storico accanto sembrerebbe un fallimento invece di un mercato che
    # paga otto volte la posta.
    for etichetta, preso, st in (("1X2", v1, s1), ("Over 2.5", vo, so),
                                 ("GG/NG", vg, sg), ("Risultato esatto", vr, sr)):
        d.text((78, yy), etichetta, font=normale(26), fill=TESTO)
        d.text((400, yy), f"{preso}/{n}", font=mono(26), fill=TESTO)
        pct_st = 100 * st / tot_st if tot_st else 0
        d.text((560, yy), f"{pct_st:.0f}%", font=mono(26), fill=TENUE)
        yy += 44

    # perche' il confronto c'e': una giornata sola non descrive niente
    d.text((60, Y_NOTE),
           "Il dato storico è accanto a quello del giorno: una sola",
           font=normale(22), fill=TENUE)
    d.text((60, Y_NOTE + INTERLINEA_NOTE),
           "giornata non definisce un metodo. Tutti gli esiti, corretti e",
           font=normale(22), fill=TENUE)
    d.text((60, Y_NOTE + 2 * INTERLINEA_NOTE),
           "sbagliati, restano pubblici sul canale Telegram.",
           font=normale(22), fill=TENUE)

    piede(d, Y_PIEDE)

    img.save(out, "PNG")
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    giorno = args[0] if args else (date.today() - timedelta(days=1)).isoformat()
    out = os.path.join(_RADICE, "esiti_") + giorno.replace("-", "") + ".png"
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    righe, storico = carica_giornata(giorno)
    if not righe:
        print(f"Nessun pronostico verificato per {giorno}: niente da pubblicare.")
        return 1
    disegna(giorno, righe, storico, out)
    n = len(righe)
    print(f"{out}\n  {n} partite · 1X2 {sum(1 for r in righe if r[3]=='VINTO')}/{n}"
          f" · Over {sum(1 for r in righe if r[4]=='VINTO')}/{n}"
          f" · GG {sum(1 for r in righe if r[5]=='VINTO')}/{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
