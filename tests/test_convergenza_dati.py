"""Il segnale nasce dai DATI, non dalla confidenza dichiarata.

PERCHE' (21/09/2026, decisione dell'utente: «l'ho costruito per emettere
segnali, non per scartarli»). Misurato lo stesso giorno su 20 partite
vere: Haiku dichiara confidenza **76 praticamente sempre** (9 volte su 10
segnali, una volta 81). Quel numero non misura niente — e' un campo
riempito. Ma due finestre temporali chiedevano **80**: per aritmetica
erano chiuse, e il segnale moriva prima di essere giudicato.

La correzione ha due pezzi:
1. le soglie irraggiungibili scendono a 75 (la scala reale del modello);
2. si aggiunge una via alternativa VERA: se i DATI convergono — almeno
   due indicatori offensivi concordanti, la regola che stava scritta nel
   prompt e non era mai stata verificata dal codice — il segnale passa
   anche con confidenza piu' bassa (SOGLIA_CONF_DATI).

Cosi' il segnale nasce se i numeri lo sostengono e muore se il PREZZO non
regge (soglia dal win rate, 21/09). Non muore piu' perche' un modello
scrive sempre lo stesso numero.

Funzioni pure: nessun test tocca rete o database.
"""
import unittest
# Vetrina: bot.py e i moduli di raccolta dati restano nel repository privato.
# Le classi che verificano l'aggancio al bot completo si saltano qui.
from _vetrina import richiede_bot_completo


from live_data import convergenza


def _s(sog=0, shots=0, corners=0, xg=0.0, possession=50):
    return {"sog": sog, "shots": shots, "corners": corners, "xg": xg,
            "possession": possession}


class TestChiSegna(unittest.TestCase):
    """Per «segna la casa» devono essere i numeri della CASA a guidare."""

    def test_casa_domina_due_indicatori(self):
        ok, motivo = convergenza("CHI_SEGNA_PROSSIMO_CASA",
                                 _s(sog=5, shots=14, corners=6, xg=1.7),
                                 _s(sog=1, shots=5, corners=1, xg=0.3))
        self.assertTrue(ok)
        self.assertIn("4 indicatori", motivo)

    def test_casa_domina_un_solo_indicatore_non_basta(self):
        """Il possesso sterile e' il caso da cui nasce la regola: tanta
        palla, zero pericolo."""
        ok, motivo = convergenza("CHI_SEGNA_PROSSIMO_CASA",
                                 _s(sog=1, shots=5, corners=1, possession=68),
                                 _s(sog=1, shots=5, corners=1, possession=32))
        self.assertFalse(ok)

    def test_ospite_domina_ma_il_segnale_e_sulla_casa(self):
        """Dati forti nella direzione SBAGLIATA non valgono: e' l'errore
        che una regola sul «volume generico» avrebbe lasciato passare."""
        ok, _ = convergenza("CHI_SEGNA_PROSSIMO_CASA",
                            _s(sog=1, shots=4, corners=1, xg=0.2),
                            _s(sog=6, shots=15, corners=7, xg=2.0))
        self.assertFalse(ok)

    def test_ospite_domina_e_il_segnale_e_sull_ospite(self):
        ok, _ = convergenza("CHI_SEGNA_PROSSIMO_OSPITE",
                            _s(sog=1, shots=4, corners=1, xg=0.2),
                            _s(sog=6, shots=15, corners=7, xg=2.0))
        self.assertTrue(ok)


class TestOver(unittest.TestCase):
    """Per gli OVER conta il RITMO complessivo, non chi domina."""

    def test_ritmo_alto_passa(self):
        ok, motivo = convergenza("OVER_2.5",
                                 _s(sog=6, shots=13, corners=5),
                                 _s(sog=4, shots=10, corners=4))
        self.assertTrue(ok)

    def test_partita_bloccata_non_passa(self):
        ok, _ = convergenza("OVER_2.5",
                            _s(sog=1, shots=4, corners=2),
                            _s(sog=1, shots=3, corners=1))
        self.assertFalse(ok)

    def test_una_sola_grandezza_alta_non_basta(self):
        """15 tiri ma 2 in porta e 1 corner: volume senza pericolo."""
        ok, _ = convergenza("OVER_2.5",
                            _s(sog=1, shots=9, corners=1),
                            _s(sog=1, shots=6, corners=0))
        self.assertFalse(ok)


class TestGG(unittest.TestCase):
    """Il GG richiede che a premere sia la squadra ANCORA A ZERO."""

    def test_la_squadra_a_zero_preme(self):
        ok, _ = convergenza("GG", _s(sog=5, shots=12, corners=5, xg=1.5),
                            _s(sog=1, shots=3, corners=1, xg=0.2),
                            gol_casa=0, gol_ospite=1)
        self.assertTrue(ok)

    def test_preme_chi_e_gia_in_vantaggio(self):
        """Se domina chi ha gia' segnato, il GG non ha sostegno: e' la
        squadra che si sta chiudendo a doverlo trovare."""
        ok, _ = convergenza("GG", _s(sog=5, shots=12, corners=5, xg=1.5),
                            _s(sog=1, shots=3, corners=1, xg=0.2),
                            gol_casa=1, gol_ospite=0)
        self.assertFalse(ok)


