# test_valida_modello.py
"""Test delle metriche di validazione."""
import math
import statistics
import unittest

from valida_modello import (
    SOGLIA_SATURAZIONE, brier, brier_multiclasse, calibrazione,
    confronto_accoppiato, e_coppa, frazione_satura, log_loss,
    presenze_per_squadra,
)


class TestMetriche(unittest.TestCase):
    def test_brier_previsione_perfetta(self):
        self.assertAlmostEqual(brier(1.0, True), 0.0)
        self.assertAlmostEqual(brier(0.0, False), 0.0)

    def test_brier_previsione_pessima(self):
        self.assertAlmostEqual(brier(0.0, True), 1.0)

    def test_brier_incertezza_massima(self):
        self.assertAlmostEqual(brier(0.5, True), 0.25)

    def test_log_loss_penalizza_la_sicurezza_sbagliata(self):
        self.assertGreater(log_loss(0.01, True), log_loss(0.4, True))

    def test_log_loss_non_esplode_su_zero(self):
        """Senza protezione sarebbe infinito e romperebbe la media."""
        v = log_loss(0.0, True)
        self.assertTrue(v < 100 and v > 0)


class TestBrierMulticlasse(unittest.TestCase):
    """Il Brier su un mercato a piu' esiti (1X2, risultato esatto) deve
    guardare l'intera distribuzione, non solo la cella dell'esito vero:
    altrimenti non e' una regola di scoring propria (conviene mentire)."""

    def test_coincide_con_la_somma_delle_differenze_al_quadrato(self):
        probs = {"1": 0.5, "X": 0.3, "2": 0.2}
        atteso = sum((v - (1.0 if k == "1" else 0.0)) ** 2 for k, v in probs.items())
        self.assertAlmostEqual(brier_multiclasse(probs, probs["1"]), atteso)

    def test_previsione_perfetta(self):
        probs = {"1": 1.0, "X": 0.0, "2": 0.0}
        self.assertAlmostEqual(brier_multiclasse(probs, probs["1"]), 0.0)

    def test_peggiora_se_si_spalma_probabilita_sulle_altre_celle(self):
        """A parita' di probabilita' sull'esito vero, spalmare il resto su
        piu' celle invece che su una sola deve dare un Brier piu' basso (piu'
        vicino a 0): e' la proprieta' che il vecchio calcolo (solo sulla
        cella vera) non catturava."""
        concentrata = {"1": 0.5, "X": 0.5, "2": 0.0}
        spalmata = {"1": 0.5, "X": 0.25, "2": 0.25}
        self.assertLess(brier_multiclasse(spalmata, 0.5), brier_multiclasse(concentrata, 0.5))


class TestConfrontoAccoppiato(unittest.TestCase):
    def test_serie_identiche_differenza_zero(self):
        r = confronto_accoppiato([0.1, 0.2, 0.3], [0.1, 0.2, 0.3])
        self.assertEqual(r["diff_media"], 0.0)
        self.assertEqual(r["t"], 0.0)

    def test_coerente_con_la_libreria_standard(self):
        """Media, errore standard e t ricalcolati a mano con `statistics`
        (libreria standard), indipendentemente dall'implementazione."""
        a = [1, 2, 3, 4, 5]
        b = [1, 1, 1, 1, 10]
        diffs = [x - y for x, y in zip(a, b)]
        media_attesa = statistics.mean(diffs)
        se_atteso = statistics.stdev(diffs) / math.sqrt(len(diffs))
        r = confronto_accoppiato(a, b)
        self.assertAlmostEqual(r["diff_media"], media_attesa)
        self.assertAlmostEqual(r["se"], se_atteso)
        self.assertAlmostEqual(r["t"], media_attesa / se_atteso)
        self.assertEqual(r["n"], 5)

    def test_campione_troppo_piccolo(self):
        r = confronto_accoppiato([0.5], [0.4])
        self.assertEqual(r["n"], 1)
        self.assertEqual(r["se"], 0.0)


