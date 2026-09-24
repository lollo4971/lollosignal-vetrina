"""Test dello script di autocontrollo dei dati live.

Verifica il PARSING e la LOGICA DEI CONTROLLI su input finti: lo script
vero legge journalctl e signals.db, qui si testano le funzioni pure.
"""
import unittest

from checkup_live import (
    BASELINE,
    format_telegram,
    Check,
    parse_log,
    run_checks,
    stima_costo_giornaliero,
)

LOG_OK = """
2026-08-14 20:01:00,000 INFO Skip 1525943 [Premier League] L3: fuori whitelist
2026-08-14 20:01:00,001 INFO Skip 1527719 [Vysshaya Liga] L3: fuori whitelist
2026-08-14 20:01:02,000 INFO Analisi 900001 Ajax vs PSV [Eredivisie] L2 | 22' 1-0
2026-08-14 20:01:02,100 INFO stats 900001: campi=28/30 xg=1.43/0.62 saves=2/1
2026-08-14 20:01:04,000 INFO cache_live: write=0 read=5747 input_dinamici=815
2026-08-14 20:01:06,000 INFO Analisi 900002 Roma vs Lazio [Serie A] L1 | 55' 0-0
2026-08-14 20:01:06,100 INFO stats 900002: campi=26/30 xg=0.9/1.1 saves=3/0
2026-08-14 20:01:08,000 INFO cache_live: write=0 read=5747 input_dinamici=790
2026-08-14 20:01:09,000 INFO Skip 900003 [Ligue 1]: nessuna statistica disponibile per la partita
2026-08-14 20:01:10,000 INFO Skip 900004 OVER_1.5: quota 1.4 sotto il minimo 1.75 per OVER_1.5
2026-08-14 20:01:11,000 INFO 900005 CHI_SEGNA_PROSSIMO_CASA: quota non verificata (quota_minima -> NULL)
"""

# Regressione: una L3 analizzata significa gate rotto.
LOG_GATE_ROTTO = LOG_OK + (
    "2026-08-14 21:00:00,000 INFO Analisi 900009 X vs Y [Paulista - U20] L3 | 12' 0-0\n"
)

# Regressione: xG a zero ovunque = il bug del nome campo e' tornato.
# Servono almeno 20 analisi: sotto quella soglia il controllo e' informativo,
# perche' il fornitore lascia expected_goals vuoto su intere competizioni e
# una manciata di partite non distingue una regressione dalla copertura.
LOG_XG_ZERO = "\n".join(
    [f"2026-08-14 20:01:02,000 INFO Analisi {900000+i} Ajax vs PSV [Eredivisie] L2 | 22' 1-0\n"
     f"2026-08-14 20:01:02,100 INFO stats {900000+i}: campi=20/30 xg=0/0 saves=2/1\n"
     f"2026-08-14 20:01:04,000 INFO cache_live: write=0 read=5747 input_dinamici=664"
     for i in range(25)])


class TestParseLog(unittest.TestCase):

    def setUp(self):
        self.p = parse_log(LOG_OK)

    def test_analisi_per_livello(self):
        self.assertEqual(self.p["analisi_per_livello"], {"L1": 1, "L2": 1})

    def test_nessuna_analisi_l3(self):
        self.assertNotIn("L3", self.p["analisi_per_livello"])

    def test_skip_whitelist_contati(self):
        self.assertEqual(self.p["skip_whitelist"], 2)

    def test_skip_senza_statistiche_contati(self):
        self.assertEqual(self.p["skip_no_stats"], 1)

    def test_chiamate_ai_e_token(self):
        self.assertEqual(self.p["chiamate_ai"], 2)
        self.assertAlmostEqual(self.p["input_dinamici_medi"], 802.5)

    def test_righe_stats_e_xg(self):
        self.assertEqual(self.p["stats_righe"], 2)
        self.assertEqual(self.p["stats_con_xg"], 2)

    def test_campi_medi_popolati(self):
        self.assertAlmostEqual(self.p["campi_medi"], 27.0)

    def test_skip_quota_sotto_soglia(self):
        self.assertEqual(self.p["skip_quota"], 1)

    def test_quota_non_verificata(self):
        self.assertEqual(self.p["quota_non_verificata"], 1)

    def test_log_vuoto_non_esplode(self):
        p = parse_log("")
        self.assertEqual(p["chiamate_ai"], 0)
        self.assertEqual(p["input_dinamici_medi"], 0)
        self.assertEqual(p["analisi_per_livello"], {})


