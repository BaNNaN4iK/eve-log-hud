# -*- coding: utf-8 -*-
"""Отчёт о бое по киллмейлам: загрузка с zKillboard (страницы, время, старый формат), стороны, статистика, адреса."""
import json
import os
import shutil
import tempfile
import time
import unittest
from calendar import timegm

from helpers import module

fleet = module("fleet")
bt = fleet.load_battle()

T0 = timegm((2026, 10, 23, 18, 0, 0, 0, 0, 0))
SYS = 30004759
# альянсы: 1 — наши, 2 — противник, 3 — их союзники; корпорация 900 без альянса — тоже противник
US, THEM, ALLY = 99000001, 99000002, 99000003


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def km(kid, t, victim, attackers, value=1e8, solo=False, npc=False):
    return {"killmail_id": kid, "killmail_time": iso(t), "solar_system_id": SYS,
            "victim": victim, "attackers": attackers,
            "zkb": {"hash": f"h{kid}", "totalValue": value, "droppedValue": value / 10, "solo": solo, "npc": npc}}


def pilot(cid, ally=None, corp=None, ship=None, dmg=0, fb=False, weapon=None):
    p = {"character_id": cid, "corporation_id": corp or cid * 10, "ship_type_id": ship}
    if ally:
        p["alliance_id"] = ally
    if dmg or fb or weapon:
        p.update(damage_done=dmg, final_blow=fb, weapon_type_id=weapon)
    else:
        p["damage_taken"] = 5000
    return p


FIGHT = [
    # наши (101, 102) убивают их 201 на Ferox, потом под
    km(1, T0 + 60, pilot(201, THEM, ship=37480), [pilot(101, US, ship=22852, dmg=4000, fb=True, weapon=3082),
                                                   pilot(102, US, ship=17738, dmg=1000, weapon=2488)], value=2e8),
    km(2, T0 + 90, pilot(201, THEM, ship=670), [pilot(102, US, ship=17738, dmg=300, fb=True, weapon=2488)], value=1e7, solo=True),
    # их союзник 301 и корпорация 900 убивают нашего 102
    km(3, T0 + 300, pilot(102, US, ship=17738), [pilot(301, ALLY, ship=11987, dmg=6000, weapon=3001),
                                                  pilot(901, corp=900, ship=24690, dmg=2000, fb=True, weapon=3001)], value=5e8),
    # NPC убили нашего пилота — в киллы противника не идёт
    km(4, T0 + 400, pilot(103, US, ship=24690), [{"corporation_id": 1000125, "ship_type_id": 23707, "damage_done": 900,
                                                   "final_blow": True, "faction_id": 500010}], value=3e7, npc=True),
    # бой вне окна — не берём
    km(0, T0 - 7200, pilot(202, THEM, ship=11987), [pilot(101, US, ship=22852, dmg=100, fb=True)]),
]


class FakeZkb:
    """zKillboard: страницы по 2 киллмейла, новые первыми; плюс ESI для имён и старого формата."""

    def __init__(self, kms, page_size=2, old_format=()):
        self.kms = sorted(kms, key=lambda k: -k["killmail_id"])
        self.page_size, self.old = page_size, set(old_format)
        self.calls = []

    def __call__(self, url, body=None):
        self.calls.append(url)
        if "zkillboard.com/api/systemID/" in url:
            page = int(url.rstrip("/").split("/page/")[1])
            rows = self.kms[(page - 1) * self.page_size: page * self.page_size]
            return [({"killmail_id": r["killmail_id"], "zkb": r["zkb"]} if r["killmail_id"] in self.old else r) for r in rows]
        if "/killmails/" in url:
            kid = int(url.split("/killmails/")[1].split("/")[0])
            r = dict(next(k for k in self.kms if k["killmail_id"] == kid))
            r.pop("zkb")
            return r
        if url.endswith("/universe/names/"):
            return [{"id": i, "name": f"N{i}"} for i in body]
        if url.endswith("/universe/ids/"):
            return {"systems": [{"id": SYS, "name": "1DQ1-A"}] if "1DQ1-A" in body else []}
        if "/alliances/" in url or "/corporations/" in url:
            return {"ticker": "T" + url.rstrip("/").split("/")[-1][-3:]}
        if "/universe/types/" in url:
            return {"group_id": 25}
        if "/universe/groups/" in url:
            return {"name": "Frigate"}
        if url.endswith("/characters/affiliation/"):
            return [{"character_id": body[0], "corporation_id": 1010, "alliance_id": US}]
        raise AssertionError(url)


