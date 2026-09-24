"""Test filtro quote minime per segnali LIVE.

Soglie decise il 14/08/2026. Non si applicano al prematch.
Chiude tre falle del filtro precedente (QUOTA_RANGES dentro bot.py):
  1. la chiave "OVER_N5" non corrispondeva a nessun tipo reale
     ("OVER_2.5".startswith("OVER_N5") e' falso) -> gli OVER non venivano
     mai filtrati: 25 OVER_1.5 su 73 sono usciti sotto 1.50;
  2. i segnali urgenti non passavano dal controllo;
  3. quota reale assente -> il segnale passava e in DB finiva la quota
     inventata dall'AI (1.80 hardcoded) come se fosse di mercato.
"""
import unittest

from quota_filter import (
    QUOTA_RANGES,
    correct_over_type,
    check_quota_range,
    resolve_quota_key,
)


class TestResolveQuotaKey(unittest.TestCase):

    def test_over_linee_esatte(self):
        for tipo in ("OVER_0.5", "OVER_1.5", "OVER_2.5", "OVER_3.5"):
            self.assertEqual(resolve_quota_key(tipo), tipo)

    def test_over_linea_non_prevista_usa_la_piu_severa(self):
        """La falla originale: una linea non mappata restava senza filtro."""
        self.assertEqual(resolve_quota_key("OVER_4.5"), "OVER_3.5")
        self.assertEqual(resolve_quota_key("OVER_5.5"), "OVER_3.5")

    def test_chi_segna_varianti(self):
        self.assertEqual(resolve_quota_key("CHI_SEGNA_PROSSIMO_CASA"), "CHI_SEGNA_PROSSIMO")
        self.assertEqual(resolve_quota_key("CHI_SEGNA_PROSSIMO_OSPITE"), "CHI_SEGNA_PROSSIMO")

    def test_ribaltone_varianti(self):
        self.assertEqual(resolve_quota_key("RIBALTONE_CASA"), "RIBALTONE")
        self.assertEqual(resolve_quota_key("RIBALTONE_OSPITE"), "RIBALTONE")

    def test_gg(self):
        self.assertEqual(resolve_quota_key("GG"), "GG")

    def test_tipo_sconosciuto(self):
        self.assertIsNone(resolve_quota_key("PIPPO"))
        self.assertIsNone(resolve_quota_key(None))


class TestSoglie(unittest.TestCase):
    """Soglie abbassate di ~0.10 il 15/08 (prima: 1.75/1.60/1.89/1.60/1.80).
    OVER_2.5 resta il piu' permissivo: unico tipo con WR sopra il 50%."""

    def test_minimi_concordati(self):
        attesi = {
            "OVER_0.5": 1.65, "OVER_1.5": 1.65,
            "OVER_2.5": 1.50, "OVER_3.5": 1.75,
            "GG": 1.50, "CHI_SEGNA_PROSSIMO": 1.70,
        }
        for tipo, minimo in attesi.items():
            self.assertAlmostEqual(QUOTA_RANGES[tipo][0], minimo, msg=f"minimo di {tipo}")

    def test_minimo_sempre_sotto_massimo(self):
        for tipo, (lo, hi) in QUOTA_RANGES.items():
            self.assertLess(lo, hi, f"range invertito su {tipo}")


# Le soglie dinamiche (dal win rate misurato, 21/09/2026) si provano in
# test_soglie_dal_winrate.py. Qui si verifica lo strato STATICO, quindi
# si passa un percorso di database inesistente: soglia_minima ricade
# sulla statica ed i casi restano deterministici. Senza, questi test
# leggevano signals.db di PRODUZIONE e cambiavano risultato da soli.
DB_VUOTO = "/inesistente/quota_filter_test.db"


class TestCheckQuotaRange(unittest.TestCase):

    def test_over15_sotto_soglia_bloccato(self):
        """Il caso storico: 25 OVER_1.5 usciti sotto 1.50. Resta bocciato
        anche con la soglia abbassata a 1.65."""
        ok, _ = check_quota_range("OVER_1.5", 1.40, db=DB_VUOTO)
        self.assertFalse(ok)

    def test_over15_sopra_soglia_passa(self):
        ok, _ = check_quota_range("OVER_1.5", 1.80, db=DB_VUOTO)
        self.assertTrue(ok)

    def test_over25_protetto_a_150(self):
        self.assertTrue(check_quota_range("OVER_2.5", 1.55, db=DB_VUOTO)[0])
        self.assertFalse(check_quota_range("OVER_2.5", 1.45, db=DB_VUOTO)[0])

    def test_chi_segna_sotto_170_bloccato(self):
        self.assertFalse(check_quota_range("CHI_SEGNA_PROSSIMO_CASA", 1.60, db=DB_VUOTO)[0])
        self.assertTrue(check_quota_range("CHI_SEGNA_PROSSIMO_CASA", 1.75, db=DB_VUOTO)[0])

    def test_gg_a_150(self):
        self.assertFalse(check_quota_range("GG", 1.45, db=DB_VUOTO)[0])
        self.assertTrue(check_quota_range("GG", 1.50, db=DB_VUOTO)[0])

    def test_estremi_inclusi(self):
        lo, hi = QUOTA_RANGES["GG"]
        self.assertTrue(check_quota_range("GG", lo)[0])
        self.assertTrue(check_quota_range("GG", hi)[0])

    def test_sopra_il_massimo_bloccato(self):
        hi = QUOTA_RANGES["GG"][1]
        self.assertFalse(check_quota_range("GG", hi + 0.01)[0])

    def test_quota_assente_passa_ma_non_verificata(self):
        """Scelta del 14/08: il segnale esce, ma marcato e con quota NULL."""
        for assente in (None, 0, 0.0):
            ok, reason = check_quota_range("CHI_SEGNA_PROSSIMO_CASA", assente)
            self.assertTrue(ok, f"con quota {assente!r} il segnale deve passare")
            self.assertEqual(reason, "quota non verificata")

    def test_tipo_non_mappato_passa(self):
        ok, reason = check_quota_range("PIPPO", 1.50)
        self.assertTrue(ok)
        self.assertEqual(reason, "tipo non mappato")

    def test_reason_spiega_il_blocco(self):
        ok, reason = check_quota_range("OVER_1.5", 1.40, db=DB_VUOTO)
        self.assertFalse(ok)
        self.assertIn("1.4", reason)
        self.assertIn("1.65", reason)


