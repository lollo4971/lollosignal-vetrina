#!/usr/bin/env python3
"""Validazione del modello su una stagione tenuta FUORI dall'addestramento.

Il confronto che conta e' con la probabilita' implicita nelle quote: se il
modello non batte quella, non ha valore predittivo autonomo (vedi
`confronta_fonti.py`). Qui invece si misura il modello contro DUE metri
interni, riproducibili da questo solo file:

- la propria calibrazione (la curva "prevista vs osservata"),
- la CLIMATOLOGIA: i tassi di base stimati sul training (quante volte
  finisce 1/X/2, Over, GG in quella lega). E' il metro "non fare niente":
  se il modello non batte nemmeno questo, l'informazione che aggiunge oltre
  alla frequenza storica e' negativa, non solo assente.

Uso:
  ./valida_modello.py                    # tutte le leghe, stagione 2025
  ./valida_modello.py --stagione 2024
  ./valida_modello.py --lega 135
"""
import argparse
import json
import math
import statistics
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from modello_storico import (
    lambde, matrice_punteggi, prob_1x2, prob_gg, prob_over, prob_risultato,
    quota_gol_primo_tempo, stima_parametri, stima_rho,
)
from storico_db import PERCORSO_DB, leggi_partite

EPS = 1e-12


def brier(prob, avvenuto):
    """Brier score per un evento binario: regola di scoring propria."""
    return (prob - (1.0 if avvenuto else 0.0)) ** 2


def brier_multiclasse(probs, prob_vero):
    """Brier score per una distribuzione discreta su piu' esiti (1X2,
    risultato esatto...): regola di scoring propria, a differenza di
    valutare solo la probabilita' assegnata all'esito vero.

    Formula: sum_c (p_c - y_c)^2 = 1 - 2*p_vero + sum_c p_c^2, dove y_c=1
    per l'esito realmente accaduto e 0 per tutti gli altri. Equivalente
    algebrico che evita di dover passare anche l'indicatore one-hot.

    `probs` puo' essere un dict {esito: probabilita'} o un iterable di
    probabilita'; `prob_vero` e' la probabilita' assegnata all'esito
    accaduto (gia' inclusa nella somma).
    """
    valori = probs.values() if hasattr(probs, "values") else probs
    return 1.0 - 2.0 * prob_vero + sum(v * v for v in valori)


def log_loss(prob, avvenuto):
    p = min(max(prob, EPS), 1 - EPS)
    return -math.log(p if avvenuto else 1 - p)


def confronto_accoppiato(a, b):
    """T-test accoppiato fra due serie di punteggi sulle STESSE osservazioni
    (es. Brier del modello e Brier della climatologia sulla stessa partita).

    Ritorna la differenza media (a - b), il suo errore standard e il t di
    Student. Un |t| >= ~2 indica una differenza difficilmente spiegabile dal
    solo rumore campionario; con |t| < 2 le due fonti non sono distinguibili
    su questo campione, e va detto esplicitamente — non "il primo batte il
    secondo" solo perche' la media e' diversa.
    """
    n = len(a)
    if n != len(b) or n < 2:
        return {"n": n, "diff_media": 0.0, "se": 0.0, "t": 0.0}
    diffs = [x - y for x, y in zip(a, b)]
    media = statistics.mean(diffs)
    dev_std = statistics.stdev(diffs)
    se = dev_std / math.sqrt(n)
    if se == 0:
        t = 0.0 if media == 0 else math.copysign(float("inf"), media)
    else:
        t = media / se
    return {"n": n, "diff_media": media, "se": se, "t": t}


def calibrazione(coppie, n_fasce=10):
    """Per ogni fascia di probabilita': quante volte e' successo davvero."""
    fasce = [{"da": i / n_fasce, "a": (i + 1) / n_fasce,
              "n": 0, "somma_prev": 0.0, "avvenuti": 0} for i in range(n_fasce)]
    for prob, avvenuto in coppie:
        i = min(int(prob * n_fasce), n_fasce - 1)
        fasce[i]["n"] += 1
        fasce[i]["somma_prev"] += prob
        fasce[i]["avvenuti"] += 1 if avvenuto else 0
    for f in fasce:
        f["prevista"] = f["somma_prev"] / f["n"] if f["n"] else 0.0
        f["osservata"] = f["avvenuti"] / f["n"] if f["n"] else 0.0
        del f["somma_prev"]
    return fasce


SOGLIA_PRESENZE_COPPA = 15   # mediana presenze/squadra sotto questa soglia -> coppa
SOGLIA_SATURAZIONE = 0.20    # oltre questa quota di squadre sature, stima inaffidabile


