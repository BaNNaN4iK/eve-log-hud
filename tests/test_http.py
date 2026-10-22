# -*- coding: utf-8 -*-
"""HTTP: все эндпоинты, 403 на чужой Host и чужой Origin, 404, 405, CSV с BOM."""
import http.client
import json
import os
import threading
import time
import unittest

from helpers import module, TempDirs, bounty, dmg_out, elw, header, make_cfg, mine
from test_crash import free_port


class TestHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = TempDirs()
        n = int(time.time())
        cls.td.write("a_1.txt", header("P", n) + dmg_out(n - 3000, 100) + mine(n - 2990, 50) + bounty(n - 2980, 1000)
                     + dmg_out(n - 5, 7))
        cls.port = free_port()
        cls.cfg = make_cfg(cls.td.logs, web_port=cls.port, online_enabled=False)
        cls.w = elw.Watcher(cls.cfg, cls.td.data)
        cls.w.poll()
        cls.app = elw.App(cls.cfg, cls.td.data, cls.w, None)
        cls.srv = elw.make_server(cls.app)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.td.cleanup()

    def req(self, path, method="GET", host=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"localhost:{self.port}"}
        h.update(headers or {})
        c.request(method, path, headers=h)
        r = c.getresponse()
        body = r.read()
        c.close()
        return r, body

    def test_dashboard(self):
        r, body = self.req("/")
        self.assertEqual(r.status, 200)
        self.assertIn("text/html", r.getheader("Content-Type"))
        self.assertEqual(r.getheader("Cache-Control"), "no-store")
        self.assertIn(b"EVE Log Watcher", body)
        self.assertIn("default-src 'none'", r.getheader("Content-Security-Policy"))

    def test_both_allowed_hosts(self):
        self.assertEqual(self.req("/api/live", host=f"127.0.0.1:{self.port}")[0].status, 200)
        self.assertEqual(self.req("/api/live", host=f"LOCALHOST:{self.port}")[0].status, 200)

    def test_live(self):
        r, body = self.req("/api/live")
        j = json.loads(body)
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("Cache-Control"), "no-store")
        for k in ("sessions", "now", "logs_dir", "progress", "history_count", "unparsed_total"):
            self.assertIn(k, j)
        self.assertEqual(len(j["sessions"]), 1)
        live = j["sessions"][0]
        # у идущей сессии те же поля, что у завершённой
        hist = json.loads(self.req("/api/history")[1])["sessions"][0]
        self.assertTrue(set(hist) <= set(live))

    def test_history_and_session(self):
        j = json.loads(self.req("/api/history")[1])
        self.assertEqual(j["count"], 1)
        rec = j["sessions"][0]
        self.assertNotIn("series", rec)          # облегчённая запись
        self.assertEqual((rec["out"], rec["ore_total"], rec["bounty"]), (100, 50, 1000.0))
        r, body = self.req("/api/session?id=" + __import__("urllib.parse").parse.quote(rec["id"]))
        full = json.loads(body)
        self.assertEqual(r.status, 200)
        self.assertIn("series", full)
        self.assertEqual(self.req("/api/session?id=nope")[0].status, 404)
        # since
        j = json.loads(self.req("/api/history?since=%d" % (int(time.time()) + 10))[1])
        self.assertEqual(j["count"], 0)

    def test_meta_and_unparsed(self):
        j = json.loads(self.req("/api/meta")[1])
        self.assertFalse(j["online_enabled"])
        self.assertIn("aliases", j)
        j = json.loads(self.req("/api/unparsed")[1])
        self.assertEqual(j["total"], 0)

    def test_csv(self):
        r, body = self.req("/history.csv")
        self.assertEqual(r.status, 200)
        self.assertTrue(body.startswith(b"\xef\xbb\xbf"))
        self.assertIn("attachment", r.getheader("Content-Disposition"))
        self.assertIn("text/csv", r.getheader("Content-Type"))
        self.assertIn("персонаж".encode("utf-8"), body)

    def test_foreign_host_403(self):
        for host in ("evil.example", f"evil.example:{self.port}", "localhost", f"localhost:{self.port + 1}"):
            r, _ = self.req("/api/live", host=host)
            self.assertEqual(r.status, 403, host)
        self.assertEqual(self.req("/", host="attacker.test")[0].status, 403)

    def test_unknown_404(self):
        for p in ("/nope", "/api/nope", "/../eve_log_watcher.py", "/config.json", "/state.json", "/icons/1.png"):
            self.assertEqual(self.req(p)[0].status, 404, p)

    def test_methods(self):
        self.assertEqual(self.req("/api/live", method="PUT")[0].status, 405)
        self.assertEqual(self.req("/api/live", method="DELETE")[0].status, 405)
        self.assertEqual(self.req("/api/live", method="HEAD")[0].status, 200)

    def test_post_requires_origin(self):
        # без Origin / с чужим Origin / без X-Requested-With — 403 (защита от CSRF с чужих сайтов)
        self.assertEqual(self.req("/api/prices/refresh", "POST")[0].status, 403)
        self.assertEqual(self.req("/api/prices/refresh", "POST", headers={
            "Origin": "http://evil.example", "X-Requested-With": "XMLHttpRequest"})[0].status, 403)
        self.assertEqual(self.req("/api/prices/refresh", "POST", headers={
            "Origin": f"http://localhost:{self.port}"})[0].status, 403)
        r, body = self.req("/api/prices/refresh", "POST", headers={
            "Origin": f"http://localhost:{self.port}", "X-Requested-With": "XMLHttpRequest"})
        self.assertEqual(r.status, 409)          # онлайн выключен в этом тесте
        self.assertIn("online_enabled", json.loads(body)["message"])
        self.assertEqual(self.req("/api/prices/refresh", "POST", host="evil.example")[0].status, 403)

    def test_damage_profile_for_overlay(self):
        dmg = module("damage_types")
        old = dmg._PROFILES
        dmg._PROFILES = {"guristas despoiler": [0.0, 0.43, 0.57, 0.0], "scourge heavy missile": [0, 0, 1, 0],
                         "hobgoblin ii": [0, 1, 0, 0]}
        try:
            npc = {"ship": "", "ticker": "", "weapons": {"(не указано)": 500}}
            self.assertEqual(dmg.damage_profile("Guristas Despoiler", npc), [0.0, 0.43, 0.57, 0.0])
            self.assertIsNone(dmg.damage_profile("Unknown Rat", npc))
            # игрок с именем как у NPC — по имени не определяем; ракеты и дроны известны, пушки — нет
            player = {"ship": "Drake", "ticker": "ABC", "weapons": {"Scourge Heavy Missile": 600, "Hobgoblin II": 200, "250mm Railgun II": 200}}
            self.assertEqual(dmg.damage_profile("Guristas Despoiler", player), [0.0, 0.2, 0.6, 0.0])
            self.assertIsNone(dmg.damage_profile("X", {"ship": "Rifter", "ticker": "A", "weapons": {"200mm AutoCannon II": 90}}))
            self.assertIsNone(dmg.damage_profile("X", {"ship": "", "ticker": "", "weapons": {}}))
            dmg._PROFILES = {}
            self.assertIsNone(dmg.damage_profile("Guristas Despoiler", npc))                 # файла нет — типов нет
        finally:
            dmg._PROFILES = old
        real = dmg.damage_profiles()                                                          # файл в комплекте
        self.assertEqual(real.get("hobgoblin ii"), [0.0, 1.0, 0.0, 0.0])
        self.assertGreater(len(real), 1000)

    @unittest.skipUnless(os.name == "nt", "защищённые папки (EFS, WinError 17) бывают только в Windows")
    def test_replace_file_survives_protected_folders(self):
        import os
        import tempfile
        from unittest import mock
        eve_appraisal, eve_fleet = module("appraisal"), module("fleet")
        d = tempfile.mkdtemp()
        p = os.path.join(d, "x.json")
        real = os.replace

        def protected(src, dst):                          # как в папке под корпоративным шифрованием
            if os.path.exists(dst):
                raise OSError(18, "Системе не удается переместить файл на другой диск", None, 17)
            return real(src, dst)
        try:
            for mod, write in ((elw, lambda v: elw.atomic_write_json(p, v)), (eve_fleet, lambda v: eve_fleet._write(p, v))):
                with mock.patch.object(os, "replace", protected):
                    write({"n": 1})
                    write({"n": 2})                       # поверх существующего — обходной путь
                with open(p, encoding="utf-8") as f:
                    self.assertEqual(json.load(f), {"n": 2}, mod.__name__)
                self.assertFalse(os.path.exists(p + ".tmp"))
                os.remove(p)
            with mock.patch.object(os, "replace", side_effect=OSError(13, "нет доступа", None, 5)):
                with self.assertRaises(OSError):          # другие ошибки не прячем
                    eve_appraisal.replace_file(p + ".tmp", p)
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_overwolf_app_has_page_access_sites_do_not(self):
        ow = "overwolf-extension://" + "a" * 32
        for path in ("/api/live", "/api/history", "/api/meta", "/history.csv"):
            r, _ = self.req(path, headers={"Origin": ow})
            self.assertEqual((r.status, r.getheader("Access-Control-Allow-Origin")), (200, ow), path)
        self.assertIsNone(self.req("/api/live")[0].getheader("Access-Control-Allow-Origin"))
        for origin in ("http://evil.example", "overwolf-extension://evil.example", "null"):   # обычным сайтам — ничего
            self.assertIsNone(self.req("/api/live", headers={"Origin": origin})[0].getheader("Access-Control-Allow-Origin"), origin)
            self.assertEqual(self.req("/api/live", "OPTIONS", headers={"Origin": origin})[0].status, 405, origin)
            self.assertEqual(self.req("/api/prices/refresh", "POST", headers={
                "Origin": origin, "X-Requested-With": "XMLHttpRequest"})[0].status, 403, origin)
        r, _ = self.req("/api/prices/refresh", "OPTIONS", headers={"Origin": ow})
        self.assertEqual((r.status, r.getheader("Access-Control-Allow-Origin")), (204, ow))
        self.assertIn("X-Requested-With", r.getheader("Access-Control-Allow-Headers"))
        self.assertEqual(self.req("/api/live", "OPTIONS")[0].status, 405)
        self.assertEqual(self.req("/", "OPTIONS", headers={"Origin": ow})[0].status, 405)
        self.assertEqual(self.req("/api/prices/refresh", "POST", headers={"Origin": ow})[0].status, 403)   # без X-Requested-With
        self.assertEqual(self.req("/api/prices/refresh", "POST", headers={       # кнопка «обновить цены» из окна Overwolf
            "Origin": ow, "X-Requested-With": "XMLHttpRequest"})[0].status, 409)             # онлайн выключен в этом тесте


if __name__ == "__main__":
    unittest.main()
