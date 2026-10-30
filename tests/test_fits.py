# -*- coding: utf-8 -*-
"""Модуль «Фиты»: готовность по SP (минимум и план), навыки из ESI через общий вход, загрузка файла фитов, адреса."""
import json
import os
import unittest

import eve_sso
from helpers import TempDirs, ctx, elw, make_cfg, module

fits = module("fits")
SKILLS = {"3333": ["Minmatar Cruiser", 5.0], "3394": ["Hull Upgrades", 2.0], "21611": ["Jump Drive Calibration", 9.0]}
DATA = {"v": 1, "built": "2026-10-30", "doctrines": [{"id": 1, "name": "Арта", "description": "", "active": True}],
        "fits": [{"id": 7, "name": "Arty", "ship_type_id": 24702, "ship_name": "Hurricane", "ship_group": "Combat Battlecruiser",
                  "description": "", "eft": "[Hurricane, Arty]", "doctrines": [1], "items": [{"type_id": 2048, "name": "Damage Control II", "slot": "low", "qty": 1}],
                  "required": {"3333": 3, "3394": 4}, "plan": {"21611": 3}}],
        "skills": SKILLS}


def write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


class FakeAuth:
    def __init__(self, scopes):
        self.chars = {9001: {"name": "Pilot", "refresh": "r", "scopes": scopes}}
        self.client_id = "x"

    def has(self, cid, scope):
        return scope in self.chars[cid]["scopes"]

    def token(self, cid):
        return "tok"

    def on_linked(self, fn):
        pass


class TestFits(unittest.TestCase):
    def test_check(self):
        req, minimum = {3333: 3, 3394: 4, 21611: 3}, {3333, 3394}
        r = fits.check(req, minimum, {3333: 3, 3394: 4}, {21611: 2}, SKILLS)
        self.assertTrue(r["known"] and r["can_fly"] and not r["ok"])
        self.assertEqual([m["skill_id"] for m in r["missing"]], [21611])
        self.assertEqual(r["missing"][0]["queued"], 2)
        self.assertLess(r["pct"], 100)
        r = fits.check(req, minimum, {3333: 2}, {}, SKILLS)
        self.assertFalse(r["can_fly"])
        self.assertEqual(r["missing"][0]["minimum"], True)                     # минимум — первым
        self.assertFalse(fits.check(req, minimum, None, {}, SKILLS)["known"])  # навыки неизвестны — не «0%»
        self.assertEqual(fits.check(req, minimum, {3333: 5, 3394: 5, 21611: 5}, {}, SKILLS)["pct"], 100)
        self.assertEqual(fits.sp_for(1, 5), 256000)

    def test_progression(self):
        """Первым — самый дешёвый фит; дальше — тот, что проще докачать после уже поставленного."""
        sk = {"1": ["A", 1.0], "2": ["B", 1.0], "3": ["C", 8.0]}
        fs = [{"id": 1, "required": {"1": 3}}, {"id": 2, "required": {"1": 3, "2": 3}},
              {"id": 3, "required": {"3": 5}}, {"id": 4, "required": {"1": 3, "2": 4}}]
        tr = fits.progression(fs, sk)
        self.assertEqual([n["id"] for n in tr], [1, 2, 4, 3])
        by = {n["id"]: n for n in tr}
        self.assertEqual((by[1]["parent"], by[2]["parent"], by[4]["parent"]), (None, 1, 2))
        self.assertEqual(by[2]["extra"], fits.sp_for(1, 3))                 # навык A уже выучен — доучить только B
        self.assertEqual(by[4]["depth"], 2)
        self.assertEqual(fits.progression([], sk), [])

    def test_valid_dataset(self):
        self.assertIsNone(fits.valid_dataset(DATA))
        self.assertTrue(fits.valid_dataset({"x": 1}))
        self.assertTrue(fits.valid_dataset({"fits": [{"ship_type_id": "no"}], "skills": {}}))

    def test_skills_sync(self):
        td = TempDirs()
        try:
            calls = []

            def req(method, url, token="", **kw):
                calls.append(url)
                if "/skills/" in url:
                    return {"total_sp": 5_000_000, "skills": [{"skill_id": 3333, "active_skill_level": 4, "trained_skill_level": 4}]}, {}
                if "/skillqueue/" in url:
                    return [{"skill_id": 3394, "finished_level": 3}, {"skill_id": 3394, "finished_level": 4}], {}
                raise AssertionError(url)
            sk = fits.Skills(td.data, FakeAuth([fits.SKILLS, fits.QUEUE]), write, req)
            sk.sync(now=1000)
            have, queue = sk.of(9001)
            self.assertEqual((have, queue), ({3333: 4}, {3394: 4}))
            sk2 = fits.Skills(td.data, FakeAuth([]), write, req)                 # нет доступа к навыкам
            sk2.data = {}
            sk2.sync(now=2000)
            self.assertIn("навык", sk2.data["9001"]["error"])
            self.assertEqual(sk2.of(9001), (None, {}))
        finally:
            td.cleanup()

    def test_endpoints(self):
        td = TempDirs()
        try:
            cfg = make_cfg(td.logs)
            app = elw.App(cfg, td.data, elw.Watcher(cfg, td.data), None)
            c = ctx(app, "fits")
            fits.setup(c)
            get = lambda: app.routes[("GET", "/api/fits")][1]({})
            self.assertFalse(get()["has_data"])
            r = app.routes[("POST", "/api/fits/import")][1]({"data": {"bad": 1}})
            self.assertFalse(r["ok"])
            r = app.routes[("POST", "/api/fits/import")][1]({"data": DATA})
            self.assertTrue(r["ok"])
            self.assertTrue(os.path.exists(os.path.join(td.data, "fits_data.json")))
            j = get()
            self.assertTrue(j["has_data"])
            self.assertEqual(j["fits"][0]["ship_name"], "Hurricane")
            self.assertFalse(j["ready"]["7"]["known"])                          # персонажа нет — навыки неизвестны
            self.assertFalse(app.routes[("POST", "/api/fits/refresh")][1]({})["ok"])
            self.assertIn("/api/fits/import", elw.BIG_POST)
            self.assertEqual(j["trees"]["1"][0]["id"], 7)                       # дерево прокачки по доктрине                     # файл фитов больше обычного лимита
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