def presenze_per_squadra(partite):
    """Numero di partite giocate da ciascuna squadra (casa o trasferta)."""
    conteggio = {}
    for p in partite:
        conteggio[p["home_id"]] = conteggio.get(p["home_id"], 0) + 1
        conteggio[p["away_id"]] = conteggio.get(p["away_id"], 0) + 1
    return conteggio


def e_coppa(partite):
    """Distingue un campionato a girone da una coppa a eliminazione, dai
    dati stessi — non da una lista di id cablata, che si disallineerebbe in
    silenzio se un torneo cambia formato.

    In un girone ogni squadra gioca decine di partite (30-40+ in un
    campionato a due gironi). In una coppa a eliminazione diretta la
    maggioranza delle squadre esce dopo 1-2 turni: la mediana delle
    presenze per squadra crolla molto sotto quella di un girone. E' un
    criterio robusto perche' guarda la FORMA del torneo, non il suo nome.
    """
    conteggio = presenze_per_squadra(partite)
    if not conteggio:
        return False
    return statistics.median(conteggio.values()) < SOGLIA_PRESENZE_COPPA


def frazione_satura(parametri):
    """Quota di squadre i cui parametri hanno toccato il tetto MINIMO o
    MASSIMO nell'ultimo aggiornamento dello stimatore (vedi `saturi` in
    `stima_parametri`): sono squadre con troppo poche presenze per una
    stima vera, non un parametro nel senso pieno del termine."""
    n = len(parametri["attacco"])
    if n == 0:
        return 0.0
    return len(parametri.get("saturi", ())) / n


def tassi_base(partite):
    """Climatologia: le frequenze di 1/X/2, Over 2.5 e GG osservate nel
    training. E' il pronostico "non fare niente" (nessuna informazione
    sulle due squadre, solo il tasso di base della lega) con cui il
    modello deve confrontarsi, non con l'uniforme (1/3,1/3,1/3)."""
    n = len(partite)
    if n == 0:
        return None
    c1 = cx = c2 = cover = cgg = 0
    for p in partite:
        gh, ga = p["ft_home"], p["ft_away"]
        if gh > ga:
            c1 += 1
        elif ga > gh:
            c2 += 1
        else:
            cx += 1
        if gh + ga > 2.5:
            cover += 1
        if gh >= 1 and ga >= 1:
            cgg += 1
    return {"1x2": {"1": c1 / n, "X": cx / n, "2": c2 / n},
            "over25": cover / n, "gg": cgg / n}


def _media(lista):
    return sum(lista) / len(lista) if lista else 0.0


