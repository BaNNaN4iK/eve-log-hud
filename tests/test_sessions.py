# -*- coding: utf-8 -*-
"""Сессии: разбиение по паузе, короткие сессии, суммы, DPS, защита от дублей, получатели итогов."""
import os
import time
import unittest

from helpers import TempDirs, bounty, dmg_in, dmg_out, elw, header, line, make_cfg, mine, read_csv, read_jsonl


def run_watcher(td, cfg, **kw):
    w = elw.Watcher(cfg, td.data, **kw)
    w.poll()
    return w


class TestSplitting(unittest.TestCase):
    def setUp(self):
        self.td = TempDirs()
        self.base = int(time.time()) - 3 * 3600
        self.cfg = make_cfg(self.td.logs, session_gap_seconds=300, min_session_seconds=20)

    def tearDown(self):
        self.td.cleanup()

    def test_split_by_gap_and_short_sessions(self):
        b = self.base
        t = header("Pilot", b)
        # сессия 1: бой 0..120 c
        for i in range(0, 121, 10):
            t += dmg_out(b + i, 100)
        t += dmg_in(b + 60, 40)
        # пауза 301 с -> новая сессия: добыча 421..481
        t += mine(b + 421, 500) + mine(b + 481, 300, "Omber")
        # пауза 600 с -> короткая сессия из одного баунти (0 с)
        t += bounty(b + 1081, 12345)
        # служебные строки не продлевают и не начинают сессию
        t += line(b + 1200, "notify", "Корабль останавливается")
        self.td.write("20261008_172152_1.txt", t)
        w = run_watcher(self.td, self.cfg)
        recs = read_jsonl(os.path.join(self.td.data, "sessions.jsonl"))
        self.assertEqual(len(recs), 3)
        r1, r2, r3 = recs
        self.assertEqual((r1["t0"], r1["t1"], r1["out"], r1["in"], r1["hits_out"]), (b, b + 120, 1300, 40, 13))
        self.assertTrue(r1["significant"])
        self.assertEqual((r2["ore"], r2["ore_total"], r2["cycles"]), ({"Veldspar": 500, "Omber": 300}, 800, 2))
        self.assertEqual((r3["bounty"], r3["dur"], r3["significant"]), (12345.0, 0, False))
        # короткая сессия всё равно в CSV
        rows = read_csv(os.path.join(self.td.data, "history.csv"))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[2]["значимая"], "нет")
        self.assertEqual(w.open, {})

    def test_gap_exactly_equal_keeps_session(self):
        b = self.base
        t = header("Pilot", b) + dmg_out(b, 10) + dmg_out(b + 300, 10)
        self.td.write("a_1.txt", t)
        run_watcher(self.td, self.cfg)
        recs = read_jsonl(os.path.join(self.td.data, "sessions.jsonl"))
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["out"], 20)

    def test_session_spans_files_of_same_character(self):
        b = self.base
        self.td.write("20261008_100000_1.txt", header("Pilot", b) + dmg_out(b, 10) + dmg_out(b + 50, 10))
        self.td.write("20261008_100200_1.txt", header("Pilot", b + 100) + dmg_out(b + 120, 10))
        run_watcher(self.td, self.cfg)
        recs = read_jsonl(os.path.join(self.td.data, "sessions.jsonl"))
        self.assertEqual(len(recs), 1)
        self.assertEqual((recs[0]["out"], recs[0]["t1"]), (30, b + 120))

    def test_characters_separate_and_filter(self):
        b = self.base
        self.td.write("x_1.txt", header("Alpha", b) + dmg_out(b, 10))
        self.td.write("x_2.txt", header("Beta", b) + dmg_out(b, 20))
        run_watcher(self.td, self.cfg)
        recs = read_jsonl(os.path.join(self.td.data, "sessions.jsonl"))
        self.assertEqual(sorted((r["who"], r["out"]) for r in recs), [("Alpha", 10), ("Beta", 20)])
        td2 = TempDirs()
        try:
            td2.write("x_1.txt", header("Alpha", b) + dmg_out(b, 10))
            td2.write("x_2.txt", header("Beta", b) + dmg_out(b, 20))
            run_watcher(td2, make_cfg(td2.logs, characters=["beta"]))
            recs = read_jsonl(os.path.join(td2.data, "sessions.jsonl"))
            self.assertEqual([r["who"] for r in recs], ["Beta"])
        finally:
            td2.cleanup()

    def test_sums_csv_equal_jsonl(self):
        b = int(time.time()) - 3 * 86400   # все события в прошлом, сессии закроются
        t = header("Pilot", b)
        import random
        rnd = random.Random(7)
        ts = b
        for i in range(400):
            ts += rnd.choice([1, 2, 5, 30, 400])   # иногда пауза > gap -> новая сессия
            k = rnd.random()
            if k < 0.5:
                t += dmg_out(ts, rnd.randint(0, 900), weapon=rnd.choice(["Gun A", "Gun B"]))
            elif k < 0.7:
                t += dmg_in(ts, rnd.randint(0, 300))
            elif k < 0.9:
                t += mine(ts, rnd.randint(1, 900), rnd.choice(["Veldspar", "Omber"]))
            else:
                t += bounty(ts, rnd.randint(1000, 90000))
        self.td.write("r_1.txt", t)
        run_watcher(self.td, self.cfg)
        recs = read_jsonl(os.path.join(self.td.data, "sessions.jsonl"))
        rows = read_csv(os.path.join(self.td.data, "history.csv"))
        self.assertGreater(len(recs), 3)
        self.assertEqual(len(recs), len(rows))
        self.assertEqual([r["id"] for r in recs], [r["id"] for r in rows])
        for key, col in (("out", "нанесено"), ("in", "получено"), ("ore_total", "руда, ед.")):
            self.assertEqual(sum(r[key] for r in recs), sum(int(x[col]) for x in rows), key)
        self.assertAlmostEqual(sum(r["bounty"] for r in recs),
                               sum(float(x["баунти, ISK"].replace(",", ".")) for x in rows), places=2)
        # и сумма по сессиям совпадает с суммой по строкам лога
        total_out = sum(elw.parse_line(l).data["amount"] for l in t.splitlines()
                        if elw.parse_line(l) and elw.parse_line(l).kind == "dmg" and elw.parse_line(l).data["dir"] == "out")
        self.assertEqual(sum(r["out"] for r in recs), total_out)
        # сумма урона по оружию = урон сессии
        for r in recs:
            self.assertEqual(sum(w["dmg"] for w in r["weapons"].values()), r["out"])


