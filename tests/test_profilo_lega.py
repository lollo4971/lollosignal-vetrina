"""Profilo storico di lega nel prompt prematch: i tassi di base misurati.

PERCHE' (17/09/2026, richiesta dell'utente): «in Olanda segnano una
valanga di gol, in Francia partite equilibrate» — pattern veri e misurati
(Eerste 3,08 gol/partita e 61% Over contro Segunda 2,37 e 43%; pareggi
Serie B 31,8% contro Eerste 22,4%) che l'AI non riceveva: doveva
ricordarseli dalla cultura generale. Ora li legge da storico.db.

Le coppe restano FUORI: li' c'e' gia' la riga UEFA, e i tassi storici di
una coppa mischiano preliminari e fasi finali — numeri sporchi.

I test leggono lo storico VERO (44 leghe x 5 stagioni): i valori attesi
sono misure, con tolleranza per l'aggiornamento settimanale dell'archivio.
"""
import unittest
# Vetrina: bot.py e i moduli di raccolta dati restano nel repository privato.
# Le classi che verificano l'aggancio al bot completo si saltano qui.
from _vetrina import richiede_bot_completo, richiede_storico


import profilo_lega as pl

EERSTE, LIGUE2, SERIE_B = 89, 62, 136
UCL, SCONOSCIUTA = 2, 424242


class TestProfilo(unittest.TestCase):

    @richiede_storico

    def test_eerste_divisie_i_numeri_veri(self):
        p = pl.profilo(EERSTE)
        self.assertAlmostEqual(p["gol_medi"], 3.08, delta=0.15)
        self.assertAlmostEqual(p["over25"], 0.61, delta=0.04)
        self.assertAlmostEqual(p["pareggi"], 0.224, delta=0.03)
        self.assertGreater(p["n"], 400)

    @richiede_storico

    def test_serie_b_equilibrata(self):
        """Il contrasto che ha motivato la feature: la Serie B pareggia
        una partita su tre, l'Eerste una su 4,5."""
        b, e = pl.profilo(SERIE_B), pl.profilo(EERSTE)
        self.assertGreater(b["pareggi"], e["pareggi"] + 0.05)
        self.assertLess(b["gol_medi"], e["gol_medi"] - 0.4)

    def test_coppa_niente_profilo(self):
        """UCL: i tassi mischierebbero preliminari e fase campionato, e la
        riga UEFA c'e' gia'. None, senza eccezioni."""
        self.assertIsNone(pl.profilo(UCL))

    def test_lega_sconosciuta_none(self):
        self.assertIsNone(pl.profilo(SCONOSCIUTA))

    def test_archivio_mancante_none_senza_sollevare(self):
        self.assertIsNone(pl.profilo(EERSTE, path="/inesistente/storico.db"))

    def test_cache_di_processo(self):
        """tassi_lega rilegge migliaia di righe: il profilo va calcolato
        una volta per lega, non a ogni scheda del batch."""
        p1 = pl.profilo(EERSTE)
        p2 = pl.profilo(EERSTE)
        self.assertIs(p1, p2)


class TestRigaPrompt(unittest.TestCase):

    @richiede_storico

    def test_campionato_con_storico(self):
        r = pl.riga_prompt(EERSTE)
        self.assertIn("PROFILO LEGA", r)
        self.assertIn("storico 5 stagioni", r)
        self.assertIn("media gol 3.1", r)
        self.assertIn("Over 2.5 61%", r)
        self.assertIn("pareggi 22%", r)
        # la frase di lettura: i tassi di base si ancorano, non si ignorano
        self.assertIn("tassi di base", r)

    def test_coppa_none(self):
        self.assertIsNone(pl.riga_prompt(UCL))

    def test_sconosciuta_none(self):
        self.assertIsNone(pl.riga_prompt(SCONOSCIUTA))


@richiede_bot_completo
class TestAggancioProduzione(unittest.TestCase):
    """Ancorato alla CHIAMATA, non ai commenti (regola del progetto)."""

    def test_il_prompt_prematch_include_il_profilo(self):
        with open("/opt/football-bot/daily_prematch.py",
                  encoding="utf-8") as f:
            src = f.read()
        self.assertIn("profilo_lega.riga_prompt(", src)


if __name__ == "__main__":
    unittest.main(verbosity=1)
