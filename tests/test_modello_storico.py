# test_modello_storico.py
"""Test del modello statistico su dati storici.

I test usano dati sintetici con la risposta nota: e' l'unico modo di
verificare che la stima recuperi i parametri veri.
"""
import math
import random
import unittest

from modello_storico import peso_temporale, stima_parametri


def p(h, a, fh, fa, data="2024-09-01"):
    return {"home_id": h, "away_id": a, "ft_home": fh, "ft_away": fa,
            "ht_home": 0, "ht_away": 0, "data": data}


def _poisson_rvs(lam, rng):
    """Campiona da una Poisson(lam) con l'algoritmo di Knuth. Solo per
    generare dati sintetici nei test: niente numpy nemmeno qui."""
    limite = math.exp(-lam)
    k = 0
    prodotto = 1.0
    while True:
        k += 1
        prodotto *= rng.random()
        if prodotto <= limite:
            return k - 1


class TestPesoTemporale(unittest.TestCase):
    def test_partita_di_oggi_pesa_uno(self):
        self.assertAlmostEqual(peso_temporale("2026-08-17", "2026-08-17", 365), 1.0)

    def test_meta_vita(self):
        """Dopo una meta-vita il peso e' 0.5."""
        self.assertAlmostEqual(peso_temporale("2025-08-17", "2026-08-17", 365),
                               0.5, places=2)

    def test_piu_vecchia_pesa_meno(self):
        recente = peso_temporale("2026-01-01", "2026-08-17", 365)
        vecchia = peso_temporale("2022-01-01", "2026-08-17", 365)
        self.assertGreater(recente, vecchia)

    def test_data_illeggibile_non_esplode(self):
        self.assertEqual(peso_temporale("boh", "2026-08-17", 365), 0.0)


class TestStimaParametri(unittest.TestCase):
    def test_squadra_forte_ha_attacco_maggiore(self):
        # 10 segna tanto, 20 e 30 poco
        partite = ([p(10, 20, 4, 0)] * 10 + [p(10, 30, 3, 0)] * 10
                   + [p(20, 30, 1, 1)] * 10)
        r = stima_parametri(partite)
        self.assertGreater(r["attacco"][10], r["attacco"][20])

    def test_squadra_solida_ha_difesa_minore(self):
        """difesa e' un moltiplicatore dei gol subiti: piu' basso = meglio."""
        partite = ([p(10, 20, 0, 0)] * 10 + [p(30, 20, 0, 0)] * 10
                   + [p(10, 30, 3, 3)] * 10)
        r = stima_parametri(partite)
        self.assertLess(r["difesa"][20], r["difesa"][30])

    def test_fattore_campo_positivo(self):
        """Con zero gol fuori casa nel campione il rapporto grezzo esplode
        (decine di miliardi): home_adv deve restare in un range plausibile,
        non collassare a un valore che azzera la matrice dei punteggi
        (bug C1, exp(-6e10) = 0.0)."""
        partite = [p(10, 20, 2, 0), p(20, 10, 2, 0)] * 15
        r = stima_parametri(partite)
        self.assertTrue(1.0 < r["home_adv"] <= 2.0, f"home_adv fuori scala: {r['home_adv']}")

    def test_attacco_medio_normalizzato_a_uno(self):
        partite = [p(10, 20, 2, 1), p(20, 10, 1, 1), p(10, 30, 3, 0),
                   p(30, 20, 0, 2)] * 5
        r = stima_parametri(partite)
        att = list(r["attacco"].values())
        self.assertAlmostEqual(sum(att) / len(att), 1.0, places=2)

    def test_tutte_le_squadre_presenti(self):
        partite = [p(10, 20, 1, 0), p(30, 40, 2, 2)]
        r = stima_parametri(partite)
        self.assertEqual(set(r["attacco"]), {10, 20, 30, 40})

    def test_nessuna_partita(self):
        r = stima_parametri([])
        self.assertEqual(r["attacco"], {})
        self.assertEqual(r["media_gol"], 0)

    def test_parametri_finiti(self):
        """Nessun NaN o infinito, nemmeno con squadre che non segnano mai."""
        partite = [p(10, 20, 0, 0)] * 20
        r = stima_parametri(partite)
        for d in (r["attacco"], r["difesa"]):
            for v in d.values():
                self.assertTrue(0 <= v < 100, f"parametro fuori scala: {v}")

    def test_data_corrotta_non_azzera_il_modello(self):
        """Bug C2: 'riferimento' era un max su stringhe. Una data tipo
        'N/A' ordina dopo qualsiasi data valida in ASCII, diventa il
        riferimento, e peso_temporale fallisce su OGNI partita: il
        risultato era un modello vuoto anche con dati buoni in mezzo."""
        partite = ([p(10, 20, 4, 0, data="2024-01-01")] * 10
                   + [p(10, 30, 3, 0, data="2024-06-01")] * 10
                   + [p(20, 30, 1, 1, data="N/A")] * 5)
        r = stima_parametri(partite)
        self.assertEqual(set(r["attacco"]), {10, 20, 30})
        self.assertGreater(r["attacco"][10], r["attacco"][20])


