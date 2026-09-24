"""Quote del mercato «HT/FT Double»: catturarle finche' esistono.

PERCHE'. Il mercato Primo Tempo/Finale e' quello su cui l'utente gioca
davvero, ma le sue quote non erano salvate da nessuna parte. E la retention
di API-Football su `/odds` e' di 7 giorni: quello che non si prende oggi non
si prende piu'. E' lo stesso buco che ha lasciato 856 pronostici senza ROI
sul risultato esatto, e che il 26/08 ha richiesto la colonna `quota_banco`
per i gruppi MultiEsiti.

Misurato il 28/08/2026 sulle 1.123 partite con quote 1X2: P(A) — «il primo
tempo non decide» — accade il 30,8% delle volte su 57.424 partite, ma le
quote di QUEL mercato non esistevano nello storico, quindi non si poteva
dire se pagasse. Da qui in avanti si potra'.

COSA DEVE RESTARE VERO:
- si filtra per **id del mercato (7)**, non per nome. Stessa trappola gia'
  vista su Exact Score: «Correct Score» esiste ma indica altro;
- le nove etichette dell'API (`Home/Draw`...) diventano le nove celle del
  progetto (`1/X`...), che sono le stesse usate da `gruppo_di` e da tutta
  l'analisi. Se le due notazioni divergono, i numeri non parlano piu' della
  stessa cosa;
- `odd` dall'API e' una **stringa**, va convertita;
- la quota combinata di piu' celle e' il dutching `1 / Σ(1/quota)`, e torna
  **None se manca anche una sola cella**: su tre celle invece di quattro la
  quota risulterebbe piu' alta del vero;
- bookmaker di riferimento **1xBet** (conto reale dell'utente), mediana come
  ripiego, esattamente come per Exact Score;
- **non puo' mai far fallire la raccolta delle altre quote.** Sta agganciato
  dentro `fetch_prematch_odds`, che serve al prompt dell'AI: se questo
  esplode, il pronostico non deve saltare.

Nessun test tocca signals.db. Nessuna chiamata esce in rete.
"""
import json
# Vetrina: bot.py e i moduli di raccolta dati restano nel repository privato.
# Le classi che verificano l'aggancio al bot completo si saltano qui.
from _vetrina import richiede_bot_completo

import os
import sqlite3
import sys
import tempfile
import unittest

sys.argv = ["test"]

import htft_odds as ho  # noqa: E402


def _raw(valori=None, bet_id=7, bookmaker="1xBet", altri_mercati=False):
    """Una risposta /odds come quella vera, ridotta all'essenziale."""
    if valori is None:
        valori = {"Home/Home": "4.33", "Home/Draw": "13.00", "Home/Away": "21.00",
                  "Draw/Home": "6.50", "Draw/Draw": "6.25", "Draw/Away": "6.00",
                  "Away/Home": "23.00", "Away/Draw": "13.00", "Away/Away": "3.55"}
    bets = [{"id": bet_id, "name": "HT/FT Double",
             "values": [{"value": k, "odd": v} for k, v in valori.items()]}]
    if altri_mercati:
        bets.insert(0, {"id": 1, "name": "Match Winner", "values": [
            {"value": "Home", "odd": "2.10"}, {"value": "Draw", "odd": "3.40"}]})
        bets.append({"id": 10, "name": "Exact Score", "values": [
            {"value": "2:1", "odd": "8.00"}]})
    return [{"bookmakers": [{"id": 1, "name": bookmaker, "bets": bets}]}]


class _ConDb(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "prova.db")
        self._vero = ho.DB_PATH
        ho.DB_PATH = self.db
        ho.init_htft_tables()

    def tearDown(self):
        ho.DB_PATH = self._vero
        for f in os.listdir(self.tmp):
            os.unlink(os.path.join(self.tmp, f))
        os.rmdir(self.tmp)


# ─── Le nove celle ───────────────────────────────────────────────────────────

class TestNotazione(unittest.TestCase):

    def test_le_nove_etichette_diventano_le_nove_celle(self):
        atteso = {"Home/Home": "1/1", "Home/Draw": "1/X", "Home/Away": "1/2",
                  "Draw/Home": "X/1", "Draw/Draw": "X/X", "Draw/Away": "X/2",
                  "Away/Home": "2/1", "Away/Draw": "2/X", "Away/Away": "2/2"}
        self.assertEqual(ho.CELLE, atteso)

    def test_sono_le_stesse_celle_del_resto_del_progetto(self):
        """Se divergessero, le quote e le statistiche parlerebbero di due
        cose diverse."""
        from prematch_adattivo import gruppo_di
        for cella in ho.CELLE.values():
            ht, _, ft = cella.partition("/")
            self.assertIn(ht, ("1", "X", "2"))
            self.assertIn(ft, ("1", "X", "2"))
        # il risultato 2-1 sta nella cella che dice gruppo_di
        self.assertTrue(gruppo_di("2-1"))


