# -*- coding: utf-8 -*-
"""Калькулятор переработки: выход по навыкам и месту, порции, цены, «переработать или продать», адреса трекера."""
import os
import unittest

from helpers import TempDirs
from helpers import module

rp = module("reprocess")

DATA = {
    "types": {
        "1230": ["Veldspar", "", 25, 462, 100, 0.1, [[34, 400]]],
        "22": ["Arkonor", "", 25, 450, 100, 16.0, [[35, 3200], [36, 1200], [40, 120]]],
        "2454": ["Hobgoblin I", "", 18, 100, 1, 5.0, [[34, 509], [35, 7], [37, 4], [38, 2]]],
    },
    "materials": {"34": ["Tritanium", "", 0.01], "35": ["Pyerite", "", 0.01], "36": ["Mexallon", "", 0.01],
                  "37": ["Isogen", "", 0.01], "38": ["Nocxium", "", 0.01], "40": ["Megacyte", "", 0.01]},
    "index": {"veldspar": 1230, "arkonor": 22, "hobgoblin i": 2454},
}
PRICES = {34: 4.0, 35: 10.0, 36: 50.0, 37: 100.0, 38: 500.0, 40: 2000.0, 1230: 10.0, 22: 3000.0, 2454: 1000.0}


class FakeEsi:
    def __init__(self):
        self.calls = []

    def __call__(self, path, method="GET", body=None, **params):
        self.calls.append(path)
        if path == "/universe/ids/":
            return {"inventory_types": [{"id": 1230, "name": n} for n in body if n == "Вельдспар" and params["language"] == "ru"]}, {}
        if path == "/markets/10000002/orders/":
            p = PRICES[params["type_id"]]
            return [{"is_buy_order": True, "price": p, "location_id": 60003760},
                    {"is_buy_order": False, "price": p * 1.2, "location_id": 60003760},
                    {"is_buy_order": True, "price": p * 9, "location_id": 1}], {"X-Pages": "1"}       # другая станция
        raise RuntimeError(path)


class TestYield(unittest.TestCase):
    def test_formula(self):
        y = lambda **kw: tuple(round(v * 100, 2) for v in rp.yields(rp.clean_settings(kw)))
        self.assertEqual(y(reprocessing=0, efficiency=0, ore=0, scrap=0), (50.0, 50.0))
        # станция NPC, всё по 5 — 69,58%; риг и безопасность на станции не действуют
        self.assertEqual(y(reprocessing=5, efficiency=5, ore=5, scrap=5, rig="t2", security="null")[0], 69.58)
        self.assertEqual(y(reprocessing=5, efficiency=5, ore=5, scrap=5)[1], 55.0)
        # максимум игры: Tatara, T2 риг, нули, все навыки 5, RX-804 — 90,6%
        self.assertEqual(round(y(place="tatara", rig="t2", security="null", reprocessing=5, efficiency=5, ore=5, implant="4")[0], 1), 90.6)
        self.assertEqual(y(ore_yield="72,5", scrap_yield=60), (72.5, 60.0))      # свой выход из окна игры
        s = rp.clean_settings({"reprocessing": 9, "place": "moon", "tax": "abc", "mode": "x", "junk": 1})
        self.assertEqual((s["reprocessing"], s["place"], s["tax"], s["mode"]), (5, "station", 0.0, "buy"))
        self.assertNotIn("junk", s)


