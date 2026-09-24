"""Le nazionali entrano nella selezione anche senza modello (22/09/2026).

RICHIESTA DELL'UTENTE: «in queste settimane ci saranno partite delle
nazionali UEFA, voglio che il bot le analizzi come se fossero campionati»
e «facciamo lavorare il criterio di analisi del bot lo stesso».

COSA BLOCCAVA. Le nazionali sono gia' in LEAGUE_LEVEL_1 (Nations League
id 5, WC Qualif 32, Euro 4, Mondiale 1) e il ciclo LIVE le analizza gia'.
Il blocco era solo sul PREMATCH: `candidate_del_giorno` tiene solo le
leghe con un modello, e `parametri_lega` ne chiede 400 partite di storico.
La Nations League ne ha 343, le qualificazioni 200, l'Europeo 46: sotto
soglia, quindi fuori dalla selezione a valore — nel periodo in cui sono
le UNICHE partite che si giocano (104 fixture fra il 24/09 e il 20/10).

COSA CAMBIA. Entrano come candidate senza modello: niente stima, quindi
niente edge e leggibilita' neutra, ma affidabilita' di lega e completezza
dei dati lavorano normalmente. Restano piu' in basso in classifica di una
partita con modello — ed e' giusto, perche' su di loro sappiamo meno — ma
quando sono le uniche in campo la selezione le pubblica invece di uscire
vuota.
"""
import unittest
# Vetrina: bot.py e i moduli di raccolta dati restano nel repository privato.
# Le classi che verificano l'aggancio al bot completo si saltano qui.
from _vetrina import richiede_bot_completo


import selezione_valore as sv


def _fix(fid, lid, ora="20:45", home="Italia", away="Francia"):
    return {"fixture": {"id": fid, "date": f"2026-09-25T{ora}:00+00:00",
                        "status": {"short": "NS"}},
            "teams": {"home": {"id": 1, "name": home},
                      "away": {"id": 2, "name": away}},
            "league": {"id": lid, "name": "UEFA Nations League",
                       "season": 2026}}


class TestCandidateSenzaModello(unittest.TestCase):

    def test_una_fixture_senza_modello_diventa_candidata(self):
        cand = sv.candidate_senza_modello([_fix(900, 5)], con_modello=set())
        self.assertEqual(len(cand), 1)
        self.assertEqual(cand[0]["fixture_id"], 900)
        self.assertTrue(cand[0]["senza_modello"])

    def test_chi_ha_gia_il_modello_non_viene_duplicato(self):
        cand = sv.candidate_senza_modello([_fix(900, 5)], con_modello={900})
        self.assertEqual(cand, [])

    def test_porta_i_campi_che_servono_alla_scheda(self):
        c = sv.candidate_senza_modello([_fix(900, 5)], con_modello=set())[0]
        for campo in ("league_id", "casa", "ospite", "ora", "data", "mercati"):
            self.assertIn(campo, c)
        self.assertEqual(c["mercati"], {})

    def test_niente_modello_niente_edge(self):
        """Senza stima non si puo' parlare di valore: la riga 💰 dira'
        «nessuno», non un numero inventato."""
        c = sv.candidate_senza_modello([_fix(900, 5)], con_modello=set())[0]
        self.assertIsNone(sv.edge_partita(c["mercati"],
                                          {("1X2", "1"): 2.50}))

    def test_fixture_malformata_non_solleva(self):
        self.assertEqual(sv.candidate_senza_modello([{"rotto": 1}],
                                                    con_modello=set()), [])


class TestPunteggio(unittest.TestCase):

    def test_senza_modello_vale_meno_di_con_modello(self):
        """A parita' di tutto il resto, una partita su cui il modello non
        sa dire niente deve stare SOTTO: il pavimento dell'edge la
        penalizza. Non e' una punizione, e' che ne sappiamo meno."""
        con = sv.score_partita(edge=0.05, affidabilita=0.5,
                               leggibilita=0.5, completezza=0.8)
        senza = sv.score_partita(edge=None, affidabilita=0.5,
                                 leggibilita=0.5, completezza=0.8)
        self.assertGreater(con, senza)

    def test_ma_resta_selezionabile(self):
        """Il punteggio deve restare un numero utilizzabile: se fosse
        negativo o None la partita sparirebbe anche quando e' l'unica."""
        s = sv.score_partita(edge=None, affidabilita=0.5,
                             leggibilita=0.5, completezza=0.8)
        self.assertIsInstance(s, float)
        self.assertGreater(s, 0)


@richiede_bot_completo
class TestAggancio(unittest.TestCase):

    def test_il_giro_del_giorno_le_include(self):
        with open("/opt/football-bot/selezione_valore.py",
                  encoding="utf-8") as f:
            src = f.read()
        self.assertIn("candidate_senza_modello(", src)

    def test_le_nazionali_sono_in_livello_1(self):
        import sys
        sys.argv = ["test"]
        import bot
        for lid in (5, 32, 4, 1):
            self.assertIn(lid, bot.LEAGUE_LEVEL_1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