class TestSaturi(unittest.TestCase):
    """`saturi` (usato dal guardrail di valida_modello.py per marcare le
    leghe con troppe poche presenze, tipico delle coppe) deve segnalare le
    squadre il cui parametro e' stato clippato sul tetto MINIMO/MASSIMO,
    senza toccare le squadre stimate su dati sufficienti."""

    def test_squadra_senza_dati_sufficienti_e_satura(self):
        """Girone equilibrato fra tre squadre, piu' una squadra X che gioca
        poche partite e non segna mai: la sua stima di attacco deve finire
        sul pavimento MINIMO ed essere segnalata in `saturi`."""
        girone = ([p(1, 2, 1, 1)] * 10 + [p(2, 3, 1, 1)] * 10
                  + [p(3, 1, 1, 1)] * 10)
        satura = [p(1, 99, 8, 0)] * 15   # 99 non segna mai, presenze scarse
        r = stima_parametri(girone + satura)
        self.assertIn(99, r["saturi"])

    def test_girone_equilibrato_nessuna_squadra_satura(self):
        partite = ([p(1, 2, 1, 1)] * 20 + [p(2, 3, 2, 1)] * 20
                   + [p(3, 1, 1, 2)] * 20 + [p(1, 3, 1, 1)] * 20
                   + [p(2, 1, 1, 1)] * 20 + [p(3, 2, 1, 1)] * 20)
        r = stima_parametri(partite)
        self.assertEqual(r["saturi"], set())

    def test_nessuna_partita_saturi_vuoto(self):
        self.assertEqual(stima_parametri([])["saturi"], set())


class TestRecuperoParametriVeri(unittest.TestCase):
    """I test ordinali sopra (assertGreater/assertLess) passerebbero anche
    con un semplice conteggio di gol: qui si generano partite da parametri
    NOTI con un seed fisso, e si verifica che la stima li recuperi entro
    una tolleranza ragionevole. E' la prova richiesta dal docstring del
    modulo (I4)."""

    def test_recupera_attacco_difesa_home_adv_media_gol(self):
        att_vero = {1: 1.7, 2: 1.4, 3: 1.2, 4: 1.0, 5: 0.9, 6: 0.7, 7: 0.6, 8: 0.5}
        home_adv_vero = 1.25
        media_gol_vero = 1.35
        # ATTENZIONE: home_adv e media_gol sono fissati UNA VOLTA sui dati
        # aggregati e non ristimati insieme ad attacco/difesa dentro il
        # ciclo iterativo (dubbio matematico segnalato nel report). Per
        # questo, al punto fisso, la media della difesa converge a
        # 2/(1+home_adv), non a 1.0: un dif_vero con media 1.0 non sarebbe
        # autoconsistente col resto del modello e il test fallirebbe per
        # costruzione, non per un bug del codice.
        media_dif_target = 2 / (1 + home_adv_vero)
        raw_dif = [0.6, 1.4, 1.0, 1.25, 0.9, 1.05, 0.75, 1.15]
        scala = media_dif_target / (sum(raw_dif) / len(raw_dif))
        dif_vero = {t: v * scala for t, v in zip(att_vero, raw_dif)}

        rng = random.Random(7)
        partite = []
        for h in att_vero:
            for a in att_vero:
                if h == a:
                    continue
                lh = att_vero[h] * dif_vero[a] * home_adv_vero * media_gol_vero
                la = att_vero[a] * dif_vero[h] * media_gol_vero
                for _ in range(150):
                    gh = _poisson_rvs(lh, rng)
                    ga = _poisson_rvs(la, rng)
                    partite.append({"home_id": h, "away_id": a,
                                     "ft_home": gh, "ft_away": ga,
                                     "ht_home": 0, "ht_away": 0,
                                     "data": "2025-01-01"})

        r = stima_parametri(partite)

        self.assertAlmostEqual(r["home_adv"], home_adv_vero, delta=0.03)
        self.assertAlmostEqual(r["media_gol"], media_gol_vero, delta=0.05)
        for t in att_vero:
            self.assertAlmostEqual(r["attacco"][t], att_vero[t], delta=0.08,
                                    msg=f"attacco squadra {t} fuori tolleranza")
            self.assertAlmostEqual(r["difesa"][t], dif_vero[t], delta=0.08,
                                    msg=f"difesa squadra {t} fuori tolleranza")