class TestLoad(unittest.TestCase):
    def test_pages_window_and_old_format(self):
        z = FakeZkb(FIGHT, old_format={3})
        got = bt.Loader(z, sleep=lambda s: None, page_size=2).system(SYS, T0, T0 + 3600)
        self.assertEqual([k["id"] for k in got], [1, 2, 3, 4])                   # 0 — вне времени боя
        self.assertTrue(any("/killmails/3/h3/" in c for c in z.calls))           # старый формат дочитан из ESI
        self.assertEqual(sum("systemID" in c for c in z.calls), 3)                # дальше 3-й страницы не пошёл
        k1 = got[0]
        self.assertEqual((k1["value"], k1["v"]["s"], len(k1["att"]), k1["att"][0]["fb"]), (2e8, 37480, 2, True))

    def test_time_parse(self):
        self.assertEqual(bt.parse_time("2026-10-23 18:00"), T0)
        self.assertEqual(bt.parse_time("2026-10-23T18:00:00Z"), T0)
        self.assertEqual(bt.parse_time("23.10.2026 18:00"), T0)
        with self.assertRaises(bt.BattleError):
            bt.parse_time("вчера")


class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.kms = [bt.compact(k) for k in FIGHT[:4]]

    def test_sides(self):
        side = bt.assign_sides(self.kms, {f"a{US}"})
        self.assertEqual((side[f"a{US}"], side[f"a{THEM}"], side[f"a{ALLY}"], side["c900"]), ("A", "B", "B", "B"))
        side = bt.assign_sides(self.kms, {f"a{US}"}, {f"a{ALLY}": "A"})       # ручной перенос важнее
        self.assertEqual(side[f"a{ALLY}"], "A")
        side = bt.assign_sides(self.kms, set())                                 # своих не знаем — самая активная группа
        self.assertEqual(side[f"a{US}"], "A")

    def test_stats(self):
        side = bt.assign_sides(self.kms, {f"a{US}"})
        r = bt.analyze(self.kms, side, fleet_ids=[101, 102, 104])
        A, B = r["sides"]["A"], r["sides"]["B"]
        self.assertEqual((A["kills"], A["losses"], A["ships_lost"], A["pods_lost"]), (2, 2, 2, 0))
        self.assertEqual((B["kills"], B["losses"], B["pods_lost"]), (1, 2, 1))   # килл NPC противнику не засчитан
        self.assertEqual((A["isk_destroyed"], A["isk_lost"]), (2.1e8, 5.3e8))
        self.assertEqual(A["efficiency"], round(2.1e8 * 100 / (2.1e8 + 5.3e8), 1))
        self.assertEqual((A["damage_done"], B["damage_done"]), (5300, 8000))
        P = {p["id"]: p for p in r["pilots"]}
        self.assertEqual((P[101]["damage"], P[101]["final_blows"], P[101]["top_damage"], P[101]["kills"]), (4000, 1, 1, 1))
        self.assertEqual((P[102]["kills"], P[102]["solo"], len(P[102]["losses"]), P[102]["isk_lost"]), (2, 1, 1, 5e8))
        self.assertEqual(P[102]["ships"], [17738])
        self.assertTrue(P[101]["in_fleet"])
        self.assertEqual(r["fleet_missing"], [104])                            # был во флоте, на киллмейлах нет
        ships = {x["type"]: x for x in A["ships"]}
        self.assertEqual((ships[17738]["fielded"], ships[17738]["lost"]), (1, 1))
        self.assertEqual({w["type"] for w in B["weapons"]}, {3001})
        tl = r["timeline"]
        self.assertTrue(tl[3]["npc"])
        self.assertEqual((tl[2]["final_blow"]["c"], tl[2]["top"]["c"], tl[2]["top"]["d"]), (901, 301, 6000))
        self.assertEqual(r["highlights"]["most_expensive"], 3)
        self.assertEqual(r["highlights"]["top_damage"], {"id": 301, "value": 6000})
        self.assertEqual(r["series"][-1], {"m": 5, "A": 5.3e8, "B": 2.1e8})


