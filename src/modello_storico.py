# modello_storico.py
"""Modello statistico sui risultati storici.

Stima la forza d'attacco e di difesa di ogni squadra e ne ricava la
probabilita' di ogni punteggio esatto. Da li' derivano coerentemente 1X2,
Over di ogni linea e GG.

Tutto in Python puro: numpy e scipy peserebbero ~100 MB su una VPS da 4 GB
e per questa forma moltiplicativa non servono, perche' gli aggiornamenti in
forma chiusa convergono senza ottimizzatore generico.
"""
import math
from datetime import date

EPS = 1e-9
MINIMO = 0.05      # pavimento sui parametri: evita zeri assorbenti
MASSIMO = 10.0
HOME_ADV_MASSIMO = 2.0   # tetto sul fattore campo: senza, un campione con
                          # pochi gol fuori casa manda home_adv a valori
                          # enormi e la matrice dei punteggi collassa a zero
CONVERGENZA = 1e-9        # variazione massima sotto la quale il fit si ferma


def peso_temporale(data_partita, riferimento, meta_vita_giorni=365):
    """Peso esponenziale: 1.0 oggi, 0.5 dopo una meta-vita.

    Serve a dare piu' importanza al calcio recente: i campionati si stanno
    appiattendo e cinque stagioni fa erano un'altra cosa.
    """
    try:
        d1 = date.fromisoformat(str(data_partita)[:10])
        d0 = date.fromisoformat(str(riferimento)[:10])
    except (ValueError, TypeError):
        return 0.0
    giorni = (d0 - d1).days
    if giorni < 0:
        return 1.0
    return 0.5 ** (giorni / meta_vita_giorni)


def stima_parametri(partite, meta_vita_giorni=365, iterazioni=60):
    """Attacco e difesa per squadra, piu' il fattore campo.

    Modello:  lambda_casa   = attacco_casa   * difesa_ospite * home_adv
              lambda_ospite = attacco_ospite * difesa_casa
    """
    if not partite:
        return {"attacco": {}, "difesa": {}, "home_adv": 1.0, "media_gol": 0, "saturi": set()}

    date_valide = []
    for p in partite:
        try:
            date.fromisoformat(str(p["data"])[:10])
        except (ValueError, TypeError):
            continue
        date_valide.append(str(p["data"])[:10])
    if not date_valide:
        return {"attacco": {}, "difesa": {}, "home_adv": 1.0, "media_gol": 0, "saturi": set()}
    riferimento = max(date_valide)
    dati = []
    for p in partite:
        w = peso_temporale(p["data"], riferimento, meta_vita_giorni)
        if w > 0:
            dati.append((p["home_id"], p["away_id"],
                         p["ft_home"], p["ft_away"], w))
    if not dati:
        return {"attacco": {}, "difesa": {}, "home_adv": 1.0, "media_gol": 0, "saturi": set()}

    squadre = sorted({d[0] for d in dati} | {d[1] for d in dati})
    att = {t: 1.0 for t in squadre}
    dif = {t: 1.0 for t in squadre}
    saturi = set()   # squadre il cui ultimo aggiornamento ha toccato MINIMO/MASSIMO

    gol_casa = sum(d[2] * d[4] for d in dati)
    gol_fuori = sum(d[3] * d[4] for d in dati)
    peso_tot = sum(d[4] for d in dati)
    home_adv = min(max((gol_casa + EPS) / (gol_fuori + EPS), 1.0), HOME_ADV_MASSIMO)
    media_gol = (gol_casa + gol_fuori) / (2 * peso_tot)

    for _ in range(iterazioni):
        att_prima = dict(att)
        dif_prima = dict(dif)
        saturi = set()

        # attacco: gol fatti / gol attesi dato il resto
        num_a = {t: 0.0 for t in squadre}
        den_a = {t: 0.0 for t in squadre}
        for h, a, gh, ga, w in dati:
            num_a[h] += w * gh
            den_a[h] += w * dif[a] * home_adv * media_gol
            num_a[a] += w * ga
            den_a[a] += w * dif[h] * media_gol
        for t in squadre:
            grezzo = (num_a[t] + EPS) / (den_a[t] + EPS)
            att[t] = min(max(grezzo, MINIMO), MASSIMO)
            if att[t] == MINIMO or att[t] == MASSIMO:
                saturi.add(t)

        # normalizza: attacco medio = 1, cosi' i parametri sono confrontabili
        # (nota: la divisione sposta l'attacco saturo lontano dal valore
        # letterale MINIMO/MASSIMO, ma la squadra e' segnata comunque: e'
        # il clip PRIMA della normalizzazione a dire che i dati non
        # bastavano, non il valore finale)
        m = sum(att.values()) / len(att)
        if m > 0:
            for t in squadre:
                att[t] /= m

        # difesa: gol subiti / gol attesi dato il resto
        num_d = {t: 0.0 for t in squadre}
        den_d = {t: 0.0 for t in squadre}
        for h, a, gh, ga, w in dati:
            num_d[a] += w * gh
            den_d[a] += w * att[h] * home_adv * media_gol
            num_d[h] += w * ga
            den_d[h] += w * att[a] * media_gol
        for t in squadre:
            grezzo = (num_d[t] + EPS) / (den_d[t] + EPS)
            dif[t] = min(max(grezzo, MINIMO), MASSIMO)
            if dif[t] == MINIMO or dif[t] == MASSIMO:
                saturi.add(t)

        # criterio di arresto: se attacco e difesa non si muovono piu',
        # continuare fino a `iterazioni` e' solo tempo sprecato
        variazione = max(
            max(abs(att[t] - att_prima[t]) for t in squadre),
            max(abs(dif[t] - dif_prima[t]) for t in squadre),
        )
        if variazione < CONVERGENZA:
            break

    return {"attacco": att, "difesa": dif,
            "home_adv": home_adv, "media_gol": media_gol,
            "saturi": saturi}