class TestRobustezza(unittest.TestCase):

    def test_tipo_sconosciuto_non_blocca(self):
        """Un tipo fuori mappa non deve diventare un divieto silenzioso:
        si lascia decidere agli altri filtri."""
        ok, motivo = convergenza("ROBA_STRANA", _s(), _s())
        self.assertTrue(ok)
        self.assertIn("non valutabile", motivo)

    def test_statistiche_vuote_non_sollevano(self):
        ok, _ = convergenza("OVER_2.5", {}, {})
        self.assertFalse(ok)

    def test_xg_assente_usa_gli_altri(self):
        """Su meta' delle leghe l'xG non arriva: la regola deve reggersi
        su tiri, tiri in porta e corner."""
        ok, _ = convergenza("CHI_SEGNA_PROSSIMO_CASA",
                            _s(sog=5, shots=14, corners=6, xg=0),
                            _s(sog=1, shots=5, corners=1, xg=0))
        self.assertTrue(ok)


@richiede_bot_completo
class TestAggancioAlCiclo(unittest.TestCase):

    def setUp(self):
        with open("/opt/football-bot/bot.py", encoding="utf-8") as f:
            self.src = f.read()

    def test_le_soglie_irraggiungibili_sono_scese(self):
        """80 con un modello che dichiara 76 = finestra chiusa.

        Ancorato alla STRUTTURA, non al testo: cercare « 80,» nel sorgente
        beccava il minuto 80 delle finestre (70, 80) e (80, 90), non la
        soglia di confidenza. Qui si legge la colonna giusta.
        """
        import sys
        sys.argv = ["test"]
        import bot
        for nome, finestre in (("PT", bot.TIME_WINDOWS_PT),
                               ("FT", bot.TIME_WINDOWS_FT)):
            for start, end, tipi, conf, quota, label in finestre:
                self.assertLessEqual(
                    conf, 76,
                    msg=f"{nome} {label}: soglia {conf}% irraggiungibile, "
                        f"il modello dichiara 76")

    def test_la_convergenza_viene_calcolata_e_passata(self):
        self.assertIn("convergenza(", self.src)
        self.assertIn("dati_convergenti", self.src)


@richiede_bot_completo
class TestGateComportamento(unittest.TestCase):
    """Il COMPORTAMENTO del cancello, non la presenza delle parole nel
    sorgente: disattivando il ramo dei dati questi test devono cadere.
    (La prima versione ancorava solo le stringhe e una mutazione che
    spegneva la via alternativa non uccideva nessun test — il difetto
    classico di questo progetto.)"""

    def setUp(self):
        import sys
        sys.argv = ["test"]
        import bot
        self.bot = bot

    def test_conf_sotto_soglia_ma_dati_convergenti_passa(self):
        """Minuto 75: la finestra chiede 75%. Con 68% e i dati che
        convergono il segnale esce lo stesso."""
        ok, motivo, _ = self.bot.check_signal_allowed_by_window(
            75, "GG", 68, 2.50, dati_convergenti=True)
        self.assertTrue(ok)
        self.assertIn("dati", motivo)

    def test_conf_sotto_soglia_senza_dati_resta_bloccato(self):
        ok, _, _ = self.bot.check_signal_allowed_by_window(
            75, "GG", 68, 2.50, dati_convergenti=False)
        self.assertFalse(ok)

    def test_i_dati_non_salvano_una_confidenza_troppo_bassa(self):
        """La convergenza sostiene un segnale borderline, non lo inventa:
        sotto SOGLIA_CONF_DATI non si passa comunque."""
        ok, _, _ = self.bot.check_signal_allowed_by_window(
            75, "GG", 55, 2.50, dati_convergenti=True)
        self.assertFalse(ok)

    def test_la_soglia_bassa_e_un_parametro(self):
        self.assertGreaterEqual(self.bot.SOGLIA_CONF_DATI, 60)

    def test_i_dati_non_aprono_le_finestre_chiuse(self):
        """Nelle fasce «solo urgenti» la convergenza non deve creare una
        scorciatoia: quelle finestre sono una decisione di prodotto."""
        ok, _, _ = self.bot.check_signal_allowed_by_window(
            85, "GG", 90, 2.50, dati_convergenti=True)
        self.assertFalse(ok)

    def test_i_dati_non_aggirano_la_quota_minima(self):
        ok, _, _ = self.bot.check_signal_allowed_by_window(
            75, "GG", 90, 1.20, dati_convergenti=True)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main(verbosity=1)
