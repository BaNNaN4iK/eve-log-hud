# -*- coding: utf-8 -*-
"""
Устойчивость: настоящий процесс убивается посреди сессии (TerminateProcess / SIGKILL),
перезапускается — сессия не теряется и не записывается дважды.
"""
import json
import os
import socket
import subprocess
import sys
import time
import unittest

from helpers import ROOT, TempDirs, dmg_out, elw, header, read_csv, read_jsonl

SCRIPT = os.path.join(ROOT, "eve_log_watcher.py")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_for(cond, timeout=20.0, step=0.1):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return False


class TestCrashRecovery(unittest.TestCase):
    def setUp(self):
        self.td = TempDirs()
        cfg = dict(elw.DEFAULT_CONFIG, logs_dir=self.td.logs, session_gap_seconds=20, poll_seconds=1,
                   state_save_seconds=1, web_enabled=False, online_enabled=False, lock_port=free_port())
        with open(os.path.join(self.td.data, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        self.state = os.path.join(self.td.data, "state.json")
        self.jsonl = os.path.join(self.td.data, "sessions.jsonl")
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait(10)
        self.td.cleanup()

    def start(self):
        p = subprocess.Popen([sys.executable, SCRIPT, "--data-dir", self.td.data],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        return p

    def open_out(self):
        try:
            with open(self.state, encoding="utf-8") as f:
                st = json.load(f)
            return st["open"].get("P", {}).get("out")
        except (OSError, ValueError):
            return None

    def test_kill_mid_session_and_restart(self):
        now = int(time.time())
        self.td.write("s_1.txt", header("P", now) + dmg_out(now, 100) + dmg_out(now + 1, 200))
        p = self.start()
        self.assertTrue(wait_for(lambda: self.open_out() == 300), "state.json не сохранился с открытой сессией")
        # дописываем ещё, ждём, пока это попадёт в state, и убиваем жёстко
        self.td.write("s_1.txt", dmg_out(now + 2, 400))
        self.assertTrue(wait_for(lambda: self.open_out() == 700))
        self.td.write("s_1.txt", dmg_out(now + 3, 800))   # может не успеть попасть в state — должно дочитаться
        p.kill()
        p.wait(10)
        self.assertEqual(read_jsonl(self.jsonl), [])
        # перезапуск: ещё одно событие той же сессии, затем событие после паузы > gap
        # (оно закрывает первую сессию и открывает вторую)
        self.td.write("s_1.txt", dmg_out(now + 4, 1600) + dmg_out(now + 200, 1))
        p2 = self.start()
        self.assertTrue(wait_for(lambda: len(read_jsonl(self.jsonl)) == 1, timeout=30), "сессия не записалась")
        time.sleep(2.5)   # убедиться, что дубль не появится
        p2.kill()
        p2.wait(10)
        recs = read_jsonl(self.jsonl)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["out"], 100 + 200 + 400 + 800 + 1600)
        self.assertEqual(recs[0]["hits_out"], 5)
        self.assertEqual(len(read_csv(os.path.join(self.td.data, "history.csv"))), 1)

    def test_crash_between_history_write_and_state_save(self):
        """Сессия записана в историю, а state.json — ещё нет: после перезапуска дубля нет."""
        now = int(time.time()) - 100
        self.td.write("s_1.txt", header("P", now) + dmg_out(now, 10) + dmg_out(now + 5, 20))
        cfg = elw.load_config(self.td.data)
        w = elw.Watcher(cfg, self.td.data)
        w.scan()
        w.save_state(force=True)          # снимок: сессия открыта
        with open(self.state, "rb") as f:
            snapshot = f.read()
        w.close_idle()                    # запись в историю (+ state)
        with open(self.state, "wb") as f:  # «сбой»: state откатился к снимку
            f.write(snapshot)
        w2 = elw.Watcher(cfg, self.td.data)
        w2.poll()
        recs = read_jsonl(self.jsonl)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["out"], 30)
        self.assertEqual(len(read_csv(os.path.join(self.td.data, "history.csv"))), 1)

    def test_single_instance_and_stop(self):
        now = int(time.time())
        self.td.write("s_1.txt", header("P", now) + dmg_out(now, 1))
        p = self.start()
        self.assertTrue(wait_for(lambda: os.path.exists(os.path.join(self.td.data, "watcher.pid"))))
        self.assertTrue(wait_for(lambda: self.open_out() == 1))
        r = subprocess.run([sys.executable, SCRIPT, "--data-dir", self.td.data], capture_output=True, timeout=30)
        self.assertEqual(r.returncode, 1)
        r = subprocess.run([sys.executable, SCRIPT, "--data-dir", self.td.data, "--backfill"],
                           capture_output=True, timeout=30)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--stop", r.stdout.decode("utf-8", "replace"))
        r = subprocess.run([sys.executable, SCRIPT, "--data-dir", self.td.data, "--stop"], capture_output=True, timeout=60)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(p.wait(15), 0)   # мягкая остановка через stop.flag
        self.assertFalse(os.path.exists(os.path.join(self.td.data, "watcher.pid")))
        # открытая сессия сохранена в state и продолжится после запуска
        self.assertEqual(self.open_out(), 1)


if __name__ == "__main__":
    unittest.main()
