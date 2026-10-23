# -*- coding: utf-8 -*-
"""Калькулятор производства: формулы игры, сборка компонентов, цены и стоимость работы, адреса трекера."""
import json
import os
import unittest

from helpers import TempDirs, module

ind = module("industry")

# маленький справочник: Hobgoblin II из Hobgoblin I + материалы; реакция
DATA = {
    "bp": {
        "2456": [2457, "m", 1000, 1, [[2454, 1], [11399, 2], [38, 10]], 10],      # Hobgoblin II
        "2454": [2455, "m", 300, 1, [[34, 509], [35, 7]], 600],                  # Hobgoblin I
        "16670": [46205, "r", 10800, 200, [[4247, 5], [16655, 100]], 1000],      # реакция: 200 за прогон
    },
    "types": {"2456": ["Hobgoblin II", 100, 18, 5.0], "2454": ["Hobgoblin I", 100, 18, 5.0], "11399": ["Morphite", 18, 4, 0.01],
              "38": ["Nocxium", 18, 4, 0.01], "34": ["Tritanium", 18, 4, 0.01], "35": ["Pyerite", 18, 4, 0.01],
              "16670": ["Crystalline Carbonide", 429, 4, 0.01], "4247": ["Helium Fuel Block", 1136, 4, 5.0],
              "16655": ["Crystallite Alloy", 428, 4, 0.01]},
    "groups": {},
}
DATA["index"] = {DATA["types"][k][0].casefold(): int(k) for k in DATA["bp"]}
PRICES = {2456: 330000, 2454: 4000, 11399: 10000, 38: 600, 34: 4, 35: 15, 16670: 1000, 4247: 20000, 16655: 300}
ADJ = {2454: 3000.0, 11399: 9000.0, 38: 500.0, 34: 3.0, 35: 10.0, 4247: 15000.0, 16655: 250.0}


class FakeEsi:
    def __init__(self):
        self.calls = []

    def __call__(self, path, method="GET", body=None, **params):
        self.calls.append(path)
        if path == "/markets/prices/":
            return [{"type_id": t, "adjusted_price": p} for t, p in ADJ.items()], {}
        if path == "/industry/systems/":
            return [{"solar_system_id": 30000142, "cost_indices": [{"activity": "manufacturing", "cost_index": 0.05},
                                                                   {"activity": "reaction", "cost_index": 0.02}]}], {}
        if path == "/universe/ids/":
            if body == ["Jita"]:
                return {"systems": [{"id": 30000142, "name": "Jita"}]}, {}
            if body == ["Хобгоблин II"]:
                return {"inventory_types": [{"id": 2456, "name": "Хобгоблин II"}]}, {}
            return {}, {}
        if path == "/markets/10000002/orders/":
            p = PRICES[params["type_id"]]
            return [{"is_buy_order": True, "price": p * 0.9, "location_id": 60003760},
                    {"is_buy_order": False, "price": p, "location_id": 60003760}], {"X-Pages": "1"}
        raise AssertionError(path)


class TestFormulas(unittest.TestCase):
    def test_material_quantity(self):
        self.assertEqual(ind.mat_qty(509, 10, 0.9), 4581)               # 10 × 509 × 0,9
        self.assertEqual(ind.mat_qty(1, 10, 0.9), 10)                   # не меньше числа прогонов
        self.assertEqual(ind.mat_qty(5625, 1, 0.9 * 0.99 * (1 - 0.024 * 2.1)), 4760)    # Sotiyo, T2 риг, нули

    def test_bonuses(self):
        s = ind.clean_settings({"me": 10, "te": 20, "structure": "sotiyo", "rig": "t2", "security": "null",
                                "industry": 5, "adv_industry": 4})
        b = ind.bonuses(s, "m", True)
        self.assertAlmostEqual(b["mat"], 0.9 * 0.99 * (1 - 0.0504))
        self.assertAlmostEqual(240000 * b["time"], 46930, places=0)    # время Ishtar из игры
        self.assertAlmostEqual(b["cost"], 0.95)
        st = ind.bonuses(ind.clean_settings({"me": 10, "rig": "t2", "security": "null"}), "m", True)
        self.assertAlmostEqual(st["mat"], 0.9)                          # на станции NPC риги не действуют
        r = ind.bonuses(ind.clean_settings({"structure": "tatara", "reactions": 5, "me": 10}), "r", True)
        self.assertAlmostEqual(r["mat"], 1.0)                           # у реакций нет ME
        self.assertAlmostEqual(r["time"], 0.75 * 0.8)
        s = ind.clean_settings({"runs": "0", "me": 99, "structure": "x", "build": ["5", "bad"], "facility_tax": ""})
        self.assertEqual((s["runs"], s["me"], s["structure"], s["build"], s["facility_tax"]), (1, 10, "station", [], 0.25))


