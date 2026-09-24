"""Selezione a valore: il punteggio, i filtri, le fasce e l'interruttore.

PERCHE' (19/09/2026, richiesta dell'utente). Le dieci pubblicate erano
«prime per livello poi orario»: nei giorni di coppa usciva la composizione
peggiore misurata, e il valore rispetto alle quote non contava nulla.
La selezione nuova ordina per score (edge, affidabilita' di lega,
leggibilita', completezza dati) e pubblica 6-10 partite; dieci e sei
restano calcolate come OMBRA per il confronto; si torna indietro con
SELEZIONE_PUBBLICATA="dieci".

Nessun test tocca rete o signals.db: DB temporanei e candidati finti.
"""
import os
# Vetrina: bot.py e i moduli di raccolta dati restano nel repository privato.
# Le classi che verificano l'aggancio al bot completo si saltano qui.
from _vetrina import richiede_bot_completo

import sqlite3
import tempfile
import unittest

import selezione_valore as sv


def _cand(fid, score=0.5, edge=0.05, ora="15:00", mercato="1X2",
          esito="1", prob=0.5, quota=2.1):
    return {"fixture_id": fid, "score": score, "edge": edge,
            "ora_locale": ora, "mercato": mercato, "esito_scelto": esito,
            "prob": prob, "quota_rif": quota}


class TestClip(unittest.TestCase):

    def test_dentro_i_limiti(self):
        self.assertEqual(sv.clip(0.05), 0.05)

    def test_tetto_e_pavimento(self):
        """Un edge del 60% e' quasi sempre un errore di quota: oltre il
        tetto non compra piu' punteggio. Sotto il pavimento idem."""
        self.assertEqual(sv.clip(0.60), 0.10)
        self.assertEqual(sv.clip(-0.50), -0.10)

    def test_il_tetto_e_dieci_punti(self):
        """Misurato il 21/09/2026: la prima giornata reale dichiarava un
        edge MEDIO del +33%, impossibile su mercati col margine del 5-8%.
        Oltre il 10% l'edge misura l'errore del modello, non quello del
        banco — e non deve comprare altro punteggio."""
        self.assertEqual(sv.CLIP_EDGE[1], 0.10)
        self.assertEqual(sv.clip(0.33), 0.10)


class TestEdgePartita(unittest.TestCase):

    MERCATI = {"1x2": {"1": 0.50, "X": 0.27, "2": 0.23},
               "over25": 0.61, "gg": 0.58}

    def test_sceglie_il_mercato_migliore(self):
        quote = {("1X2", "1"): 2.30, ("OVER25", "OVER"): 1.70}
        e = sv.edge_partita(self.MERCATI, quote)
        # 0.50*2.30-1 = +15% batte 0.61*1.70-1 = +3.7%
        self.assertEqual((e["mercato"], e["esito"]), ("1X2", "1"))
        self.assertAlmostEqual(e["edge"], 0.15, places=6)

    def test_under_e_ng_sono_il_complemento(self):
        quote = {("OVER25", "UNDER"): 2.80, ("GG", "NG"): 2.60}
        e = sv.edge_partita(self.MERCATI, quote)
        # UNDER: (1-0.61)*2.80-1 = +9.2% ; NG: (1-0.58)*2.60-1 = +9.2%...
        self.assertGreater(e["edge"], 0.08)
        self.assertIn(e["esito"], ("UNDER", "NG"))
        self.assertAlmostEqual(e["prob"], 1 - (0.61 if e["esito"] == "UNDER"
                                               else 0.58), places=6)

    def test_mercato_senza_quota_non_concorre(self):
        quote = {("OVER25", "OVER"): 1.70}
        e = sv.edge_partita(self.MERCATI, quote)
        self.assertEqual(e["mercato"], "OVER25")

    def test_nessuna_quota_nessun_edge(self):
        self.assertIsNone(sv.edge_partita(self.MERCATI, {}))

    def test_probabilita_minima_esclude_i_colpi_rari(self):
        """Una X al 16% con quota generosa e' il «lift» gia' misurato
        morto il 07/09 (1,9%, sei volte peggio di una costante): amplifica
        il rumore sui casi rari. Sotto PROB_MIN_VALORE non si gioca."""
        mercati = {"1x2": {"1": 0.64, "X": 0.16, "2": 0.20}}
        quote = {("1X2", "X"): 8.00, ("1X2", "1"): 1.50}
        e = sv.edge_partita(mercati, quote)
        # X avrebbe edge +28%, ma 0.16 < PROB_MIN_VALORE: vince l'1
        self.assertEqual(e["esito"], "1")

    def test_soglia_probabilita_e_un_parametro(self):
        self.assertGreaterEqual(sv.PROB_MIN_VALORE, 0.20)

    def test_soglia_alzata_dopo_la_prima_giornata(self):
        """21/09/2026: 7 scelte su 10 erano segni a quota 3,2-5,5, cioe'
        la zona dove il lift e' gia' misurato morto. Sotto il 40% non si
        sceglie piu', per quanto invitante sia la quota."""
        self.assertGreaterEqual(sv.PROB_MIN_VALORE, 0.40)
        mercati = {"1x2": {"1": 0.45, "X": 0.28, "2": 0.27}}
        quote = {("1X2", "2"): 5.50, ("1X2", "1"): 2.40}
        e = sv.edge_partita(mercati, quote)
        # il 2 avrebbe edge +49%, ma 0.27 e' sotto soglia
        self.assertEqual(e["esito"], "1")


