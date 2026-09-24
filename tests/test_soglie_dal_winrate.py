"""Soglie di quota derivate dal win rate misurato, per tipo (21/09/2026).

PERCHE'. Le soglie di QUOTA_RANGES erano decise a tavolino nell'agosto
2026 e uguali nello spirito per tutti i tipi. Ma i tipi rendono in modo
molto diverso, e il prezzo che serve per andare in pari dipende SOLO dal
win rate:

    OVER 2.5   65,6%  ->  pareggio a 1,52  ·  mercato paga 1,70-1,90  OK
    OVER 0.5   60,0%  ->  pareggio a 1,67  ·  mercato paga ~1,20      NO
    CHI_SEGNA  35,7%  ->  pareggio a 2,80  ·  mercato paga 1,80-2,50  NO

La regola dell'espulsione emetteva CHI_SEGNA con quota minima 1,80
scritta a mano: perdente per costruzione, non per sfortuna.

Qui la soglia diventa aritmetica: 1/winrate, piu' un margine di
sicurezza. Niente opinioni, e si aggiorna da sola quando i dati
cambiano.

GARANZIE (tutte con un test):
- campione insufficiente -> si tiene la soglia statica di agosto;
- la soglia non scende MAI sotto quella statica (il filtro puo' solo
  diventare piu' severo: allentarlo su dati scarsi e' il rischio vero);
- tetto di sicurezza, perche' un tipo con winrate 10% chiederebbe 10.00.

Nessun test tocca signals.db: DB temporaneo.
"""
import os
# Vetrina: bot.py e i moduli di raccolta dati restano nel repository privato.
# Le classi che verificano l'aggancio al bot completo si saltano qui.
from _vetrina import richiede_bot_completo

import sqlite3
import tempfile
import unittest

import quota_filter as qf


class _ConDB(unittest.TestCase):

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE signals(tipo TEXT, esito TEXT, "
                     "motivazione TEXT, timestamp TEXT)")
        conn.commit()
        conn.close()
        qf.svuota_cache_soglie()

    def tearDown(self):
        os.unlink(self.db)
        qf.svuota_cache_soglie()

    def _segnali(self, tipo, n, vinti, motivazione="analisi"):
        conn = sqlite3.connect(self.db)
        for i in range(n):
            conn.execute(
                "INSERT INTO signals VALUES(?,?,?,datetime('now'))",
                (tipo, "VINTO" if i < vinti else "PERSO", motivazione))
        conn.commit()
        conn.close()


class TestSogliaDalWinrate(_ConDB):

    def test_over25_resta_giocabile(self):
        """65% -> pareggio 1.54, col margine ~1.62: sotto le quote reali
        di mercato (1.70-1.90), quindi il tipo resta vivo."""
        self._segnali("OVER_2.5", 100, 65)
        s = qf.soglia_minima("OVER_2.5", db=self.db)
        self.assertGreater(s, 1.55)
        self.assertLess(s, 1.70)

    def test_chi_segna_diventa_severo(self):
        """36% -> pareggio 2.78: il tipo passa solo se il banco paga
        davvero tanto, non piu' a 1.80."""
        self._segnali("CHI_SEGNA_PROSSIMO_CASA", 84, 30)
        s = qf.soglia_minima("CHI_SEGNA_PROSSIMO_CASA", db=self.db)
        self.assertGreater(s, 2.70)

    def test_over05_si_chiude_da_solo(self):
        """60% -> pareggio 1.67, contro un mercato che paga 1.20: la
        soglia lo esclude senza che nessuno debba deciderlo."""
        self._segnali("OVER_0.5", 65, 39)
        s = qf.soglia_minima("OVER_0.5", db=self.db)
        self.assertGreater(s, 1.70)
        ok, _ = qf.check_quota_range("OVER_0.5", 1.20, db=self.db)
        self.assertFalse(ok)

    def test_campione_scarso_tiene_la_soglia_statica(self):
        self._segnali("OVER_1.5", 12, 6)
        self.assertEqual(qf.soglia_minima("OVER_1.5", db=self.db),
                         qf.QUOTA_RANGES["OVER_1.5"][0])

    def test_mai_piu_permissiva_della_statica(self):
        """Un tipo con winrate altissimo chiederebbe 1.20: il filtro puo'
        diventare piu' severo, mai piu' largo. Allentare su un campione
        di qualche decina e' il modo classico di farsi male."""
        self._segnali("OVER_2.5", 100, 95)
        self.assertGreaterEqual(qf.soglia_minima("OVER_2.5", db=self.db),
                                qf.QUOTA_RANGES["OVER_2.5"][0])

    def test_tetto_di_sicurezza(self):
        """Winrate 10% chiederebbe 10.00: oltre il tetto il tipo sarebbe
        di fatto spento da un numero, non da una decisione."""
        self._segnali("GG", 50, 5)
        self.assertLessEqual(qf.soglia_minima("GG", db=self.db),
                             qf.SOGLIA_MASSIMA)

    def test_il_margine_e_un_parametro(self):
        self.assertGreater(qf.MARGINE_SICUREZZA, 0)

    def test_tipo_sconosciuto_non_solleva(self):
        self.assertIsNone(qf.soglia_minima("ROBA_STRANA", db=self.db))

    def test_db_irraggiungibile_tiene_la_statica(self):
        self.assertEqual(
            qf.soglia_minima("OVER_2.5", db="/inesistente/x.db"),
            qf.QUOTA_RANGES["OVER_2.5"][0])


class TestCheckQuotaRange(_ConDB):

    def test_usa_la_soglia_dinamica(self):
        self._segnali("CHI_SEGNA_PROSSIMO_CASA", 84, 30)
        ok, motivo = qf.check_quota_range("CHI_SEGNA_PROSSIMO_CASA", 2.00,
                                          db=self.db)
        self.assertFalse(ok)
        self.assertIn("winrate", motivo)

    def test_quota_alta_passa(self):
        self._segnali("CHI_SEGNA_PROSSIMO_CASA", 84, 30)
        ok, _ = qf.check_quota_range("CHI_SEGNA_PROSSIMO_CASA", 3.00,
                                     db=self.db)
        self.assertTrue(ok)

    def test_senza_quota_si_passa_come_prima(self):
        ok, motivo = qf.check_quota_range("OVER_2.5", None, db=self.db)
        self.assertTrue(ok)
        self.assertIn("non verificata", motivo)

    def test_il_massimo_resta_quello_statico(self):
        self._segnali("OVER_2.5", 100, 65)
        ok, _ = qf.check_quota_range("OVER_2.5", 9.99, db=self.db)
        self.assertFalse(ok)


@richiede_bot_completo
class TestUrgentiAllineati(unittest.TestCase):
    """La regola dell'espulsione scriveva 1.80 a mano: ora chiede la
    soglia come tutti, altrimenti resta l'unico punto che emette segnali
    a un prezzo che i dati dicono perdente."""

    def test_l_urgente_non_ha_piu_la_quota_scritta_a_mano(self):
        with open("/opt/football-bot/bot.py", encoding="utf-8") as f:
            src = f.read()
        i = src.find("Espulsione {squadra_label}")
        blocco = src[max(0, i - 1500):i + 200]
        self.assertIn("soglia_minima(", blocco)


if __name__ == "__main__":
    unittest.main(verbosity=1)