class TestRunChecks(unittest.TestCase):

    def _esito(self, checks, nome):
        for c in checks:
            if c.nome == nome:
                return c
        self.fail(f"controllo '{nome}' assente")

    def test_tutto_ok_nessun_fallimento(self):
        checks = run_checks(parse_log(LOG_OK), db={})
        falliti = [c.nome for c in checks if not c.ok]
        self.assertEqual(falliti, [], f"non dovevano fallire: {falliti}")

    def test_gate_rotto_viene_rilevato(self):
        checks = run_checks(parse_log(LOG_GATE_ROTTO), db={})
        self.assertFalse(self._esito(checks, "gate_whitelist").ok)

    def test_xg_a_zero_viene_rilevato(self):
        checks = run_checks(parse_log(LOG_XG_ZERO), db={})
        self.assertFalse(self._esito(checks, "xg_presente").ok)

    def test_segnale_sotto_soglia_nel_db_fallisce(self):
        checks = run_checks(parse_log(LOG_OK),
                            db={"violazioni_quota": 3, "segnali": 5})
        self.assertFalse(self._esito(checks, "quote_rispettano_soglie").ok)

    def test_segnale_da_lega_fuori_whitelist_fallisce(self):
        checks = run_checks(parse_log(LOG_OK),
                            db={"leghe_fuori_whitelist": ["Paulista - U20"]})
        self.assertFalse(self._esito(checks, "segnali_solo_whitelist").ok)

    def test_zero_analisi_non_e_un_fallimento(self):
        """Fascia oraria senza partite in whitelist: niente da misurare.
        Con 0 analisi, xg_presente deve essere informativo, non FAIL."""
        checks = run_checks(parse_log("2026-08-14 03:00:00 INFO Skip 1 [X] L3: fuori whitelist"), db={})
        falliti = [c.nome for c in checks if not c.ok and c.atteso != "informativo"]
        self.assertEqual(falliti, [], f"non dovevano fallire: {falliti}")
        self.assertEqual(self._esito(checks, "xg_presente").atteso, "informativo")

    def test_ogni_check_ha_atteso_e_valore(self):
        for c in run_checks(parse_log(LOG_OK), db={}):
            self.assertIsInstance(c, Check)
            self.assertTrue(c.atteso, f"{c.nome} senza atteso")
            self.assertIsNotNone(c.valore, f"{c.nome} senza valore")


class TestStimaCosto(unittest.TestCase):

    def test_costo_scende_rispetto_alla_baseline(self):
        c = stima_costo_giornaliero(chiamate=205, input_dinamici=815)
        self.assertLess(c, BASELINE["costo_giorno"])

    def test_zero_chiamate_costo_zero(self):
        self.assertEqual(stima_costo_giornaliero(0, 0), 0.0)

    def test_baseline_riproduce_il_costo_live(self):
        """588 chiamate a 664 token = la baseline LIVE (solo Haiku).

        Non confrontabile con i ~$2,50/giorno di CLAUDE.md, che sono il
        totale e comprendono il batch prematch con Sonnet.
        """
        c = stima_costo_giornaliero(588, 664)
        self.assertAlmostEqual(c, BASELINE["costo_giorno"], delta=0.05)




class TestDaToSql(unittest.TestCase):
    """--da deve allineare la finestra del DB a quella dei log."""

    def test_ora_breve_diventa_timestamp_di_oggi(self):
        from checkup_live import _da_to_sql
        from datetime import datetime
        oggi = f"{datetime.now():%Y-%m-%d}"
        self.assertEqual(_da_to_sql("20:00"), f"{oggi} 20:00:00")
        self.assertEqual(_da_to_sql("14:21:30"), f"{oggi} 14:21:30")

    def test_timestamp_completo_invariato(self):
        from checkup_live import _da_to_sql
        self.assertEqual(_da_to_sql("2026-08-14 20:00:00"), "2026-08-14 20:00:00")