class TestScore(unittest.TestCase):

    def test_formula_coi_pesi(self):
        s = sv.score_partita(edge=0.10, affidabilita=0.8,
                             leggibilita=0.5, completezza=1.0)
        atteso = 0.45 * 0.10 + 0.25 * 0.8 + 0.20 * 0.5 + 0.10 * 1.0
        self.assertAlmostEqual(s, atteso, places=9)

    def test_edge_assente_vale_il_pavimento(self):
        """Niente quota = nessun valore dimostrabile: il termine edge
        contribuisce come il caso peggiore, non come un neutro."""
        s = sv.score_partita(edge=None, affidabilita=0.5,
                             leggibilita=0.5, completezza=0.5)
        atteso = 0.45 * (-0.10) + 0.25 * 0.5 + 0.20 * 0.5 + 0.10 * 0.5
        self.assertAlmostEqual(s, atteso, places=9)


class TestSelezione(unittest.TestCase):

    def test_pubblica_chi_ha_valore_fino_a_dieci(self):
        cands = [_cand(i, score=1 - i * 0.01, edge=0.05,
                       ora=f"{10 + i % 12:02d}:00") for i in range(14)]
        scelte = sv.seleziona(cands)
        self.assertEqual(len(scelte), sv.MAX_PUBB)
        self.assertTrue(all(not c["senza_valore"] for c in scelte))

    def test_sotto_soglia_completa_a_sei_e_marca(self):
        cands = ([_cand(i, score=0.9, edge=0.05, ora=f"1{i}:00")
                  for i in range(3)] +
                 [_cand(10 + i, score=0.5, edge=0.01, ora=f"2{i % 4}:00")
                  for i in range(5)])
        scelte = sv.seleziona(cands)
        self.assertEqual(len(scelte), sv.MIN_PUBB)
        marcate = [c for c in scelte if c["senza_valore"]]
        self.assertEqual(len(marcate), 3)

    def test_meno_di_sei_disponibili_si_pubblica_quel_che_c_e(self):
        cands = [_cand(i, edge=0.05, ora=f"1{i}:00") for i in range(4)]
        self.assertEqual(len(sv.seleziona(cands)), 4)

    def test_fascia_oraria_al_massimo_quattro(self):
        """Otto partite tutte alle 15: solo 4 passano, le altre scalano
        alla fascia successiva in classifica."""
        stesse = [_cand(i, score=0.9 - i * 0.01, edge=0.05, ora="15:00")
                  for i in range(8)]
        altre = [_cand(100 + i, score=0.5, edge=0.05, ora="21:00")
                 for i in range(4)]
        scelte = sv.seleziona(stesse + altre)
        alle_15 = [c for c in scelte if c["ora_locale"] == "15:00"]
        self.assertEqual(len(alle_15), sv.MAX_PER_FASCIA)
        self.assertEqual(len(scelte), 8)   # 4 + 4 della sera

    def test_il_pavimento_vince_sul_tetto_di_fascia(self):
        """21/09/2026, giornata vera: sei partite disponibili tutte alle
        20:30, pubblicate QUATTRO — il tetto di fascia aveva bloccato il
        riempimento fino a MIN_PUBB. Il pavimento ha la precedenza: se non
        c'e' altro, si pubblica quello che c'e'."""
        stesse = [_cand(i, score=0.9 - i * 0.01, edge=0.05, ora="20:30")
                  for i in range(6)]
        scelte = sv.seleziona(stesse)
        self.assertEqual(len(scelte), sv.MIN_PUBB)

    def test_il_tetto_di_fascia_vale_finche_ci_sono_alternative(self):
        """La deroga e' SOLO per arrivare al minimo: con partite in altre
        fasce il tetto resta, altrimenti la vetrina torna tutta di sera."""
        stesse = [_cand(i, score=0.9 - i * 0.01, edge=0.05, ora="20:30")
                  for i in range(8)]
        altre = [_cand(100 + i, score=0.5, edge=0.05, ora="15:00")
                 for i in range(4)]
        scelte = sv.seleziona(stesse + altre)
        alle_2030 = [c for c in scelte if c["ora_locale"] == "20:30"]
        self.assertEqual(len(alle_2030), sv.MAX_PER_FASCIA)

    def test_ordine_finale_per_orario(self):
        """Il messaggio si legge per orario, come oggi."""
        cands = [_cand(1, score=0.9, edge=0.05, ora="21:00"),
                 _cand(2, score=0.8, edge=0.05, ora="12:30")]
        scelte = sv.seleziona(cands)
        self.assertEqual([c["fixture_id"] for c in scelte], [2, 1])


