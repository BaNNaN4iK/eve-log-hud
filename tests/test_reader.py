# -*- coding: utf-8 -*-
"""Инкрементальное чтение: дописывание, неполная строка, усечение, заголовки, старые файлы."""
import os
import time
import unittest

from helpers import TempDirs, dmg_out, elw, header, make_cfg, mine, read_jsonl


class TestIncremental(unittest.TestCase):
    def setUp(self):
        self.td = TempDirs()
        self.now = int(time.time())
        self.cfg = make_cfg(self.td.logs, session_gap_seconds=300)

    def tearDown(self):
        self.td.cleanup()

    def open_out(self, w):
        return w.open["P"]["out"] if "P" in w.open else None

    def test_append(self):
        n = self.now
        self.td.write("a_1.txt", header("P", n) + dmg_out(n - 10, 100))
        w = elw.Watcher(self.cfg, self.td.data)
        w.poll()
        self.assertEqual(self.open_out(w), 100)
        self.td.write("a_1.txt", dmg_out(n - 5, 50) + dmg_out(n - 4, 25))
        w.poll()
        self.assertEqual(self.open_out(w), 175)
        w.poll()      # без новых данных ничего не меняется
        self.assertEqual(self.open_out(w), 175)

    def test_incomplete_last_line(self):
        n = self.now
        full = dmg_out(n - 5, 777)
        self.td.write("a_1.txt", header("P", n) + dmg_out(n - 10, 1) + full[:25])
        w = elw.Watcher(self.cfg, self.td.data)
        w.poll()
        self.assertEqual(self.open_out(w), 1)
        size_before = w.files["a_1.txt"]["off"]
        self.td.write("a_1.txt", full[25:])
        w.poll()
        self.assertEqual(self.open_out(w), 778)
        self.assertGreater(w.files["a_1.txt"]["off"], size_before)

    def test_truncation_restarts_from_zero(self):
        n = self.now
        path = self.td.write("a_1.txt", header("P", n) + dmg_out(n - 100, 1000) + dmg_out(n - 90, 1000))
        w = elw.Watcher(self.cfg, self.td.data)
        w.poll()
        w.close_session("P")
        # файл пересоздан и стал короче
        with open(path, "wb") as f:
            f.write((header("P", n) + dmg_out(n - 3, 7)).encode("utf-8"))
        w.poll()
        self.assertEqual(self.open_out(w), 7)

    def test_incomplete_header_waits(self):
        n = self.now
        path = self.td.write("a_1.txt", "-" * 60 + "\r\n  Игровой журнал\r\n")
        w = elw.Watcher(self.cfg, self.td.data)
        w.poll()
        self.assertNotIn("a_1.txt", w.files)
        with open(path, "wb") as f:
            f.write((header("P", n) + mine(n - 2, 10)).encode("utf-8"))
        w.poll()
        self.assertEqual(w.open["P"]["ore_total"] if "ore_total" in w.open["P"] else sum(w.open["P"]["ore"].values()), 10)

    def test_login_screen_file_skipped(self):
        n = self.now
        self.td.write("20261009_143549.txt", header(None, n))
        w = elw.Watcher(self.cfg, self.td.data)
        w.poll()
        self.assertTrue(w.files["20261009_143549.txt"]["skip"])
        self.assertEqual(w.open, {})

    def test_english_listener(self):
        n = self.now
        self.td.write("a_1.txt", header("Eng Pilot", n, english=True) + dmg_out(n - 1, 5))
        w = elw.Watcher(self.cfg, self.td.data)
        w.poll()
        self.assertIn("Eng Pilot", w.open)

    def test_old_files_ignored_unless_known(self):
        n = self.now
        old_ts = n - 40 * 86400
        p = self.td.write("old_1.txt", header("P", old_ts) + dmg_out(old_ts, 100))
        os.utime(p, (old_ts, old_ts))
        w = elw.Watcher(self.cfg, self.td.data)
        w.poll()
        self.assertNotIn("old_1.txt", w.files)
        self.assertEqual(read_jsonl(os.path.join(self.td.data, "sessions.jsonl")), [])
        # уже известный файл читается, даже если старый по mtime
        p2 = self.td.write("known_1.txt", header("P", n) + dmg_out(n - 2, 3))
        w.poll()
        os.utime(p2, (old_ts, old_ts))
        self.td.write("known_1.txt", dmg_out(n - 1, 4))
        os.utime(p2, (old_ts, old_ts))
        w.poll()
        self.assertEqual(self.open_out(w), 7)

    def test_events_older_than_import_window_ignored(self):
        n = self.now
        self.td.write("a_1.txt", header("P", n) + dmg_out(n - 40 * 86400, 100) + dmg_out(n - 1, 5))
        w = elw.Watcher(self.cfg, self.td.data)
        w.poll()
        self.assertEqual(self.open_out(w), 5)

    def test_state_resume_without_rereading(self):
        n = self.now
        self.td.write("a_1.txt", header("P", n) + dmg_out(n - 10, 100))
        w = elw.Watcher(self.cfg, self.td.data)
        w.poll()
        w.save_state(force=True)
        w2 = elw.Watcher(self.cfg, self.td.data)
        w2.poll()
        self.assertEqual(w2.open["P"]["out"], 100)       # не удвоилось
        self.td.write("a_1.txt", dmg_out(n - 5, 1))
        w2.poll()
        self.assertEqual(w2.open["P"]["out"], 101)

    def test_crlf_and_cyrillic_bytes(self):
        n = self.now
        # Строка с кириллицей разрезана посреди многобайтного символа
        full = mine(n - 1, 42, "Omber")
        b = (header("P", n) + full).encode("utf-8")
        cut = b.index("ед.".encode("utf-8")) + 1
        p = os.path.join(self.td.logs, "a_1.txt")
        with open(p, "wb") as f:
            f.write(b[:cut])
        w = elw.Watcher(self.cfg, self.td.data)
        w.poll()
        self.assertEqual(w.open, {})
        with open(p, "ab") as f:
            f.write(b[cut:])
        w.poll()
        self.assertEqual(w.open["P"]["ore"], {"Omber": 42})


if __name__ == "__main__":
    unittest.main()