def _poisson(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def lambde(parametri, home_id, away_id):
    """Gol attesi delle due squadre. Squadra sconosciuta -> media di lega.

    La media di lega e' la media dei valori STIMATI, non 1.0: l'attacco e'
    normalizzato a media 1 dentro `stima_parametri`, ma la difesa no (la
    sua media di equilibrio e' circa 2/(1+home_adv), circa 0.9 in una lega
    tipica). Usare 1.0 come fallback per la difesa penalizzerebbe le
    neopromosse di un ~10% per puro artefatto numerico.
    """
    att = parametri["attacco"]
    dif = parametri["difesa"]
    mg = parametri["media_gol"]
    ha = parametri["home_adv"]
    att_medio = sum(att.values()) / len(att) if att else 1.0
    dif_medio = sum(dif.values()) / len(dif) if dif else 1.0
    a_h = att.get(home_id, att_medio)
    a_a = att.get(away_id, att_medio)
    d_h = dif.get(home_id, dif_medio)
    d_a = dif.get(away_id, dif_medio)
    return a_h * d_a * ha * mg, a_a * d_h * mg


def _tau(x, y, lam_h, lam_a, rho):
    """Correzione Dixon-Coles sui quattro punteggi bassi 0-0, 1-0, 0-1, 1-1.

    Con rho negativo (il caso tipico nel calcio) alza 0-0 e 1-1, che il
    Poisson puro sottostima, e ABBASSA 1-0 e 0-1, che sovrastima
    leggermente: non e' vero che il Poisson sottostima tutti e quattro.
    """
    if rho == 0:
        return 1.0
    if x == 0 and y == 0:
        return 1 - lam_h * lam_a * rho
    if x == 0 and y == 1:
        return 1 + lam_h * rho
    if x == 1 and y == 0:
        return 1 + lam_a * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def _rho_valido(rho, lam_h, lam_a):
    """Clippa rho ai limiti Dixon-Coles (Dixon & Coles 1997, eq. 4) che
    garantiscono tau non negativo sui quattro punteggi corretti:
    max(-1/lam_h, -1/lam_a) <= rho <= min(1/(lam_h*lam_a), 1).

    Senza questo, un rho fuori range rende tau(0,0) negativo con lambda
    alti, il `max(v, 0.0)` a valle lo azzera in silenzio e la massa di
    probabilita' non si conserva piu' esattamente.
    """
    if lam_h <= 0 or lam_a <= 0:
        return rho
    minimo = max(-1.0 / lam_h, -1.0 / lam_a, -1.0)
    massimo = min(1.0 / (lam_h * lam_a), 1.0)
    return min(max(rho, minimo), massimo)


def matrice_punteggi(lam_h, lam_a, rho=0.0, max_gol=8):
    """Probabilita' di ogni punteggio da 0-0 a max_gol-max_gol, normalizzata."""
    rho = _rho_valido(rho, lam_h, lam_a)
    m = {}
    for x in range(max_gol + 1):
        for y in range(max_gol + 1):
            v = _poisson(x, lam_h) * _poisson(y, lam_a) * \
                _tau(x, y, lam_h, lam_a, rho)
            m[(x, y)] = max(v, 0.0)
    tot = sum(m.values())
    if tot > 0:
        for k in m:
            m[k] /= tot
    return m


def prob_1x2(matrice):
    p = {"1": 0.0, "X": 0.0, "2": 0.0}
    for (x, y), v in matrice.items():
        p["1" if x > y else ("2" if y > x else "X")] += v
    return p


def prob_over(matrice, linea):
    """Probabilita' che i gol totali superino `linea`.

    ATTENZIONE (validazione del 18/08/2026, vedi
    docs/superpowers/specs/2026-08-17-modello-storico-design.md#risultati-della-validazione):
    nel PREMATCH (`matrice` costruita da `matrice_punteggi`, pre-partita)
    questa probabilita' e' misurata PEGGIO della semplice climatologia di
    lega (il tasso storico di Over 2.5 in quel campionato) sia sui
    campionati a girone sia sulle coppe. Non usarla per decidere in
    prematch. Nel LIVE, con `matrice_da_minuto` (che parte dal punteggio
    reale in corso), il modello batte la climatologia: la distinzione e'
    fra "prima" e "durante" la partita, non fra Over e GG.
    """
    return sum(v for (x, y), v in matrice.items() if x + y > linea)


def prob_gg(matrice):
    """Probabilita' che entrambe le squadre segnino.

    ATTENZIONE: stessa avvertenza di `prob_over` qui sopra — in PREMATCH
    misurata peggio della climatologia di lega, non affidabile per
    decidere. In LIVE (via `matrice_da_minuto`) batte la climatologia.
    """
    return sum(v for (x, y), v in matrice.items() if x >= 1 and y >= 1)


def prob_risultato(matrice, casa, ospite):
    return matrice.get((casa, ospite), 0.0)


def stima_rho(partite, parametri, griglia=None):
    """Sceglie il rho che massimizza la verosimiglianza, per ricerca a griglia.

    Una ricerca su 25 valori e' piu' che sufficiente e non richiede un
    ottimizzatore: rho vive in un intervallo stretto e noto.
    """
    if griglia is None:
        griglia = [-0.30 + i * 0.02 for i in range(26)]
    migliore, best_ll = 0.0, float("-inf")
    for rho in griglia:
        ll = 0.0
        for p in partite:
            lh, la = lambde(parametri, p["home_id"], p["away_id"])
            v = _poisson(p["ft_home"], lh) * _poisson(p["ft_away"], la) * \
                _tau(p["ft_home"], p["ft_away"], lh, la, rho)
            ll += math.log(max(v, 1e-12))
        if ll > best_ll:
            best_ll, migliore = ll, rho
    return migliore


QUOTA_PT_DEFAULT = 0.45   # frazione di gol nel primo tempo, valore consolidato


def quota_gol_primo_tempo(partite):
    """Frazione dei gol segnata nel primo tempo, dai parziali storici."""
    pt = tot = 0
    for p in partite:
        if p.get("ht_home") is None or p.get("ht_away") is None:
            continue
        pt += p["ht_home"] + p["ht_away"]
        tot += p["ft_home"] + p["ft_away"]
    if tot == 0:
        return QUOTA_PT_DEFAULT
    return pt / tot


def matrice_primo_tempo(lam_h, lam_a, quota_pt, rho=0.0, max_gol=6):
    """Punteggi al 45', scalando i gol attesi sulla quota di primo tempo."""
    return matrice_punteggi(lam_h * quota_pt, lam_a * quota_pt, rho, max_gol)


def matrice_da_minuto(lam_h, lam_a, minuto, gol_casa, gol_ospite,
                      rho=0.0, max_gol=8, quota_pt=None):
    """Probabilita' dei punteggi FINALI dato lo stato attuale.

    I gol nel tempo restante seguono un Poisson con intensita' proporzionale
    ai minuti che mancano. Il punteggio corrente e' il pavimento: 2-1 al 70'
    non puo' finire 1-1.

    Di default (`quota_pt=None`) l'intensita' e' uniforme sui 90 minuti,
    comportamento invariato rispetto alla versione precedente. Passando
    `quota_pt` (es. il valore misurato da `quota_gol_primo_tempo`) si usa
    invece un ritmo costante a tratti — primo tempo a intensita' quota_pt,
    secondo tempo a intensita' 1-quota_pt — perche' nel calcio si segna
    sistematicamente di piu' nella ripresa (quota_pt tipico ~0.44, non
    0.5): con l'ipotesi uniforme i gol residui nel secondo tempo sono
    sottostimati.

    Limite noto (vedi spec): senza cronologia gol storica non si modella
    l'effetto dello stato della partita — chi e' in vantaggio si difende.
    """
    if quota_pt is None:
        restante = max(0.0, min(90 - minuto, 90)) / 90.0
    elif minuto <= 0:
        restante = 1.0
    elif minuto >= 90:
        restante = 0.0
    elif minuto <= 45:
        # minuti che restano nel PT (a intensita' quota_pt) + tutto il ST
        restante = quota_pt * (45 - minuto) / 45 + (1 - quota_pt)
    else:
        # solo la coda del ST, a intensita' (1 - quota_pt)
        restante = (1 - quota_pt) * (90 - minuto) / 45
    rh = lam_h * restante
    ra = lam_a * restante
    rho = _rho_valido(rho, rh, ra)
    m = {}
    for dx in range(max_gol + 1):
        for dy in range(max_gol + 1):
            x, y = gol_casa + dx, gol_ospite + dy
            v = _poisson(dx, rh) * _poisson(dy, ra) * _tau(dx, dy, rh, ra, rho)
            m[(x, y)] = m.get((x, y), 0.0) + max(v, 0.0)
    tot = sum(m.values())
    if tot > 0:
        for k in m:
            m[k] /= tot
    return m
