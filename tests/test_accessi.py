"""Test della policy accessi a due stati.

Decisa il 05/06/2026, implementata il 16/08/2026. Nasce dal bug del 04/06:
un abbonato scaduto veniva messo in `blocked_users`, la stessa tabella dei
bannati. Da li' due conseguenze:
  - chi rinnovava restava murato fuori, perche' nessuno lo toglieva da li';
  - non si distingueva piu' chi era scaduto da chi aveva violato le regole.

I due stati sono diversi per natura:
  scaduto  -> automatico, REVERSIBILE pagando
  bannato  -> solo manuale, riammissione a giudizio dell'admin
"""
import unittest
from datetime import datetime, timedelta

from accessi import (
    STATO_ATTIVO,
    STATO_BANNATO,
    STATO_SCADUTO,
    STATO_SCONOSCIUTO,
    is_expired,
    normalize_expires,
    renewal_expires,
    stato_accesso,
)

ORA = datetime(2026, 8, 16, 12, 0, 0)


class TestNormalizeExpires(unittest.TestCase):
    """In DB convivono due formati: '2026-07-20T21:27:58.050288' e
    '2027-04-19 23:14:01'. Confrontarli come stringhe e' sbagliato, perche'
    'T' viene dopo lo spazio: uno scaduto puo' risultare attivo."""

    def test_formato_con_la_T(self):
        self.assertEqual(normalize_expires("2026-07-20T21:27:58.050288"),
                         "2026-07-20 21:27:58")

    def test_formato_con_lo_spazio_invariato(self):
        self.assertEqual(normalize_expires("2027-04-19 23:14:01"),
                         "2027-04-19 23:14:01")

    def test_solo_data(self):
        self.assertEqual(normalize_expires("2026-12-31"), "2026-12-31 00:00:00")

    def test_datetime_python(self):
        self.assertEqual(normalize_expires(ORA), "2026-08-16 12:00:00")

    def test_valori_non_validi(self):
        for v in (None, "", "   ", "boh"):
            self.assertIsNone(normalize_expires(v))

    def test_normalizzati_si_ordinano_correttamente(self):
        """Il punto di tutto: dopo la normalizzazione l'ordine e' giusto."""
        mattina = normalize_expires("2026-08-16T10:00:00.000000")
        sera = normalize_expires("2026-08-16 23:00:00")
        self.assertLess(mattina, sera)
        # prova che senza normalizzazione l'ordine si invertirebbe
        self.assertGreater("2026-08-16T10:00:00.000000", "2026-08-16 23:00:00")


class TestIsExpired(unittest.TestCase):

    def test_scadenza_futura(self):
        self.assertFalse(is_expired("2027-01-01 00:00:00", now=ORA))

    def test_scadenza_passata(self):
        self.assertTrue(is_expired("2026-07-20T21:27:58.050288", now=ORA))

    def test_scadenza_assente_non_scade(self):
        """expires NULL = abbonamento senza scadenza, non scaduto."""
        self.assertFalse(is_expired(None, now=ORA))

    def test_formati_misti_confrontati_correttamente(self):
        self.assertTrue(is_expired("2026-08-16T10:00:00.000000", now=ORA))
        self.assertFalse(is_expired("2026-08-16 23:00:00", now=ORA))


class TestRenewalExpires(unittest.TestCase):
    """BUG RINNOVO: `datetime(expires, '+N days')` partiva dalla VECCHIA
    scadenza. Chi rinnovava dopo mesi di inattivita' perdeva i giorni in
    mezzo, e con abbastanza ritardo restava scaduto anche dopo aver pagato."""

    def test_abbonamento_scaduto_riparte_da_oggi(self):
        # scaduto da 60 giorni, rinnovo di 30
        vecchia = (ORA - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
        nuova = renewal_expires(vecchia, 30, now=ORA)
        self.assertEqual(nuova, (ORA + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"))

    def test_scaduto_da_tanto_non_resta_scaduto(self):
        """Il caso peggiore: con la vecchia formula pagava e restava fuori."""
        vecchia = (ORA - timedelta(days=200)).strftime("%Y-%m-%d %H:%M:%S")
        nuova = renewal_expires(vecchia, 30, now=ORA)
        self.assertFalse(is_expired(nuova, now=ORA))

    def test_abbonamento_attivo_si_estende_dalla_scadenza(self):
        """Chi rinnova in anticipo non deve perdere i giorni residui."""
        vecchia = (ORA + timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        nuova = renewal_expires(vecchia, 30, now=ORA)
        self.assertEqual(nuova, (ORA + timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S"))

    def test_scadenza_assente_riparte_da_oggi(self):
        nuova = renewal_expires(None, 30, now=ORA)
        self.assertEqual(nuova, (ORA + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"))

    def test_formato_con_la_T_gestito(self):
        vecchia = "2026-07-20T21:27:58.050288"   # scaduta
        nuova = renewal_expires(vecchia, 30, now=ORA)
        self.assertFalse(is_expired(nuova, now=ORA))

    def test_giorni_zero_o_negativi_rifiutati(self):
        for d in (0, -5):
            with self.assertRaises(ValueError):
                renewal_expires("2027-01-01 00:00:00", d, now=ORA)


class TestStatoAccesso(unittest.TestCase):
    """I due stati non vanno mescolati: era la causa del bug del 04/06."""

    def test_attivo(self):
        self.assertEqual(stato_accesso("2027-01-01 00:00:00", banned=False, now=ORA),
                         STATO_ATTIVO)

    def test_scaduto(self):
        self.assertEqual(stato_accesso("2026-01-01 00:00:00", banned=False, now=ORA),
                         STATO_SCADUTO)

    def test_bannato_prevale_su_attivo(self):
        """Un ban vale anche con abbonamento in corso: e' una sanzione."""
        self.assertEqual(stato_accesso("2027-01-01 00:00:00", banned=True, now=ORA),
                         STATO_BANNATO)

    def test_bannato_prevale_su_scaduto(self):
        self.assertEqual(stato_accesso("2026-01-01 00:00:00", banned=True, now=ORA),
                         STATO_BANNATO)

    def test_non_abbonato(self):
        self.assertEqual(stato_accesso(None, banned=False, now=ORA, esiste=False),
                         STATO_SCONOSCIUTO)

    def test_solo_attivo_da_accesso(self):
        """Il criterio unico: accede solo chi e' attivo."""
        for exp, ban, esiste in (("2026-01-01 00:00:00", False, True),   # scaduto
                                 ("2027-01-01 00:00:00", True, True),    # bannato
                                 (None, False, False)):                   # sconosciuto
            self.assertNotEqual(stato_accesso(exp, ban, now=ORA, esiste=esiste),
                                STATO_ATTIVO)

    def test_il_rinnovo_riporta_ad_attivo_senza_sbloccare(self):
        """Il secondo bug sparisce per costruzione: scaduto non e' bloccato,
        quindi rinnovare basta a riottenere l'accesso."""
        scaduta = (ORA - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
        self.assertEqual(stato_accesso(scaduta, banned=False, now=ORA), STATO_SCADUTO)
        nuova = renewal_expires(scaduta, 30, now=ORA)
        self.assertEqual(stato_accesso(nuova, banned=False, now=ORA), STATO_ATTIVO)

    def test_il_rinnovo_non_toglie_il_ban(self):
        """Riammissione a giudizio dell'admin, non automatica col pagamento."""
        nuova = renewal_expires("2026-01-01 00:00:00", 30, now=ORA)
        self.assertEqual(stato_accesso(nuova, banned=True, now=ORA), STATO_BANNATO)


if __name__ == "__main__":
    unittest.main()