class TestBattles(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="elw-battle-")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_build_from_fleet_move_and_list(self):
        z = FakeZkb(FIGHT)
        fleet_rec = {"id": 77, "started_at": T0, "ended_at": T0 + 1800,
                     "members": {"101": {"route": [{"system": SYS, "at": T0, "until": T0 + 1800}]}, "102": {"route": []}}}
        built = []
        b = bt.Battles(self.d, loader=bt.Loader(z, sleep=lambda s: None, page_size=2), get=z, me=lambda: None,
                       fleet=lambda fid: fleet_rec if fid == 77 else None, on_built=built.append)
        pre = b.prefill(77)
        self.assertEqual((pre["systems"][0]["id"], pre["start"], pre["end"]), (SYS, "2026-10-23 17:55", "2026-10-23 18:40"))
        with self.assertRaises(bt.BattleError):
            b._system_ids("Нет Такой")
        rec = b.build_now({"systems": b._system_ids("1DQ1-A"), "start": T0, "end": T0 + 3600, "fleet_id": 77, "title": "Тест"})
        self.assertEqual(rec["seeds"], [f"a{US}"])                              # наши — по пилотам флота
        self.assertEqual(rec["report"]["sides"]["A"]["pilots"], 3)
        self.assertEqual(rec["lookup"]["names"][str(101)], "N101")
        self.assertEqual(rec["lookup"]["classes"]["37480"], "Frigate")
        self.assertTrue(rec["lookup"]["entities"][f"a{US}"]["ticker"].startswith("T"))
        self.assertIn(37480, built[0])                                          # иконки кораблей запрошены
        v = b.move(rec["id"], f"a{ALLY}", "A")
        self.assertEqual(v["overrides"], {f"a{ALLY}": "A"})
        self.assertEqual(b.load(rec["id"])["side"][f"a{ALLY}"], "A")
        self.assertEqual([x["id"] for x in b.list()], [rec["id"]])
        with self.assertRaises(bt.BattleError):
            b.move(rec["id"], "../x", "A")
        self.assertIsNone(b.load("../../etc"))

    def test_start_validation_and_empty(self):
        z = FakeZkb(FIGHT)
        b = bt.Battles(self.d, loader=bt.Loader(z, sleep=lambda s: None, page_size=2), get=z)
        for body, word in (({"systems": "1DQ1-A", "start": "2026-10-23 18:00", "end": "2026-10-23 17:00"}, "позже"),
                           ({"systems": "1DQ1-A", "start": "2026-10-20 18:00", "end": "2026-10-23 17:00"}, "суток"),
                           ({"systems": "", "start": "2026-10-23 18:00", "end": "2026-10-23 19:00"}, "систему")):
            with self.assertRaises(bt.BattleError) as cm:
                b.start(body)
            self.assertIn(word, str(cm.exception))
        with self.assertRaises(bt.BattleError) as cm:
            b.build_now({"systems": [(SYS, "1DQ1-A")], "start": T0 + 7200, "end": T0 + 9000})
        self.assertIn("нет ни одного", str(cm.exception))


class TestBattleHttp(unittest.TestCase):
    def test_endpoints(self):
        import http.client
        import threading
        from helpers import TempDirs, ctx, elw, make_cfg
        from test_crash import free_port
        td = TempDirs()
        try:
            port = free_port()
            cfg = make_cfg(td.logs, web_port=port)
            app = elw.App(cfg, td.data, elw.Watcher(cfg, td.data), None)
            srv = elw.make_server(app)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            fleet.setup(ctx(app, "fleet"))
            z = FakeZkb(FIGHT)
            api_b = app.routes[("POST", "/api/battle/build")][1].__self__
            api_b.b.get = z
            api_b.b.loader = bt.Loader(z, sleep=lambda s: None, page_size=2)
            api_b.b.names.get = z

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

            body = {"systems": "1DQ1-A", "start": "2026-10-23 18:00", "end": "2026-10-23 19:00"}
            self.assertEqual(req("/api/battle/build", "POST", body, origin=False)[0], 403)
            j = req("/api/battle/build", "POST", body)[1]
            self.assertTrue(j["ok"])
            for _ in range(50):
                st = req("/api/battle/job?id=" + j["job"])[1]
                if st["state"] != "running":
                    break
                time.sleep(0.1)
            self.assertEqual(st["state"], "done", st)
            rep = req("/api/battle?id=" + st["battle"])[1]
            self.assertEqual(rep["report"]["kms"], 4)
            self.assertNotIn("kms", {k for k in rep if k == "kms"})                 # сырые киллмейлы страница не получает
            self.assertEqual(len(req("/api/battles")[1]["battles"]), 1)
            self.assertEqual(req("/api/battle?id=nope_1")[0], 404)
            self.assertFalse(req("/api/battle/build", "POST", {"systems": "1DQ1-A", "start": "x", "end": "y"})[1]["ok"])
            self.assertFalse(req("/api/battle/prefill?fleet_id=5")[1]["ok"])
            srv.shutdown()
            srv.server_close()
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
