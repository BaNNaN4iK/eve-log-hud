# -*- coding: utf-8 -*-
"""Модули: поиск, включение и выключение, сбой модуля не роняет трекер, только разрешённые файлы страницы."""
import http.client
import json
import os
import shutil
import tempfile
import threading
import unittest

from helpers import MODULES, TempDirs, elw, make_cfg
import modkit
from test_crash import free_port


def make_module(root, mid, meta=None, files=None):
    d = os.path.join(root, mid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "module.json"), "w", encoding="utf-8") as f:
        json.dump(dict({"id": mid, "name": mid.title(), "version": "1.0.0"}, **(meta or {})), f)
    for name, text in (files or {}).items():
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(text)
    return d


GOOD = '''
def setup(ctx):
    ctx.get("/api/hello", lambda qs: {"ok": True, "hi": (qs.get("name") or ["мир"])[0]})
    ctx.post("/api/echo", lambda body, qs: (201, {"got": body}))
    ctx.get("/api/boom", lambda qs: 1 / 0)
    ctx.on_live(lambda s: s.update(tagged=True))
    ctx.status("hello_status", lambda: {"n": 1})
'''


class TestModules(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="elw_mods_")
        self.td = TempDirs()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        self.td.cleanup()

    def test_bundled_modules_are_valid(self):
        mods = {m.id: m for m in modkit.discover(MODULES)}
        self.assertEqual(sorted(mods), ["alliance_auth", "appraisal", "damage_types", "fleet", "overlay", "reprocess"])
        for m in mods.values():
            target = m.meta.get("entry") or m.meta.get("process")
            self.assertTrue(os.path.isfile(os.path.join(m.path, target)), m.id)
            for f in m.meta["web"]:
                self.assertTrue(os.path.isfile(os.path.join(m.path, f)), (m.id, f))
            self.assertTrue(m.meta.get("name") and m.meta.get("description") and m.meta.get("version"), m.id)

    def test_discover_rejects_bad_manifests(self):
        make_module(self.root, "good_one")
        make_module(self.root, "Bad-Name")                                    # недопустимое имя
        make_module(self.root, "mismatch", {"id": "other"})                   # id не совпадает с папкой
        make_module(self.root, "escape", {"entry": "../evil.py"})            # путь из папки модуля
        make_module(self.root, "webcheck", {"web": ["tab.js", "../x.js", "a.exe"]})
        os.makedirs(os.path.join(self.root, "no_manifest"))
        with open(os.path.join(self.root, "broken.txt"), "w") as f:
            f.write("x")
        found = {m.id: m for m in modkit.discover(self.root)}
        self.assertEqual(sorted(found), ["good_one", "webcheck"])
        self.assertEqual(found["webcheck"].meta["web"], ["tab.js"])
        self.assertEqual(modkit.discover(os.path.join(self.root, "nope")), [])

    def test_enable_disable_and_defaults(self):
        make_module(self.root, "on_mod")
        make_module(self.root, "off_mod", {"default": False})
        mods = modkit.discover(self.root)
        modkit.apply_settings(mods, {})
        self.assertEqual({m.id: m.enabled for m in mods}, {"on_mod": True, "off_mod": False})
        modkit.apply_settings(mods, {"modules": {"on_mod": False, "off_mod": True, "ghost": True}})
        self.assertEqual({m.id: m.enabled for m in mods}, {"on_mod": False, "off_mod": True})
        cfg_path = os.path.join(self.td.data, "config.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"web_port": 1}, f)
        modkit.set_enabled(cfg_path, "on_mod", False, elw.atomic_write_json)
        with open(cfg_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"web_port": 1, "modules": {"on_mod": False}})   # остальное не тронуто
        self.assertIsNone(modkit.find(self.root, "on_mod", {"modules": {"on_mod": False}}))
        self.assertIsNotNone(modkit.find(self.root, "on_mod"))

    def server(self, cfg):
        w = elw.Watcher(cfg, self.td.data)
        app = elw.App(cfg, self.td.data, w, None)
        stop = threading.Event()
        modkit.activate(elw, app, self.root, stop)
        srv = elw.make_server(app)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return app, w

    def req(self, port, path, method="GET", body=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        h = {"Host": f"localhost:{port}"}
        if method == "POST":
            h.update({"Origin": f"http://localhost:{port}", "X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json"})
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, raw.decode("utf-8", "replace")

    def test_routes_hooks_errors_and_files(self):
        make_module(self.root, "hello", {"entry": "hello.py", "web": ["tab.js"]}, {"hello.py": GOOD, "tab.js": "// вкладка", "secret.txt": "нет"})
        make_module(self.root, "crashy", {"entry": "crashy.py"}, {"crashy.py": "raise RuntimeError('сломан')"})
        make_module(self.root, "sleepy", {"entry": "sleepy.py", "web": ["tab.js"], "default": False},
                    {"sleepy.py": "def setup(ctx):\n    ctx.get('/api/sleepy', lambda qs: {})", "tab.js": "//"})
        port = free_port()
        app, w = self.server(make_cfg(self.td.logs, web_port=port, online_enabled=False))
        state = {m["id"]: m for m in self.req(port, "/api/modules")[1]["modules"]}
        self.assertEqual({k: (v["enabled"], v["loaded"], bool(v["error"])) for k, v in state.items()},
                         {"hello": (True, True, False), "crashy": (True, False, True), "sleepy": (False, False, False)})
        self.assertIn("сломан", state["crashy"]["error"])                       # сломанный модуль не уронил трекер
        self.assertEqual(self.req(port, "/api/hello?name=Pilot")[1], {"ok": True, "hi": "Pilot"})
        self.assertEqual(self.req(port, "/api/echo", "POST", {"a": 1}), (201, {"got": {"a": 1}}))
        code, body = self.req(port, "/api/boom")
        self.assertEqual((code, body["ok"]), (500, False))                      # ошибка обработчика — 500, не падение
        self.assertEqual(self.req(port, "/api/live")[0], 200)
        self.assertEqual(self.req(port, "/api/sleepy")[0], 404)                 # выключенный модуль не подключён
        self.assertEqual(self.req(port, "/modules/hello/tab.js")[0], 200)
        for path in ("/modules/hello/secret.txt", "/modules/hello/hello.py", "/modules/sleepy/tab.js", "/modules/hello/../hello/tab.js"):
            self.assertEqual(self.req(port, path)[0], 404, path)
        # живые данные: поле модуля и правка сессии
        self.assertEqual(w.live()["hello_status"], {"n": 1})
        # выключение через страницу
        with open(os.path.join(self.td.data, "config.json"), "w", encoding="utf-8") as f:
            json.dump({}, f)
        self.assertTrue(self.req(port, "/api/modules/set", "POST", {"id": "hello", "enabled": False})[1]["ok"])
        self.assertFalse(self.req(port, "/api/modules/set", "POST", {"id": "ghost", "enabled": False})[1]["ok"])
        self.assertFalse(self.req(port, "/api/modules/set", "POST", {"id": "hello"})[1]["ok"])
        with open(os.path.join(self.td.data, "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["modules"], {"hello": False})
        self.assertTrue(self.req(port, "/api/restart", "POST")[1]["ok"])
        self.assertTrue(os.path.exists(os.path.join(self.td.data, "stop.flag")))   # трекер остановится, приложение поднимет снова


if __name__ == "__main__":
    unittest.main()