class TestEsitoScelta(unittest.TestCase):

    def test_tutti_i_mercati(self):
        casi = [("1X2", "1", "2-1", "VINTO"), ("1X2", "X", "2-1", "PERSO"),
                ("OVER25", "OVER", "2-1", "VINTO"),
                ("OVER25", "UNDER", "2-1", "PERSO"),
                ("OVER25", "UNDER", "1-0", "VINTO"),
                ("GG", "GG", "1-1", "VINTO"), ("GG", "NG", "1-1", "PERSO"),
                ("GG", "NG", "2-0", "VINTO")]
        for mercato, esito, score, atteso in casi:
            self.assertEqual(sv.esito_scelta(mercato, esito, score), atteso,
                             msg=f"{mercato} {esito} su {score}")

    def test_score_rotto_none(self):
        self.assertIsNone(sv.esito_scelta("1X2", "1", None))


class TestAffidabilita(unittest.TestCase):

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE prematch_predictions(league_id INTEGER, "
                     "league TEXT, ft_1x2_conf INTEGER, esito_1x2 TEXT)")
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self.db)

    def _riempi(self, league_id, n, vinte, conf=60):
        conn = sqlite3.connect(self.db)
        for i in range(n):
            conn.execute("INSERT INTO prematch_predictions VALUES(?,?,?,?)",
                         (league_id, "X", conf,
                          "VINTO" if i < vinte else "PERSO"))
        conn.commit()
        conn.close()

    def test_calibrazione_perfetta_vale_uno(self):
        """Dice 60% e prende il 60%: affidabilita' 1.0. Non premia chi
        vince, premia chi mantiene quello che dichiara."""
        self._riempi(40, 50, 30, conf=60)
        tab = sv.calcola_affidabilita(db=self.db)
        self.assertAlmostEqual(tab[40], 1.0, places=6)

    def test_scarto_di_venti_punti_costa_venti(self):
        self._riempi(78, 50, 20, conf=60)   # dice 60, prende 40
        tab = sv.calcola_affidabilita(db=self.db)
        self.assertAlmostEqual(tab[78], 0.8, places=6)

    def test_senza_colonna_league_id_si_mappa_dal_nome(self):
        """Il DB di produzione non ha league_id finche' la migrazione non
        gira (e le righe storiche restano NULL per sempre): la calibrazione
        deve funzionare anche solo col nome della lega."""
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE pp2(league TEXT, ft_1x2_conf INTEGER, "
                     "esito_1x2 TEXT)")
        for i in range(40):
            conn.execute("INSERT INTO pp2 VALUES('Championship', 60, ?)",
                         ("VINTO" if i < 24 else "PERSO",))
        conn.execute("ALTER TABLE prematch_predictions RENAME TO via")
        conn.execute("ALTER TABLE pp2 RENAME TO prematch_predictions")
        conn.commit()
        conn.close()
        tab = sv.calcola_affidabilita(db=self.db)
        self.assertAlmostEqual(tab[40], 1.0, places=6)

    def test_sotto_il_minimo_neutro(self):
        self._riempi(62, sv.N_MIN_LEGA - 1, 10)
        tab = sv.calcola_affidabilita(db=self.db)
        self.assertNotIn(62, tab)
        self.assertEqual(sv.affidabilita_di(62, tab), 0.5)

    def test_scritta_su_tabella(self):
        self._riempi(40, 40, 20)
        sv.calcola_affidabilita(db=self.db)
        conn = sqlite3.connect(self.db)
        r = conn.execute("SELECT n, score FROM affidabilita_lega "
                         "WHERE league_id=40").fetchone()
        conn.close()
        self.assertEqual(r[0], 40)


