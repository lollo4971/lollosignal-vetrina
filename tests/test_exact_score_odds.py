"""Run: /opt/football-bot/venv/bin/python3 test_exact_score_odds.py"""

import json
import os
import sqlite3
import tempfile
import unittest

import exact_score_odds as eso

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "odds_1576144.json")


def load_raw():
    with open(FIXTURE) as f:
        return json.load(f)["response"]


class NormalizeScoreTests(unittest.TestCase):
    def test_colon_to_dash(self):
        self.assertEqual(eso.normalize_score("2:1"), "2-1")

    def test_already_dash(self):
        self.assertEqual(eso.normalize_score("2-1"), "2-1")

    def test_whitespace(self):
        self.assertEqual(eso.normalize_score("  3 : 0 "), "3-0")

    def test_invalid(self):
        self.assertIsNone(eso.normalize_score("Any Other"))
        self.assertIsNone(eso.normalize_score(""))


class ParseLadderTests(unittest.TestCase):
    def setUp(self):
        self.ladder = eso.parse_ladder(load_raw())

    def test_1xbet_ladder_complete(self):
        # 1xBet quota 121 punteggi su questa partita (misurato)
        with_x1 = [s for s, v in self.ladder.items() if v["x1"] is not None]
        self.assertEqual(len(with_x1), 121)

    def test_scores_normalized(self):
        for score in self.ladder:
            self.assertNotIn(":", score)
            self.assertRegex(score, r"^\d+-\d+$")

    def test_known_odd(self):
        # Bet365 quotava 2-1 a 9.50; il max fra 11 bookmaker e' >= 9.50
        self.assertGreaterEqual(self.ladder["2-1"]["agg"]["max"], 9.50)
        self.assertGreater(self.ladder["2-1"]["agg"]["n"], 1)

    def test_empty_raw(self):
        self.assertEqual(eso.parse_ladder([]), {})
        self.assertEqual(eso.parse_ladder(None), {})

    def test_market_absent(self):
        raw = [{"bookmakers": [{"name": "X", "bets": [{"id": 1, "values": []}]}]}]
        self.assertEqual(eso.parse_ladder(raw), {})

    def test_non_numeric_odd_skipped(self):
        raw = [{"bookmakers": [{"name": "1xBet", "bets": [
            {"id": 10, "values": [{"value": "1:0", "odd": "n/a"},
                                  {"value": "2:0", "odd": "5.00"}]}]}]}]
        out = eso.parse_ladder(raw)
        self.assertNotIn("1-0", out)
        self.assertEqual(out["2-0"]["x1"], 5.00)


