"""Run: python3 test_prediction_validator.py"""

import unittest

from prediction_validator import parse_score, validate_prediction


def pred(ris, x12, over25, gg):
    return {
        "1x2": x12,
        "over25": over25,
        "gg": gg,
        "risultato_probabile": ris,
    }


class ParseScoreTests(unittest.TestCase):
    def test_standard(self):
        self.assertEqual(parse_score("2-1"), (2, 1))

    def test_whitespace(self):
        self.assertEqual(parse_score("  0 - 0 "), (0, 0))

    def test_invalid(self):
        self.assertIsNone(parse_score("abc"))
        self.assertIsNone(parse_score(""))
        self.assertIsNone(parse_score(None))


class ValidCases(unittest.TestCase):
    def _assert_valid(self, p):
        errs = validate_prediction(p)
        self.assertEqual(errs, [], f"expected valid, got: {errs}")

    def test_2_1_gg_over25(self):
        self._assert_valid(pred("2-1", "1", "SI", "GG"))

    def test_0_0_nogg_under(self):
        self._assert_valid(pred("0-0", "X", "NO", "NG"))

    def test_1_0_nogg_under25(self):
        self._assert_valid(pred("1-0", "1", "NO", "NG"))


class InvalidCases(unittest.TestCase):
    def _assert_invalid(self, p):
        errs = validate_prediction(p)
        self.assertNotEqual(errs, [], "expected errors, got none")

    def test_1_2_ng_under25(self):
        # 1-2 → 3 goals (over) AND both scored (GG). NG + NO is double-wrong.
        self._assert_invalid(pred("1-2", "2", "NO", "NG"))

    def test_0_0_gg(self):
        # 0-0 cannot have both teams scoring.
        self._assert_invalid(pred("0-0", "X", "NO", "GG"))

    def test_3_0_gg(self):
        # 3-0 → away did not score.
        self._assert_invalid(pred("3-0", "1", "SI", "GG"))

    def test_1_1_ng(self):
        # 1-1 → both scored, cannot be NG.
        self._assert_invalid(pred("1-1", "X", "NO", "NG"))

    def test_2_2_12(self):
        # Doppia chance "12" excludes the draw → 2-2 invalid.
        self._assert_invalid(pred("2-2", "12", "SI", "GG"))

    def test_den_bosch_2_1_under_ng(self):
        # Caso reale 24/04/2026: 2-1 dichiarato Under 2.5 + NG.
        # 2+1=3 ⇒ over25=NO incoerente; 2≥1 e 1≥1 ⇒ gg=NG incoerente.
        # Garantisce ≥2 errori → fa scattare il retry in analyze_with_retry.
        errs = validate_prediction(pred("2-1", "1", "NO", "NG"))
        self.assertGreaterEqual(len(errs), 2,
            f"atteso ≥2 errori (over25, gg), ottenuti: {errs}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