class TestParse(unittest.TestCase):

    def test_legge_tutte_e_nove(self):
        d = ho.parse(_raw())
        self.assertEqual(len(d), 9)
        self.assertAlmostEqual(d["1/1"]["ref"], 4.33)
        self.assertAlmostEqual(d["X/2"]["ref"], 6.00)

    def test_filtra_per_ID_non_per_nome(self):
        """Stessa trappola di Exact Score: il nome non basta."""
        self.assertEqual(ho.parse(_raw(bet_id=99)), {})

    def test_ignora_gli_altri_mercati(self):
        d = ho.parse(_raw(altri_mercati=True))
        self.assertEqual(len(d), 9)
        self.assertNotIn("Home", d)

    def test_la_quota_e_una_stringa_e_va_convertita(self):
        d = ho.parse(_raw())
        self.assertIsInstance(d["1/1"]["ref"], float)

    def test_etichetta_sconosciuta_scartata_senza_esplodere(self):
        d = ho.parse(_raw({"Home/Home": "4.33", "Boh/Mah": "9.99"}))
        self.assertEqual(list(d), ["1/1"])

    def test_quota_malformata_scartata(self):
        d = ho.parse(_raw({"Home/Home": "4.33", "Draw/Home": "n.d."}))
        self.assertEqual(list(d), ["1/1"])

    def test_risposta_vuota_o_rotta(self):
        for cattiva in (None, [], [{}], [{"bookmakers": []}], "boh"):
            self.assertEqual(ho.parse(cattiva), {})

    def test_il_bookmaker_di_riferimento_e_1xbet(self):
        self.assertEqual(ho.REF_BOOKMAKER, "1xBet")
        d = ho.parse(_raw(bookmaker="Pinnacle"))
        self.assertIsNone(d["1/1"]["ref"], "solo 1xBet va in odd_ref")
        self.assertIsNotNone(d["1/1"]["agg"]["med"], "la mediana c'e' comunque")


# ─── Il salvataggio ──────────────────────────────────────────────────────────

class TestSalvataggio(_ConDb):

    def test_salva_nove_righe(self):
        self.assertEqual(ho.save(333, _raw()), 9)
        conn = sqlite3.connect(self.db)
        n = conn.execute("SELECT COUNT(*) FROM htft_odds WHERE fixture_id=333").fetchone()[0]
        conn.close()
        self.assertEqual(n, 9)

    def test_rilanciarlo_non_duplica(self):
        ho.save(333, _raw()); ho.save(333, _raw())
        conn = sqlite3.connect(self.db)
        n = conn.execute("SELECT COUNT(*) FROM htft_odds WHERE fixture_id=333").fetchone()[0]
        conn.close()
        self.assertEqual(n, 9)

    def test_niente_da_salvare_non_e_un_errore(self):
        self.assertEqual(ho.save(333, _raw(bet_id=99)), 0)

    def test_non_solleva_mai(self):
        """Sta dentro fetch_prematch_odds: se esplode, salta il pronostico."""
        ho.DB_PATH = "/percorso/che/non/esiste/x.db"
        try:
            self.assertEqual(ho.save(333, _raw()), 0)
        finally:
            ho.DB_PATH = self.db

    def test_la_migrazione_regge_i_riavvii(self):
        for _ in range(3):
            ho.init_htft_tables()
        self.assertEqual(ho.save(333, _raw()), 9)


# ─── La quota combinata ──────────────────────────────────────────────────────

