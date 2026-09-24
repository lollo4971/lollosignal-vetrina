# test_ombra.py
"""Test della modalita' ombra del modello statistico.

Regola assoluta sotto test: la modalita' ombra non deve MAI poter sollevare
un'eccezione che arrivi al chiamante (bot.py), qualunque sia l'input.

I dati storici sintetici sono deterministici (nessun campionamento casuale):
punteggi fissi ripetuti su piu' stagioni, cosi' il fit converge sempre allo
stesso risultato e i test non sono mai flaky.
"""
import os
# Vetrina: bot.py e i moduli di raccolta dati restano nel repository privato.
# Le classi che verificano l'aggancio al bot completo si saltano qui.
from _vetrina import richiede_bot_completo

import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

from modello_storico import lambde, matrice_punteggi, prob_gg, prob_over
from storico_db import init_storico, salva_partite

import ombra

LEGA_TEST = 999999   # id di fantasia, non esiste in nessun storico.db reale
# Team 1: attacco fortissimo, difesa fortissima -> lambda molto sbilanciati
# contro il Team 2 (attacco quasi nullo, difesa colabrodo).
# Team 3 e Team 4: forza simile fra loro (quasi sempre 1-1) -> lambda
# realistici, per i test dove non serve uno sbilanciamento estremo.
_PUNTEGGI_FISSI = {
    (1, 2): (4, 0), (2, 1): (0, 3),
    (1, 3): (3, 0), (3, 1): (0, 2),
    (1, 4): (3, 1), (4, 1): (0, 2),
    (2, 3): (0, 1), (3, 2): (2, 0),
    (2, 4): (0, 2), (4, 2): (2, 0),
    (3, 4): (1, 1), (4, 3): (1, 1),
}
N_STAGIONI = 9   # 12 coppie * 9 stagioni = 108 partite, sopra la soglia minima


def _genera_storico(path, league_id=LEGA_TEST):
    """Crea uno storico.db temporaneo con partite sintetiche deterministiche."""
    init_storico(path)
    partite = []
    fid = league_id * 1000
    for s in range(N_STAGIONI):
        stagione = 2016 + s
        data = f"{stagione}-09-01"
        for (h, a), (gh, ga) in _PUNTEGGI_FISSI.items():
            fid += 1
            partite.append({
                "fixture_id": fid, "league_id": league_id, "season": stagione,
                "data": data, "home_id": h, "away_id": a,
                "home_nome": f"T{h}", "away_nome": f"T{a}",
                "ht_home": gh // 2, "ht_away": ga // 2,
                "ft_home": gh, "ft_away": ga,
            })
    salva_partite(path, partite)
    return len(partite)


class OmbraTestCase(unittest.TestCase):
    """Base comune: storico.db temporaneo + cache dei parametri svuotata."""

    def setUp(self):
        fd, self.storico_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.storico_path)   # deve crearlo init_storico
        _genera_storico(self.storico_path)
        ombra._cache.clear()

    def tearDown(self):
        if os.path.exists(self.storico_path):
            os.remove(self.storico_path)