class TestFinestraTemporaleDB(unittest.TestCase):
    """Regressione: il DB salva i timestamp in ISO con la 'T'
    ('2026-08-14T09:57:11'), il confronto usava uno spazio. Essendo
    lessicografico e 'T' > ' ', un segnale del mattino risultava
    successivo a un --da del pomeriggio."""

    def setUp(self):
        import sqlite3, tempfile, os
        self.tmp = tempfile.mktemp(suffix=".db")
        c = sqlite3.connect(self.tmp)
        c.execute("CREATE TABLE signals (tipo TEXT, league TEXT, "
                  "quota_minima REAL, timestamp TEXT)")
        # Date relative a OGGI: con date fisse il test passava solo il giorno
        # in cui era stato scritto, perche' _da_to_sql risolve su datetime.now().
        from datetime import datetime as _dt
        oggi = f"{_dt.now():%Y-%m-%d}"
        c.executemany("INSERT INTO signals VALUES (?,?,?,?)", [
            ("GG", "Serie A", 1.70, f"{oggi}T09:57:11.537424"),   # mattina
            ("GG", "Serie A", 1.90, f"{oggi}T21:30:00.000000"),   # sera
        ])
        c.commit(); c.close()

    def tearDown(self):
        import os
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    def test_da_pomeridiano_esclude_il_segnale_del_mattino(self):
        from checkup_live import load_db_stats
        d = load_db_stats(self.tmp, ore=24, da="20:00")
        self.assertEqual(d["segnali"], 1, "il segnale delle 09:57 non deve rientrare")

    def test_da_mattutino_li_prende_entrambi(self):
        from checkup_live import load_db_stats
        d = load_db_stats(self.tmp, ore=24, da="08:00")
        self.assertEqual(d["segnali"], 2)


class TestFormatTelegram(unittest.TestCase):
    """Il messaggio serale: deve stare nei limiti di Telegram, mettere in
    evidenza i FAIL e non rompersi con periodi vuoti."""

    def test_riporta_i_fallimenti_con_il_valore_atteso(self):
        checks = run_checks(parse_log(LOG_XG_ZERO), db={})
        msg = format_telegram(checks, parse_log(LOG_XG_ZERO), {}, "20:00")
        self.assertIn("xg_presente", msg)
        self.assertIn("> 0", msg, "deve mostrare il valore atteso")

    def test_serata_pulita_lo_dice(self):
        msg = format_telegram(run_checks(parse_log(LOG_OK), db={}),
                              parse_log(LOG_OK), {}, "20:00")
        self.assertNotIn("FAIL", msg)

    def test_include_i_numeri_chiave(self):
        p = parse_log(LOG_OK)
        msg = format_telegram(run_checks(p, db={"segnali": 4}), p,
                              {"segnali": 4}, "20:00")
        for atteso in ("2", "L1", "L2", "whitelist"):
            self.assertIn(atteso, msg, f"manca '{atteso}' nel messaggio")

    def test_entro_il_limite_telegram(self):
        p = parse_log(LOG_OK)
        msg = format_telegram(run_checks(p, db={}), p, {}, "20:00")
        self.assertLess(len(msg), 4096)

    def test_periodo_senza_dati_non_esplode(self):
        p = parse_log("")
        msg = format_telegram(run_checks(p, db={}), p, {}, "20:00")
        self.assertTrue(msg.strip())


class TestRiepilogoSettimanale(unittest.TestCase):
    """Deve coprire gli ultimi 7 GIORNI, non gli ultimi 7 file: piu'
    esecuzioni nello stesso giorno accorcerebbero la settimana."""

    def setUp(self):
        import json, tempfile, os
        import checkup_live
        self.dir = tempfile.mkdtemp()
        self._orig = checkup_live.SNAP_DIR
        checkup_live.SNAP_DIR = self.dir
        # tre snapshot lo stesso giorno + due giorni distinti
        for nome, chiamate in [("2026-08-10_2330", 100), ("2026-08-11_2330", 200),
                               ("2026-08-12_1000", 5), ("2026-08-12_1500", 7),
                               ("2026-08-12_2330", 300)]:
            with open(os.path.join(self.dir, nome + ".json"), "w") as f:
                json.dump({"log": {"chiamate_ai": chiamate, "input_dinamici_medi": 800,
                                   "stats_righe": 1, "stats_con_xg": 1},
                           "db": {"segnali": 1}, "checks": []}, f)

    def tearDown(self):
        import shutil
        import checkup_live
        checkup_live.SNAP_DIR = self._orig
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_una_riga_per_giorno(self):
        from checkup_live import riepilogo_settimanale
        testo = riepilogo_settimanale()
        self.assertEqual(testo.count("2026-08-12"), 1,
                         "il giorno con tre esecuzioni deve comparire una volta sola")

    def test_tiene_lo_snapshot_piu_recente_del_giorno(self):
        from checkup_live import riepilogo_settimanale
        testo = riepilogo_settimanale()
        self.assertIn("300", testo, "deve usare l'ultimo snapshot del 12, non i primi")
        self.assertNotIn(" 5 ", testo)

    def test_tutti_i_giorni_presenti(self):
        from checkup_live import riepilogo_settimanale
        testo = riepilogo_settimanale()
        for g in ("2026-08-10", "2026-08-11", "2026-08-12"):
            self.assertIn(g, testo)