class SaveLadderTests(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig = eso.DB_PATH
        eso.DB_PATH = self.db
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE prematch_predictions(fixture_id INTEGER UNIQUE)")
        conn.commit(); conn.close()
        eso.init_exact_score_tables()

    def tearDown(self):
        eso.DB_PATH = self._orig
        os.unlink(self.db)

    def test_save_and_count(self):
        n = eso.save_ladder(1576144, load_raw())
        self.assertGreater(n, 100)
        conn = sqlite3.connect(self.db)
        rows = conn.execute(
            "SELECT COUNT(*) FROM exact_score_ladder WHERE fixture_id=1576144").fetchone()[0]
        self.assertEqual(rows, n)

    def test_save_is_idempotent(self):
        eso.save_ladder(1576144, load_raw())
        n2 = eso.save_ladder(1576144, load_raw())
        conn = sqlite3.connect(self.db)
        rows = conn.execute(
            "SELECT COUNT(*) FROM exact_score_ladder WHERE fixture_id=1576144").fetchone()[0]
        self.assertEqual(rows, n2)

    def test_migration_adds_columns(self):
        conn = sqlite3.connect(self.db)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(prematch_predictions)")]
        for c in ("odd_pred", "odd_real", "odds_json"):
            self.assertIn(c, cols)


class GetOddTests(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig = eso.DB_PATH
        eso.DB_PATH = self.db
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE prematch_predictions(fixture_id INTEGER UNIQUE)")
        conn.execute("INSERT INTO prematch_predictions(fixture_id) VALUES(1576144)")
        conn.commit(); conn.close()
        eso.init_exact_score_tables()
        eso.save_ladder(1576144, load_raw())

    def tearDown(self):
        eso.DB_PATH = self._orig
        os.unlink(self.db)

    def test_lookup_uses_1xbet(self):
        r = eso.get_odd(1576144, "2-1")
        self.assertEqual(r["src"], "1xbet")
        self.assertGreater(r["odd"], 1.0)

    def test_lookup_missing_score(self):
        self.assertIsNone(eso.get_odd(1576144, "12-12"))

    def test_lookup_unknown_fixture(self):
        self.assertIsNone(eso.get_odd(999999, "2-1"))

    def test_fallback_to_median(self):
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE exact_score_ladder SET odd_1xbet=NULL WHERE score='2-1'")
        conn.commit(); conn.close()
        r = eso.get_odd(1576144, "2-1")
        self.assertEqual(r["src"], "med")
        self.assertGreater(r["odd"], 1.0)

    def test_save_pred_odd(self):
        odd = eso.save_pred_odd(1576144, "2-1")
        self.assertIsNotNone(odd)
        self.assertEqual(eso.get_stored_pred_odd(1576144), odd)

    def test_save_pred_odd_missing_score(self):
        self.assertIsNone(eso.save_pred_odd(1576144, "12-12"))
        self.assertIsNone(eso.get_stored_pred_odd(1576144))


class CollapseTests(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig = eso.DB_PATH
        eso.DB_PATH = self.db
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE prematch_predictions(fixture_id INTEGER UNIQUE)")
        conn.execute("INSERT INTO prematch_predictions(fixture_id) VALUES(1576144)")
        conn.commit(); conn.close()
        eso.init_exact_score_tables()
        eso.save_ladder(1576144, load_raw())
        eso.save_pred_odd(1576144, "2-1")

    def tearDown(self):
        eso.DB_PATH = self._orig
        os.unlink(self.db)

    def test_collapse_writes_and_deletes(self):
        out = eso.collapse(1576144, "2-1", "1-3")
        self.assertIsNotNone(out["real"])
        conn = sqlite3.connect(self.db)
        left = conn.execute(
            "SELECT COUNT(*) FROM exact_score_ladder WHERE fixture_id=1576144").fetchone()[0]
        self.assertEqual(left, 0)
        row = conn.execute(
            "SELECT odd_pred,odd_real,odds_json FROM prematch_predictions "
            "WHERE fixture_id=1576144").fetchone()
        conn.close()
        self.assertIsNotNone(row[0])
        self.assertIsNotNone(row[1])
        payload = json.loads(row[2])
        self.assertEqual(payload["pred"]["score"], "2-1")
        self.assertEqual(payload["real"]["score"], "1-3")

    def test_collapse_preserves_odd_pred(self):
        before = eso.get_stored_pred_odd(1576144)
        eso.collapse(1576144, "2-1", "1-3")
        self.assertEqual(eso.get_stored_pred_odd(1576144), before)

    def test_collapse_unquoted_real_score(self):
        out = eso.collapse(1576144, "2-1", "12-12")
        self.assertIsNone(out["real"])
        conn = sqlite3.connect(self.db)
        left = conn.execute(
            "SELECT COUNT(*) FROM exact_score_ladder WHERE fixture_id=1576144").fetchone()[0]
        conn.close()
        self.assertEqual(left, 0)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig = eso.DB_PATH
        eso.DB_PATH = self.db
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE prematch_predictions(fixture_id INTEGER UNIQUE)")
        conn.commit(); conn.close()
        eso.init_exact_score_tables()

    def tearDown(self):
        eso.DB_PATH = self._orig
        os.unlink(self.db)

    def test_cleanup_removes_only_old(self):
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO exact_score_ladder(fixture_id,score,captured_at) "
                     "VALUES(1,'1-0',datetime('now','-10 days'))")
        conn.execute("INSERT INTO exact_score_ladder(fixture_id,score,captured_at) "
                     "VALUES(2,'1-0',datetime('now','-1 day'))")
        conn.commit(); conn.close()
        removed = eso.cleanup(days=4)
        self.assertEqual(removed, 1)
        conn = sqlite3.connect(self.db)
        left = [r[0] for r in conn.execute("SELECT fixture_id FROM exact_score_ladder")]
        conn.close()
        self.assertEqual(left, [2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
