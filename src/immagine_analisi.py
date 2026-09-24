"""Seconda slide: la LETTURA della giornata, non l'elenco.

PERCHE'. `immagine_esiti.py` mostra i fatti — dieci righe, pronostico contro
risultato. Chi scorre Instagram legge «9 su 10» e conclude una cosa sbagliata:
che il bot prende nove partite su dieci. Non e' vero, la media e' 51%.

Questa slide dice ad alta voce quello che l'elenco lascia implicito:
- il numero grosso della giornata **accanto alla sua media storica**;
- una frase che nega esplicitamente l'interpretazione facile;
- i risultati esatti presi, con «detto» e «finito» affiancati;
- **cosa NON ha funzionato lo stesso giorno**, che e' la parte che nessun
  pronosticatore pubblica ed e' l'unica che rende credibile il resto.

L'ordine e' voluto: il dato che attira, poi subito il suo ridimensionamento.
Invertirlo sarebbe la solita vetrina.

Uso:
    python3 immagine_analisi.py [YYYY-MM-DD] [--out percorso.png]
Senza data, prende ieri.
"""
import os
import sqlite3
import sys
from datetime import date, timedelta

from PIL import Image, ImageDraw

# Nella vetrina i percorsi sono relativi al repository (in produzione: /opt/football-bot).
_RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


from avvertenza import AVVERTENZA, AVVERTENZA_BREVE  # noqa: E402
from immagine_esiti import (ALT, DB, LATO, MAX_ESATTI, ORO, PANNELLO,
                            PAVIMENTO, RICHIAMO, ROSSO, Y_NOTE, Y_PIEDE,
                            INTERLINEA_NOTE, accuratezza, elenco_che_ci_sta,
                            SFONDO, TENUE, TESTO, VERDE, _corto, _f, piede, sfondo_campo)

# I tre mercati principali, nell'ordine in cui li pubblichiamo.
MERCATI = (("1X2", 3, 1), ("Over 2.5", 4, 2), ("GG/NG", 5, 3))

# ── la geometria della slide, in un posto solo ───────────────────────────
# Erano numeri sparsi dentro `disegna`, ed e' il motivo per cui il pannello
# del mese e' finito sopra il piede il 09/09/2026: nessuno poteva sommarli
# senza rileggere la funzione. Ora si sommano qui e un test lo verifica.
Y_PRIMO_PANNELLO = 356
ALT_RIGA_ESATTI = 46
STACCO = 26
INTESTAZIONE = 78
ALT_RIGA_PANNELLO = 44

# Quello che sta SOTTO l'elenco degli esatti e che deve starci comunque:
# «altri mercati» (due righe) e «ultimo mese» (quattro).
CODA_SLIDE_DUE = (STACCO + INTESTAZIONE + 2 * ALT_RIGA_PANNELLO +
                  STACCO + INTESTAZIONE + 4 * ALT_RIGA_PANNELLO)


def fondo_contenuto(n_esatti, n_altri=2, n_mese=4):
    """La y in cui finisce l'ultimo pannello. Deve stare sopra PAVIMENTO.

    Esiste per essere CHIAMATA DA UN TEST. Il difetto del 09/09 non era
    difficile — era invisibile: la somma delle altezze stava sparsa in
    quindici righe di `disegna`, e nessuno la faceva.
    """
    y = Y_PRIMO_PANNELLO + INTESTAZIONE + max(n_esatti, 1) * ALT_RIGA_ESATTI
    y += STACCO + INTESTAZIONE + n_altri * ALT_RIGA_PANNELLO
    y += STACCO + INTESTAZIONE + n_mese * ALT_RIGA_PANNELLO
    return y