def valida_lega(path_db, league_id, stagione_test):
    """Stima sui dati esclusa la stagione di test, poi misura su quella."""
    tutte = leggi_partite(path_db, league_id)
    train = [p for p in tutte if p["season"] != stagione_test]
    test = [p for p in tutte if p["season"] == stagione_test]
    if len(train) < 100 or len(test) < 30:
        return None

    # coppa vs girone: criterio sui dati (vedi e_coppa), calcolato su TUTTE
    # le partite disponibili per la lega, non solo il training, perche' e'
    # una proprieta' del torneo e non deve dipendere da quale stagione e'
    # stata tenuta fuori per il test.
    coppa = e_coppa(tutte)

    par = stima_parametri(train)
    rho = stima_rho(train[-500:], par)     # rho su un sottoinsieme: e' stabile
    quota_pt = quota_gol_primo_tempo(train)
    clima = tassi_base(train)

    # guardrail: se troppe squadre hanno lo stimatore saturato sui tetti
    # MINIMO/MASSIMO (tipico delle coppe, dove meta' del tabellone ha
    # meno di 10 presenze), la stima e' fallita in silenzio e la lega va
    # segnalata come inaffidabile invece di essere trattata come le altre.
    frazione_sat = frazione_satura(par)
    inaffidabile = frazione_sat > SOGLIA_SATURAZIONE

    ris = {"league_id": league_id, "n_train": len(train), "n_test": len(test),
           "rho": rho, "quota_pt": quota_pt, "climatologia": clima,
           "coppa": coppa, "frazione_satura": frazione_sat,
           "inaffidabile": inaffidabile}

    # coppie (prob, avvenuto) per le curve di calibrazione: piu' voci per
    # partita nel caso 1X2 (una per classe), una sola per over25/gg.
    cal = {"1x2": [], "over25": [], "gg": []}

    # serie di punteggi PER PARTITA (una voce a partita): servono al
    # confronto accoppiato modello/climatologia, che ha bisogno di
    # osservazioni appaiate sulla stessa partita, non di medie gia' fatte.
    serie = {mercato: {"modello": [], "climatologia": []}
             for mercato in ("1x2_brier", "1x2_ll", "over25_brier",
                              "over25_ll", "gg_brier", "gg_ll")}
    serie_esatto = {"brier": [], "log_loss": []}   # niente climatologia: vedi report

    for p in test:
        lh, la = lambde(par, p["home_id"], p["away_id"])
        m = matrice_punteggi(lh, la, rho)
        gh, ga = p["ft_home"], p["ft_away"]
        esito = "1" if gh > ga else ("2" if ga > gh else "X")

        p1x2 = prob_1x2(m)
        for k in ("1", "X", "2"):
            cal["1x2"].append((p1x2[k], k == esito))
        cl1x2 = clima["1x2"]
        serie["1x2_brier"]["modello"].append(brier_multiclasse(p1x2, p1x2[esito]))
        serie["1x2_brier"]["climatologia"].append(brier_multiclasse(cl1x2, cl1x2[esito]))
        serie["1x2_ll"]["modello"].append(log_loss(p1x2[esito], True))
        serie["1x2_ll"]["climatologia"].append(log_loss(cl1x2[esito], True))

        pr_over = prob_over(m, 2.5)
        avv_over = (gh + ga) > 2.5
        cal["over25"].append((pr_over, avv_over))
        serie["over25_brier"]["modello"].append(brier(pr_over, avv_over))
        serie["over25_brier"]["climatologia"].append(brier(clima["over25"], avv_over))
        serie["over25_ll"]["modello"].append(log_loss(pr_over, avv_over))
        serie["over25_ll"]["climatologia"].append(log_loss(clima["over25"], avv_over))

        pr_gg = prob_gg(m)
        avv_gg = gh >= 1 and ga >= 1
        cal["gg"].append((pr_gg, avv_gg))
        serie["gg_brier"]["modello"].append(brier(pr_gg, avv_gg))
        serie["gg_brier"]["climatologia"].append(brier(clima["gg"], avv_gg))
        serie["gg_ll"]["modello"].append(log_loss(pr_gg, avv_gg))
        serie["gg_ll"]["climatologia"].append(log_loss(clima["gg"], avv_gg))

        pr_esatto = prob_risultato(m, gh, ga)
        serie_esatto["brier"].append(brier_multiclasse(m, pr_esatto))
        serie_esatto["log_loss"].append(log_loss(pr_esatto, True))

    n = len(test)
    ris["metriche"] = {
        "1x2": {"brier": _media(serie["1x2_brier"]["modello"]),
                "log_loss": _media(serie["1x2_ll"]["modello"]), "n": n},
        "over25": {"brier": _media(serie["over25_brier"]["modello"]),
                   "log_loss": _media(serie["over25_ll"]["modello"]), "n": n},
        "gg": {"brier": _media(serie["gg_brier"]["modello"]),
               "log_loss": _media(serie["gg_ll"]["modello"]), "n": n},
        "esatto": {"brier": _media(serie_esatto["brier"]),
                   "log_loss": _media(serie_esatto["log_loss"]), "n": n},
    }
    ris["calibrazione_1x2"] = calibrazione(cal["1x2"])
    ris["calibrazione_over25"] = calibrazione(cal["over25"])
    ris["calibrazione_gg"] = calibrazione(cal["gg"])

    # Dati grezzi per l'aggregazione FUORI da questa funzione (in main()):
    # calibrazione su tutte le leghe insieme e confronto accoppiato con la
    # climatologia sull'intero campione, non lega per lega. Rimossi prima
    # di scrivere il JSON (vedi main): non fanno parte dell'output pubblico.
    ris["_cal"] = cal
    ris["_serie"] = serie
    ris["_serie_esatto"] = serie_esatto
    return ris


def _stampa_confronto(nome, modello, climatologia, accoppiato):
    segno = "MEGLIO" if accoppiato["diff_media"] < 0 else "PEGGIO"
    dubbio = "" if abs(accoppiato["t"]) >= 2 else "  (non distinguibili, |t|<2)"
    print(f"  {nome:<10} modello {modello:.4f}  climatologia {climatologia:.4f}  "
          f"-> modello {segno}  (t={accoppiato['t']:+.2f}){dubbio}")