LOG_RATELIMIT = """
2026-08-16 16:00:00,000 WARNING rate-limit su fixtures/events (residuo al minuto: 247, nostre chiamate nell'ultimo minuto: 12) → ritento fra 2.0s [tentativo 1/2]
2026-08-16 16:00:02,000 INFO Analisi 900001 Ajax vs PSV [Eredivisie] L2 | 22' 1-0
2026-08-16 16:05:00,000 WARNING rate-limit su fixtures/events (residuo al minuto: 251, nostre chiamate nell'ultimo minuto: 9) → ritento fra 2.0s [tentativo 1/2]
2026-08-16 16:05:07,000 ERROR rate-limit su fixtures/events: esauriti i tentativi (residuo al minuto: 250, nostre chiamate: 9)
"""


class TestDiagnosticaRateLimit(unittest.TestCase):
    """Il 15/08 il fornitore ha rifiutato 37 volte con volumi bassissimi.
    Il report deve dire quante volte il ritentativo ha salvato la partita e
    quante richieste risultavano disponibili al momento del rifiuto: e' il
    dato che distingue un problema nostro da uno loro."""

    def setUp(self):
        self.p = parse_log(LOG_RATELIMIT)

    def test_conta_i_ritentativi(self):
        self.assertEqual(self.p["ratelimit_ritentati"], 2)

    def test_conta_le_partite_perse(self):
        self.assertEqual(self.p["ratelimit_persi"], 1)

    def test_recuperati_e_la_differenza(self):
        self.assertEqual(self.p["ratelimit_recuperati"], 1)

    def test_registra_il_residuo_medio(self):
        """Media di TUTTI i residui osservati: 247, 251 e 250 (anche la riga
        di rinuncia ne riporta uno) -> 249.33. Se il valore e' alto, il
        rifiuto non dipende dal nostro volume."""
        self.assertAlmostEqual(self.p["ratelimit_residuo_medio"], 748 / 3)

    def test_il_report_espone_la_diagnosi(self):
        checks = run_checks(self.p, db={})
        nomi = [c.nome for c in checks]
        self.assertIn("rate_limit_fornitore", nomi)

    def test_residuo_alto_indica_problema_del_fornitore(self):
        c = [x for x in run_checks(self.p, db={}) if x.nome == "rate_limit_fornitore"][0]
        self.assertIn("249", c.valore)

    def test_log_senza_ratelimit_non_rompe(self):
        p = parse_log(LOG_OK)
        self.assertEqual(p["ratelimit_ritentati"], 0)
        self.assertEqual(p["ratelimit_residuo_medio"], 0)