class TestProbDelModello(OmbraTestCase):

    def test_over_ft_probabilita_plausibile(self):
        p = ombra.prob_del_modello(LEGA_TEST, 3, 4, "OVER_1.5", 30, 0, 0,
                                    path_storico=self.storico_path)
        self.assertIsNotNone(p)
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_over_pt_probabilita_plausibile(self):
        p = ombra.prob_del_modello(LEGA_TEST, 3, 4, "OVER_0.5_PT", 20, 0, 0,
                                    path_storico=self.storico_path)
        self.assertIsNotNone(p)
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_gg_probabilita_plausibile(self):
        p = ombra.prob_del_modello(LEGA_TEST, 3, 4, "GG", 40, 0, 0,
                                    path_storico=self.storico_path)
        self.assertIsNotNone(p)
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_chi_segna_probabilita_plausibile(self):
        p = ombra.prob_del_modello(LEGA_TEST, 3, 4, "CHI_SEGNA_PROSSIMO_CASA", 60, 0, 0,
                                    path_storico=self.storico_path)
        self.assertIsNotNone(p)
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_ribaltone_probabilita_plausibile(self):
        p = ombra.prob_del_modello(LEGA_TEST, 3, 4, "RIBALTONE_OSPITE", 60, 1, 0,
                                    path_storico=self.storico_path)
        self.assertIsNotNone(p)
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_tipo_sconosciuto_ritorna_none(self):
        p = ombra.prob_del_modello(LEGA_TEST, 3, 4, "PIPPO_TIPO_INESISTENTE", 30, 0, 0,
                                    path_storico=self.storico_path)
        self.assertIsNone(p)

    def test_chi_segna_casa_dominante_supera_50_percento(self):
        """Team 1 (attacco fortissimo/difesa fortissima) contro Team 2
        (attacco quasi nullo/difesa colabrodo): la probabilita' che il
        prossimo gol lo faccia la casa deve superare 0.5."""
        p = ombra.prob_del_modello(LEGA_TEST, 1, 2, "CHI_SEGNA_PROSSIMO_CASA", 30, 1, 0,
                                    path_storico=self.storico_path)
        self.assertIsNotNone(p)
        self.assertGreater(p, 0.5)

    def test_ribaltone_tardivo_e_basso(self):
        """0-1 all'80', squadre di forza simile: la probabilita' di
        sorpasso della casa nei 10 minuti restanti deve essere bassa."""
        p = ombra.prob_del_modello(LEGA_TEST, 3, 4, "RIBALTONE_CASA", 80, 0, 1,
                                    path_storico=self.storico_path)
        self.assertIsNotNone(p)
        self.assertLess(p, 0.10)

    def test_over_pt_orizzonte_e_45_non_90(self):
        """Al 20', 0-0: la probabilita' PT di superare lo 0.5 entro il 45'
        deve essere piu' bassa della stessa probabilita' calcolata su tutta
        la partita (FT), dove restano 70 minuti invece di 25.

        Deliberatamente NON testato al 44' (dove il tempo residuo verso il
        45' e' cosi' poco che un errore moltiplicativo sistematico nella
        formula resterebbe comunque sotto qualunque soglia ragionevole,
        invisibile al test — e' esattamente cosi' che e' passato inosservato
        un bug che sovrastimava il PT di 2,25 volte)."""
        p_pt = ombra.prob_del_modello(LEGA_TEST, 3, 4, "OVER_0.5_PT", 20, 0, 0,
                                       path_storico=self.storico_path)
        p_ft = ombra.prob_del_modello(LEGA_TEST, 3, 4, "OVER_0.5", 20, 0, 0,
                                       path_storico=self.storico_path)
        self.assertIsNotNone(p_pt)
        self.assertIsNotNone(p_ft)
        self.assertLess(p_pt, p_ft)

    def test_over_pt_minuto_45_o_oltre_ritorna_none(self):
        """Al 45' (o oltre) 'entro il 45'' e' un evento gia' deciso: 0.0 o
        1.0 in silenzio manderebbero una log-loss a +-infinito se
        sbagliato. Deve tornare None, non un numero degenere."""
        for minuto in (45, 46, 60):
            p = ombra.prob_del_modello(LEGA_TEST, 3, 4, "OVER_0.5_PT", minuto, 0, 0,
                                        path_storico=self.storico_path)
            self.assertIsNone(p, f"atteso None al minuto {minuto}, ottenuto {p}")

    def test_chi_segna_somma_meno_di_uno(self):
        """CHI_SEGNA_CASA + CHI_SEGNA_OSPITE deve essere STRETTAMENTE minore
        di 1: la somma delle due probabilita' e' P(almeno un altro gol), non
        1 (il segnale e' PERSO se non segna nessuno, CLAUDE.md). Se la
        somma tornasse esattamente 1 sarebbe il sintomo del bug corretto
        qui: probabilita' condizionata a torto spacciata per assoluta."""
        p_casa = ombra.prob_del_modello(LEGA_TEST, 3, 4, "CHI_SEGNA_PROSSIMO_CASA", 80, 0, 0,
                                         path_storico=self.storico_path)
        p_ospite = ombra.prob_del_modello(LEGA_TEST, 3, 4, "CHI_SEGNA_PROSSIMO_OSPITE", 80, 0, 0,
                                           path_storico=self.storico_path)
        self.assertIsNotNone(p_casa)
        self.assertIsNotNone(p_ospite)
        self.assertLess(p_casa + p_ospite, 1.0)
        self.assertGreater(p_casa + p_ospite, 0.0)

    def test_chi_segna_si_riduce_con_meno_tempo_residuo(self):
        """A parita' di punteggio, con meno tempo restante la probabilita'
        che arrivi 'il prossimo gol' scende: e' l'effetto della
        moltiplicazione per P(almeno un altro gol) che mancava."""
        p_presto = ombra.prob_del_modello(LEGA_TEST, 3, 4, "CHI_SEGNA_PROSSIMO_CASA", 30, 0, 0,
                                           path_storico=self.storico_path)
        p_tardi = ombra.prob_del_modello(LEGA_TEST, 3, 4, "CHI_SEGNA_PROSSIMO_CASA", 85, 0, 0,
                                          path_storico=self.storico_path)
        self.assertIsNotNone(p_presto)
        self.assertIsNotNone(p_tardi)
        self.assertLess(p_tardi, p_presto)

    def test_ribaltone_none_se_squadra_non_in_svantaggio(self):
        """RIBALTONE_CASA chiamato quando la casa e' avanti (o in parita')
        non e' un evento sensato: deve tornare None, non P(vittoria casa)."""
        p_casa_avanti = ombra.prob_del_modello(LEGA_TEST, 3, 4, "RIBALTONE_CASA", 60, 1, 0,
                                                path_storico=self.storico_path)
        p_pareggio = ombra.prob_del_modello(LEGA_TEST, 3, 4, "RIBALTONE_CASA", 60, 0, 0,
                                             path_storico=self.storico_path)
        self.assertIsNone(p_casa_avanti)
        self.assertIsNone(p_pareggio)

    def test_dati_insufficienti_ritorna_none(self):
        """Una lega senza storico (o con troppe poche partite) non deve
        far esplodere nulla: solo None."""
        p = ombra.prob_del_modello(424242, 1, 2, "GG", 30, 0, 0,
                                    path_storico=self.storico_path)
        self.assertIsNone(p)