class TestRigaValore(unittest.TestCase):

    def test_con_valore(self):
        c = _cand(1, edge=0.07, mercato="1X2", esito="X",
                  prob=0.31, quota=3.45)
        c["senza_valore"] = False
        r = sv.riga_valore(c)
        self.assertIn("💰 Valore: 1X2 X", r)
        self.assertIn("prob 31%", r)
        self.assertIn("quota rif 3.45", r)
        self.assertIn("edge +7%", r)
        # quota minima = (1+EDGE_PUBB)/prob = 1.03/0.31 = 3.32
        self.assertIn("quota minima 3.32", r)

    def test_senza_valore(self):
        c = _cand(1)
        c["senza_valore"] = True
        self.assertIn("nessuno alle quote attuali", sv.riga_valore(c))


class TestRegistroEConfronto(unittest.TestCase):

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE prematch_predictions(fixture_id INTEGER, "
                     "esito_1x2 TEXT, risultato_reale TEXT, "
                     "ft_1x2_conf INTEGER)")
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self.db)

    def test_registra_e_confronta(self):
        righe = [dict(_cand(1, edge=0.08, mercato="OVER25", esito="OVER",
                            prob=0.6, quota=1.8), senza_valore=False,
                      home="A", away="B", league_id=40, score=0.7),
                 dict(_cand(2, edge=0.05, mercato="1X2", esito="1",
                            prob=0.5, quota=2.2), senza_valore=False,
                      home="C", away="D", league_id=40, score=0.6)]
        sv.registra_selezioni("2026-09-19", "valore", righe, db=self.db)
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO prematch_predictions VALUES"
                     "(1,'VINTO','2-1',60), (2,'PERSO','0-2',55)")
        conn.commit()
        conn.close()
        testo = sv.confronto(giorni=7, db=self.db)
        self.assertIn("valore", testo)
        self.assertIn("2 partite", testo)
        # 1X2 AI: 1 vinta su 2
        self.assertIn("1X2 50%", testo)
        # mercato di valore: fid1 OVER su 2-1 VINTO (+0.8), fid2 '1' su 0-2
        # PERSO (-1) -> ROI (0.8-1)/2 = -10%
        self.assertIn("ROI -10%", testo)

    def test_registrare_due_volte_non_solleva(self):
        righe = [dict(_cand(1), senza_valore=False, home="A", away="B",
                      league_id=40, score=0.5)]
        sv.registra_selezioni("2026-09-19", "dieci", righe, db=self.db)
        sv.registra_selezioni("2026-09-19", "dieci", righe, db=self.db)


@richiede_bot_completo
class TestInterruttore(unittest.TestCase):

    def test_default_valore(self):
        self.assertEqual(sv.SELEZIONE_PUBBLICATA, "valore")

    def test_bot_usa_l_interruttore(self):
        """Ancorato alle chiamate: il rollback e' UNA variabile."""
        with open("/opt/football-bot/bot.py", encoding="utf-8") as f:
            src = f.read()
        self.assertIn('SELEZIONE_PUBBLICATA == "valore"', src)
        self.assertIn("selezione_valore.selezione_del_giorno", src.replace(
            "sv.selezione_del_giorno", "selezione_valore.selezione_del_giorno"))

    def test_le_sei_non_partono_quando_pubblica_il_valore(self):
        with open("/opt/football-bot/bot.py", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("sei in ombra", src)

    def test_le_ombre_vengono_registrate(self):
        with open("/opt/football-bot/bot.py", encoding="utf-8") as f:
            src = f.read()
        self.assertIn('registra_selezioni(today, "dieci"', src.replace(
            "sv.registra_selezioni", "registra_selezioni"))
        self.assertIn('registra_selezioni(today, "sei"', src.replace(
            "sv.registra_selezioni", "registra_selezioni"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