class TestSoglieAllineate(unittest.TestCase):
    """Le soglie del report devono venire da quota_filter, non da una copia.

    Il 15/08 le soglie sono state abbassate in quota_filter; la copia dentro
    checkup_live e' rimasta ai vecchi valori e il report del 17/08 ha
    segnalato 2 "segnali sotto soglia" su segnali regolari.
    """

    def test_coincidono_con_quota_filter(self):
        from checkup_live import soglia_minima
        from quota_filter import QUOTA_RANGES
        for tipo in ("OVER_0.5", "OVER_1.5", "OVER_2.5", "OVER_3.5", "GG"):
            self.assertEqual(soglia_minima(tipo), QUOTA_RANGES[tipo][0],
                             f"soglia divergente su {tipo}")

    def test_chi_segna_risolve_le_varianti(self):
        from checkup_live import soglia_minima
        from quota_filter import QUOTA_RANGES
        atteso = QUOTA_RANGES["CHI_SEGNA_PROSSIMO"][0]
        for t in ("CHI_SEGNA_PROSSIMO_CASA", "CHI_SEGNA_PROSSIMO_OSPITE"):
            self.assertEqual(soglia_minima(t), atteso)

    def test_i_segnali_del_17_08_non_sono_violazioni(self):
        """I tre casi reali che avevano fatto scattare il falso allarme."""
        from checkup_live import soglia_minima
        for tipo, quota in (("OVER_2.5", 1.50), ("OVER_3.5", 1.833),
                            ("OVER_1.5", 1.909)):
            self.assertGreaterEqual(quota, soglia_minima(tipo),
                                    f"{tipo} a {quota} non deve essere violazione")

    def test_tipo_sconosciuto(self):
        from checkup_live import soglia_minima
        self.assertIsNone(soglia_minima("PIPPO"))


class TestXgVolumeMinimo(unittest.TestCase):
    """Il 18/08 il report ha bocciato "xG 0/13" su tre preliminari di Champions.
    Non era una regressione: il fornitore espone expected_goals ma lo lascia
    vuoto su quelle competizioni. Serve un volume minimo per gridare al lupo."""

    def _log(self, n_analisi, con_xg):
        righe = []
        for i in range(n_analisi):
            xg = "1.2/0.8" if i < con_xg else "0/0"
            righe.append(f"2026-08-18 20:0{i%10}:00,000 INFO stats {900+i}: "
                         f"campi=24/30 xg={xg} saves=1/1")
        return "\n".join(righe)

    def _check(self, testo):
        for c in run_checks(parse_log(testo), db={}):
            if c.nome == "xg_presente":
                return c
        self.fail("controllo xg_presente assente")

    def test_poche_analisi_senza_xg_non_bocciano(self):
        c = self._check(self._log(13, 0))
        self.assertEqual(c.atteso, "informativo")
        self.assertTrue(c.ok)

    def test_molte_analisi_senza_xg_bocciano(self):
        """Con volume sufficiente, zero xG resta una regressione."""
        c = self._check(self._log(40, 0))
        self.assertFalse(c.ok)

    def test_molte_analisi_con_xg_passano(self):
        c = self._check(self._log(40, 37))
        self.assertTrue(c.ok)
        self.assertNotEqual(c.atteso, "informativo")

    def test_il_caso_reale_del_18_08(self):
        c = self._check(self._log(13, 0))
        self.assertIn("13", c.valore)
        self.assertTrue(c.ok, "0/13 non deve essere un fallimento")


# ─── Errori: di chi è la colpa ───────────────────────────────────────────────

# Righe ERROR realmente presenti nel journal, raccolte il 01/09/2026 sulla
# settimana 25-31/08. 58 righe in totale, tutte riconducibili a queste forme.
ERR_FORNITORE = (
    "2026-08-29 14:02:11,000 ERROR 🛑 API-Football errore su fixtures/events: "
    "{'bug': 'This is on our side, please report us this message', 'error': '5xEr'}\n"
    "2026-08-29 14:05:00,000 ERROR API error fixtures: HTTPSConnectionPool("
    "host='v3.football.api-sports.io', port=443): Read timed out.\n"
)
ERR_INFRASTRUTTURA = (
    "2026-08-29 14:10:00,000 ERROR Exception happened while polling for updates.\n"
    "2026-08-29 14:10:00,001 ERROR No error handlers are registered, logging exception.\n"
)
ERR_NOSTRO = (
    "2026-08-29 09:12:00,000 ERROR [SKIP-COHERENCE] Ararat vs Craiova | "
    "errori: [\"over25='NO' ma risultato 3-1\"] | payload: {}\n"
)