class TestCalculate(unittest.TestCase):
    def test_offline_tree_and_build(self):
        c = ind.Calculator(None, DATA)
        r = c.calculate("hobgoblin ii", {"runs": 10, "me": 0, "te": 0, "industry": 0, "adv_industry": 0})
        self.assertTrue(r["ok"])
        self.assertFalse(r["prices"])
        self.assertEqual({x["name"]: x["qty"] for x in r["shopping"]}, {"Hobgoblin I": 10, "Morphite": 20, "Nocxium": 100})
        self.assertEqual(r["totals"]["time"], 10000)
        self.assertIsNone(r["totals"]["profit"])
        r = c.calculate("Hobgoblin II", {"runs": 10, "me": 0, "comp_me": 10, "industry": 0, "adv_industry": 0, "build": [2454]})
        self.assertEqual({x["name"]: x["qty"] for x in r["shopping"]},
                         {"Morphite": 20, "Nocxium": 100, "Tritanium": 4581, "Pyerite": 63})    # Hobgoblin I строим сами (ME 10)
        self.assertEqual([j["name"] for j in r["jobs"]], ["Hobgoblin II", "Hobgoblin I"])
        built = r["tree"]["materials"][0]["build"]
        self.assertEqual((built["runs"], built["out"]), (10, 10))
        r = c.calculate("Crystalline Carbonide", {"runs": 2, "structure": "tatara"})
        self.assertEqual((r["product"]["units"], r["product"]["kind"]), (400, "r"))
        self.assertEqual({x["name"]: x["qty"] for x in r["shopping"]}, {"Helium Fuel Block": 10, "Crystallite Alloy": 200})
        self.assertFalse(c.calculate("Nothing", {})["ok"])

    def test_component_surplus(self):
        c = ind.Calculator(None, DATA)
        tree = c.plan(2456, 3, ind.clean_settings({"me": 0}), set())
        self.assertEqual(tree["runs"], 3)
        rtree = c.plan(16670, 250, ind.clean_settings({}), set())        # 250 штук → 2 прогона по 200, останется 150
        self.assertEqual((rtree["runs"], rtree["out"]), (2, 400))

    def test_prices_job_cost_profit(self):
        esi = FakeEsi()
        c = ind.Calculator(esi, DATA, big=lambda path: esi(path)[0])        # большие списки — тоже из поддельного ESI
        s = {"runs": 10, "me": 0, "te": 0, "industry": 0, "adv_industry": 0, "system": "Jita", "facility_tax": 0.25, "scc": 4,
             "sales_tax": 3.6, "broker": 1.5, "buy_mode": "sell", "sell_mode": "sell"}
        r = c.calculate("Хобгоблин II", s)                                # русское название — через ESI
        t = r["totals"]
        mats = 10 * 4000 + 20 * 10000 + 100 * 600
        self.assertEqual(t["materials"], mats)
        eiv = (1 * 3000 + 2 * 9000 + 10 * 500) * 10
        self.assertAlmostEqual(t["jobs"], eiv * (0.05 + 0.0025 + 0.04))
        self.assertAlmostEqual(r["cost_index"], 5.0)
        self.assertEqual(r["system"], "Jita")
        revenue = 330000 * 10
        self.assertAlmostEqual(t["fees"], revenue * 0.051)
        self.assertAlmostEqual(t["profit"], revenue - revenue * 0.051 - mats - t["jobs"])
        self.assertAlmostEqual(t["isk_hour"], t["profit"] / (10000 / 3600))
        r2 = c.calculate("Hobgoblin II", dict(s, cost_index=10, structure="sotiyo"))   # свой индекс и бонус комплекса
        self.assertAlmostEqual(r2["totals"]["jobs"], eiv * (0.10 * 0.95 + 0.0025 + 0.04))
        self.assertEqual(sum(1 for p in esi.calls if p == "/industry/systems/"), 1)    # индексы кэшируются

    def test_static_cache_on_disk(self):
        import tempfile
        d = tempfile.mkdtemp()
        path = os.path.join(d, "industry_cache.json")
        esi = FakeEsi()
        c = ind.Calculator(esi, DATA, cache_path=path, big=lambda p: esi(p)[0])
        c.refresh_static(now=1000)
        self.assertTrue(os.path.exists(path))
        c2 = ind.Calculator(esi, DATA, cache_path=path, big=lambda p: (_ for _ in ()).throw(AssertionError("сеть")))
        self.assertEqual(c2.adjusted[1][34], 3.0)                       # после перезапуска — с диска, без сети
        self.assertEqual(c2.indices[1][30000142]["manufacturing"], 0.05)
        c2.refresh_static(now=1000 + 60)                                  # свежие — не перекачивает
        self.assertEqual(c2.static_error, "")

    def test_search(self):
        c = ind.Calculator(None, DATA)
        self.assertEqual([x["name"] for x in c.search("hob")], ["Hobgoblin I", "Hobgoblin II"])
        self.assertEqual(c.search("h"), [])

    def test_real_data(self):
        d = ind.load_data()
        self.assertGreater(len(d["bp"]), 3000)
        self.assertEqual(d["bp"]["626"][1], "m")                         # Vexor
        self.assertIn("vexor", d["index"])


class TestIndustryHttp(unittest.TestCase):
    def test_endpoints(self):
        import http.client
        import threading
        from helpers import ctx, elw, make_cfg
        from test_crash import free_port
        td = TempDirs()
        try:
            port = free_port()
            cfg = make_cfg(td.logs, web_port=port)
            app = elw.App(cfg, td.data, elw.Watcher(cfg, td.data), None)
            srv = elw.make_server(app)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            ind.setup(ctx(app, "industry"))

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

            code, r = req("/api/industry", "POST", {"product": "Vexor", "settings": {"runs": 2, "me": 10}})
            self.assertEqual((code, r["ok"], r["product"]["units"]), (200, True, 2))
            self.assertIn("онлайн", r["note"])
            self.assertEqual(req("/api/industry/settings")[1]["product"], "Vexor")
            self.assertTrue(os.path.exists(os.path.join(td.data, "industry_settings.json")))
            self.assertIn("Vexor", [x["name"] for x in req("/api/industry/search?q=vexo")[1]["items"]])
            self.assertEqual(req("/api/industry", "POST", {"product": "Vexor"}, origin=False)[0], 403)
            self.assertFalse(req("/api/industry", "POST", {"nope": 1})[1]["ok"])
            srv.shutdown()
            srv.server_close()
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