from modello_storico import (
    _tau, lambde, matrice_punteggi, prob_1x2, prob_gg, prob_over,
    prob_risultato, stima_rho,
)


class TestMatricePunteggi(unittest.TestCase):
    def test_somma_a_uno(self):
        m = matrice_punteggi(1.5, 1.2)
        self.assertAlmostEqual(sum(m.values()), 1.0, places=3)

    def test_punteggio_piu_probabile_coerente_coi_lambda(self):
        """Con 2.5 contro 0.4 il risultato modale deve vedere la casa avanti."""
        m = matrice_punteggi(2.5, 0.4)
        (h, a), _ = max(m.items(), key=lambda kv: kv[1])
        self.assertGreater(h, a)

    def test_tutte_probabilita_valide(self):
        for v in matrice_punteggi(1.3, 1.1, rho=-0.05).values():
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)

    def test_correzione_rho_alza_i_punteggi_bassi(self):
        """E' il motivo di esistere di Dixon-Coles: con rho negativo il
        Poisson puro sottostima 0-0 e 1-1 (qui la correzione li alza).
        NOTA: non vale per 1-0 e 0-1, che la correzione ABBASSA — vedi
        TestTau sotto per i quattro casi completi."""
        senza = matrice_punteggi(1.2, 1.1, rho=0.0)
        con = matrice_punteggi(1.2, 1.1, rho=-0.10)
        self.assertGreater(con[(0, 0)], senza[(0, 0)])
        self.assertGreater(con[(1, 1)], senza[(1, 1)])
        self.assertLess(con[(1, 0)], senza[(1, 0)])
        self.assertLess(con[(0, 1)], senza[(0, 1)])

    def test_rho_nullo_equivale_al_poisson(self):
        m = matrice_punteggi(1.4, 1.0, rho=0.0)
        atteso = (math.exp(-1.4) * 1.4) * (math.exp(-1.0) * 1.0)
        self.assertAlmostEqual(m[(1, 1)], atteso, places=4)


class TestTau(unittest.TestCase):
    """I4: valori esatti della correzione Dixon-Coles sui quattro
    punteggi che tocca, per non fidarsi solo di assertGreater/assertLess."""

    def test_valori_nei_quattro_casi_corretti(self):
        lam_h, lam_a, rho = 1.4, 1.1, -0.08
        self.assertAlmostEqual(_tau(0, 0, lam_h, lam_a, rho),
                                1 - lam_h * lam_a * rho)
        self.assertAlmostEqual(_tau(0, 1, lam_h, lam_a, rho), 1 + lam_h * rho)
        self.assertAlmostEqual(_tau(1, 0, lam_h, lam_a, rho), 1 + lam_a * rho)
        self.assertAlmostEqual(_tau(1, 1, lam_h, lam_a, rho), 1 - rho)

    def test_altri_punteggi_non_toccati(self):
        for x, y in [(2, 0), (0, 2), (2, 2), (1, 2), (3, 1)]:
            self.assertEqual(_tau(x, y, 1.4, 1.1, -0.08), 1.0)

    def test_massa_conservata_oltre_i_punteggi_bassi(self):
        """Dixon-Coles e' costruito apposta perche' la correzione sui
        quattro punteggi bassi non alteri la massa totale (si veda la
        derivazione nel paper originale): quindi prob_over(m, 2.5), che
        dipende solo da punteggi con somma > 2, deve restare invariata
        al variare di rho (nessuno dei quattro punteggi corretti ha
        somma > 2)."""
        base = matrice_punteggi(1.6, 1.2, rho=0.0)
        corretta = matrice_punteggi(1.6, 1.2, rho=-0.08)
        self.assertAlmostEqual(prob_over(base, 2.5), prob_over(corretta, 2.5),
                                places=3)


