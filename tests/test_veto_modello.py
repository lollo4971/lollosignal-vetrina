"""Il modello ha potere di VETO sui segnali live (22/09/2026).

PERCHE'. Fra le tre fonti misurate nella modalita' ombra il modello e'
l'unica CALIBRATA: nella fascia 55-70% dichiara 62,8% e rende 60,0%
(scarto 2,8 punti, la cella migliore di tutta la tabella), mentre l'AI
dichiara sopra il 70% in 39 stime su 39 e rende 41% (scarto 38 punti).

Sui 75 CHI_SEGNA nati dall'espulsione il modello diceva 33,1% e l'esito
reale e' stato 37,3%: aveva ragione, ma nessuno lo interpellava.

REGOLA: il modello puo' solo TOGLIERE, mai proporre. Non e' la caccia al
valore che nel prematch ha fatto danni (li' si sceglieva il massimo edge,
qui si scarta il negativo). Il segnale esce se
`prob_modello × quota_reale ≥ 1 + MARGINE_VETO`; se il modello non ha una
stima il segnale passa — un veto muto non deve diventare un divieto.

Funzioni pure: nessun test tocca rete o database.
"""
import unittest
# Vetrina: bot.py e i moduli di raccolta dati restano nel repository privato.
# Le classi che verificano l'aggancio al bot completo si saltano qui.
from _vetrina import richiede_bot_completo


from veto_modello import MARGINE_VETO, TIPI_CON_VETO, veto


class TestVeto(unittest.TestCase):

    def test_passa_se_il_valore_e_positivo(self):
        """40% a quota 3.00 = 1.20 di ritorno atteso: passa."""
        ok, motivo = veto("CHI_SEGNA_PROSSIMO_CASA", 0.40, 3.00)
        self.assertTrue(ok)
        self.assertIn("40%", motivo)

    def test_blocca_il_caso_misurato(self):
        """Il caso vero: CHI_SEGNA a 1.80 con il modello al 33%.
        0.33 × 1.80 = 0.594, cioe' 40 centesimi persi per ogni euro."""
        ok, motivo = veto("CHI_SEGNA_PROSSIMO_CASA", 0.331, 1.80)
        self.assertFalse(ok)
        self.assertIn("serve almeno", motivo)

    def test_il_margine_non_e_zero(self):
        """Esattamente al pareggio non basta: il modello sbaglia anche lui
        (nella fascia 40-55% sovrastima di 17 punti)."""
        ok, _ = veto("GG", 0.50, 2.00)     # 1.00 esatto
        self.assertFalse(ok)
        self.assertGreater(MARGINE_VETO, 0)

    def test_senza_stima_del_modello_passa(self):
        """Il modello non copre tutte le leghe: 40 righe su 148 erano
        senza stima. Un veto muto non deve diventare un divieto."""
        ok, motivo = veto("GG", None, 2.50)
        self.assertTrue(ok)
        self.assertIn("nessuna stima", motivo)

    def test_senza_quota_passa(self):
        """Senza prezzo il valore non e' calcolabile: decide il resto."""
        ok, motivo = veto("GG", 0.30, None)
        self.assertTrue(ok)
        self.assertIn("quota", motivo)

    def test_tipo_fuori_elenco_non_viene_filtrato(self):
        """Gli OVER a 90 minuti rendono 53-66% e funzionano: il veto e'
        per i tipi dove il modello e' misurato meglio dell'AI, non per
        tutto. Allargarlo e' una decisione da prendere coi dati."""
        ok, motivo = veto("OVER_2.5", 0.10, 1.50)
        self.assertTrue(ok)
        self.assertIn("senza veto", motivo)

    def test_i_tipi_con_veto_sono_quelli_decisi(self):
        for t in ("CHI_SEGNA_PROSSIMO_CASA", "CHI_SEGNA_PROSSIMO_OSPITE",
                  "GG", "RIBALTONE_CASA", "RIBALTONE_OSPITE",
                  "OVER_0.5_PT"):
            self.assertTrue(any(t.startswith(p) for p in TIPI_CON_VETO),
                            msg=f"{t} dovrebbe avere il veto")

    def test_valori_sporchi_non_sollevano(self):
        for p, q in ((-1, 2.0), (0, 2.0), (0.5, 0), (0.5, -3), ("x", 2.0)):
            ok, _ = veto("GG", p, q)
            self.assertIsInstance(ok, bool)


@richiede_bot_completo
class TestAggancio(unittest.TestCase):

    def setUp(self):
        with open("/opt/football-bot/bot.py", encoding="utf-8") as f:
            self.src = f.read()

    def test_il_ciclo_chiama_il_veto(self):
        self.assertIn("veto_modello.veto(", self.src)

    def test_il_veto_non_riapre_cio_che_una_misura_ha_chiuso(self):
        """Avevo riaperto il RIBALTONE nella fascia 70-80' contando sul
        veto; `test_finestre_ribaltone` l'ha bocciato e aveva ragione.
        La misura del 17/08 e' zero ribaltoni su 11 dopo il 75': il veto
        protegge cio' che e' ammesso, non autorizza a disfare un dato."""
        import sys
        sys.argv = ["test"]
        import bot
        tardiva = [w for w in bot.TIME_WINDOWS_FT if w[5] == "tardiva_ft"][0]
        tipi = tardiva[2]
        self.assertIn("GG", tipi)
        self.assertNotIn("RIBALTONE", tipi)


if __name__ == "__main__":
    unittest.main(verbosity=1)
