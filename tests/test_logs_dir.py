# -*- coding: utf-8 -*-
"""Папка логов: поиск в Linux (Steam Proton, Wine, Lutris, Bottles), ручной ввод пути, страница «Настройки»."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from helpers import TempDirs, elw, make_cfg


def touch_log(folder, name="20261022_120000_123.txt", mtime=None):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write("------\n  Игровой журнал\n")
    if mtime:
        os.utime(path, (mtime, mtime))
    return path


def gamelogs(*parts):
    return os.path.join(*parts, "EVE", "logs", "Gamelogs")


class TestLinuxDetect(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="elw-home-")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_proton_wine_lutris_bottles(self):
        steam = os.path.join(self.home, ".local", "share", "Steam")
        extra = os.path.join(self.home, "SSD", "SteamLibrary")
        os.makedirs(os.path.join(steam, "steamapps"))
        with open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), "w", encoding="utf-8") as f:
            f.write('"libraryfolders"\n{\n "0" { "path" "%s" }\n "1" { "path" "%s" }\n}\n' % (steam, extra))
        proton_extra = gamelogs(extra, "steamapps", "compatdata", "8500", "pfx", "drive_c", "users", "steamuser", "Documents")
        lutris = gamelogs(self.home, "Games", "eve-online", "drive_c", "users", "pilot", "My Documents")
        bottles = gamelogs(self.home, ".local", "share", "bottles", "bottles", "EVE", "drive_c", "users", "pilot", "Documents")
        wine = gamelogs(self.home, ".wine", "drive_c", "users", "pilot", "Documents")
        for p in (proton_extra, lutris, bottles, wine):
            os.makedirs(p)
        cands = elw.wine_logs_candidates(self.home)
        for p in (proton_extra, lutris, bottles, wine):
            self.assertIn(os.path.realpath(p) if p == proton_extra else p, [os.path.realpath(c) if "compatdata" in c else c for c in cands])
        # стандартная библиотека Steam тоже в списке, даже если папки ещё нет
        self.assertTrue(any("compatdata" in c and c.startswith(os.path.realpath(steam)) for c in cands))

    def test_freshest_folder_wins(self):
        old = gamelogs(self.home, ".wine", "drive_c", "users", "pilot", "Documents")
        new = gamelogs(self.home, "Games", "eve", "drive_c", "users", "pilot", "Documents")
        touch_log(old, mtime=1_700_000_000)
        touch_log(new, mtime=1_800_000_000)
        with mock.patch.object(elw, "logs_candidates", return_value=[old, new, os.path.join(self.home, "nope")]):
            found = elw.found_logs_dirs()
            self.assertEqual([f["path"] for f in found], [new, old])
            self.assertEqual(found[0]["files"], 1)
            self.assertEqual(elw.detect_logs_dir(), new)
        with mock.patch.object(elw, "logs_candidates", return_value=[os.path.join(self.home, "nope")]):
            self.assertEqual(elw.detect_logs_dir(), os.path.join(self.home, "nope"))      # ничего нет — первый вариант

    def test_normalize(self):
        g = gamelogs(self.home, "Documents")
        os.makedirs(g)
        for typed in (g, os.path.join(self.home, "Documents"), os.path.join(self.home, "Documents", "EVE"),
                      os.path.join(self.home, "Documents", "EVE", "logs"), f'  "{g}"  '):
            self.assertEqual(elw.normalize_logs_path(typed), g, typed)
        self.assertEqual(elw.normalize_logs_path(""), "")
        other = os.path.join(self.home, "random")
        self.assertEqual(elw.normalize_logs_path(other), other)                        # несуществующий — как ввели
        with mock.patch.dict(os.environ, {"HOME": self.home, "USERPROFILE": self.home}):
            self.assertEqual(elw.normalize_logs_path("~/Documents"), g)


class TestLogsSettingsHttp(unittest.TestCase):
    def test_check_save_auto(self):
        import http.client
        import threading
        from test_crash import free_port
        td = TempDirs()
        try:
            port = free_port()
            cfg = make_cfg(td.logs, web_port=port)
            app = elw.App(cfg, td.data, elw.Watcher(cfg, td.data), None)
            srv = elw.make_server(app)
            threading.Thread(target=srv.serve_forever, daemon=True).start()

            def req(path, method="GET", body=None, origin=True):
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                h = {"Host": f"localhost:{port}"}
                if method == "POST" and origin:
                    h.update({"Origin": f"http://localhost:{port}", "X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json"})
                c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
                r = c.getresponse()
                raw = r.read()
                c.close()
                try:
                    return r.status, json.loads(raw)
                except ValueError:
                    return r.status, raw.decode("utf-8", "replace")

            st = req("/api/settings/logs")[1]
            self.assertEqual(st["current"]["path"], td.logs)
            other = gamelogs(td.root, "Documents")
            touch_log(other)
            touch_log(other, "20261022_130000_123.txt")
            r = req("/api/settings/logs", "POST", {"path": os.path.join(td.root, "Documents"), "save": False})[1]
            self.assertTrue(r["ok"])
            self.assertEqual((r["check"]["path"], r["check"]["files"]), (other, 2))
            self.assertNotIn("restart", r)
            self.assertFalse(req("/api/settings/logs", "POST", {"path": os.path.join(td.root, "nope"), "save": True})[1]["ok"])
            self.assertEqual(req("/api/settings/logs", "POST", {"path": other, "save": True}, origin=False)[0], 403)
            r = req("/api/settings/logs", "POST", {"path": other, "save": True})[1]
            self.assertTrue(r["ok"] and r["restart"])
            with open(os.path.join(td.data, "config.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["logs_dir"], other)
            self.assertEqual(elw.load_config(td.data)["logs_dir"], other)               # после перезапуска возьмётся она
            empty = os.path.join(td.root, "empty", "Gamelogs")
            os.makedirs(empty)
            r = req("/api/settings/logs", "POST", {"path": empty, "save": False})[1]
            self.assertIn("нет логов", r["warning"])
            r = req("/api/settings/logs", "POST", {"path": "", "save": True})[1]          # «Искать автоматически»
            self.assertTrue(r["ok"])
            with open(os.path.join(td.data, "config.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["logs_dir"], "")
            self.assertFalse(req("/api/settings/logs", "POST", {"path": 5})[1]["ok"])
            srv.shutdown()
            srv.server_close()
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
