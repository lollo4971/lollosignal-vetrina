"""Terza slide: i pronostici di OGGI, prima che si giochino.

PERCHE' ESISTE. Le altre due immagini dicono com'e' andata ieri. Sono la
prova, ma chi le guarda deve fidarsi che avessimo davvero detto quelle cose
prima. Questa slide toglie di mezzo la fiducia: le stesse partite escono
pubblicamente **prima del fischio d'inizio**, e l'immagine degli esiti del
giorno dopo diventa la verifica di qualcosa che il lettore ha gia' visto.

E' anche l'unico contenuto tempestivo che il profilo pubblichi: un account di
soli risultati e' un archivio, e gli archivi non si seguono.

QUALI PARTITE — la regola e' arrivata alla terza versione, e le prime due
erano sbagliate per motivi che vale la pena non ripetere.

**«Le prime N per orario» non e' neutro.** Le partite di richiamo si giocano
la sera: prendere le prime significa pubblicare sistematicamente le piu'
anonime. Misurato su 20 giorni, 0,9 partite di campionato importante in
vetrina contro 2,4 dietro il paywall.

**Prendere le posizioni alterne non basta.** Riequilibra il richiamo, ma con
tre soli posti il dedup pesca sempre dalle prime, e la vetrina resta tutta di
pomeriggio.

**Quella buona: una partita per FASCIA ORARIA.** La giornata si divide in tre
blocchi e da ognuno si prende la prima scheda non gia' vista. Misurato sugli
stessi 20 giorni: 30% di partite di richiamo in vetrina contro il 34% agli
abbonati — praticamente uguali, quindi il campione e' rappresentativo — e zero
giornate con due schede identiche.

Il criterio NON guarda la confidenza ne' il campionato. Scegliere le partite
«sicure» mostrerebbe un bot migliore di quello che si compra, ed e' esattamente
la selezione che rende inaffidabili i pronosticatori. Quello che vedi gratis e'
quello che compri, in quantita' minore.

Uso:
    python3 immagine_prematch.py [YYYY-MM-DD] [--out percorso.png]
Senza data, prende oggi.
"""
import os
import sqlite3
import sys
from datetime import date

from PIL import Image, ImageDraw

# Nella vetrina i percorsi sono relativi al repository (in produzione: /opt/football-bot).
_RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


from avvertenza import AVVERTENZA, AVVERTENZA_BREVE  # noqa: E402
from immagine_esiti import (ALT, DB, LATO, ORO, PANNELLO, PAVIMENTO, RICHIAMO,
                            SFONDO, Y_NOTE, Y_PIEDE, INTERLINEA_NOTE, elenco_che_ci_sta,
                            TENUE, TESTO, VERDE, _corto, _f, piede, sfondo_campo)

# Quante partite escono in vetrina, su dieci. Una costante sola: cambiare
# questo numero e' l'unica cosa da fare per allargare o stringere la vetrina.
QUANTE = 3

ETICHETTA_1X2 = {"1": "1", "X": "X", "2": "2"}