class TestCacheParametri(OmbraTestCase):

    def test_non_ricalcola_due_volte_la_stessa_lega(self):
        with mock.patch("ombra.stima_parametri", wraps=ombra.stima_parametri) as spia:
            ombra.prob_del_modello(LEGA_TEST, 3, 4, "GG", 30, 0, 0,
                                    path_storico=self.storico_path)
            ombra.prob_del_modello(LEGA_TEST, 3, 4, "GG", 45, 1, 0,
                                    path_storico=self.storico_path)
            self.assertEqual(spia.call_count, 1)

    def test_ricalcola_dopo_24_ore(self):
        with mock.patch("ombra.stima_parametri", wraps=ombra.stima_parametri) as spia:
            with mock.patch("ombra.time.time", return_value=1000.0):
                ombra.prob_del_modello(LEGA_TEST, 3, 4, "GG", 30, 0, 0,
                                        path_storico=self.storico_path)
            with mock.patch("ombra.time.time", return_value=1000.0 + 24 * 3600 + 1):
                ombra.prob_del_modello(LEGA_TEST, 3, 4, "GG", 30, 0, 0,
                                        path_storico=self.storico_path)
            self.assertEqual(spia.call_count, 2)


class TestRegistra(unittest.TestCase):

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)
        ombra.init_ombra(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_registra_scrive_una_riga(self):
        ok = ombra.registra(self.db_path, signal_id=1, fixture_id=555, league_id=39,
                             home_id=1, away_id=2, tipo="GG", minuto=30,
                             gol_casa=0, gol_ospite=0, conf_ai=75, quota_mercato=1.85)
        self.assertTrue(ok)
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT signal_id, fixture_id, league_id, tipo, minuto, punteggio, "
            "conf_ai, quota_mercato, prob_mercato FROM confronto_modello WHERE signal_id=1"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], 555)
        self.assertEqual(row[2], 39)
        self.assertEqual(row[3], "GG")
        self.assertEqual(row[4], 30)
        self.assertEqual(row[5], "0-0")
        self.assertEqual(row[6], 75)
        self.assertAlmostEqual(row[7], 1.85)
        self.assertAlmostEqual(row[8], 1.0 / 1.85)

    def test_registra_non_solleva_con_db_inesistente(self):
        percorso_impossibile = "/percorso/che/non/esiste/xyz/signals.db"
        try:
            esito = ombra.registra(percorso_impossibile, signal_id=1, fixture_id=1,
                                    league_id=39, home_id=1, away_id=2, tipo="GG",
                                    minuto=30, gol_casa=0, gol_ospite=0)
        except Exception as e:
            self.fail(f"registra ha sollevato un'eccezione: {e}")
        self.assertFalse(esito)

    def test_registra_non_solleva_con_valori_nulli(self):
        try:
            esito = ombra.registra(self.db_path, signal_id=2, fixture_id=None,
                                    league_id=None, home_id=None, away_id=None,
                                    tipo=None, minuto=None, gol_casa=None,
                                    gol_ospite=None, conf_ai=None, quota_mercato=None)
        except Exception as e:
            self.fail(f"registra ha sollevato un'eccezione: {e}")
        self.assertTrue(esito)

    def test_registra_non_solleva_con_tipo_strano(self):
        try:
            esito = ombra.registra(self.db_path, signal_id=3, fixture_id=1,
                                    league_id=39, home_id=1, away_id=2,
                                    tipo="QUALCOSA_DI_MAI_VISTO", minuto=30,
                                    gol_casa=0, gol_ospite=0)
        except Exception as e:
            self.fail(f"registra ha sollevato un'eccezione: {e}")
        self.assertTrue(esito)
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT prob_modello FROM confronto_modello WHERE signal_id=3").fetchone()
        conn.close()
        self.assertIsNone(row[0])

    def test_registra_non_solleva_con_tabella_assente(self):
        """Anche se init_ombra non e' mai stato chiamato su questo file
        (tabella assente), registra non deve propagare l'errore."""
        fd, altro_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            try:
                esito = ombra.registra(altro_path, signal_id=1, fixture_id=1,
                                        league_id=39, home_id=1, away_id=2,
                                        tipo="GG", minuto=30, gol_casa=0, gol_ospite=0)
            except Exception as e:
                self.fail(f"registra ha sollevato un'eccezione: {e}")
            self.assertFalse(esito)
        finally:
            os.remove(altro_path)