class TestMercatiDerivati(unittest.TestCase):
    def setUp(self):
        self.m = matrice_punteggi(1.6, 1.1)

    def test_1x2_somma_a_uno(self):
        p = prob_1x2(self.m)
        self.assertAlmostEqual(p["1"] + p["X"] + p["2"], 1.0, places=3)

    def test_casa_favorita_con_lambda_maggiore(self):
        p = prob_1x2(self.m)
        self.assertGreater(p["1"], p["2"])

    def test_over_decresce_con_la_linea(self):
        self.assertGreater(prob_over(self.m, 0.5), prob_over(self.m, 2.5))
        self.assertGreater(prob_over(self.m, 2.5), prob_over(self.m, 4.5))

    def test_over_05_e_complemento_dello_zero_zero(self):
        self.assertAlmostEqual(prob_over(self.m, 0.5), 1 - self.m[(0, 0)], places=4)

    def test_gg_fra_zero_e_uno(self):
        g = prob_gg(self.m)
        self.assertTrue(0 < g < 1)

    def test_prob_risultato_esatto(self):
        self.assertAlmostEqual(prob_risultato(self.m, 1, 1), self.m[(1, 1)])

    def test_risultato_fuori_matrice_vale_zero(self):
        self.assertEqual(prob_risultato(self.m, 99, 99), 0.0)


class TestLambde(unittest.TestCase):
    def test_usa_attacco_difesa_e_fattore_campo(self):
        par = {"attacco": {1: 1.5, 2: 0.8}, "difesa": {1: 0.9, 2: 1.2},
               "home_adv": 1.3, "media_gol": 1.4}
        lh, la = lambde(par, 1, 2)
        self.assertAlmostEqual(lh, 1.5 * 1.2 * 1.3 * 1.4, places=6)
        self.assertAlmostEqual(la, 0.8 * 0.9 * 1.4, places=6)

    def test_squadra_sconosciuta_usa_la_media(self):
        """Le neopromosse non hanno storico: fallback sulla media di lega."""
        par = {"attacco": {1: 1.5}, "difesa": {1: 0.9},
               "home_adv": 1.2, "media_gol": 1.4}
        lh, la = lambde(par, 1, 999)
        self.assertGreater(lh, 0)
        self.assertGreater(la, 0)

    def test_fallback_usa_la_media_dei_valori_stimati_non_uno(self):
        """Bug I1: solo l'attacco e' normalizzato a media 1 dentro
        stima_parametri, la difesa no (la sua media di equilibrio e'
        circa 2/(1+home_adv), non 1.0). Le medie qui sotto sono
        deliberatamente diverse da 1.0 su entrambi i dizionari: se il
        fallback fosse ancora hardcoded a 1.0 (il vecchio bug) questo
        test fallisce."""
        par = {"attacco": {1: 1.8, 2: 1.0}, "difesa": {1: 0.4, 2: 0.8},
               "home_adv": 1.2, "media_gol": 1.4}
        att_medio = (1.8 + 1.0) / 2   # 1.4
        dif_medio = (0.4 + 0.8) / 2   # 0.6
        lh, la = lambde(par, 1, 999)
        self.assertAlmostEqual(lh, 1.8 * dif_medio * 1.2 * 1.4, places=6)
        self.assertAlmostEqual(la, att_medio * 0.4 * 1.4, places=6)


class TestStimaRho(unittest.TestCase):
    def test_rho_in_intervallo_plausibile(self):
        partite = [p(10, 20, 0, 0)] * 8 + [p(10, 20, 1, 1)] * 6 + \
                  [p(20, 10, 2, 1)] * 6
        par = stima_parametri(partite)
        r = stima_rho(partite, par)
        self.assertTrue(-0.3 <= r <= 0.2, f"rho fuori scala: {r}")


from modello_storico import (
    matrice_da_minuto, matrice_primo_tempo, quota_gol_primo_tempo,
)


class TestPrimoTempo(unittest.TestCase):
    def test_quota_pt_su_dati_noti(self):
        """4 gol nel primo tempo su 10 totali -> 0.4"""
        partite = [{"ht_home": 2, "ht_away": 2, "ft_home": 5, "ft_away": 5,
                    "home_id": 1, "away_id": 2, "data": "2024-01-01"}]
        self.assertAlmostEqual(quota_gol_primo_tempo(partite), 0.4)

    def test_ignora_partite_senza_parziale(self):
        partite = [{"ht_home": None, "ht_away": None, "ft_home": 3, "ft_away": 0,
                    "home_id": 1, "away_id": 2, "data": "2024-01-01"},
                   {"ht_home": 1, "ht_away": 0, "ft_home": 2, "ft_away": 0,
                    "home_id": 1, "away_id": 2, "data": "2024-01-01"}]
        self.assertAlmostEqual(quota_gol_primo_tempo(partite), 0.5)

    def test_nessun_dato_usa_default(self):
        """Senza parziali si usa 0.45, valore consolidato nel calcio."""
        self.assertAlmostEqual(quota_gol_primo_tempo([]), 0.45)

    def test_matrice_pt_ha_meno_gol_della_intera_partita(self):
        pt = matrice_primo_tempo(1.6, 1.2, 0.45)
        ft = matrice_punteggi(1.6, 1.2)
        atteso_pt = sum((x + y) * v for (x, y), v in pt.items())
        atteso_ft = sum((x + y) * v for (x, y), v in ft.items())
        self.assertLess(atteso_pt, atteso_ft)

    def test_over_05_primo_tempo_plausibile(self):
        """Con 2.8 gol attesi a partita, un gol entro il 45' sta fra 60% e 85%."""
        pt = matrice_primo_tempo(1.6, 1.2, 0.45)
        self.assertTrue(0.60 < prob_over(pt, 0.5) < 0.85)