def seleziona(righe, quante=QUANTE):
    """Una partita per fascia oraria, saltando le schede fotocopia.

    `righe` arriva ordinata per orario. Si divide in `quante` blocchi uguali e
    da ognuno si prende la prima partita la cui scheda (1X2, Over, GG,
    risultato esatto) non sia gia' stata presa.

    IL DEDUP non e' un vezzo. Il 03/09 la vetrina sarebbe uscita cosi':
        Palermo - Mantova        1 · SI · GG · 2-1
        Gent - OH Leuven         1 · SI · GG · 2-1
        Al Diriyah - Al-Qadisiyah 2 · SI · GG · 1-2
        Toulouse - Lille          2 · SI · GG · 1-2
    Quattro righe a coppie identiche. Il bot le aveva previste davvero cosi',
    ma pubblicate sembrano un programma che si ripete, e dalla seconda riga di
    ogni coppia il lettore non impara niente.

    Si scarta per FORMA della scheda, mai per confidenza: la varieta' non
    correla con l'azzeccarci, quindi non falsa il campione.
    """
    n = len(righe)
    if not n:
        return []
    scelte, viste = [], set()
    for i in range(quante):
        blocco = righe[i * n // quante:(i + 1) * n // quante]
        for r in blocco:
            if r[4:] not in viste:
                scelte.append(r)
                viste.add(r[4:])
                break
    # una fascia puo' restare vuota se tutte le sue schede erano gia' viste:
    # si completa dal resto della giornata, cedendo sulla varieta' e non sul
    # numero di partite pubblicate.
    for r in righe:
        if len(scelte) >= quante:
            break
        if r not in scelte:
            scelte.append(r)
    return sorted(scelte[:quante], key=lambda r: (r[3] or "", r[0]))


def _scheda(riga):
    """La riga di pronostico come esce stampata: 1X2 · Over · GG · esatto."""
    return " · ".join(str(x) for x in riga[4:8])


def doppioni(righe):
    """Quante schede identiche ci sono fra quelle pubblicate.

    Il dedup di `seleziona` scarta le fotocopie, ma cede quando la
    giornata ha poche partite e tutte simili: il 21/09/2026, con sole
    quattro partite disponibili tutte alle 20:30, in vetrina sono uscite
    due schede gemelle (1 · NO · NG · 1-0). Non e' un errore da bloccare
    — meglio tre partite con una ripetizione che due partite — ma va
    visto, perche' il 03/09 il dedup era nato esattamente per questo.
    """
    schede = [_scheda(r) for r in righe]
    return len(schede) - len(set(schede))


def registra_vetrina(giorno, righe, db_path=DB):
    """Registra COSA e' uscito davvero in vetrina, al momento del disegno.

    PERCHE' (21/09/2026). Le tre gratuite sono la prova pubblica del
    prodotto: «l'avevamo detto prima che si giocasse». Ma di quello che
    era stato pubblicato non restava traccia — `pubblicati.json` segna
    solo che l'immagine del giorno e' uscita. Le tre si potevano solo
    RICALCOLARE, e il ricalcolo cambia in silenzio se una riga cambia
    origine (successo il 09/09) o se ne compare una nuova quel giorno.

    Il `fixture_id` e' un di piu', risolto per nome: se non combacia la
    riga si registra comunque con NULL. Perdere la prova di cosa e'
    uscito e' il danno peggiore; un id mancante si ritrova a mano.

    Idempotente (PK data+posizione): rigenerare l'immagine riscrive le
    stesse righe. Non solleva mai — sta nello script del mattino.
    """
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS vetrina_pubblicate(
                data TEXT NOT NULL, posizione INTEGER NOT NULL,
                fixture_id INTEGER, home TEXT, away TEXT, lega TEXT,
                kickoff TEXT, scheda TEXT,
                PRIMARY KEY(data, posizione))""")
            n = 0
            for pos, r in enumerate(righe, start=1):
                fid = conn.execute(
                    "SELECT fixture_id FROM prematch_predictions "
                    "WHERE match_date=? AND home=? AND away=? LIMIT 1",
                    (giorno, r[0], r[1])).fetchone()
                conn.execute(
                    "INSERT OR REPLACE INTO vetrina_pubblicate "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (giorno, pos, fid[0] if fid else None,
                     r[0], r[1], r[2], r[3], _scheda(r)))
                n += 1
            conn.commit()
            return n
        finally:
            conn.close()
    except Exception as e:
        print(f"  registro vetrina non aggiornato: {e}")
        return 0


def carica(giorno, db_path=DB):
    """Le partite del batch di oggi e quelle che vanno in vetrina."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        righe = conn.execute(
            "SELECT home, away, league, kickoff, ft_1x2, ft_over25, ft_gg, "
            "risultato_ft FROM prematch_predictions "
            "WHERE match_date=? AND origine IN ('batch','valore') ORDER BY kickoff, id",
            (giorno,)).fetchall()
        storico = conn.execute(
            "SELECT COUNT(*), SUM(esito_1x2='VINTO'), SUM(esito_over25='VINTO'), "
            "SUM(esito_gg='VINTO'), SUM(esito_risultato='VINTO') "
            "FROM prematch_predictions "
            "WHERE origine IN ('batch','valore') AND esito_1x2 IS NOT NULL").fetchone()
    finally:
        conn.close()
    return seleziona(righe), len(righe), storico