class TestCalibrazione(unittest.TestCase):
    def test_modello_perfettamente_calibrato(self):
        """In ogni fascia la frequenza osservata deve avvicinarsi alla
        probabilita' media prevista."""
        coppie = [(0.1, i < 10) for i in range(100)] + \
                 [(0.9, i < 90) for i in range(100)]
        f = calibrazione(coppie, n_fasce=10)
        for fascia in f:
            if fascia["n"]:
                self.assertLess(abs(fascia["prevista"] - fascia["osservata"]), 0.05)

    def test_riporta_il_numero_di_casi(self):
        f = calibrazione([(0.5, True)] * 7, n_fasce=10)
        self.assertEqual(sum(x["n"] for x in f), 7)

    def test_lista_vuota(self):
        self.assertEqual(sum(x["n"] for x in calibrazione([], 10)), 0)

    def test_confini_delle_fasce(self):
        """Verifica l'INDICE della fascia in cui cade ciascuna probabilita',
        non solo prevista/osservata (che vengono dallo stesso bucket
        dell'indice e quindi non lo mettono alla prova): un errore off-by-one
        nel calcolo dell'indice, ad es. min(int(p*n)+1, n-1), passa
        inosservato se si guarda solo prevista/osservata ma sposta le
        probabilita' vicine ai confini nella fascia sbagliata."""
        casi = [(0.0, 0), (0.099, 0), (0.1, 1), (0.999, 9), (1.0, 9)]
        for prob, fascia_attesa in casi:
            f = calibrazione([(prob, True)], n_fasce=10)
            indici_popolati = [i for i, fascia in enumerate(f) if fascia["n"]]
            self.assertEqual(indici_popolati, [fascia_attesa],
                              f"prob={prob} attesa in fascia {fascia_attesa}")


def _partita(h, a):
    return {"home_id": h, "away_id": a}


class TestPresenzePerSquadra(unittest.TestCase):
    def test_conta_casa_e_trasferta(self):
        partite = [_partita(1, 2), _partita(2, 1), _partita(1, 3)]
        conteggio = presenze_per_squadra(partite)
        self.assertEqual(conteggio, {1: 3, 2: 2, 3: 1})

    def test_lista_vuota(self):
        self.assertEqual(presenze_per_squadra([]), {})


class TestECoppa(unittest.TestCase):
    def test_girone_non_e_coppa(self):
        """Un girone all'italiana: ogni squadra gioca tante partite (qui 20
        squadre, andata e ritorno = 38 presenze ciascuna, come una Serie A
        vera — 6 squadre darebbero solo 10 presenze, sotto la soglia)."""
        squadre = list(range(20))
        partite = []
        for h in squadre:
            for a in squadre:
                if h != a:
                    partite.append(_partita(h, a))
        self.assertFalse(e_coppa(partite))

    def test_eliminazione_diretta_e_coppa(self):
        """Tabellone a eliminazione diretta: 64 squadre al primo turno, 32
        al secondo, ... la mediana delle presenze crolla sotto la soglia."""
        partite = []
        squadre = list(range(64))
        turno = 1
        while len(squadre) > 1:
            vincenti = []
            for i in range(0, len(squadre), 2):
                h, a = squadre[i], squadre[i + 1]
                partite.append(_partita(h, a))
                vincenti.append(h)   # il "primo" vince sempre, non conta chi
            squadre = vincenti
            turno += 1
        self.assertTrue(e_coppa(partite))

    def test_nessuna_partita_non_e_coppa(self):
        self.assertFalse(e_coppa([]))


class TestFrazioneSatura(unittest.TestCase):
    def test_nessuna_squadra_satura(self):
        par = {"attacco": {1: 1.0, 2: 1.0}, "saturi": set()}
        self.assertEqual(frazione_satura(par), 0.0)

    def test_meta_squadre_sature(self):
        par = {"attacco": {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0}, "saturi": {1, 2}}
        self.assertAlmostEqual(frazione_satura(par), 0.5)

    def test_nessuna_squadra_totale(self):
        par = {"attacco": {}, "saturi": set()}
        self.assertEqual(frazione_satura(par), 0.0)

    def test_soglia_e_venti_percento(self):
        self.assertAlmostEqual(SOGLIA_SATURAZIONE, 0.20)


if __name__ == "__main__":
    unittest.main()
