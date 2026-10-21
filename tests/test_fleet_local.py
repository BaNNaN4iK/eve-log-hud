# -*- coding: utf-8 -*-
"""Флот без Alliance Auth: вход через EVE (PKCE), опрос ESI, время во флоте, отлучки, отметки, история."""
import base64
import json
import os
import unittest
import urllib.parse

from helpers import TempDirs
from helpers import module

ef = module("fleet")

ME, BOB, CAT = 1001, 1002, 1003
NAMES = {ME: "Boss", BOB: "Bob", CAT: "Cat", 587: "Rifter", 24690: "Hurricane", 30000142: "Jita", 30002813: "Tama"}


def jwt(cid=ME, name="Boss"):
    body = base64.urlsafe_b64encode(json.dumps({"sub": f"CHARACTER:EVE:{cid}", "name": name}).encode()).rstrip(b"=").decode()
    return f"hdr.{body}.sig"


class FakeEve:
    """Подмена CCP: SSO и ESI. Состояние флота задаётся атрибутами."""

    def __init__(self):
        self.calls, self.fleet_id, self.boss, self.members = [], 555, ME, []
        self.fleet_status, self.token_status, self.down = 200, 200, False

    def member(self, cid, system=30000142, ship=587, station=None):
        return {"character_id": cid, "solar_system_id": system, "ship_type_id": ship, "station_id": station, "role": "squad_member"}

    def __call__(self, method, url, *, token="", form=None, body=None, timeout=15):
        self.calls.append((method, url, form, token))
        path = urllib.parse.urlsplit(url).path
        if path == "/v2/oauth/token":
            if self.token_status != 200:
                raise ef.FleetError("login ответил", self.token_status)
            return {"access_token": jwt(), "refresh_token": "refresh-" + str(len(self.calls)), "expires_in": 1200}
        if self.down:
            raise ef.FleetError("нет связи с esi.evetech.net")
        if path.endswith("/universe/names/"):
            return [{"id": i, "name": NAMES[i]} for i in body if i in NAMES]
        if not token:
            raise ef.FleetError("без токена", 401)
        if path.endswith(f"/characters/{ME}/fleet/"):
            if self.fleet_status != 200:
                raise ef.FleetError("ESI", self.fleet_status)
            return {"fleet_id": self.fleet_id, "fleet_boss_id": self.boss}
        if path.endswith(f"/fleets/{self.fleet_id}/members/"):
            return list(self.members)
        raise ef.FleetError("нет такого", 404)