class TestCorrectOverType(unittest.TestCase):
    """Il suffisso _PT non deve andare perso.

    Bug del 15/08: `correct_over = f"OVER_{sh+sa}.5"` riscriveva
    OVER_0.5_PT in OVER_0.5. Poi si leggeva la quota dei 90 minuti (1.04)
    per una scommessa sul primo tempo (che vale ~1.70) e la si bocciava.
    48 suggerimenti su 85 in una giornata erano Over di primo tempo.
    """

    def test_over_intera_partita_invariato(self):
        self.assertEqual(correct_over_type("OVER_2.5", 1, 1), "OVER_2.5")

    def test_over_intera_partita_corretto_sul_punteggio(self):
        """Con 2-1 la prossima linea utile e' OVER_3.5, non OVER_1.5."""
        self.assertEqual(correct_over_type("OVER_1.5", 2, 1), "OVER_3.5")

    def test_primo_tempo_mantiene_il_suffisso(self):
        self.assertEqual(correct_over_type("OVER_0.5_PT", 0, 0), "OVER_0.5_PT")

    def test_primo_tempo_corretto_sul_punteggio(self):
        """1-0 nel primo tempo: la linea aperta e' OVER_1.5_PT."""
        self.assertEqual(correct_over_type("OVER_0.5_PT", 1, 0), "OVER_1.5_PT")

    def test_primo_tempo_due_gol(self):
        self.assertEqual(correct_over_type("OVER_0.5_PT", 1, 1), "OVER_2.5_PT")

    def test_non_over_invariato(self):
        for t in ("GG", "CHI_SEGNA_PROSSIMO_CASA", "RIBALTONE_CASA"):
            self.assertEqual(correct_over_type(t, 2, 1), t)


class TestSogliePrimoTempo(unittest.TestCase):
    """Il primo tempo ha prezzi propri: un Over 0.5 sui 90 minuti vale 1.04,
    lo stesso sul primo tempo al 6' vale circa 1.70. Servono soglie separate."""

    def test_esistono_soglie_dedicate(self):
        for t in ("OVER_0.5_PT", "OVER_1.5_PT", "OVER_2.5_PT"):
            self.assertIn(t, QUOTA_RANGES, f"manca la soglia per {t}")

    def test_il_pt_non_eredita_la_soglia_dei_90_minuti(self):
        self.assertNotEqual(QUOTA_RANGES["OVER_0.5_PT"], QUOTA_RANGES["OVER_0.5"])

    def test_piu_gol_richiesti_soglia_piu_alta(self):
        self.assertLess(QUOTA_RANGES["OVER_0.5_PT"][0], QUOTA_RANGES["OVER_1.5_PT"][0])
        self.assertLess(QUOTA_RANGES["OVER_1.5_PT"][0], QUOTA_RANGES["OVER_2.5_PT"][0])

    def test_resolve_riconosce_il_pt(self):
        self.assertEqual(resolve_quota_key("OVER_0.5_PT"), "OVER_0.5_PT")
        self.assertEqual(resolve_quota_key("OVER_1.5_PT"), "OVER_1.5_PT")

    def test_pt_non_previsto_ricade_sul_piu_severo(self):
        self.assertEqual(resolve_quota_key("OVER_4.5_PT"), "OVER_2.5_PT")

    def test_caso_reale_furth_nurnberg(self):
        """6', 0-0: quota reale di primo tempo ~1.70 -> deve passare.
        Con la vecchia logica leggeva 1.04 e bocciava."""
        ok, _ = check_quota_range("OVER_0.5_PT", 1.70)
        self.assertTrue(ok)


class TestSoglieAbbassate(unittest.TestCase):
    """Richiesta del 15/08: abbassare le soglie, non eliminarle."""

    def test_i_minimi_restano_sopra_il_floor_assoluto(self):
        for tipo, (lo, _) in QUOTA_RANGES.items():
            self.assertGreaterEqual(lo, 1.40, f"{tipo} sotto il floor di 1.40")

    def test_nessuna_soglia_e_stata_eliminata(self):
        for tipo in ("OVER_0.5", "OVER_1.5", "OVER_2.5", "OVER_3.5",
                     "GG", "CHI_SEGNA_PROSSIMO", "RIBALTONE"):
            self.assertIn(tipo, QUOTA_RANGES)

    def test_quote_irrisorie_restano_bocciate(self):
        """Le 40 bocciature a 1.02-1.40 di ieri devono restare tali."""
        for q in (1.02, 1.05, 1.11, 1.20, 1.40):
            self.assertFalse(check_quota_range("OVER_1.5", q)[0],
                             f"quota {q} non deve passare")


if __name__ == "__main__":
    unittest.main()