class TestCalcoloIndipendente(OmbraTestCase):
    """Per ogni tipo di segnale, ricalcola la probabilita' 'a mano' usando
    solo primitive generiche (matrice_punteggi, prob_over, prob_gg — MAI
    matrice_da_minuto, che e' proprio cio' che ombra.py chiama internamente)
    e confronta col risultato di prob_del_modello. Non condivide la logica
    di scala/orizzonte con l'implementazione: e' il tipo di test che avrebbe
    intercettato sia la sovrastima PT (x2,25) sia il CHI_SEGNA che ignorava
    P(almeno un gol)."""

    def _parametri(self):
        par, rho, quota_pt = ombra._parametri_lega(LEGA_TEST, path_storico=self.storico_path)
        lam_h, lam_a = lambde(par, 3, 4)
        return lam_h, lam_a, rho, quota_pt

    def test_over_ft_a_mano(self):
        lam_h, lam_a, rho, quota_pt = self._parametri()
        minuto = 60
        # Stessa formula "a tratti" documentata nel docstring di
        # matrice_da_minuto per quota_pt != None, minuto > 45: ricopiata
        # qui indipendentemente, non richiamata da la'.
        restante = (1 - quota_pt) * (90 - minuto) / 45
        atteso = prob_over(matrice_punteggi(lam_h * restante, lam_a * restante, rho), 1.5)
        calcolato = ombra.prob_del_modello(LEGA_TEST, 3, 4, "OVER_1.5", minuto, 0, 0,
                                            path_storico=self.storico_path)
        self.assertAlmostEqual(calcolato, atteso, places=9)

    def test_over_pt_a_mano(self):
        lam_h, lam_a, rho, quota_pt = self._parametri()
        minuto = 20
        # Budget dell'INTERO primo tempo = lam*quota_pt, di cui resta la
        # frazione (45-minuto)/45. Nessun trucco del minuto raddoppiato qui:
        # e' proprio il calcolo che il trucco deve riprodurre.
        restante = (45 - minuto) / 45
        rh, ra = lam_h * quota_pt * restante, lam_a * quota_pt * restante
        atteso = prob_over(matrice_punteggi(rh, ra, rho), 0.5)
        calcolato = ombra.prob_del_modello(LEGA_TEST, 3, 4, "OVER_0.5_PT", minuto, 0, 0,
                                            path_storico=self.storico_path)
        self.assertAlmostEqual(calcolato, atteso, places=9)

    def test_gg_a_mano(self):
        lam_h, lam_a, rho, quota_pt = self._parametri()
        minuto = 60
        restante = (1 - quota_pt) * (90 - minuto) / 45
        atteso = prob_gg(matrice_punteggi(lam_h * restante, lam_a * restante, rho))
        calcolato = ombra.prob_del_modello(LEGA_TEST, 3, 4, "GG", minuto, 0, 0,
                                            path_storico=self.storico_path)
        self.assertAlmostEqual(calcolato, atteso, places=9)

    def test_chi_segna_a_mano(self):
        lam_h, lam_a, rho, quota_pt = self._parametri()
        minuto = 60
        restante = (1 - quota_pt) * (90 - minuto) / 45
        matrice = matrice_punteggi(lam_h * restante, lam_a * restante, rho)
        p_almeno_un_gol = 1.0 - matrice.get((0, 0), 0.0)
        atteso = p_almeno_un_gol * (lam_h / (lam_h + lam_a))
        calcolato = ombra.prob_del_modello(LEGA_TEST, 3, 4, "CHI_SEGNA_PROSSIMO_CASA",
                                            minuto, 0, 0, path_storico=self.storico_path)
        self.assertAlmostEqual(calcolato, atteso, places=9)

    def test_ribaltone_a_mano(self):
        lam_h, lam_a, rho, quota_pt = self._parametri()
        minuto = 80
        gol_casa, gol_ospite = 0, 1
        restante = (1 - quota_pt) * (90 - minuto) / 45
        # matrice_punteggi non conosce il punteggio attuale: si trasla a
        # mano lo stesso pavimento che matrice_da_minuto applica.
        m = matrice_punteggi(lam_h * restante, lam_a * restante, rho)
        atteso = sum(v for (dx, dy), v in m.items() if (gol_casa + dx) > (gol_ospite + dy))
        calcolato = ombra.prob_del_modello(LEGA_TEST, 3, 4, "RIBALTONE_CASA",
                                            minuto, gol_casa, gol_ospite,
                                            path_storico=self.storico_path)
        self.assertAlmostEqual(calcolato, atteso, places=9)