class TestLocalFleet(unittest.TestCase):
    def setUp(self):
        self.td = TempDirs()
        self.eve = FakeEve()
        self.lf = ef.LocalFleet(self.td.data, "client123", request=self.eve)

    def tearDown(self):
        self.td.cleanup()

    def login(self, lf=None):
        lf = lf or self.lf
        url = lf.auth.login_url("http://localhost:47322/sso/callback")
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        return lf.auth.finish("code1", q["state"][0]), q

    def test_login_pkce_and_token_storage(self):
        self.assertEqual(self.lf.auth.status(), {"client_id_set": True, "logged_in": False, "character": "", "character_id": None})
        name, q = self.login()
        self.assertEqual((name, self.lf.auth.status()["character_id"]), ("Boss", ME))
        self.assertEqual((q["client_id"], q["scope"], q["code_challenge_method"], q["response_type"]),
                         (["client123"], ["esi-fleets.read_fleet.v1"], ["S256"], ["code"]))
        form = self.eve.calls[-1][2]
        self.assertEqual((form["grant_type"], form["code"], form["client_id"]), ("authorization_code", "code1", "client123"))
        self.assertNotIn("client_secret", form)                                  # PKCE: секрета нет вообще
        raw = open(os.path.join(self.td.data, "esi_token.json"), encoding="utf-8").read()
        self.assertNotIn("refresh-", raw)                                        # токен в файле зашифрован (Windows DPAPI)
        again = ef.LocalFleet(self.td.data, "client123", request=self.eve)        # перезапуск — вход сохранился
        self.assertTrue(again.auth.logged_in)
        self.assertEqual(again.auth.token(), jwt())
        self.assertEqual(self.eve.calls[-1][2]["grant_type"], "refresh_token")
        with self.assertRaises(ef.FleetError):                                   # чужой или повторный state
            self.lf.auth.finish("code2", q["state"][0])
        with self.assertRaises(ef.FleetError):
            ef.EsiAuth(self.td.data, "").login_url("http://localhost:1/sso/callback")
        self.eve.token_status, again.auth.access_until = 400, 0                   # разрешение отозвано на сайте CCP
        with self.assertRaises(ef.FleetError):
            again.auth.token()
        self.assertFalse(again.auth.logged_in)
        self.assertFalse(os.path.exists(os.path.join(self.td.data, "esi_token.json")))

    def test_only_ccp_hosts(self):
        for url in ("https://evil.example/x", "http://esi.evetech.net/latest/", "https://login.eveonline.com.evil.example/"):
            with self.assertRaises(ef.FleetError, msg=url):
                ef.http("GET", url)

    def test_start_requires_login_fleet_and_boss(self):
        self.assertEqual(self.lf.start(1000)["reason"], "no_login")
        self.login()
        self.eve.fleet_status = 404
        self.assertEqual(self.lf.start(1000)["reason"], "not_in_fleet")
        self.eve.fleet_status, self.eve.boss = 200, BOB
        r = self.lf.start(1000)
        self.assertEqual(r["reason"], "not_boss")
        self.assertIn("Bob", r["message"])
        self.assertIsNone(self.lf.current())

    def test_tracking_time_away_marks_history(self):
        self.login()
        e = self.eve
        e.members = [e.member(ME, ship=24690), e.member(BOB), e.member(CAT)]
        self.assertTrue(self.lf.start(1000)["ok"])
        for t in range(1010, 1601, 10):                                          # 10 минут: Bob с 1300 в другой системе
            e.members = [e.member(ME, ship=24690), e.member(BOB, system=30002813 if t >= 1300 else 30000142)]
            if t < 1200:
                e.members.append(e.member(CAT, station=60000001))                # Cat вышел на 200-й секунде
            self.assertTrue(self.lf.poll(t).startswith("участников"))
        f = self.lf.current()
        self.assertEqual((f["count"], f["boss"], f["boss_system"], f["is_active"], f["duration"], f["can_manage"]),
                         (2, "Boss", "Jita", True, 600, True))
        self.assertEqual(f["ships"], [{"name": "Hurricane", "n": 1}, {"name": "Rifter", "n": 1}])
        self.assertEqual([(s["name"], s["n"]) for s in f["systems"]], [("Jita", 1), ("Tama", 1)])
        p = {x["name"]: x for x in f["pilots"]}
        self.assertEqual((p["Boss"]["seconds"], p["Boss"]["away_now"], p["Boss"]["me"], p["Boss"]["boss"]), (600, 0, True, True))
        self.assertEqual((p["Bob"]["seconds"], p["Bob"]["away_now"], p["Bob"]["away_eps"], p["Bob"]["system"]), (600, 300, [300], "Tama"))
        self.assertEqual([(x["name"], x["joined"], x["left"], x["seconds"]) for x in f["left"]], [("Cat", 1000, 1190, 190)])
        # отметки
        self.assertTrue(self.lf.mark(BOB, "bad", "  ушёл без команды ")["ok"])
        self.assertEqual(self.lf.mark(BOB, "purple", "")["reason"], "bad")
        self.assertEqual(self.lf.mark(9999, "good", "")["reason"], "bad")
        b = {x["name"]: x for x in self.lf.current()["pilots"]}["Bob"]
        self.assertEqual((b["mark"], b["comment"]), ("bad", "ушёл без команды"))
        # Cat вернулся — время складывается, выход посчитан
        e.members.append(e.member(CAT))
        self.lf.poll(1700)
        self.lf.poll(1760)
        c = {x["name"]: x for x in self.lf.current()["pilots"]}["Cat"]
        self.assertEqual((c["seconds"], c["rejoins"]), (250, 1))
        # приложение перезапустили при идущем флоте — продолжаем следить
        again = ef.LocalFleet(self.td.data, "client123", request=e)
        self.assertEqual(again.current()["count"], 3)
        # флот распущен → в истории, с отметками; текущего больше нет
        e.fleet_status = 404
        self.assertEqual(again.poll(1800), "флот завершён")
        self.assertIsNone(again.current())
        rows = again.list()
        self.assertEqual([(r["is_active"], r["boss"], r["pilots"], r["duration"]) for r in rows], [(False, "Boss", 3, 800)])
        old = again.get(rows[0]["id"])
        self.assertEqual((old["is_active"], old["end_reason"], old["count"], len(old["left"])), (False, "Флот распущен или вы из него вышли", 3, 0))
        self.assertEqual({x["name"]: x["mark"] for x in old["pilots"]}["Bob"], "bad")
        self.assertEqual(old["pilots"][0]["away_now"], 0)
        self.assertTrue(again.mark(BOB, "good", "исправился", fleet_id=rows[0]["id"])["ok"])   # правка после закрытия
        self.assertEqual({x["name"]: x["comment"] for x in again.get(rows[0]["id"])["pilots"]}["Bob"], "исправился")
        self.assertIsNone(again.get("abc"))
        self.assertEqual(again.mark(BOB, "good", "", fleet_id=123456)["reason"], "no_fleet")

    def test_boss_change_and_network_errors(self):
        self.login()
        e = self.eve
        e.members = [e.member(ME), e.member(BOB)]
        self.lf.start(1000)
        e.down = True
        self.assertEqual(self.lf.poll(1010), "ошибка")                           # сеть моргнула — флот не закрываем
        self.assertIsNotNone(self.lf.current())
        e.down = False
        self.assertTrue(self.lf.poll(1020).startswith("участников"))
        e.boss = BOB
        self.assertEqual(self.lf.poll(1030), "флот завершён")
        self.assertIn("Bob", self.lf.list()[0] and self.lf.get(self.lf.list()[0]["id"])["end_reason"])
        self.assertEqual(self.lf.stop()["ok"], False)