class TestDps(unittest.TestCase):
    def test_peak_window(self):
        sec = {0: 100, 10: 100, 29: 100, 30: 100, 100: 50}
        # окна [1..30] = 300, [0..29] = 300
        self.assertAlmostEqual(elw.peak_window(sec), 300 / 30)
        self.assertEqual(elw.peak_window({}), 0)

    def test_avg_dps_and_weapon_dps(self):
        s = elw.new_session("P", 1000)
        for i, (dt, w) in enumerate([(0, "A"), (10, "A"), (20, "B"), (40, "A")]):
            ev = elw.Event(1000 + dt, "dmg", {"dir": "out", "amount": 100, "refl": 0, "quality": "Попал",
                                             "target": "T", "ticker": "", "ship": "", "weapon": w}, {})
            elw.session_add(s, ev, "Jita")
        rec = elw.session_finalize(s, 20)
        self.assertAlmostEqual(rec["avg_dps"], 400 / 40)
        self.assertAlmostEqual(rec["weapons"]["A"]["dps"], 300 / 40)
        self.assertAlmostEqual(rec["weapons"]["B"]["dps"], 100 / 1)   # один выстрел: интервал не меньше 1 с
        self.assertAlmostEqual(rec["peak_dps"], 300 / 30)
        self.assertEqual(rec["systems"]["Jita"]["out"], 400)
        self.assertEqual(rec["series"]["out"], [[0, 100], [1, 100], [2, 100], [4, 100]])

    def test_reflected_not_counted(self):
        s = elw.new_session("P", 0)
        elw.session_add(s, elw.Event(0, "dmg", {"dir": "out", "amount": 195, "refl": 195, "quality": "Попал",
                                                "target": "Sotyo", "ticker": "", "ship": "Sotiyo", "weapon": "M"}, {}), None)
        elw.session_add(s, elw.Event(1, "dmg", {"dir": "out", "amount": 200, "refl": 50, "quality": "Попал",
                                                "target": "Sotyo", "ticker": "", "ship": "Sotiyo", "weapon": "M"}, {}), None)
        rec = elw.session_finalize(s, 20)
        self.assertEqual((rec["out"], rec["refl"]), (150, 245))