def carica_turno(turno, db_path=DB):
    """Come `carica`, ma per un turno chiesto dall'admin."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        righe = conn.execute(
            "SELECT home, away, risultato_reale, esito_1x2, esito_over25, "
            "esito_gg, esito_risultato, risultato_ft, "
            "ft_1x2, ft_over25, ft_gg "
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


def carica_mese(giorno, db_path=DB, giorni=30):
    """(n, 1X2, Over, GG, esatto) negli ultimi `giorni` fino a `giorno`.

    None se in quella finestra non c'e' niente di verificato — il pannello
    allora non si disegna, che e' meglio di quattro zeri: uno zero si legge
    come «nessun pronostico preso», non come «nessun pronostico».

    LA FINESTRA SI CONTA DA `giorno`, NON DA OGGI. Una slide puo' essere
    rigenerata giorni dopo — successo il 09/09/2026 riparando l'08 — e deve
    dare gli stessi numeri di allora. Con `date('now')` due copie della
    stessa immagine si contraddirebbero.

    Stesso filtro `origine` dello storico in fondo alla slide: se i due
    pannelli contassero platee diverse, confrontarli non direbbe niente.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        r = conn.execute(
            "SELECT COUNT(*), SUM(esito_1x2='VINTO'), SUM(esito_over25='VINTO'), "
            "SUM(esito_gg='VINTO'), SUM(esito_risultato='VINTO') "
            "FROM prematch_predictions "
            "WHERE origine IN ('batch','turno','valore') AND esito_1x2 IS NOT NULL "
            "AND match_date BETWEEN date(?, ?) AND ?",
            (giorno, f"-{giorni} days", giorno)).fetchone()
    finally:
        conn.close()
    return r if r and r[0] else None


def righe_mese(mese):
    """[(etichetta, 'presi/n', 'pct%')] per il pannello ULTIMO MESE.

    Funzione pura e separata dal disegno: e' l'unico modo di bloccare il
    formato con un test senza andare a leggere i pixel dell'immagine.
    """
    if not mese or not mese[0]:
        return []
    n = mese[0]
    return [(etichetta, f"{mese[i]or 0}/{n}", f"{100*(mese[i] or 0)/n:.0f}%")
            for etichetta, i in (("1X2", 1), ("Over 2.5", 2),
                                 ("GG/NG", 3), ("Ris. esatto", 4))]


def carica(giorno, db_path=DB):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        righe = conn.execute(
            "SELECT home, away, risultato_reale, esito_1x2, esito_over25, "
            "esito_gg, esito_risultato, risultato_ft, "
            "ft_1x2, ft_over25, ft_gg "
            "FROM prematch_predictions "
            "WHERE match_date=? AND origine IN ('batch','valore') AND esito_1x2 IS NOT NULL "
            "ORDER BY id", (giorno,)).fetchall()
        storico = conn.execute(
            "SELECT COUNT(*), SUM(esito_1x2='VINTO'), SUM(esito_over25='VINTO'), "
            "SUM(esito_gg='VINTO'), SUM(esito_risultato='VINTO') "
            "FROM prematch_predictions "
            "WHERE origine IN ('batch','turno','valore') AND esito_1x2 IS NOT NULL"
        ).fetchone()
    finally:
        conn.close()
    return righe, storico


def leggi(righe, storico, mese=None):
    """Cosa dire di questa giornata, deciso dai dati e non a mano.

    Il mercato in evidenza e' quello col distacco piu' grande dalla propria
    media: e' la notizia del giorno, qualunque verso abbia. Se la giornata e'
    andata male esce un numero brutto, ed e' corretto cosi' — la slide serve
    a leggere, non a scegliere cosa mostrare.
    """
    n = len(righe)
    tot_st = storico[0]
    misure = []
    for etichetta, col, i_st in MERCATI:
        presi = sum(1 for r in righe if r[col] == "VINTO")
        media = 100 * (storico[i_st] or 0) / tot_st if tot_st else 0
        misure.append((etichetta, presi, media, 100 * presi / n - media))
    misure.sort(key=lambda m: -abs(m[3]))
    esatti = [(r[0], r[1], r[7], r[2]) for r in righe if r[6] == "VINTO"]
    media_es = 100 * (storico[4] or 0) / tot_st if tot_st else 0

    # La partita andata peggio NON si calcola piu': fino al 09/09/2026
    # occupava un pannello suo e due righe di didascalia. Al suo posto c'e'
    # la finestra a 30 giorni. Vedi test_analisi_mese.py per il perche'.
    return {
        "n": n, "tot_st": tot_st,
        "spicca": misure[0],
        "altri": sorted(misure[1:], key=lambda m: m[3]),
        "esatti": esatti,
        "esatti_media": media_es,
        "mese": mese,
        # La tupla grezza serve al pannello del mese, che mette la media
        # storica accanto a ogni riga invece che in un pannello lontano.
        "storico": storico,
    }