def carica_turno(turno, db_path=DB):
    """Le partite di un turno chiesto dall'admin, ancora da giocare."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        righe = conn.execute(
            "SELECT home, away, league, kickoff, ft_1x2, ft_over25, ft_gg, "
            "risultato_ft FROM prematch_predictions "
            "WHERE turno=? ORDER BY kickoff, id", (turno,)).fetchall()
        storico = conn.execute(
            "SELECT COUNT(*), SUM(esito_1x2='VINTO'), SUM(esito_over25='VINTO'), "
            "SUM(esito_gg='VINTO'), SUM(esito_risultato='VINTO') "
            "FROM prematch_predictions "
            "WHERE origine IN ('batch','turno','valore') AND esito_1x2 IS NOT NULL"
        ).fetchone()
    finally:
        conn.close()
    # Qui NON si seleziona: le partite del turno sono gia' state scelte a
    # monte, per importanza, quando il turno e' stato richiesto.
    return righe, len(righe), storico


def disegna(giorno, righe, totale, storico, out, titolo=None, coda=None):
    img = sfondo_campo(LATO, ALT)
    d = ImageDraw.Draw(img)
    grassetto = lambda s: _f("DejaVuSans-Bold.ttf", s)
    normale = lambda s: _f("DejaVuSans.ttf", s)
    mono = lambda s: _f("DejaVuSansMono-Bold.ttf", s)

    g, m, a = giorno[8:10], giorno[5:7], giorno[:4]
    d.text((60, 52), "LOLLOSIGNAL", font=grassetto(34), fill=ORO)
    # `titolo` serve ai turni chiesti dall'admin: «UEFA Champions League —
    # Giornata 1» al posto della data. Il resto dell'immagine e' identico,
    # perche' l'identita' visiva non deve dipendere da chi l'ha chiesta.
    sottotitolo = titolo or f"Segnali attesi del {g}/{m}/{a}"
    f_sub = normale(30)
    while d.textlength(sottotitolo, font=f_sub) > 960 and f_sub.size > 20:
        f_sub = normale(f_sub.size - 1)
    d.text((60, 96), sottotitolo, font=f_sub, fill=TENUE)
    d.text((60, 140), "Pubblicati PRIMA del calcio d'inizio",
           font=grassetto(21), fill=VERDE)

    # Le stesse colonne, nello stesso ordine, dell'immagine degli esiti: il
    # confronto del giorno dopo deve leggersi senza cercare niente.
    X_ORA, X_1X2, X_OVER, X_GG, X_RIS = 452, 560, 650, 762, 872
    d.text((60, 190), "PARTITA", font=grassetto(19), fill=TENUE)
    d.text((X_ORA, 190), "ORA", font=normale(17), fill=TENUE)
    d.text((X_1X2, 190), "1X2", font=normale(17), fill=TENUE)
    d.text((X_OVER, 190), "OVER 2.5", font=normale(17), fill=TENUE)
    d.text((X_GG, 190), "GG", font=normale(17), fill=TENUE)
    d.text((X_RIS, 190), "RIS. ESATTO", font=normale(17), fill=TENUE)
    d.line([(60, 216), (LATO - 60, 216)], fill=PANNELLO, width=2)

    # ALTEZZA DELLE RIGHE CALCOLATA SUL NUMERO DI PARTITE.
    #
    # Il disegno era tarato su TRE righe alte, e con tre partite e' giusto:
    # l'immagine si guarda su un telefono, e scrivere grande e' il vantaggio
    # di averne poche. Ma i turni chiesti dall'admin ne hanno fino a dieci, e
    # con il passo fisso l'elenco finiva a y 1534 su un'immagine alta 1080:
    # sette righe visibili e le ultime sopra il testo del piede.
    #
    # Ora il passo si ricava dallo spazio disponibile. Sotto i 60 px non ci
    # sta la riga del campionato e si toglie: meglio perderla che vedere due
    # testi accavallati.
    #
    # Dal 09/09/2026 il conto NON e' piu' una costante scritta a mano
    # (`FONDO_ELENCO = 640`) ma `elenco_che_ci_sta`, la stessa delle altre
    # due slide. Una costante tarata a occhio e' precisamente cio' che si e'
    # rotto sulla slide dell'analisi: giusta finche' il contenuto sotto non
    # cambia, e muta il giorno in cui cambia.
    y = 254
    CODA_CURRICULUM = 24 + 150
    quante, passo = elenco_che_ci_sta(y, len(righe), 128, 46,
                                      coda=CODA_CURRICULUM)
    fuori_spazio = len(righe) - quante
    compatto = passo < 60
    c_nome = 31 if passo >= 100 else (26 if passo >= 60 else 23)
    c_val = 32 if passo >= 100 else (28 if passo >= 60 else 24)
    for home, away, lega, ora, p1, po, pg, pr in righe[:quante]:
        nome = f"{_corto(home, 20)} – {_corto(away, 20)}"
        f_nome = normale(c_nome)
        while d.textlength(nome, font=f_nome) > 370 and f_nome.size > 15:
            f_nome = normale(f_nome.size - 1)
        d.text((60, y), nome, font=f_nome, fill=TESTO)
        if not compatto:
            d.text((62, y + c_nome + 9), _corto(lega or "", 34),
                   font=normale(19), fill=TENUE)
        d.text((X_ORA, y + 2), (ora or "")[:5], font=mono(min(c_val - 4, 26)),
               fill=TENUE)
        # I pronostici NON sono colorati di verde o rosso: non c'e' ancora
        # nessun esito, e un colore qui suggerirebbe una fiducia che non
        # abbiamo. Il colore arriva domani, sull'immagine degli esiti.
        for x, valore in ((X_1X2, ETICHETTA_1X2.get(p1, p1 or "?")),
                          (X_OVER, po or "?"), (X_GG, pg or "?"),
                          (X_RIS, pr or "?")):
            d.text((x, y), str(valore), font=mono(c_val), fill=ORO)
        y += passo

    # ── il curriculum, perche' un pronostico senza tasso base non dice niente
    tot_st, s1, so, sg, sr = storico
    pct = lambda v: 100 * (v or 0) / tot_st if tot_st else 0
    if fuori_spazio:
        # Terza volta che serve questa regola nel progetto: niente sparisce
        # in silenzio.
        d.text((60, y + 4), f"e altre {fuori_spazio} partite",
               font=normale(21), fill=TENUE)
        y += 30

    # attaccato alla fine dell'elenco, non a una coordinata fissa: con tre
    # partite invece di dieci il pannello non deve restare a mezz'aria, e
    # con dieci non deve finirci sopra. Il tetto e' il PAVIMENTO meno
    # l'altezza del pannello, non un numero tarato a occhio: cosi' cambiare
    # il formato del foglio non richiede di ritarare niente.
    y = min(max(y + 24, 620), PAVIMENTO - 150)
    d.rounded_rectangle([48, y, LATO - 48, y + 150], 22, fill=PANNELLO)
    d.text((78, y + 24), f"RENDIMENTO · {tot_st} segnali verificati",
           font=grassetto(22), fill=TENUE)
    x = 78
    for etichetta, v in (("1X2", s1), ("Over 2.5", so), ("GG/NG", sg),
                         ("Ris. esatto", sr)):
        d.text((x, y + 64), f"{pct(v):.0f}%", font=mono(34), fill=TESTO)
        d.text((x, y + 106), etichetta, font=normale(20), fill=TENUE)
        x += 240

    if coda:
        # Testo libero per i turni: la regola di selezione e' un'altra e va
        # dichiarata, altrimenti l'immagine spiega un criterio che non e'
        # quello usato.
        for i, riga in enumerate(coda[:3]):
            d.text((60, Y_NOTE + i * INTERLINEA_NOTE), riga, font=normale(22), fill=TENUE)
    else:
        d.text((60, Y_NOTE),
               f"{len(righe)} segnali pubblici. I restanti "
               f"{max(totale - len(righe), 0)} sono riservati ai membri,",
               font=normale(22), fill=TENUE)
        d.text((60, Y_NOTE + INTERLINEA_NOTE),
               "insieme ai segnali live. Domani mattina gli esiti di tutti.",
               font=normale(22), fill=TENUE)
        d.text((60, Y_NOTE + 2 * INTERLINEA_NOTE),
               "Scelte una per fascia oraria, mai per confidenza.",
               font=normale(20), fill=TENUE)

    piede(d, Y_PIEDE)

    img.save(out, "PNG")
    return out


def didascalia(giorno, righe, totale, storico):
    """Testo per il canale. Stesso limite di 1024 caratteri dell'album."""
    from immagine_analisi import MESI
    g, mese = int(giorno[8:10]), MESI[int(giorno[5:7]) - 1]
    tot_st = storico[0]
    r = [f"{g} {mese} — i segnali attesi di oggi, prima che si giochino.", ""]
    for home, away, lega, ora, p1, po, pg, pr in righe:
        r.append(f"{ora} {home} – {away}")
        r.append(f"   {ETICHETTA_1X2.get(p1, p1 or '?')} · Over {po or '?'} · "
                 f"{pg or '?'} · esatto {pr or '?'}")
    r.append("")
    r.append(f"{len(righe)} segnali pubblici. I restanti "
             f"{max(totale - len(righe), 0)} sono riservati ai membri del VIP "
             f"Club, insieme ai segnali live.")
    r.append("Domani mattina gli esiti di tutti, corretti e sbagliati.")
    r.append("")
    r.append(f"Scelte una per fascia oraria, mai per confidenza. "
             f"Storico su {tot_st} segnali verificati.")
    r.append("")
    r.append(AVVERTENZA_BREVE)
    # Il richiamo va DOPO l'avvertenza (spec 11/09): e' l'ultima riga che
    # si legge, e con PAGAMENTI_ATTIVI=False e' vuoto e non si aggiunge.
    if RICHIAMO:
        r.append("")
        r.append(RICHIAMO)
    testo = "\n".join(r)
    while len(testo) > 1024 and len(r) > 8:
        del r[2]                      # toglie una partita, mai il disclaimer
        testo = "\n".join(r)
    return testo


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    giorno = args[0] if args else date.today().isoformat()
    out = os.path.join(_RADICE, "prematch_") + giorno.replace("-", "") + ".png"
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    righe, totale, storico = carica(giorno)
    if not righe:
        print(f"Nessun pronostico batch per {giorno}: niente da pubblicare.")
        return 1
    disegna(giorno, righe, totale, storico, out)
    registra_vetrina(giorno, righe)
    print(f"{out}\n  {len(righe)} in vetrina su {totale} · "
          + " · ".join(f"{r[3]} {r[0]}-{r[1]}" for r in righe))
    _dopp = doppioni(righe)
    if _dopp:
        print(f"  ⚠️  {_dopp} scheda/e identica/he in vetrina: la giornata "
              f"aveva poche partite da cui pescare")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def didascalia_instagram(giorno, righe, totale, storico):
    """Il testo pronto da incollare sotto il Reel o il post dei pronostici.

    LA PRIMA RIGA DEVE REGGERE DA SOLA. Nei Reel Instagram mostra una riga e
    mezza e poi taglia con «altro»: per la maggior parte di chi guarda,
    quella riga è tutta la didascalia. Deve dire cosa si sta guardando e
    perche' tornare domani.

    Nessun indirizzo Telegram nel testo: non sarebbe cliccabile e l'indirizzo
    e' gia' impresso negli ultimi secondi del video, dove sopravvive anche
    agli screenshot.
    """
    from immagine_analisi import HASHTAG, MESI
    g, mese = int(giorno[8:10]), MESI[int(giorno[5:7]) - 1]
    tot_st, s1, so, sg, sr = storico
    pct = lambda v: 100 * (v or 0) / tot_st if tot_st else 0

    r = ["Tre segnali attesi pubblicati stamattina, prima che si giochino. "
         "Domani gli esiti.", ""]
    r.append(f"{g} {mese}:")
    for home, away, lega, ora, p1, po, pg, pr in righe:
        r.append(f"  {ora} {home} - {away} ({lega})")
    r.append("")
    r.append("Per ognuna: 1X2, Over 2.5, GG e risultato esatto, detti prima "
             "del calcio d'inizio.")
    r.append("")
    r.append(f"Su {tot_st} segnali verificati: 1X2 {pct(s1):.0f}% · "
             f"Over 2.5 {pct(so):.0f}% · GG {pct(sg):.0f}% · "
             f"esatto {pct(sr):.0f}%.")
    r.append("Anche le giornate negative restano pubbliche.")
    r.append("")
    r.append(f"I restanti {max(totale - len(righe), 0)} sono riservati ai "
             f"membri del VIP Club, insieme ai segnali live. Link in bio.")
    r.append("")
    r.append(AVVERTENZA)
    r.append("")
    r.append(HASHTAG)
    return "\n".join(r)
