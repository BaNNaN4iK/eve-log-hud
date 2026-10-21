# -*- coding: utf-8 -*-
"""Обновления с GitHub: сверка версий, проверка архива и контрольной суммы, установка модуля с откатом, адреса трекера."""
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile

from helpers import ROOT  # noqa: F401  (путь к ядру)
import updater  # noqa: E402

REL = "https://api.github.com/repos/me/hud/releases/latest"


def mod_zip(mid, version, files=None, extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{mid}/module.json", json.dumps({"id": mid, "name": mid.title(), "version": version, "entry": f"{mid}.py"}))
        for name, text in (files or {f"{mid}.py": "def setup(ctx):\n    pass\n"}).items():
            z.writestr(f"{mid}/{name}", text)
        for name, text in (extra or {}).items():
            z.writestr(name, text)
    return buf.getvalue()


class FakeModule:
    def __init__(self, mid, version):
        self.id, self.meta = mid, {"id": mid, "name": mid.title(), "version": version, "entry": "x.py"}

    def info(self):
        return {"kind": "tracker"}


class Remote:
    """Выпуск на «GitHub»: файлы по адресам."""

    def __init__(self, tag="v2.3.0", modules=None, app_version="2.3.0"):
        self.files, self.calls = {}, []
        assets, index = [], []
        for mid, ver, data in modules or []:
            name = f"{mid}-{ver}.zip"
            url = f"https://github.com/me/hud/releases/download/{tag}/{name}"
            self.files[url] = data
            assets.append({"name": name, "browser_download_url": url})
            index.append({"id": mid, "name": mid.title(), "version": ver, "file": name, "size": len(data),
                          "sha256": hashlib.sha256(data).hexdigest(), "min_app": ""})
        self.index = {"app_version": app_version, "modules": index}
        iurl = f"https://github.com/me/hud/releases/download/{tag}/modules-index.json"
        assets.append({"name": "modules-index.json", "browser_download_url": iurl})
        assets.append({"name": "EveLogHUD-2.3.0.zip", "browser_download_url": "https://github.com/me/hud/releases/download/v2.3.0/EveLogHUD-2.3.0.zip"})
        self.release = {"tag_name": tag, "html_url": "https://github.com/me/hud/releases/tag/" + tag, "assets": assets}
        self.iurl = iurl

    def __call__(self, url, accept):
        self.calls.append(url)
        if url == REL:
            return json.dumps(self.release).encode()
        if url == self.iurl:
            return json.dumps(self.index).encode()
        if url in self.files:
            return self.files[url]
        raise updater.UpdateError("404")


class TestVersions(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(updater.newer("1.10.0", "1.9.9"))
        self.assertTrue(updater.newer("v2.2", "2.1.9"))
        self.assertFalse(updater.newer("1.0.0", "1.0.0"))
        self.assertFalse(updater.newer("", "1.0"))

    def test_only_github_hosts(self):
        with self.assertRaises(updater.UpdateError):
            updater.http_get("https://evil.example.com/x.zip", "ua")
        with self.assertRaises(updater.UpdateError):
            updater.http_get("http://github.com/x.zip", "ua")              # только https


class TestUpdater(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="elw-upd-")
        os.makedirs(os.path.join(self.root, "fleet"))
        with open(os.path.join(self.root, "fleet", "module.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "fleet", "version": "1.0.0"}, f)
        with open(os.path.join(self.root, "fleet", "fleet.py"), "w", encoding="utf-8") as f:
            f.write("OLD = 1\n")
        self.local = [FakeModule("fleet", "1.0.0"), FakeModule("appraisal", "1.0.0")]

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, remote, repo="me/hud", app="2.2.0"):
        return updater.Updater(repo, app, self.root, lambda: self.local, fetch=remote,
                               state_path=os.path.join(self.root, "updates.json"))

    def test_check_and_install(self):
        remote = Remote(modules=[("fleet", "1.1.0", mod_zip("fleet", "1.1.0", {"fleet.py": "NEW = 1\n"})),
                                 ("appraisal", "1.0.0", mod_zip("appraisal", "1.0.0")),
                                 ("reprocess", "1.0.0", mod_zip("reprocess", "1.0.0"))])
        u = self.make(remote)
        st = u.check()
        self.assertEqual(st["error"], "")
        rows = {r["id"]: r for r in st["modules"]}
        self.assertTrue(rows["fleet"]["update"])
        self.assertFalse(rows["appraisal"]["update"])
        self.assertTrue(rows["reprocess"]["new"])
        self.assertEqual(st["updates"], 1)
        self.assertEqual((st["app"]["latest"], st["app"]["newer"]), ("2.3.0", True))
        self.assertTrue(st["app"]["download"].endswith("EveLogHUD-2.3.0.zip"))

        res = u.install("fleet")
        self.assertEqual((res["from"], res["to"]), ("1.0.0", "1.1.0"))
        with open(os.path.join(self.root, "fleet", "fleet.py"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "NEW = 1\n")
        backups = os.listdir(os.path.join(self.root, ".old"))
        self.assertTrue(backups[0].startswith("fleet-1.0.0-"))                 # старая версия отложена
        self.assertFalse([d for d in os.listdir(self.root) if d.startswith(".staging")])
        row = {r["id"]: r for r in u.status()["modules"]}["fleet"]
        self.assertEqual((row["pending"], row["update"]), ("1.1.0", False))    # до перезапуска не предлагать снова
        u.install("reprocess")                                                 # новый модуль
        self.assertTrue(os.path.isfile(os.path.join(self.root, "reprocess", "module.json")))

        u2 = self.make(remote)                                                 # после перезапуска — из сохранённой проверки
        self.assertEqual(u2.status()["app"]["latest"], "2.3.0")

    def test_rejects_bad_archives(self):
        good = mod_zip("fleet", "1.1.0")
        remote = Remote(modules=[("fleet", "1.1.0", good)])
        u = self.make(remote)
        u.check()
        url = [k for k in remote.files][0]
        for bad, word in ((good + b"x", "Размер"),
                          (mod_zip("fleet", "1.1.0", extra={"../evil.py": "x"}), "путь"),
                          (mod_zip("fleet", "1.1.0", extra={"other/x.py": "x"}), "путь"),
                          (mod_zip("fleet", "9.9.9"), "не совпадает")):
            remote.files[url] = bad
            if word != "Размер":                                               # подменённый архив с верной длиной
                remote.index["modules"][0].update(size=len(bad), sha256=hashlib.sha256(bad).hexdigest())
                u.check()
            with self.assertRaises(updater.UpdateError) as cm:
                u.install("fleet")
            self.assertIn(word, str(cm.exception))
        remote.files[url] = mod_zip("fleet", "1.1.0", {"fleet.py": "EVIL = 1\n"})   # сумма из индекса не совпала
        remote.index["modules"][0].update(size=len(remote.files[url]), sha256="0" * 64)
        u.check()
        with self.assertRaises(updater.UpdateError) as cm:
            u.install("fleet")
        self.assertIn("Контрольная сумма", str(cm.exception))
        with open(os.path.join(self.root, "fleet", "fleet.py"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "OLD = 1\n")                            # старая версия не тронута
        self.assertFalse(os.path.exists(os.path.join(self.root, "evil.py")))

    def test_needs_newer_app_and_errors(self):
        remote = Remote(modules=[("fleet", "2.0.0", mod_zip("fleet", "2.0.0"))])
        remote.index["modules"][0]["min_app"] = "3.0.0"
        u = self.make(remote)
        row = {r["id"]: r for r in u.check()["modules"]}["fleet"]
        self.assertEqual((row["update"], row["needs_app"]), (False, "3.0.0"))
        with self.assertRaises(updater.UpdateError):
            u.install("fleet")
        self.assertIn("репозиторий", self.make(remote, repo="").check()["error"])

        def down(url, accept):
            raise updater.UpdateError("Нет связи с GitHub: timeout")
        st = self.make(down).check()
        self.assertIn("Нет связи", st["error"])
        self.assertTrue(st["checked"])


class TestUpdatesHttp(unittest.TestCase):
    def test_endpoints(self):
        import http.client
        import threading
        from helpers import TempDirs, elw, make_cfg
        from test_crash import free_port
        td = TempDirs()
        root = tempfile.mkdtemp(prefix="elw-upd-http-")
        try:
            port = free_port()
            cfg = make_cfg(td.logs, web_port=port, online_enabled=False)
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

            self.assertFalse(req("/api/updates")[1]["enabled"])                # выключено — честно говорим
            remote = Remote(modules=[("reprocess", "1.0.0", mod_zip("reprocess", "1.0.0"))])
            app.updater = updater.Updater("me/hud", elw.VERSION, root, lambda: app.modules, fetch=remote)
            st = req("/api/updates/check", "POST", {})[1]
            self.assertTrue(st["modules"][0]["new"])
            self.assertEqual(req("/api/updates/install", "POST", {"id": "reprocess"}, origin=False)[0], 403)
            r = req("/api/updates/install", "POST", {"id": "reprocess"})[1]
            self.assertTrue(r["ok"] and r["restart"])
            self.assertTrue(os.path.isfile(os.path.join(root, "reprocess", "module.json")))
            r = req("/api/updates/install", "POST", {"id": "nope"})[1]
            self.assertFalse(r["ok"])
            self.assertEqual(req("/api/updates/install", "POST", {"all": True})[1]["message"], "Обновлять нечего.")
            srv.shutdown()
            srv.server_close()
        finally:
            td.cleanup()
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