def disegna(giorno, dati, out):
    img = sfondo_campo(LATO, ALT)
    d = ImageDraw.Draw(img)
    grassetto = lambda s: _f("DejaVuSans-Bold.ttf", s)
    normale = lambda s: _f("DejaVuSans.ttf", s)
    mono = lambda s: _f("DejaVuSansMono-Bold.ttf", s)

    g, m, a = giorno[8:10], giorno[5:7], giorno[:4]
    d.text((60, 52), "LOLLOSIGNAL", font=grassetto(30), fill=ORO)
    d.text((60, 94), f"Analisi del {g}/{m}/{a}", font=normale(30), fill=TENUE)

    # ── il numero che attira, e subito accanto la sua media ──────────────
    etichetta, presi, media, scarto = dati["spicca"]
    n = dati["n"]
    colore = VERDE if scarto >= 0 else ROSSO
    # PERCENTUALE E NON «9/10», dal 09/09/2026. Il conteggio veniva letto
    # come una schedina centrata, ed e' l'interpretazione che questa slide
    # esiste apposta per negare: la media e' 51%, non 90%. Il denominatore
    # NON sparisce — sta nella riga sotto, perche' un 90% su dieci partite
    # e' molto meno solido di un 90% su mille.
    pct, dettaglio = accuratezza(presi, n)
    d.text((60, 158), pct, font=mono(96), fill=colore)
    larg = d.textlength(pct, font=mono(96))
    d.text((60 + larg + 26, 178), "indice di accuratezza",
           font=normale(26), fill=TENUE)
    d.text((60 + larg + 26, 212), f"sull'{etichetta}" if etichetta == "1X2"
           else f"su {etichetta}", font=normale(34), fill=TESTO)
    d.text((60 + larg + 28, 256),
           f"{dettaglio} · media storica {media:.0f}% su {dati['tot_st']} analisi",
           font=normale(21), fill=TENUE)

    # La frase che nega l'interpretazione facile. E' il motivo della slide.
    verso = ("Un singolo giorno non definisce il metodo."
             if scarto >= 0 else
             "Giornata sotto la media. Pubblicata comunque.")
    d.text((60, 296), verso, font=grassetto(27), fill=ORO)

    y = Y_PRIMO_PANNELLO

    # ── i risultati esatti presi ─────────────────────────────────────────
    # L'unico elenco a lunghezza variabile della slide, quindi l'unico che
    # puo' spingere il resto sotto il pavimento. Il tetto era `[:3]`, scelto
    # per motivi editoriali; adesso e' il tetto editoriale E quello fisico,
    # e vince il piu' basso dei due.
    quanti, _ = elenco_che_ci_sta(y, min(len(dati["esatti"]), MAX_ESATTI),
                                  46, 46, coda=CODA_SLIDE_DUE)
    esatti = dati["esatti"][:quanti]
    non_elencati = len(dati["esatti"]) - len(esatti)
    alt = 78 + max(len(esatti), 1) * 46
    d.rounded_rectangle([48, y, LATO - 48, y + alt], 20, fill=PANNELLO)
    d.text((78, y + 24), "RISULTATO ESATTO", font=grassetto(22), fill=TESTO)
    d.text((78 + d.textlength("RISULTATO ESATTO", font=grassetto(22)) + 18,
            y + 27),
           f"{len(esatti)} su {n} · media {dati['esatti_media']:.0f}%",
           font=normale(20), fill=TENUE)
    yy = y + 68
    if esatti:
        for home, away, detto, finita in esatti:
            nome = f"{_corto(home, 18)} – {_corto(away, 18)}"
            f_n = normale(24)
            while d.textlength(nome, font=f_n) > 520 and f_n.size > 16:
                f_n = normale(f_n.size - 1)
            d.text((78, yy + (24 - f_n.size) // 2), nome, font=f_n, fill=TESTO)
            # Le x si CALCOLANO dalla larghezza dell'etichetta, non si
            # scrivono a mano: erano tarate su «detto» e passando a
            # «previsto» — quattro lettere in piu' — la parola finiva sopra
            # il valore. Cosi' cambiare una parola non rompe piu' il disegno.
            e1, e2 = "previsto", "reale"
            x1 = 600
            x2 = x1 + d.textlength(e1, font=normale(20)) + 12
            x3 = x2 + 96
            x4 = x3 + d.textlength(e2, font=normale(20)) + 12
            d.text((x1, yy), e1, font=normale(20), fill=TENUE)
            d.text((x2, yy - 2), detto or "?", font=mono(25), fill=VERDE)
            d.text((x3, yy), e2, font=normale(20), fill=TENUE)
            d.text((x4, yy - 2), finita or "?", font=mono(25), fill=TESTO)
            yy += 46
    else:
        d.text((78, yy), "Nessuno, questa volta.", font=normale(24), fill=TENUE)

    # Niente tagli silenziosi: il conteggio in intestazione dice comunque
    # «N su 10», quindi il numero vero resta visibile — ma se l'elenco e'
    # piu' corto va detto perche'.
    if non_elencati:
        d.text((78, yy - 4), f"e altri {non_elencati}",
               font=normale(21), fill=TENUE)

    y += alt + 26

    # ── cosa NON ha funzionato: la parte che nessuno pubblica ────────────
    d.rounded_rectangle([48, y, LATO - 48, y + 78 + len(dati["altri"]) * 44],
                        20, fill=PANNELLO)
    d.text((78, y + 24), "ALTRI MERCATI", font=grassetto(22), fill=TESTO)
    yy = y + 68
    for etich, pres, med, sc in dati["altri"]:
        d.text((78, yy), etich, font=normale(24), fill=TESTO)
        d.text((330, yy), f"{pres}/{n}", font=mono(24),
               fill=VERDE if sc >= 0 else ROSSO)
        d.text((460, yy), f"media {med:.0f}%", font=normale(22), fill=TENUE)
        yy += 44

    # ── ultimo mese: il dato parziale accanto a quello storico ───────────
    # Sostituisce «L'ERRORE PIU' GRANDE» dal 09/09/2026. Due numeri, due
    # domande diverse: lo storico dice quanto vale il metodo, il mese come
    # sta andando adesso. Tenerli separati evita che l'uno sembri la
    # smentita dell'altro — al 26/08 divergevano di sei punti sull'1X2.
    mensili = righe_mese(dati["mese"])
    if mensili:
        y += 78 + len(dati["altri"]) * 44 + 26
        d.rounded_rectangle([48, y, LATO - 48, y + 78 + len(mensili) * 44],
                            20, fill=PANNELLO)
        d.text((78, y + 24), "ULTIMO MESE", font=grassetto(22), fill=TESTO)
        etichetta = f"{dati['mese'][0]} segnali · media storica su {dati['tot_st']}"
        d.text((78 + d.textlength("ULTIMO MESE", font=grassetto(22)) + 18,
                y + 27), etichetta, font=normale(20), fill=TENUE)
        yy = y + 68
        # La media storica sta ACCANTO al numero del mese, sulla stessa
        # riga: e' il metro con cui si legge, e a due pannelli di distanza
        # nessuno li confronta.
        for i, (etich, conteggio, pct) in enumerate(mensili):
            grezzo = dati["storico"][i + 1] if dati["storico"] else 0
            st = 100 * (grezzo or 0) / dati["tot_st"] if dati["tot_st"] else 0
            d.text((78, yy), etich, font=normale(24), fill=TESTO)
            d.text((330, yy), conteggio, font=mono(24), fill=TENUE)
            d.text((470, yy), pct, font=mono(24),
                   fill=VERDE if float(pct[:-1]) >= st else ROSSO)
            d.text((580, yy), f"storico {st:.0f}%", font=normale(22), fill=TENUE)
            yy += 44

    d.text((60, Y_NOTE + INTERLINEA_NOTE),
           "Tutti gli esiti, corretti e sbagliati, restano pubblici",
           font=normale(22), fill=TENUE)
    d.text((60, Y_NOTE + 2 * INTERLINEA_NOTE),
           "sul canale Telegram, comprese le giornate negative.",
           font=normale(22), fill=TENUE)
    piede(d, Y_PIEDE)

    img.save(out, "PNG")
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    giorno = args[0] if args else (date.today() - timedelta(days=1)).isoformat()
    out = os.path.join(_RADICE, "analisi_") + giorno.replace("-", "") + ".png"
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    righe, storico = carica(giorno)
    if not righe:
        print(f"Nessun pronostico verificato per {giorno}.")
        return 1
    dati = leggi(righe, storico, mese=carica_mese(giorno))
    disegna(giorno, dati, out)
    e, p, med, sc = dati["spicca"]
    print(f"{out}\n  in evidenza: {e} {p}/{dati['n']} contro media {med:.0f}%"
          f" ({sc:+.0f} punti) · esatti presi: {len(dati['esatti'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# ── didascalia per il canale Telegram ────────────────────────────────────────

MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre")

# Telegram taglia la didascalia di un album a 1024 caratteri. Instagram ne
# accetta 2200: sono due testi diversi, e questo e' quello corto.
MAX_DIDASCALIA = 1024


def didascalia(giorno, dati):
    """Il testo che accompagna le due immagini sul canale.

    Scritto dai dati, non a mano: deve uscire ogni mattina senza che nessuno
    lo rilegga. Per questo dice sempre anche cio' che e' andato male — se
    dipendesse da chi scrive, i giorni storti sparirebbero da soli.

    Niente Markdown: i nomi delle squadre possono contenere trattini bassi e
    asterischi, e un carattere sbagliato fa rifiutare l'intero messaggio da
    Telegram con «Can't parse entities». Testo semplice, nessun rischio.
    """
    n, etichetta = dati["n"], dati["spicca"][0]
    presi, media = dati["spicca"][1], dati["spicca"][2]
    g, mese = int(giorno[8:10]), MESI[int(giorno[5:7]) - 1]

    r = [f"{g} {mese} — {n} partite analizzate la mattina, prima del calcio "
         f"d'inizio.", ""]
    pct, dettaglio = accuratezza(presi, n)
    r.append(f"Indice di accuratezza {pct} "
             f"{chr(39).join(['sull', '']) if etichetta == '1X2' else 'su '}"
             f"{etichetta} ({dettaglio}). "
             f"La media storica è {media:.0f}%, su {dati['tot_st']} "
             f"analisi verificate.")
    r.append("Un singolo giorno non definisce il metodo."
             if dati["spicca"][3] >= 0 else
             "Giornata sotto la media. Pubblicata comunque.")
    r.append("")

    esatti = dati["esatti"]
    r.append(f"Risultato esatto: {len(esatti)} su {n} "
             f"(media {dati['esatti_media']:.0f}%)")
    for home, away, detto, finita in esatti[:3]:
        r.append(f"  {home} – {away}: previsto {detto}, reale {finita}")
    if len(esatti) > 3:
        r.append(f"  e altre {len(esatti) - 3}")
    r.append("")

    # La partita andata peggio NON viene piu' nominata qui — scelta
    # dell'utente il 09/09/2026: «non serve accentuare le negativita', ma
    # solo esaltare le cose positive senza nascondere cio' che non si e'
    # avverato».
    #
    # PERCHE' NON E' UN PASSO INDIETRO SULLA TRASPARENZA. Nominare la
    # peggiore era un modo di dimostrare che non selezioniamo i risultati,
    # ma non e' l'unico ne' il principale: l'immagine mostra OGNI riga col
    # suo esito, verde o rossa, e la frase qui sotto dice che restano
    # pubbliche anche le giornate storte. La garanzia sta nel mostrare
    # tutto, non nel puntare il dito su una partita sola.
    r.append("Tutti gli esiti, corretti e sbagliati, restano pubblici qui, "
             "comprese le giornate negative.")
    r.append("")
    r.append(AVVERTENZA_BREVE)
    # Il richiamo va DOPO l'avvertenza (spec 11/09): e' l'ultima riga che
    # si legge, e con PAGAMENTI_ATTIVI=False e' vuoto e non si aggiunge.
    if RICHIAMO:
        r.append("")
        r.append(RICHIAMO)

    testo = "\n".join(r)
    # Se un giorno sforasse, si tolgono righe dal centro (i risultati esatti
    # elencati), mai il disclaimer e mai la riga della media: sono i due
    # pezzi che rendono il messaggio onesto.
    while len(testo) > MAX_DIDASCALIA and len(r) > 8:
        del r[6]
        testo = "\n".join(r)
    return testo


# ── didascalia per Instagram ────────────────────────────────────────────────
#
# DIVERSA da quella del canale, e non per capriccio: Instagram accetta 2200
# caratteri contro i 1024 di Telegram, non rende cliccabile nessun link, e
# usa il testo per capire di cosa parla il post — cioe' per decidere a chi
# mostrarlo. Quindi qui si scrive piu' disteso, si dice «link in bio» invece
# di stampare un indirizzo che nessuno puo' toccare, e si chiude con gli
# hashtag, che servono allo stesso scopo: dire di cosa si tratta.

HASHTAG = ("#analisicalcio #calcio #seriea #premierleague #laliga "
           "#bundesliga #championship #statistiche #datisportivi")


def didascalia_instagram(giorno, dati):
    """Il testo pronto da incollare sotto il carosello degli esiti."""
    n, etichetta = dati["n"], dati["spicca"][0]
    presi, media, scarto = dati["spicca"][1:4]
    g, mese = int(giorno[8:10]), MESI[int(giorno[5:7]) - 1]

    r = [f"{g} {mese}. {n} partite analizzate la mattina, prima del fischio "
         f"d'inizio.", ""]
    pct, dettaglio = accuratezza(presi, n)
    r.append(f"Indice di accuratezza {pct} su {etichetta} ({dettaglio}), "
             f"contro una media storica del {media:.0f}% "
             f"su {dati['tot_st']} analisi verificate.")
    r.append("Un singolo giorno non definisce il metodo."
             if scarto >= 0 else
             "Giornata sotto la media. Pubblicata comunque.")
    r.append("")

    esatti = dati["esatti"]
    if esatti:
        r.append(f"Risultato esatto centrato {len(esatti)} volte su {n} "
                 f"(media {dati['esatti_media']:.0f}%):")
        for home, away, detto, finita in esatti[:3]:
            r.append(f"  {home} - {away}: detto {detto}, finita {finita}")
    else:
        r.append(f"Risultato esatto: nessuno oggi. La media è "
                 f"{dati['esatti_media']:.0f}%, quindi capita spesso.")
    r.append("")

    # Niente riga sulla partita andata peggio: vedi il commento gemello in
    # didascalia(). Le due didascalie devono dire la stessa cosa — se una
    # nomina la peggiore e l'altra no, il canale e Instagram raccontano due
    # giornate diverse.
    r.append("Tutti gli esiti, presi e non presi, restano pubblici sul canale "
             "Telegram. Link in bio.")
    r.append("")
    r.append("Stamattina sono già usciti i segnali attesi di oggi, prima che si "
             "giochino. Segui per vedere come vanno.")
    r.append("")
    r.append(AVVERTENZA)
    r.append("")
    r.append(HASHTAG)
    return "\n".join(r)