def aggrega(risultati, etichetta, stampa=True):
    """Calibrazione e confronto modello/climatologia su un gruppo di leghe
    gia' validate (campionati, coppe, o tutte insieme: e' lo stesso calcolo,
    cambia solo il sottoinsieme di `risultati` passato).
    """
    tutte_cal = {"1x2": [], "over25": [], "gg": []}
    tutte_serie = {k: {"modello": [], "climatologia": []} for k in
                   ("1x2_brier", "1x2_ll", "over25_brier", "over25_ll",
                    "gg_brier", "gg_ll")}
    n_partite = 0
    for r in risultati:
        n_partite += r["n_test"]
        for k in tutte_cal:
            tutte_cal[k] += r["_cal"][k]
        for k in tutte_serie:
            tutte_serie[k]["modello"] += r["_serie"][k]["modello"]
            tutte_serie[k]["climatologia"] += r["_serie"][k]["climatologia"]

    calibrazione_aggregata = {k: calibrazione(v) for k, v in tutte_cal.items()}

    modello_vs_climatologia = {}
    if stampa:
        print(f"\nModello vs climatologia — {etichetta} "
              f"({len(risultati)} leghe, n={n_partite}):")
    for mercato, chiave_brier, chiave_ll in (
            ("1x2", "1x2_brier", "1x2_ll"),
            ("over25", "over25_brier", "over25_ll"),
            ("gg", "gg_brier", "gg_ll")):
        s_b, s_l = tutte_serie[chiave_brier], tutte_serie[chiave_ll]
        acc_b = confronto_accoppiato(s_b["modello"], s_b["climatologia"])
        acc_l = confronto_accoppiato(s_l["modello"], s_l["climatologia"])
        modello_vs_climatologia[mercato] = {
            "brier": {"modello": _media(s_b["modello"]),
                      "climatologia": _media(s_b["climatologia"]),
                      "accoppiato": acc_b},
            "log_loss": {"modello": _media(s_l["modello"]),
                         "climatologia": _media(s_l["climatologia"]),
                         "accoppiato": acc_l},
        }
        if stampa:
            _stampa_confronto(mercato, _media(s_b["modello"]), _media(s_b["climatologia"]), acc_b)

    return {"n_leghe": len(risultati), "n_partite": n_partite,
            "calibrazione": calibrazione_aggregata,
            "modello_vs_climatologia": modello_vs_climatologia}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stagione", type=int, default=2025)
    ap.add_argument("--lega", type=int, default=None)
    ap.add_argument("--out", default="validazione.json")
    args = ap.parse_args()

    import sqlite3
    conn = sqlite3.connect(f"file:{PERCORSO_DB}?mode=ro", uri=True)
    leghe = ([args.lega] if args.lega else
             [r[0] for r in conn.execute("SELECT DISTINCT league_id FROM partite")])
    conn.close()

    risultati = []
    for lid in sorted(leghe):
        r = valida_lega(PERCORSO_DB, lid, args.stagione)
        if r:
            risultati.append(r)
            mm = r["metriche"]
            tipo = "coppa" if r["coppa"] else "girone"
            avviso = (f"  *** INAFFIDABILE (satura {r['frazione_satura']:.0%}) ***"
                      if r["inaffidabile"] else "")
            print(f"  lega {lid:>4}  {tipo:<6}  test {r['n_test']:>4}  "
                  f"Brier 1X2 {mm['1x2']['brier']:.4f}  "
                  f"logloss esatto {mm['esatto']['log_loss']:.3f}{avviso}")

    n_inaffidabili = sum(1 for r in risultati if r["inaffidabile"])
    if n_inaffidabili:
        print(f"\n{n_inaffidabili} lega/leghe con stima inaffidabile "
              f"(>{SOGLIA_SATURAZIONE:.0%} squadre sui tetti MINIMO/MASSIMO): "
              "incluse nei numeri sotto, non nascoste.")

    # --- Aggregazione: campionati a girone e coppe a eliminazione sono
    # popolazioni diverse (vedi e_coppa) e mischiarle nasconde il quadro
    # vero: il modello va meglio sui gironi e peggio sulle coppe di quanto
    # dica il solo aggregato. Si riportano tutti e tre i livelli, sono i
    # numeri su cui si decide, quindi escono da qui (codice committato), non
    # da script ad-hoc.
    campionati = [r for r in risultati if not r["coppa"]]
    coppe = [r for r in risultati if r["coppa"]]

    agg_campionati = aggrega(campionati, "campionati a girone")
    agg_coppe = aggrega(coppe, "coppe a eliminazione")
    agg_totale = aggrega(risultati, "aggregato (tutte le leghe)")

    # per il file di output non salviamo i dati grezzi (interni, usati solo
    # per l'aggregazione qui sopra): lo JSON deve restare leggibile.
    risultati_puliti = [{k: v for k, v in r.items() if not k.startswith("_")}
                         for r in risultati]

    out = {"generato": datetime.now(ZoneInfo("Europe/Rome")).isoformat(timespec="seconds"),
           "stagione_test": args.stagione, "leghe": risultati_puliti,
           "n_leghe_inaffidabili": n_inaffidabili,
           "campionati": agg_campionati, "coppe": agg_coppe,
           "aggregato": agg_totale,
           # compatibilita' con consumatori del vecchio formato: stessi dati
           # dell'aggregato, sotto i nomi precedenti.
           "calibrazione_aggregata": agg_totale["calibrazione"],
           "modello_vs_climatologia": agg_totale["modello_vs_climatologia"]}
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n{len(risultati)} leghe validate "
          f"({len(campionati)} campionati, {len(coppe)} coppe) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