class TestColpaDegliErrori(unittest.TestCase):
    """Il controllo `errori_nei_log` pretendeva ZERO errori mentre il bot
    dipende da un fornitore esterno che risponde `{'bug': 'This is on our
    side'}`. Risultato: FAIL tutti i giorni, per sempre.

    Il costo non e' estetico. Il 29/08/2026 quel controllo ha segnalato 40
    errori: se fra quei 40 ce ne fosse stato uno nostro, sarebbe passato
    inosservato nel rumore. Un allarme che suona sempre insegna a ignorarlo.

    REGOLA: tutto cio' che non e' riconosciuto come fornitore o
    infrastruttura conta come NOSTRO. Un errore nuovo e sconosciuto deve far
    scattare l'allarme, non essere assorbito in silenzio.
    """

    def _p(self, testo):
        return parse_log(LOG_OK + testo)

    def _check(self, testo, nome):
        for c in run_checks(self._p(testo), db={}):
            if c.nome == nome:
                return c
        self.fail(f"controllo {nome} assente")

    # --- classificazione ---

    def test_gli_errori_del_fornitore_sono_suoi(self):
        p = self._p(ERR_FORNITORE)
        self.assertEqual(p["errori_fornitore"], 2)
        self.assertEqual(p["errori_nostri"], 0)

    def test_il_polling_telegram_e_infrastruttura(self):
        p = self._p(ERR_INFRASTRUTTURA)
        self.assertEqual(p["errori_infrastruttura"], 2)
        self.assertEqual(p["errori_nostri"], 0)

    def test_skip_coherence_e_NOSTRO(self):
        """Scatta dopo che tutti i tentativi sono falliti: quella partita
        resta senza pronostico. E' un fallimento vero."""
        p = self._p(ERR_NOSTRO)
        self.assertEqual(p["errori_nostri"], 1)

    def test_un_errore_SCONOSCIUTO_conta_come_nostro(self):
        """Il default sicuro: se non lo riconosco, e' colpa mia finche' non
        si dimostra il contrario. Altrimenti il prossimo bug si nasconde."""
        p = self._p("2026-08-29 12:00:00,000 ERROR Qualcosa di mai visto prima\n")
        self.assertEqual(p["errori_nostri"], 1)
        self.assertEqual(p["errori_fornitore"], 0)

    def test_il_totale_resta_la_somma(self):
        p = self._p(ERR_FORNITORE + ERR_INFRASTRUTTURA + ERR_NOSTRO)
        self.assertEqual(p["errori"], 5)
        self.assertEqual(
            p["errori_nostri"] + p["errori_fornitore"] + p["errori_infrastruttura"],
            p["errori"])

    # --- il controllo ---

    def test_solo_errori_del_fornitore_NON_e_un_fallimento(self):
        """E' il caso di quasi tutti i giorni: 57 righe su 58."""
        c = self._check(ERR_FORNITORE + ERR_INFRASTRUTTURA, "errori_bot")
        self.assertTrue(c.ok, "il rumore del fornitore fa ancora fallire il check")

    def test_un_errore_nostro_fa_fallire(self):
        c = self._check(ERR_FORNITORE * 20 + ERR_NOSTRO, "errori_bot")
        self.assertFalse(c.ok, "un errore nostro e' sepolto sotto quelli altrui")
        self.assertIn("1", c.valore)

    def test_nessun_errore_passa(self):
        c = self._check("", "errori_bot")
        self.assertTrue(c.ok)

    def test_gli_errori_altrui_restano_VISIBILI(self):
        """Non si nascondono: separarli non vuol dire ignorarli. Un picco di
        errori del fornitore va visto, semplicemente non e' colpa nostra."""
        c = self._check(ERR_FORNITORE + ERR_INFRASTRUTTURA, "errori_esterni")
        self.assertEqual(c.atteso, "informativo")
        self.assertIn("2", c.valore)

    def test_il_caso_reale_della_settimana(self):
        """58 righe ERROR fra il 25 e il 31/08: 57 non nostre, 1 nostra
        (uno SKIP-COHERENCE). Prima il check diceva solo «58 FAIL»."""
        finto = ERR_FORNITORE * 15 + ERR_INFRASTRUTTURA * 13 + ERR_NOSTRO
        p = self._p(finto)
        self.assertEqual(p["errori_nostri"], 1)
        self.assertEqual(p["errori"], 57)
        c = self._check(finto, "errori_bot")
        self.assertFalse(c.ok)
        self.assertIn("1", c.valore)


if __name__ == "__main__":
    unittest.main()