class TestInitOmbra(unittest.TestCase):

    def test_crea_tabella_idempotente(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(path)
        try:
            ombra.init_ombra(path)
            ombra.init_ombra(path)   # non deve sollevare la seconda volta
            conn = sqlite3.connect(path)
            cols = [r[1] for r in conn.execute("PRAGMA table_info(confronto_modello)")]
            conn.close()
            attese = {"signal_id", "fixture_id", "league_id", "tipo", "minuto",
                      "punteggio", "prob_modello", "conf_ai", "quota_mercato",
                      "prob_mercato", "esito", "creato_il"}
            self.assertTrue(attese.issubset(set(cols)))
        finally:
            if os.path.exists(path):
                os.remove(path)


@richiede_bot_completo
class TestIntegrazioneBotSaveSignal(unittest.TestCase):
    """L'invariante piu' importante di tutta la patch: save_signal deve
    sopravvivere anche se ombra.registra solleva un'eccezione qualsiasi.
    Nessun test lo verificava finora."""

    @classmethod
    def setUpClass(cls):
        sys.argv = ["test"]
        import bot   # noqa: E402  (import pesante, una volta sola per classe)
        cls.bot = bot

    def setUp(self):
        fd, self.signals_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.signals_path)
        fd, self.ombra_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.ombra_path)
        # Solo lo schema minimo che save_signal usa davvero: niente
        # init_db() completo, che scalderebbe la cache su storico.db vero
        # (lenta e inutile per questo test di sola sopravvivenza).
        conn = sqlite3.connect(self.signals_path)
        conn.execute("""CREATE TABLE signals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, fixture_id INTEGER, home TEXT, away TEXT,
            league TEXT, score_at_signal TEXT, minute INTEGER,
            tipo TEXT, confidenza INTEGER, quota_minima REAL,
            rischio TEXT, motivazione TEXT, esito TEXT DEFAULT NULL,
            stato_coda TEXT DEFAULT 'ATTIVO', tempo TEXT DEFAULT 'FT')""")
        conn.commit()
        conn.close()
        ombra.init_ombra(self.ombra_path)

    def tearDown(self):
        for p in (self.signals_path, self.ombra_path):
            if os.path.exists(p):
                os.remove(p)

    def _fixture_finta(self):
        fix = {"fixture": {"id": 999888},
               "teams": {"home": {"id": 1, "name": "Casa Finta"},
                         "away": {"id": 2, "name": "Ospite Finto"}},
               "league": {"id": 39, "name": "Lega Finta"},
               "goals": {"home": 1, "away": 0}}
        a = {"tipo": "GG", "confidenza": 70, "rischio": "MEDIO", "motivazione": "test"}
        return fix, a

    def test_save_signal_sopravvive_a_ombra_che_esplode(self):
        fix, a = self._fixture_finta()
        with mock.patch.object(self.bot, "DB_PATH", self.signals_path), \
             mock.patch.object(self.bot, "OMBRA_DB_PATH", self.ombra_path), \
             mock.patch.object(self.bot._ombra, "registra",
                                side_effect=RuntimeError("esplosione simulata")):
            try:
                self.bot.save_signal(fix, a, 60)
            except Exception as e:
                self.fail(f"save_signal ha propagato l'eccezione di ombra: {e}")
        conn = sqlite3.connect(self.signals_path)
        n = conn.execute("SELECT COUNT(*) FROM signals WHERE fixture_id=999888").fetchone()[0]
        conn.close()
        self.assertEqual(n, 1, "il segnale reale deve essere salvato comunque")

    def test_save_signal_registra_ombra_quando_tutto_va_bene(self):
        """Controprova: nel percorso normale (nessun guasto) la riga ombra
        arriva davvero, cosi' il test sopra non e' vero solo perche' ombra
        non viene mai chiamata per errore di collegamento."""
        fix, a = self._fixture_finta()
        with mock.patch.object(self.bot, "DB_PATH", self.signals_path), \
             mock.patch.object(self.bot, "OMBRA_DB_PATH", self.ombra_path):
            self.bot.save_signal(fix, a, 60)
        conn = sqlite3.connect(self.ombra_path)
        row = conn.execute(
            "SELECT fixture_id, league_id, tipo FROM confronto_modello "
            "WHERE fixture_id=999888").fetchone()
        conn.close()
        self.assertIsNotNone(row, "ombra.registra doveva essere chiamata e scrivere la riga")
        self.assertEqual(row, (999888, 39, "GG"))


if __name__ == "__main__":
    unittest.main()
