# -*- coding: utf-8 -*-
"""Отправка итогов в Alliance Auth: адрес, очередь на диске, повторы, отклонения, live, CLI."""
import io
import json
import os
import threading
import time
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from helpers import TempDirs, dmg_out, elw, header, make_cfg, module, read_jsonl

aa = module("alliance_auth")

KEY = "fw_testkey"


class FakeAA(BaseHTTPRequestHandler):
    """Подставной AA: ключ, принимает сессии только персонажа «P», может «падать»."""
    store = {}
    fail = False
    fleet = None
    marks = []
    requests = []

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _auth(self):
        if self.headers.get("Authorization") != "Bearer " + KEY:
            self._json(401, {"ok": False, "error": "Неверный или отозванный ключ"})
            return False
        return True

    def do_GET(self):
        FakeAA.requests.append(("GET", self.path))
        if self.path == "/fleetwatch/api/v1/fleets/":
            if self._auth():
                self._json(200, {"ok": True, "fleets": [{"id": 7, "boss": "P", "is_active": False}]})
        elif self.path == "/fleetwatch/api/v1/fleet/?id=7":
            if self._auth():
                self._json(200, {"ok": True, "fleet": {"id": 7, "is_active": False, "count": 3}})
        elif self.path == "/fleetwatch/api/v1/fleet/":
            if FakeAA.fleet == "old":
                self._json(404, {})
            elif self._auth():
                self._json(200, {"ok": True, "fleet": FakeAA.fleet})
        elif self.path == "/fleetwatch/api/v1/ping/" and self._auth():
            self._json(200, {"ok": True, "user": "pilot", "characters": ["P"], "sessions": len(FakeAA.store)})
        elif self.path.startswith("/fleetwatch/api/v1/fleet/?id="):
            self._auth() and self._json(200, {"ok": True, "fleet": None})
        elif self.path != "/fleetwatch/api/v1/ping/":
            self._json(404, {"error": "нет"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeAA.requests.append(("POST", self.path, body))
        if self.path == "/fleetwatch/api/v1/fleet/mark/":
            if self._auth():
                FakeAA.marks.append(body)
                self._json(200, {"ok": body.get("mark") != "zzz", "message": "Сохранено."})
            return
        if self.path == "/fleetwatch/api/v1/fleet/track/":
            if self._auth():
                FakeAA.fleet = {"name": "", "count": 1}
                self._json(200, {"ok": True, "message": "Отслеживание включено (P).", "fleet": FakeAA.fleet})
            return
        if FakeAA.fail:
            self._json(503, {"error": "обслуживание"})
            return
        if not self._auth():
            return
        acc, rej = [], []
        for r in body["sessions"]:
            if r["who"] != "P":
                rej.append({"id": r["id"], "reason": f"персонаж {r['who']} не привязан к вашему аккаунту AA"})
                continue
            old = FakeAA.store.get(r["id"])
            if not (old and not old["live"] and r["live"]):
                FakeAA.store[r["id"]] = r
            acc.append(r["id"])
        self._json(200, {"ok": True, "accepted": acc, "rejected": rej})


class AATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeAA)
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        FakeAA.store, FakeAA.fail, FakeAA.requests, FakeAA.fleet = {}, False, [], None
        self.td = TempDirs()
        self.cfg = make_cfg(self.td.logs, aa_url=self.url, aa_key=KEY, session_gap_seconds=300)
        with open(os.path.join(self.td.data, "config.json"), "w", encoding="utf-8") as f:
            json.dump(self.cfg, f)

    def tearDown(self):
        self.td.cleanup()

    def watcher(self):
        w = elw.Watcher(self.cfg, self.td.data)
        w.uploader = aa.AAUploader(self.cfg, self.td.data)          # как в setup() модуля
        w.session_hooks.append(w.uploader.enqueue)
        return w

    def test_module_has_no_fleet_code(self):
        self.assertFalse(any("fleet/" in line for line in open(aa.__file__, encoding="utf-8") if "AA_API" not in line and "/sessions/" not in line))

    def test_url_rules(self):
        self.assertEqual(aa.check_aa_url("https://auth.example.com/"), "https://auth.example.com")
        self.assertEqual(aa.check_aa_url("http://localhost:8000"), "http://localhost:8000")
        for bad in ("http://auth.example.com", "ftp://x", "auth.example.com", "https://a.com/fleetwatch/"):
            with self.assertRaises(ValueError, msg=bad):
                aa.check_aa_url(bad)

    def test_closed_sessions_queued_and_sent(self):
        now = int(time.time())
        self.td.write("a_1.txt", header("P", now - 3000) + dmg_out(now - 3000, 100) + dmg_out(now - 2900, 50)
                      + dmg_out(now - 1000, 7))
        w = self.watcher()
        w.poll()
        self.assertEqual(len(w.uploader.queue), 2)              # обе завершённые сессии в очереди
        self.assertTrue(os.path.exists(os.path.join(self.td.data, "aa_outbox.json")))
        self.assertEqual(w.uploader.flush(), 2)
        self.assertEqual(w.uploader.queue, {})
        r = FakeAA.store[f"P|{now - 3000}"]
        self.assertEqual((r["out"], r["live"]), (150, False))
        self.assertIn("series", r)              # для графиков DPS в AA
        self.assertTrue(r["per_min"])
        # в журнал и ответы ключ не попадает
        with open(os.path.join(self.td.data, "watcher.log"), "a+", encoding="utf-8") as f:
            f.seek(0)
            self.assertNotIn(KEY, f.read())

    def test_outage_keeps_queue_across_restart(self):
        now = int(time.time())
        self.td.write("a_1.txt", header("P", now - 3000) + dmg_out(now - 3000, 100))
        w = self.watcher()
        w.poll()
        FakeAA.fail = True
        with self.assertRaises(aa.AAError):
            w.uploader.flush()
        self.assertEqual(len(w.uploader.queue), 1)
        # «перезапуск»: очередь читается с диска
        up2 = aa.AAUploader(self.cfg, self.td.data)
        self.assertEqual(len(up2.queue), 1)
        FakeAA.fail = False
        self.assertEqual(up2.flush(), 1)
        self.assertEqual(aa.AAUploader(self.cfg, self.td.data).queue, {})

    def test_rejected_removed_and_reported(self):
        up = aa.AAUploader(self.cfg, self.td.data)
        rec = {"id": "Other|1", "who": "Other", "t0": 1, "t1": 2, "out": 1}
        up.enqueue(rec)
        self.assertEqual(up.flush(), 0)
        self.assertEqual(up.queue, {})
        self.assertEqual(up.status["rejected"], 1)
        self.assertIn("не привязан", up.status["last_rejects"][0])

    def test_wrong_key(self):
        up = aa.AAUploader(dict(self.cfg, aa_key="fw_wrong"), self.td.data)
        with self.assertRaisesRegex(aa.AAError, "401"):
            up.ping()

    def test_not_configured_does_nothing(self):
        up = aa.AAUploader(dict(self.cfg, aa_url="", aa_key=""), self.td.data)
        up.enqueue({"id": "P|1", "who": "P"})
        self.assertEqual(up.queue, {})

    def test_live_sessions_sent_only_when_changed(self):
        now = int(time.time())
        self.td.write("a_1.txt", header("P", now) + dmg_out(now - 5, 10))
        w = self.watcher()
        w.poll()
        last = w.uploader.tick(w, time.time(), 0)
        live = [x for x in FakeAA.requests if x[0] == "POST"]
        self.assertEqual(len(live), 1)
        self.assertTrue(live[0][2]["sessions"][0]["live"])
        w.uploader.tick(w, last + 61, last)          # без новых событий — не отправляется
        self.assertEqual(len([x for x in FakeAA.requests if x[0] == "POST"]), 1)
        self.td.write("a_1.txt", dmg_out(now - 1, 20))
        w.poll()
        w.uploader.tick(w, last + 122, last + 61)
        self.assertEqual(len([x for x in FakeAA.requests if x[0] == "POST"]), 2)
        self.assertEqual(FakeAA.store[f"P|{now - 5}"]["out"], 30)

    def test_backfill_does_not_upload(self):
        now = int(time.time())
        self.td.write("a_1.txt", header("P", now - 3000) + dmg_out(now - 3000, 100))
        w = elw.Watcher(self.cfg, self.td.data, backfill=True)
        w.uploader = aa.AAUploader(self.cfg, self.td.data)
        w.session_hooks.append(w.uploader.enqueue)
        w.poll()
        self.assertEqual(w.uploader.queue, {})

    def test_setup_connects_module_to_tracker(self):
        from helpers import ctx
        w = elw.Watcher(self.cfg, self.td.data)
        app = elw.App(self.cfg, self.td.data, w, None)
        c = ctx(app, "alliance_auth")
        aa.setup(c)
        self.assertEqual(len(w.session_hooks), 1)
        self.assertEqual(w.live()["aa"]["host"], self.url.split("//")[1])           # состояние — в /api/live
        c.stop.set()

    def test_cli_connect_and_upload_history(self):
        now = int(time.time())
        self.td.write("a_1.txt", header("P", now - 7000) + dmg_out(now - 7000, 100) + dmg_out(now - 5000, 1))
        self.td.write("b_1.txt", header("Alt", now - 7000) + dmg_out(now - 7000, 5))
        with open(os.path.join(self.td.data, "config.json"), "w", encoding="utf-8") as f:
            json.dump(make_cfg(self.td.logs), f)          # пока без AA
        elw.Watcher(make_cfg(self.td.logs), self.td.data).poll()
        self.assertEqual(len(read_jsonl(os.path.join(self.td.data, "sessions.jsonl"))), 3)
        out = io.StringIO()
        with redirect_stdout(out):
            code = elw.main(["--data-dir", self.td.data, "--aa-connect", self.url, "fw_wrong"])
        self.assertEqual(code, 1)
        with redirect_stdout(out):
            code = elw.main(["--data-dir", self.td.data, "--aa-connect", self.url + "/", KEY])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("Alt", out.getvalue())                 # предупреждение: персонаж не в AA
        with open(os.path.join(self.td.data, "config.json"), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual((saved["aa_url"], saved["aa_key"]), (self.url, KEY))
        out = io.StringIO()
        with redirect_stdout(out):
            code = elw.main(["--data-dir", self.td.data, "--aa-upload-history"])
        self.assertEqual(code, 3, out.getvalue())           # есть отклонённые (Alt)
        self.assertIn("Принято: 2", out.getvalue())
        self.assertEqual(len(FakeAA.store), 2)
        with redirect_stdout(out):                           # повтор — без дублей
            elw.main(["--data-dir", self.td.data, "--aa-upload-history"])
        self.assertEqual(len(FakeAA.store), 2)
        with redirect_stdout(out):
            elw.main(["--data-dir", self.td.data, "--aa-disconnect"])
        with open(os.path.join(self.td.data, "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["aa_key"], "")


if __name__ == "__main__":
    unittest.main()
