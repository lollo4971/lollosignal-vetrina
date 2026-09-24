"""Coefficienti UEFA nei pronostici di coppa: la forza strutturale come
dato in piu' per l'AI, e le colonne per misurarne l'effetto.

PERCHE' (17/09/2026). Il modello non entra nelle coppe europee (misurato
peggio della climatologia) e l'AI, senza precedenti e con la forma presa
da campionati di livello diverso, si appoggia quasi solo alle quote. Il
coefficiente UEFA e' il criterio delle fasce del sorteggio: si da' all'AI
solo per UCL/UEL/UECL e si registra per il confronto fra un mese.

I test usano il CSV VERO (data/coefficienti_uefa_2026_27_ids.csv, 108
squadre gia' allineate ai team_id API-Football). Nessun test tocca rete
o signals.db.
"""
import os
# Vetrina: bot.py e i moduli di raccolta dati restano nel repository privato.
# Le classi che verificano l'aggancio al bot completo si saltano qui.
from _vetrina import richiede_bot_completo

import tempfile
import unittest

import coefficienti_uefa as cu

# id veri dal CSV allineato
REAL_MADRID, BAYERN, SABAH = 541, 157, 13976
ATALANTA, GETAFE = 499, 546
UCL, UEL, UECL, SERIE_A = 2, 3, 848, 135


class TestNormalizzazione(unittest.TestCase):

    def test_accenti_e_maiuscole(self):
        self.assertEqual(cu.norm("Bayern München"), "bayern munchen")

    def test_punteggiatura(self):
        self.assertEqual(cu.norm("St. Truiden"), "st truiden")


class TestAbbina(unittest.TestCase):

    CANDIDATI = [(157, "Bayern München"), (541, "Real Madrid"),
                 (505, "Inter"), (999, "Inter Club d'Escaldes")]

    def test_esatto_su_alias(self):
        self.assertEqual(cu.abbina("Bayern München", "Bayern Munich",
                                   self.CANDIDATI), 157)

    def test_accento_normalizzato(self):
        """«Bayern Munchen» senza umlaut deve trovare «Bayern München»."""
        self.assertEqual(cu.abbina("Bayern Munchen", "x", self.CANDIDATI), 157)

    def test_non_trovato_e_none(self):
        self.assertIsNone(cu.abbina("Borussia", "Borussia MG",
                                    self.CANDIDATI))

    def test_ambiguo_e_none_non_si_indovina(self):
        """Un alias che per contenimento matcha due squadre: 0 o 2+
        candidati NON sono un abbinamento — regola dell'utente, mai
        indovinare."""
        self.assertIsNone(cu.abbina("Inter", "Inter",
                                    [(1, "FC Inter"), (2, "Inter Club")]))

    def test_esatto_vince_sul_contenimento(self):
        """«Inter» esatto e' l'Inter, anche se e' contenuto in «Inter Club
        d'Escaldes»: il contenimento si prova solo se l'esatto fallisce."""
        self.assertEqual(cu.abbina("Inter", "Inter", self.CANDIDATI), 505)


class TestCarica(unittest.TestCase):

    def test_csv_vero_108_squadre(self):
        t = cu.carica()
        self.assertEqual(len(t), 108)
        self.assertEqual(t[REAL_MADRID]["competizione"], "UCL")
        self.assertEqual(t[REAL_MADRID]["fascia"], 1)
        self.assertAlmostEqual(t[REAL_MADRID]["coefficiente"], 144.5)

    def test_fasce_totali_per_competizione(self):
        """UCL/UEL hanno 4 urne, la Conference 6: il «di N» nella riga
        deve venire dai dati, non da una costante."""
        t = cu.carica()
        self.assertEqual(t[REAL_MADRID]["fasce_tot"], 4)
        self.assertEqual(t[ATALANTA]["fasce_tot"], 6)

    def test_file_mancante_non_ferma_il_bot(self):
        self.assertEqual(cu.carica("/inesistente/coeff.csv"), {})


class TestRigaPrompt(unittest.TestCase):

    def test_partita_di_coppa_con_entrambe(self):
        r = cu.riga_prompt(UCL, REAL_MADRID, SABAH)
        self.assertIn("Coefficiente UEFA", r)
        self.assertIn("Real Madrid 144.5 (fascia 1 di 4)", r)
        self.assertIn("Sabah 6.0 (fascia 4 di 4)", r)
        self.assertIn("Rapporto 24:1", r)          # 144.5 / 6.0 = 24.08
        self.assertIn("supera 3:1", r)             # la frase di lettura

    def test_conference_fascia_di_sei(self):
        r = cu.riga_prompt(UECL, ATALANTA, GETAFE)
        self.assertIn("fascia 1 di 6", r)
        self.assertIn("fascia 3 di 6", r)

    def test_rapporto_vicino_a_uno(self):
        r = cu.riga_prompt(UCL, REAL_MADRID, BAYERN)   # 147.5 vs 144.5
        self.assertIn("Rapporto 1:1", r)

    def test_campionato_niente_riga(self):
        """Getafe e Real Madrid sono entrambi in tabella, ma in Liga la
        riga non deve esistere: solo UCL/UEL/UECL."""
        self.assertIsNone(cu.riga_prompt(SERIE_A, REAL_MADRID, GETAFE))

    def test_squadra_mancante_niente_riga(self):
        self.assertIsNone(cu.riga_prompt(UCL, REAL_MADRID, 424242))

    def test_squadra_di_altra_competizione_ha_comunque_la_riga(self):
        """Un'atalantina in UEL per i playoff? No: ma una squadra UECL che
        gioca in UEL non capita nella fase campionato. Se pero' entrambe
        sono in tabella la riga esce con i loro dati: il cancello e' il
        league_id della PARTITA, la tabella dice solo chi sono."""
        r = cu.riga_prompt(UEL, REAL_MADRID, GETAFE)
        self.assertIsNotNone(r)


class TestCoppia(unittest.TestCase):

    def test_valori_per_il_registro(self):
        c = cu.coppia(UCL, REAL_MADRID, SABAH)
        self.assertEqual(c, (144.5, 6.0, 1, 4))

    def test_campionato_tutto_none(self):
        self.assertEqual(cu.coppia(SERIE_A, REAL_MADRID, SABAH),
                         (None, None, None, None))

    def test_mancante_tutto_none(self):
        self.assertEqual(cu.coppia(UCL, REAL_MADRID, 424242),
                         (None, None, None, None))


@richiede_bot_completo
class TestAggancioProduzione(unittest.TestCase):
    """Ancorati alle CHIAMATE, non ai commenti (regola del progetto)."""

    def test_il_prompt_prematch_include_la_riga(self):
        with open("/opt/football-bot/daily_prematch.py",
                  encoding="utf-8") as f:
            src = f.read()
        self.assertIn("coefficienti_uefa.riga_prompt(", src)

    def test_l_insert_salva_le_quattro_colonne(self):
        with open("/opt/football-bot/bot.py", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("coefficienti_uefa.coppia(", src)
        self.assertIn("coeff_casa", src)
        self.assertIn("fascia_ospite", src)

    def test_migrazione_presente(self):
        """La migrazione e' un ciclo sulle quattro colonne: si ancora la
        tupla e l'ALTER parametrico, che insieme la generano."""
        with open("/opt/football-bot/bot.py", encoding="utf-8") as f:
            src = f.read()
        self.assertIn('("coeff_casa", "REAL")', src)
        self.assertIn('("fascia_ospite", "INTEGER")', src)
        self.assertIn("ADD COLUMN {_col} {_tipo}", src)


if __name__ == "__main__":
    unittest.main(verbosity=1)