class TestHistoryDedup(unittest.TestCase):
    def test_write_is_idempotent(self):
        td = TempDirs()
        try:
            h = elw.History(td.data)
            s = elw.new_session("P", 100)
            elw.session_add(s, elw.Event(100, "bounty", {"isk": 5.0}, {}), None)
            rec = elw.session_finalize(s, 20)
            self.assertTrue(h.write(rec))
            self.assertFalse(h.write(rec))
            h2 = elw.History(td.data)       # после перезапуска id читаются из файлов
            self.assertFalse(h2.write(rec))
            self.assertEqual(len(read_jsonl(h.jsonl)), 1)
            self.assertEqual(len(read_csv(h.csv)), 1)
            with open(h.csv, "rb") as f:
                self.assertTrue(f.read(3) == b"\xef\xbb\xbf")
        finally:
            td.cleanup()

    def test_partial_tail_repaired(self):
        td = TempDirs()
        try:
            h = elw.History(td.data)
            s = elw.new_session("P", 100)
            elw.session_add(s, elw.Event(100, "bounty", {"isk": 5.0}, {}), None)
            h.write(elw.session_finalize(s, 20))
            with open(h.jsonl, "a", encoding="utf-8") as f:
                f.write('{"id":"P|200","out":')      # обрыв записи при сбое
            h2 = elw.History(td.data)
            self.assertEqual(len(read_jsonl(h2.jsonl)), 1)
        finally:
            td.cleanup()


class TestNotifiers(unittest.TestCase):
    def test_called_once_for_new_significant_sessions_only_after_import(self):
        td = TempDirs()
        sent = []

        class Fake(elw.Notifier):
            name = "fake"

            def send(self, record):
                sent.append(record["id"])
        try:
            b = int(time.time()) - 7200
            td.write("a_1.txt", header("P", b) + dmg_out(b, 10) + dmg_out(b + 60, 10))
            cfg = make_cfg(td.logs)
            w = elw.Watcher(cfg, td.data, notifiers=[Fake({})])
            w.poll()                      # первичный импорт — без отправки
            self.assertEqual(sent, [])
            now = int(time.time())
            td.write("a_1.txt", dmg_out(now - 1000, 10) + dmg_out(now - 900, 10) + bounty(now - 800, 1))
            w.poll()
            self.assertEqual(len(sent), 1)
            w.poll()
            self.assertEqual(len(sent), 1)
            # короткая сессия (1 событие) — не отправляется
            td.write("a_1.txt", bounty(now - 400, 5))
            w.poll()
            self.assertEqual(len(sent), 1)
            # --backfill не отправляет
            w2 = elw.Watcher(cfg, td.data, backfill=True, notifiers=[Fake({})])
            w2.poll()
            self.assertEqual(len(sent), 1)
        finally:
            td.cleanup()

    def test_unknown_notifier_in_config_is_skipped(self):
        self.assertEqual(elw.build_notifiers({"notifiers": {"discord": {"webhook": "x"}}}), [])


if __name__ == "__main__":
    unittest.main()
