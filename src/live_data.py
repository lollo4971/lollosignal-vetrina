"""Statistiche live da API-Football e gate sui dati.

Due responsabilita', entrambe misurate sui dati del 14/08/2026:

1. ESTRAZIONE. L'API espone 18 campi per squadra; bot.py ne leggeva 7 e uno
   di questi ("Expected Goals") non esisteva: il nome reale e' "expected_goals"
   in minuscolo. Risultato, l'xG valeva sempre 0 e la riga nel prompt era
   soppressa dal test skip-if-0, pur essendo citato tre volte nel system
   prompt come dato su cui ragionare.

2. GATE. Su 671 analisi in 24 ore, 436 (65%) riguardavano leghe di livello 3,
   che non hanno statistiche: il modello riceveva solo punteggio e minuto.
   should_analyze_fixture() taglia quelle chiamate PRIMA di pagarle.
"""

# chiave interna -> "type" esatto restituito da API-Football.
# Esclusi di proposito: "Yellow Cards"/"Red Cards" (gia' ricavati dagli
# eventi con il minuto esatto) e "Passes accurate" (= passes * pass_pct).
API_FIELDS = {
    "sog":              "Shots on Goal",
    "shots_off":        "Shots off Goal",
    "shots":            "Total Shots",
    "blocked":          "Blocked Shots",
    "shots_inside":     "Shots insidebox",
    "shots_outside":    "Shots outsidebox",
    "fouls":            "Fouls",
    "corners":          "Corner Kicks",
    "offsides":         "Offsides",
    "possession":       "Ball Possession",
    "saves":            "Goalkeeper Saves",
    "passes":           "Total passes",
    "pass_pct":         "Passes %",
    "xg":               "expected_goals",
    "goals_prevented":  "goals_prevented",
}


def stat_val(name, stat_list):
    """Valore numerico di una statistica, 0 se assente o nulla.

    Gestisce interi ("9"), percentuali ("73%") e decimali ("1.43"):
    la versione precedente faceva int() diretto e sarebbe esplosa sull'xG
    una volta corretto il nome del campo.
    """
    if not stat_list:
        return 0
    for s in stat_list:
        if s.get("type") != name:
            continue
        v = s.get("value")
        if v is None:
            return 0
        txt = str(v).replace("%", "").strip()
        if not txt:
            return 0
        try:
            return float(txt) if "." in txt else int(txt)
        except ValueError:
            return 0
    return 0


def extract_stats(stat_list):
    """Tutti i campi di API_FIELDS come dict, con 0 per quelli mancanti."""
    return {k: stat_val(tipo, stat_list) for k, tipo in API_FIELDS.items()}


# ─── Convergenza dei dati (21/09/2026) ──────────────────────────────────────
# «L'ho costruito per emettere segnali, non per scartarli» (utente).
# La regola dei DUE INDICATORI CONCORDANTI stava scritta nel prompt ma non
# era mai stata verificata dal codice: il cancello vero era la confidenza
# dichiarata, che pero' Haiku scrive quasi sempre uguale (76 in 9 casi su
# 10, misurato su 20 partite). Qui la regola diventa un controllo sui
# numeri, e vale come via alternativa alla soglia di confidenza.
MARGINE_DOMINIO = 1.5       # quanto deve guidare un indicatore per "contare"
INDICATORI_MINIMI = 2
# Soglie di RITMO (somma delle due squadre) tarate sui dati veri e non a
# occhio: 4.281 rilevazioni al minuto 55-80 di signals.db. Sono i valori
# dell'80° percentile — «ritmo alto» deve voler dire una partita su cinque,
# non quattro su cinque. Con la prima taratura a occhio (5/12/5) l'OVER
# convergeva nell'89% dei casi: una porta spalancata, non un criterio.
#   tiri in porta  mediana 6 · 80° perc 8
#   tiri totali    mediana 17 · 80° perc 22
#   corner         mediana 6 · 80° perc 9
RITMO_MINIMO = {"sog": 8, "shots": 22, "corners": 9}