class TestEvoluzione(unittest.TestCase):
    def test_al_minuto_zero_coincide_con_la_partita_intera(self):
        a = matrice_da_minuto(1.5, 1.1, 0, 0, 0)
        b = matrice_punteggi(1.5, 1.1)
        self.assertAlmostEqual(a[(1, 1)], b[(1, 1)], places=4)

    def test_il_punteggio_attuale_e_il_pavimento(self):
        """A 2-1 al 70' il finale non puo' avere meno di 2 gol per la casa."""
        m = matrice_da_minuto(1.5, 1.1, 70, 2, 1)
        self.assertEqual(sum(v for (x, y), v in m.items() if x < 2 or y < 1), 0.0)

    def test_meno_tempo_meno_gol_attesi(self):
        presto = matrice_da_minuto(1.5, 1.1, 10, 0, 0)
        tardi = matrice_da_minuto(1.5, 1.1, 80, 0, 0)
        self.assertGreater(tardi[(0, 0)], presto[(0, 0)])

    def test_a_fine_partita_il_risultato_e_certo(self):
        m = matrice_da_minuto(1.5, 1.1, 90, 2, 1)
        self.assertAlmostEqual(m[(2, 1)], 1.0, places=2)

    def test_somma_a_uno(self):
        m = matrice_da_minuto(1.4, 1.4, 60, 1, 1)
        self.assertAlmostEqual(sum(m.values()), 1.0, places=3)

    def test_ribaltone_al_75_e_raro(self):
        """Coerente con la misura del 17/08: zero ribaltoni su 11 casi
        dopo il 75'. Il modello deve dare una probabilita' bassa."""
        m = matrice_da_minuto(1.5, 1.2, 75, 0, 1)
        vince_casa = sum(v for (x, y), v in m.items() if x > y)
        self.assertLess(vince_casa, 0.15)

    def test_quota_pt_ricompone_i_gol_attesi_della_partita_intera(self):
        """Bug I2: con ritmo uniforme (quota_pt=None) i gol residui nella
        ripresa sono sottostimati, perche' quota_gol_primo_tempo misurata
        sui dati veri e' ~0.44, non 0.5. Passando quota_pt esplicito,
        i gol attesi nel PT (da matrice_primo_tempo) piu' quelli attesi
        dal 45' in poi (da matrice_da_minuto con lo stesso quota_pt)
        devono ricomporre i gol attesi dell'intera partita."""
        lam_h, lam_a, quota_pt = 1.6, 1.2, 0.44
        pt = matrice_primo_tempo(lam_h, lam_a, quota_pt)
        atteso_pt = sum((x + y) * v for (x, y), v in pt.items())
        m45 = matrice_da_minuto(lam_h, lam_a, 45, 0, 0, quota_pt=quota_pt)
        atteso_residuo = sum((x + y) * v for (x, y), v in m45.items())
        self.assertAlmostEqual(atteso_pt + atteso_residuo, lam_h + lam_a, places=3)

    def test_quota_pt_alza_i_gol_attesi_nella_ripresa(self):
        """Con quota_pt<0.5 il secondo tempo ha piu' ritmo di quanto
        assuma il modello uniforme: Over 2.5 dal 60' sull'1-1 deve essere
        maggiore con la correzione che senza."""
        senza = prob_over(matrice_da_minuto(1.6, 1.2, 60, 1, 1), 2.5)
        con = prob_over(matrice_da_minuto(1.6, 1.2, 60, 1, 1, quota_pt=0.4437), 2.5)
        self.assertGreater(con, senza)


if __name__ == "__main__":
    unittest.main()