class TestCombinata(_ConDb):

    def test_dutching_su_numeri_noti(self):
        """Quattro celle a 4.00 coprono tutto: combinata 1.00."""
        ho.save(333, _raw({"Home/Home": "4.00", "Home/Draw": "4.00",
                           "Draw/Home": "4.00", "Draw/Draw": "4.00"}))
        self.assertAlmostEqual(
            ho.combined(333, ("1/1", "1/X", "X/1", "X/X")), 1.0, places=4)

    def test_il_mercato_X2_1_del_biglietto(self):
        """P(B) = X/1 + 2/1. Con 6.50 e 23.00: 1/(1/6.5+1/23) = 5.0678."""
        ho.save(333, _raw())
        self.assertAlmostEqual(ho.combined(333, ("X/1", "2/1")), 5.06780, places=4)

    def test_il_mercato_1X_2_del_biglietto(self):
        """P(C) = X/2 + 1/2. Con 6.00 e 21.00 la combinata e' 4.67."""
        ho.save(333, _raw())
        self.assertAlmostEqual(ho.combined(333, ("X/2", "1/2")), 4.6667, places=3)

    def test_manca_una_cella_niente_quota(self):
        """Su tre celle invece di quattro la quota sarebbe piu' ALTA del vero."""
        ho.save(333, _raw({"Home/Home": "4.00", "Home/Draw": "4.00"}))
        self.assertIsNone(ho.combined(333, ("1/1", "1/X", "X/1")))

    def test_partita_sconosciuta(self):
        self.assertIsNone(ho.combined(999, ("X/1", "2/1")))

    def test_P_di_A_sono_le_quattro_celle_giuste(self):
        """P(A) = X/1 + X/2 + 1/2 + 2/1, la definizione usata in tutta
        l'analisi del 28/08."""
        self.assertEqual(set(ho.CELLE_A), {"X/1", "X/2", "1/2", "2/1"})
        ho.save(333, _raw())
        self.assertIsNotNone(ho.combined(333, ho.CELLE_A))


class TestPulizia(_ConDb):

    def test_toglie_le_vecchie_e_tiene_le_nuove(self):
        ho.save(333, _raw())
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE htft_odds SET captured_at=datetime('now','-30 days')")
        conn.commit(); conn.close()
        ho.save(444, _raw())
        tolte = ho.cleanup(days=7)
        self.assertEqual(tolte, 9)
        self.assertIsNotNone(ho.combined(444, ("X/1", "2/1")))
        self.assertIsNone(ho.combined(333, ("X/1", "2/1")))


# ─── Contro la risposta VERA dell'API ────────────────────────────────────────

class TestRispostaVera(_ConDb):
    """Il campione e' una risposta `/odds` scaricata il 28/08/2026.

    L'esempio sintetico prova la logica; questo prova che la logica combaci
    con quello che l'API manda davvero — nomi dei campi, forma annidata,
    quote come stringhe.
    """

    def setUp(self):
        super().setUp()
        percorso = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "tests_data_htft_sample.json")
        if not os.path.exists(percorso):
            self.skipTest("campione API assente")
        self.vera = json.load(open(percorso))["response"]

    def test_legge_le_nove_celle_dalla_risposta_vera(self):
        d = ho.parse(self.vera[:1])
        self.assertEqual(len(d), 9, f"lette {len(d)} celle invece di 9")
        for cella in CELLE_ATTESE:
            self.assertIn(cella, d)

    def test_le_quote_sono_numeri_positivi(self):
        for c, v in ho.parse(self.vera[:1]).items():
            q = v["ref"] if v["ref"] is not None else v["agg"]["med"]
            self.assertGreater(q, 1.0, c)

    def test_i_mercati_combinati_del_biglietto_si_calcolano(self):
        ho.save(1, self.vera[:1])
        for nome, celle in (("P(A)", ho.CELLE_A), ("P(B)", ho.CELLE_B),
                            ("P(C)", ho.CELLE_C)):
            q = ho.combined(1, celle)
            self.assertIsNotNone(q, nome)
            self.assertGreater(q, 1.0, nome)

    def test_su_tutte_le_partite_del_campione(self):
        ok = sum(1 for p in self.vera if len(ho.parse([p])) == 9)
        self.assertEqual(ok, len(self.vera),
                         f"{ok}/{len(self.vera)} partite lette per intero")


CELLE_ATTESE = ("1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2")


# ─── L'aggancio ──────────────────────────────────────────────────────────────

@richiede_bot_completo
class TestAggancio(unittest.TestCase):
    """`fetch_prematch_odds` deve chiamare `htft_odds.save`.

    Se qualcuno riscrive quella funzione e si dimentica la riga, le quote
    smettono di essere raccolte in silenzio — e non sono recuperabili dopo.
    """

    def test_fetch_prematch_odds_salva_le_quote_htft(self):
        import ast
        albero = ast.parse(open(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "match_data.py"),
            encoding="utf-8").read())
        fn = next((n for n in ast.walk(albero)
                   if isinstance(n, ast.FunctionDef)
                   and n.name == "fetch_prematch_odds"), None)
        self.assertIsNotNone(fn, "fetch_prematch_odds non esiste piu'")
        chiamate = [n for n in ast.walk(fn)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "save"
                    and getattr(n.func.value, "id", "") == "htft_odds"]
        self.assertTrue(chiamate,
                        "fetch_prematch_odds non chiama piu' htft_odds.save: "
                        "le quote HT/FT non vengono piu' raccolte")


if __name__ == "__main__":
    unittest.main(verbosity=2)