class TestLocalFleetInApp(unittest.TestCase):
    """То же через трекер: адреса страницы, вход, отслеживание — без Alliance Auth."""

    def setUp(self):
        import http.client
        import threading
        from helpers import ctx, elw, make_cfg
        from test_crash import free_port
        self.http = http.client
        self.td = TempDirs()
        self.eve = FakeEve()
        self.port = free_port()
        cfg = make_cfg(self.td.logs, web_port=self.port, online_enabled=False)
        w = elw.Watcher(cfg, self.td.data)
        self.app = elw.App(cfg, self.td.data, w, None)
        self.local = ef.LocalFleet(self.td.data, "", request=self.eve)
        self.opened = []
        ef.FleetApi(self.local, self.port, cfg, self.td.data, elw.atomic_write_json, open_url=self.opened.append).register(ctx(self.app, "fleet"))
        self.srv = elw.make_server(self.app)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.td.cleanup()

    def req(self, path, method="GET", body=None, origin=True):
        c = self.http.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"localhost:{self.port}"}
        if method == "POST" and origin:
            h.update({"Origin": f"http://localhost:{self.port}", "X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json"})
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, raw.decode("utf-8", "replace")

    def test_full_flow_without_alliance_auth(self):
        st = self.req("/api/sso")[1]
        self.assertEqual((st["source"], st["client_id_set"], st["logged_in"], st["available"]), ("", False, False, True))
        self.assertEqual([m["id"] for m in self.req("/api/modules")[1]["modules"]], ["fleet"])
        self.assertEqual(self.req("/modules/fleet/tab.js")[0], 200)                         # вкладка модуля отдаётся
        self.assertEqual(self.req("/modules/fleet/fleet.py")[0], 404)                       # а код — нет
        self.assertEqual(st["callback"], f"http://localhost:{self.port}/sso/callback")
        self.assertEqual(self.req("/api/fleet")[1]["reason"], "no_login")
        self.assertFalse(self.req("/api/sso/login", "POST")[1]["ok"])                       # Client ID ещё не задан
        self.assertFalse(self.req("/api/sso/client", "POST", {"client_id": "not-an-id"})[1]["ok"])
        cid = "0123456789abcdef0123456789abcdef"
        self.assertTrue(self.req("/api/sso/client", "POST", {"client_id": cid})[1]["ok"])
        self.assertEqual(json.load(open(os.path.join(self.td.data, "config.json"), encoding="utf-8"))["esi_client_id"], cid)
        self.assertEqual(self.req("/api/sso/login", "POST", origin=False)[0], 403)           # чужой сайт вход не запустит
        self.assertTrue(self.req("/api/sso/login", "POST")[1]["ok"])
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.opened[0]).query)
        self.assertEqual((q["client_id"], q["redirect_uri"]), ([cid], [f"http://localhost:{self.port}/sso/callback"]))
        code, page = self.req("/sso/callback?code=abc&state=wrong")
        self.assertEqual(code, 400)
        self.assertIn("Вход не выполнен", page)
        code, page = self.req("/sso/callback?code=abc&state=" + q["state"][0])
        self.assertEqual(code, 200)
        self.assertIn("Вы вошли как Boss", page)
        self.assertNotIn("refresh-", page)
        st = self.req("/api/sso")[1]
        self.assertEqual((st["source"], st["logged_in"], st["character"]), ("local", True, "Boss"))
        self.assertNotIn("refresh", json.dumps(st))                                        # токен наружу не отдаётся
        # флот
        self.assertEqual((self.req("/api/fleet")[1]["ok"], self.req("/api/fleet")[1]["fleet"]), (True, None))
        self.eve.members = [self.eve.member(ME), self.eve.member(BOB, system=30002813)]
        r = self.req("/api/fleet/track", "POST")[1]
        self.assertTrue(r["ok"], r)
        f = self.req("/api/fleet")[1]["fleet"]
        self.assertEqual((f["count"], f["boss"], [s["name"] for s in f["systems"]]), (2, "Boss", ["Jita", "Tama"]))
        self.assertTrue(self.req("/api/fleet/mark", "POST", {"character_id": BOB, "mark": "warn", "comment": "проверка"})[1]["ok"])
        self.assertEqual({p["name"]: p["mark"] for p in self.req("/api/fleet")[1]["fleet"]["pilots"]}["Bob"], "warn")
        self.assertTrue(self.req("/api/sso")[1]["tracking"])
        self.assertTrue(self.req("/api/fleet/stop", "POST")[1]["ok"])
        rows = self.req("/api/fleets")[1]["fleets"]
        self.assertEqual([(x["is_active"], x["pilots"]) for x in rows], [(False, 2)])
        old = self.req(f"/api/fleet?id={rows[0]['id']}")[1]["fleet"]
        self.assertEqual((old["is_active"], old["end_reason"]), (False, "Отслеживание остановлено вручную"))
        # выход: токен удалён, источника снова нет
        self.assertTrue(self.req("/api/sso/logout", "POST")[1]["ok"])
        self.assertEqual((self.req("/api/sso")[1]["source"], os.path.exists(os.path.join(self.td.data, "esi_token.json"))), ("", False))
        self.assertEqual(self.req("/api/fleet")[1]["reason"], "no_login")
        self.assertEqual(len(self.req("/api/fleets")[1]["fleets"]), 1)                       # история остаётся и после выхода


if __name__ == "__main__":
    unittest.main()