def _guida(a, b, margine=MARGINE_DOMINIO):
    """a guida su b in modo netto (e non per un pelo su numeri piccoli)."""
    if a <= 0:
        return False
    if b <= 0:
        return a >= 2
    return a >= b * margine


def convergenza(tipo, s_casa, s_ospite, gol_casa=0, gol_ospite=0):
    """(ok, motivo): i dati sostengono questo tipo di segnale?

    - CHI_SEGNA / RIBALTONE: deve guidare la squadra INDICATA, su almeno
      INDICATORI_MINIMI fra tiri in porta, tiri, corner e xG. Dati forti
      nella direzione sbagliata non valgono.
    - OVER: conta il RITMO complessivo (somma delle due squadre) su almeno
      due grandezze: volume senza pericolo non basta.
    - GG: deve premere la squadra ancora a ZERO gol.
    - tipo non mappato: `True, "non valutabile"` — un tipo fuori mappa non
      deve diventare un divieto silenzioso, decidono gli altri filtri.
    """
    if not tipo:
        return True, "non valutabile"
    c = {k: (s_casa or {}).get(k, 0) or 0 for k in ("sog", "shots", "corners", "xg")}
    o = {k: (s_ospite or {}).get(k, 0) or 0 for k in ("sog", "shots", "corners", "xg")}

    if tipo.startswith("OVER"):
        tot = {k: c[k] + o[k] for k in ("sog", "shots", "corners")}
        alti = [k for k, soglia in RITMO_MINIMO.items() if tot[k] >= soglia]
        if len(alti) >= INDICATORI_MINIMI:
            return True, f"ritmo alto su {len(alti)} indicatori ({', '.join(alti)})"
        return False, (f"ritmo insufficiente: solo {len(alti)} indicatori sopra "
                       f"soglia (sog {tot['sog']}, tiri {tot['shots']}, "
                       f"corner {tot['corners']})")

    if tipo.startswith("GG"):
        if gol_casa == 0 and gol_ospite == 0:
            att, dif, chi = c, o, "casa"      # 0-0: basta che una prema
            if sum(o[k] for k in ("sog", "shots")) > sum(c[k] for k in ("sog", "shots")):
                att, dif, chi = o, c, "ospite"
        elif gol_casa == 0:
            att, dif, chi = c, o, "casa"
        elif gol_ospite == 0:
            att, dif, chi = o, c, "ospite"
        else:
            return False, "entrambe hanno gia' segnato"
    elif "CASA" in tipo:
        att, dif, chi = c, o, "casa"
    elif "OSPITE" in tipo:
        att, dif, chi = o, c, "ospite"
    else:
        return True, "non valutabile"

    concordanti = [k for k in ("sog", "shots", "corners", "xg")
                   if _guida(att[k], dif[k])]
    if len(concordanti) >= INDICATORI_MINIMI:
        return True, (f"{chi} guida su {len(concordanti)} indicatori "
                      f"({', '.join(concordanti)})")
    return False, (f"{chi} guida solo su {len(concordanti)} indicatore/i: "
                   f"non e' un trend")


def has_statistics(stats_response):
    """True se la risposta /fixtures/statistics contiene dati veri.

    Serve che ENTRAMBE le squadre abbiano almeno un valore non nullo: un
    array presente ma tutto a None e' assenza di dati, non uno 0-0.
    """
    if not stats_response or len(stats_response) < 2:
        return False
    for team in stats_response[:2]:
        valori = team.get("statistics") or []
        if not any(s.get("value") not in (None, "") for s in valori):
            return False
    return True


def should_analyze_fixture(league_level, stats_response):
    """(ok, reason) — se analizzare la partita con l'AI.

    Il livello si controlla per primo: su livello 3 si esce senza guardare
    le statistiche, cosi' lo scarto non costa nemmeno una lettura.
    """
    if league_level >= 3:
        return False, "lega di livello 3 fuori whitelist"
    if not has_statistics(stats_response):
        return False, "nessuna statistica disponibile per la partita"
    return True, "ok"