class TestCalculate(unittest.TestCase):
    def test_offline_portions_and_materials(self):
        r = rp.Reprocessor(None, DATA).calculate("Veldspar\t250\nHobgoblin I x3\nArkonor 99\nNo Such Rock 5\nВельдспар 100",
                                                 {"reprocessing": 0, "efficiency": 0, "ore": 0, "scrap": 0})
        self.assertTrue(r["ok"])
        self.assertFalse(r["prices"])
        rows = {x["name"]: x for x in r["rows"]}
        self.assertEqual((rows["Veldspar"]["batches"], rows["Veldspar"]["left"]), (2, 50))
        self.assertEqual(rows["Veldspar"]["out"], [{"type_id": 34, "name": "Tritanium", "qty": 400}])    # 2 × 400 × 50%
        self.assertEqual(rows["Arkonor"]["batches"], 0)                       # меньше порции — ничего
        self.assertEqual(rows["Hobgoblin I"]["out"][0], {"type_id": 34, "name": "Tritanium", "qty": 763})   # floor(3×509×0,5)
        mats = {m["name"]: m["qty"] for m in r["materials"]}
        self.assertEqual(mats["Tritanium"], 1163)
        self.assertEqual(mats["Pyerite"], 10)                                 # floor(3×7×0,5)
        self.assertEqual(r["missing"], ["No Such Rock", "Вельдспар"])          # без интернета русское название не найти
        self.assertIsNone(r["totals"]["value"])

    def test_prices_verdict_tax(self):
        esi = FakeEsi()
        r = rp.Reprocessor(esi, DATA).calculate("Вельдспар 100\nArkonor 100\nHobgoblin I 2",
                                                {"reprocessing": 0, "efficiency": 0, "ore": 0, "scrap": 0, "tax": 10})
        rows = {x["name"]: x for x in r["rows"]}
        v = rows["Veldspar"]                                                  # найдено через ESI по-русски
        self.assertEqual((v["input"], v["as_is"]), ("Вельдспар", 1000.0))
        self.assertAlmostEqual(v["value"], 200 * 4.0 * 0.9)                    # 200 Tritanium минус 10% налога
        self.assertEqual(v["verdict"], "sell")
        a = rows["Arkonor"]                                                   # 1600 Pye + 600 Mex + 60 Mega = 166 000
        self.assertAlmostEqual(a["value"], (1600 * 10 + 600 * 50 + 60 * 2000) * 0.9)
        self.assertEqual(a["as_is"], 300000.0)
        self.assertEqual(a["verdict"], "sell")
        t = r["totals"]
        self.assertAlmostEqual(t["tax"], t["gross"] * 0.1)
        self.assertAlmostEqual(t["best"], sum(max(x["as_is"], x["value"]) for x in r["rows"]))
        cheap = rp.Reprocessor(esi, DATA).calculate("Arkonor 100", {"ore_yield": 100, "mode": "buy"})
        self.assertEqual(cheap["rows"][0]["verdict"], "reprocess")         # при 100% выходе 332 000 > 300 000
        PRICES[22] = 100.0
        try:
            r2 = rp.Reprocessor(FakeEsi(), DATA).calculate("Arkonor 100", {"reprocessing": 0, "efficiency": 0, "ore": 0})
            self.assertEqual(r2["rows"][0]["verdict"], "reprocess")
            self.assertGreater(r2["rows"][0]["gain"], 0)
        finally:
            PRICES[22] = 3000.0

    def test_empty(self):
        self.assertFalse(rp.Reprocessor(None, DATA).calculate("   ")["ok"])

    def test_real_data_file(self):
        d = rp.load_data()
        self.assertGreater(len(d["types"]), 5000)
        self.assertEqual(d["types"]["1230"][6], [[34, 400]])                 # Veldspar → 400 Tritanium
        for name in ("arkonor ii-grade", "bistot", "hobgoblin ii", "clear icicle"):     # названия из логов добычи
            self.assertIn(name, d["index"])


class TestReprocessHttp(unittest.TestCase):
    def test_endpoints(self):
        import http.client
        import json
        import threading
        import types
        from helpers import ctx, elw, make_cfg
        from test_crash import free_port
        td = TempDirs()
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

            rp.setup(ctx(app, "reprocess"))                                    # без онлайна — выход без цен
            code, r = req("/api/reprocess", "POST", {"text": "Veldspar 1000", "settings": {"reprocessing": 5, "efficiency": 5, "ore": 5}})
            self.assertEqual((code, r["ok"], r["prices"]), (200, True, False))
            self.assertEqual(r["materials"][0]["qty"], int(10 * 400 * 0.6958 // 1))
            self.assertIn("онлайн", r["note"])
            s = req("/api/reprocess/settings")[1]                              # настройки запомнились
            self.assertEqual((s["settings"]["ore"], s["ore_yield"]), (5, 69.58))
            self.assertTrue(os.path.exists(os.path.join(td.data, "reprocess_settings.json")))
            self.assertEqual(req("/api/reprocess", "POST", {"text": "x"}, origin=False)[0], 403)
            self.assertFalse(req("/api/reprocess", "POST", {"nope": 1})[1]["ok"])
            app.online = types.SimpleNamespace(esi=FakeEsi(), cache={}, lock=threading.RLock(), fetch_icon=lambda tid: True)
            rp.setup(ctx(app, "reprocess"))
            r = req("/api/reprocess", "POST", {"text": "Veldspar 1000"})[1]
            self.assertTrue(r["prices"])
            self.assertIsNotNone(r["totals"]["as_is"])
            srv.shutdown()
            srv.server_close()
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
