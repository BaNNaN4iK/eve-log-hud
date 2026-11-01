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


class TestScanner(unittest.TestCase):
    """Цены всего хаба (страницы ордеров региона), прибыльность чертежей, защита от ловушек, спрос."""

    def hub(self, orders):
        pages = [orders[i:i + 2] for i in range(0, len(orders), 2)] or [[]]
        return ind.Hub("", get_page=lambda region, page: (pages[page - 1], len(pages)), workers=2)

    def test_hub_and_scan(self):
        J = 60003760
        o = lambda t, p, buy=False, loc=J, v=10: {"type_id": t, "price": p, "is_buy_order": buy, "location_id": loc, "volume_remain": v}
        hub = self.hub([o(2456, 330000), o(2456, 300000, True), o(2456, 1, loc=1),           # чужая станция не в счёт
                        o(2454, 4000), o(2454, 3800, True), o(11399, 10000), o(38, 600), o(34, 4), o(35, 15),
                        o(16670, 50000), o(4247, 20000), o(16655, 300)])
        hub.refresh("jita", now=1000)
        b = hub.book("jita")
        self.assertEqual((b[2456]["sell"], b[2456]["buy"], b[2456]["sv"]), (330000, 300000, 10))
        self.assertEqual(hub.state("jita")["done"], hub.state("jita")["pages"])
        data = dict(DATA, bp=dict(DATA["bp"]))
        data["bp"]["2456"] = DATA["bp"]["2456"] + ["inv"]                                   # T2 из изобретения
        c = ind.Calculator(None, data)
        c.hub = hub
        c.adjusted, c.average = (1000, dict(ADJ)), {2456: 320000.0, 16670: 1000.0}
        c.indices = (1000, {30000142: {"manufacturing": 0.05, "reaction": 0.02}})
        rows = {r["id"]: r for r in ind.scan(c, "jita", ind.clean_settings({"me": 10}), 1000)}
        h2 = rows[2456]
        self.assertEqual(h2["src"], "inv")
        mats = 4000 * 1 + 10000 * ind.mat_qty(2, 1, 0.98) + 600 * ind.mat_qty(10, 1, 0.98)      # ME 2 у копии T2
        eiv = 3000 + 2 * 9000 + 10 * 500
        self.assertAlmostEqual(h2["cost"], mats + eiv * (0.05 + 0.0025 + 0.04))
        self.assertAlmostEqual(h2["sell"]["profit"], 330000 * (1 - 0.051) - h2["cost"])
        self.assertAlmostEqual(h2["buy"]["profit"], 300000 * (1 - 0.036) - h2["cost"])
        self.assertTrue(h2["sure"])
        self.assertTrue(rows[16670]["sell"]["odd"])                                          # 50 000 при средней 1 000
        self.assertFalse(rows[16670]["sure"])
        self.assertEqual(rows[2454]["src"], "bpo")

    def test_lp_guess(self):
        hub = self.hub([{"type_id": 2454, "price": 900000, "is_buy_order": False, "location_id": 60003760},
                        {"type_id": 34, "price": 4, "is_buy_order": False, "location_id": 60003760},
                        {"type_id": 35, "price": 15, "is_buy_order": False, "location_id": 60003760}])
        hub.refresh("jita", now=1000)
        c = ind.Calculator(None, DATA)
        c.hub = hub
        c.indices = (1000, {})
        r = {x["id"]: x for x in ind.scan(c, "jita", ind.clean_settings({}), 1000)}[2454]
        self.assertEqual(r["src"], "lp")                                                     # маржа > 85% — чертёж не с рынка

    def test_history_week_by_date(self):
        import time as _t
        now = 2_000_000_000
        day = lambda k: _t.strftime("%Y-%m-%d", _t.gmtime(now - k * 86400))
        esi = lambda path, **kw: ([{"date": day(30), "volume": 1000}, {"date": day(3), "volume": 5}, {"date": day(1), "volume": 7}], {})
        h = ind.History(esi)
        got = h.get("jita", [2456], now=now)["2456"]
        self.assertEqual((got["week"], got["last"]), (12, 7))                                # старая запись не в неделе
        self.assertEqual(h.week("jita", 2456), 12)


class TestPlan(unittest.TestCase):
    """План: общие компоненты считаются один раз, остатки от округления, изобретение T2, режимы."""

    def data(self):
        d = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DATA.items()}
        d["bp"]["2456"] = DATA["bp"]["2456"] + ["inv"]
        d["bp"]["99"] = [98, "m", 600, 1, [[2454, 3], [16670, 50]], 10, "bpo"]        # продукт из Hobgoblin I и реакции
        d["types"]["99"] = ["Combo", 100, 18, 5.0]
        d["inv"] = {"2457": [2455, 2454, 0.34, 10, [[20418, 1], [20419, 1]], 7800]}
        d["types"]["20418"] = ["Datacore A", 333, 17, 0.1]
        d["types"]["20419"] = ["Datacore B", 333, 17, 0.1]
        return d

    def test_shared_components_leftovers_invention(self):
        c = ind.Calculator(None, self.data())
        s = ind.clean_settings({"me": 0, "comp_me": 0, "inv_sci": 0, "inv_enc": 0})
        r = ind.plan_order(c, [(2456, 10), (99, 2)], s, "full")
        jobs = {j["type_id"]: j for j in r["jobs"]}
        self.assertEqual(jobs[2454]["need"], 10 + 6)                               # Hobgoblin I: 10 для T2 + 2×3 для Combo
        self.assertEqual(jobs[2454]["runs"], 16)
        self.assertEqual((jobs[16670]["runs"], jobs[16670]["made"]), (1, 200))     # 100 нужно, прогон даёт 200
        left = {x["type_id"]: x["qty"] for x in r["leftovers"]}
        self.assertEqual(left[16670], 100)
        self.assertEqual(jobs[2456]["me"], 2)                                       # T2 — копия после изобретения
        inv = r["invention"][0]
        self.assertAlmostEqual(inv["chance"], 0.34)
        self.assertEqual(inv["attempts"], 3)                                       # 10 прогонов / (0,34 × 10) → 3
        buy = {x["type_id"]: x for x in r["shopping"]}
        self.assertEqual(buy[20418]["qty"], 3)
        self.assertEqual(buy[20418]["group"], "Изобретение: датакоры")
        self.assertIn(34, buy)                                                      # минералы — покупаются
        b = ind.plan_order(c, [(2456, 10), (99, 2)], s, "buy")
        self.assertEqual({j["type_id"] for j in b["jobs"]}, {2456, 99})            # строим только продукты
        self.assertEqual({x["type_id"]: x["qty"] for x in b["shopping"]}[2454], 16)
        self.assertEqual(len(b["invention"]), 1)                                    # копия T2 нужна и при закупке

    def test_invention_skills(self):
        self.assertAlmostEqual(ind.invention_chance(0.34, ind.clean_settings({"inv_sci": 5, "inv_enc": 4})),
                               0.34 * (1 + 10 / 30 + 4 / 40))

    def test_plan_with_products_and_prices(self):
        esi = FakeEsi()
        d = self.data()
        c = ind.Calculator(esi, d, big=lambda p: esi(p)[0])
        PRICES.update({99: 500000, 20418: 1000, 20419: 2000})
        try:
            r = ind.plan_with_products(c, [(2456, 10)], ind.clean_settings({"system": "Jita", "inv_sci": 0, "inv_enc": 0}), "buy")
        finally:
            for k in (99, 20418, 20419):
                PRICES.pop(k, None)
        t = r["totals"]
        self.assertAlmostEqual(t["invention"] - sum(x["job"] for x in r["invention"]), 3 * (1000 + 2000))   # датакоры
        self.assertAlmostEqual(t["spend"], t["buy"] + t["jobs"] + t["invention"])
        self.assertAlmostEqual(t["profit"], t["revenue"] - t["cost"])
        p = r["products"][0]
        self.assertAlmostEqual(p["cost"], t["cost"])                                # один продукт — тот же итог
        self.assertAlmostEqual(p["unit_cost"], t["cost"] / 10)


class HistEsi(FakeEsi):
    def __call__(self, path, method="GET", body=None, **params):
        if path == "/markets/10000002/history/":
            return [{"date": f"2026-10-{d:02d}", "average": 300000 + d, "lowest": 290000, "highest": 340000, "volume": 100 + d}
                    for d in range(1, 21)], {}
        if path == "/universe/ids/" and body and "Морфит" in body:
            return {"inventory_types": [{"id": 11399, "name": "Морфит"}]}, {}
        return super().__call__(path, method, body, **params)


class TestProjects(unittest.TestCase):
    """Ведение производства: закреплённый чертёж, склад, вставка из игры, этапы, партии, снимки цен."""

    def setUp(self):
        self.td = TempDirs()
        self.calc = ind.Calculator(HistEsi(), DATA)
        self.pr = ind.Projects(self.calc, os.path.join(self.td.data, "industry_projects.json"))
        self.s = {"runs": 10, "me": 0, "te": 0, "industry": 0, "adv_industry": 0, "system": "Jita"}

    def tearDown(self):
        self.td.cleanup()

    def test_parse_stock(self):
        rows = ind.parse_stock("Tritanium\t1 000 000\tMineral\t\t10 000 m3\nPyerite 25,000\nMexallon x500\n3 x Vexor\n"
                               "Морфит\t2 000\nTritanium\t5\nDrake*\n\n")
        self.assertEqual(rows, [("Tritanium", 1000005), ("Pyerite", 25000), ("Mexallon", 500), ("Vexor", 3), ("Морфит", 2000), ("Drake", 1)])

    def test_flow(self):
        with self.assertRaises(ValueError):
            self.pr.create("Nothing", self.s)
        p = self.pr.create("Hobgoblin II", self.s, now=1000)
        d = self.pr.detail(p, now=1000)
        self.assertTrue(d["ok"])
        self.assertEqual({m["name"]: m["left"] for m in d["materials"]}, {"Hobgoblin I": 10, "Morphite": 20, "Nocxium": 100})
        self.assertEqual(d["totals"]["progress"], 0)
        self.assertEqual(d["totals"]["left_cost"], 10 * 4000 + 20 * 10000 + 100 * 600)
        self.assertEqual(len(d["snaps"]), 1)                                 # снимок цен для графика
        # склад из игры: английские и русские названия, чужое пропускается
        r = self.pr.paste(p, "Hobgoblin I\t10\nМорфит\t15\nVexor\t1", now=1000)
        self.assertEqual((r["matched"], r["skipped"]), (2, ["Vexor"]))
        d = self.pr.detail(p, now=1100)
        m = {x["name"]: x for x in d["materials"]}
        self.assertEqual((m["Hobgoblin I"]["left"], m["Morphite"]["left"], m["Morphite"]["have"]), (0, 5, 15))
        self.assertEqual(d["totals"]["have_cost"], 10 * 4000 + 15 * 10000)
        self.assertEqual(d["totals"]["ready"], 1)
        self.assertEqual(len(d["snaps"]), 1)                                 # не чаще раза в час
        self.pr.paste(p, "Morphite 10\nNocxium 120", mode="add", now=1200)
        d = self.pr.detail(p, now=5000)
        self.assertEqual(d["totals"]["progress"], 100.0)
        self.assertEqual(next(x for x in d["materials"] if x["name"] == "Nocxium")["extra"], 20)
        self.assertEqual(len(d["snaps"]), 2)
        # этапы: запуск → готово (материалы списаны, партия записана) → ещё партия
        self.pr.set_status(p, "building", now=6000)
        d = self.pr.detail(p, now=6000)
        self.assertEqual(d["eta"], 6000 + d["totals"]["top_time"])
        self.pr.toggle_job(p, f"{2456}:0", True)
        self.assertTrue(self.pr.detail(p, now=6100)["jobs"][0]["done"])
        self.pr.set_status(p, "done", now=9000)
        self.assertEqual(p["have"], {"38": 20, "11399": 5})                    # лишнее осталось на складе
        self.assertEqual(len(p["batches"]), 1)
        self.assertEqual(p["batches"][0]["units"], 10)
        self.assertEqual(p["batches"][0]["time"], 3000)
        self.pr.set_status(p, "collect", now=9100)
        self.assertEqual((p["status"], p["jobs_done"]), ("collect", []))
        # сохраняется и читается заново
        again = ind.Projects(self.calc, self.pr.path)
        self.assertEqual(again.get(p["id"])["have"], {"38": 20, "11399": 5})
        self.pr.update_settings(p, {"runs": 2}, "Хобы")
        self.assertEqual((p["settings"]["runs"], p["name"]), (2, "Хобы"))
        self.assertEqual(self.pr.summary(p, now=9200)["units"], 2)
        self.assertTrue(self.pr.delete(p["id"]))
        self.assertIsNone(self.pr.get(p["id"]))

    def test_raw_materials(self):
        p = self.pr.create("Hobgoblin II", self.s, now=1000)
        d = self.pr.detail(p, now=1000)
        raw = {m["name"]: m["qty"] for m in d["raw"]["materials"]}
        self.assertEqual(raw, {"Morphite": 20, "Nocxium": 100, "Tritanium": 4581, "Pyerite": 63})    # Hobgoblin I раскрыт до минералов (ME компонентов 10)
        r = self.pr.paste(p, "Tritanium 4581" + chr(10) + "Pyerite 35", now=1000)                               # склад узнаёт и сырьё
        self.assertEqual(r["matched"], 2)
        d = self.pr.detail(p, now=1000)
        rt = d["raw"]["totals"]
        self.assertEqual((rt["ready"], rt["positions"]), (1, 4))
        fams = {f["fam"]: f for f in rt["families"]}                     # шкалы по видам сырья
        self.assertEqual(fams["mineral"]["positions"], 4)
        self.assertEqual({m["name"]: m["fam_label"] for m in d["raw"]["materials"]}["Tritanium"], "минерал")
        self.assertGreater(rt["progress"], 0)
        self.assertEqual(d["totals"]["progress"], 0)                         # закупка по плану (Hobgoblin I) не тронута
        p2 = self.pr.create("Crystalline Carbonide", {"runs": 1, "structure": "tatara", "security": "null"}, now=1000)
        self.assertIsNone(self.pr.detail(p2, now=1000)["raw"])               # строить нечего — сырьё и есть закупка

    def test_draft_pin_build(self):
        d = self.pr.create("Hobgoblin II", self.s, now=1000, draft=True)
        d2 = self.pr.create("Hobgoblin II", self.s, now=1001, draft=True)            # новый черновик заменяет прежний
        self.assertIsNone(self.pr.get(d["id"]))
        self.assertTrue(self.pr.detail(d2, now=1001)["ok"])
        self.assertEqual(d2["snaps"], [])                                    # у черновика снимков цен нет
        self.pr.set_build(d2, 2454, True)                                    # Hobgoblin I строю сам
        det = self.pr.detail(d2, now=1002)
        self.assertEqual({m["name"] for m in det["materials"]}, {"Morphite", "Nocxium", "Tritanium", "Pyerite"})
        self.assertTrue(next(m for m in det["calc"]["tree"] if m["name"] == "Hobgoblin I")["built"])
        self.assertIn("compare", det["calc"])
        self.pr.pin(d2, now=1003)
        self.assertFalse(d2["draft"])

    def test_plan_project(self):
        p = self.pr.create("", self.s, "Хобы и карбонид", now=1000, items=[(2456, 10), (16670, 200)], mode="buy")
        d = self.pr.detail(p, now=1000)
        self.assertTrue(d["ok"])
        self.assertEqual(d["calc"]["kind"], "plan")
        self.assertEqual([x["name"] for x in d["calc"]["products"]], ["Hobgoblin II", "Crystalline Carbonide"])
        self.assertIn("Hobgoblin I", {m["name"] for m in d["materials"]})   # «покупаю компоненты»
        self.assertIsNotNone(d["raw"])                                      # полный цикл — сырьё
        self.assertIn("Tritanium", {m["name"] for m in d["raw"]["materials"]})
        self.assertEqual(d["calc"]["product"]["units"], 210)
        self.assertEqual({j["depth"] for j in d["jobs"]}, {0})
        self.pr.paste(p, "Hobgoblin I 10", now=1000)
        self.assertEqual(next(m for m in self.pr.detail(p, now=1000)["materials"] if m["name"] == "Hobgoblin I")["left"], 0)
        self.pr.set_status(p, "building", now=2000)
        self.pr.set_status(p, "done", now=3000)
        self.assertEqual(p["batches"][0]["units"], 210)
        self.assertEqual(self.pr.summary(p, now=3100)["kind"], "plan")

    def test_fit(self):
        fit = "[Hobgoblin II, test]\nHobgoblin I x3\nMorphite x10\nUnknown Thing\n[Empty High slot]\nHobgoblin II, Tritanium"
        r = ind.fit_items(self.calc, fit, 2)
        self.assertEqual(r["ship"], "Hobgoblin II")
        self.assertEqual({i["name"]: i["qty"] for i in r["items"]}, {"Hobgoblin II": 4, "Hobgoblin I": 6})
        self.assertEqual([b["name"] for b in r["buy"]], ["Morphite"])
        self.assertEqual([b["name"] for b in r["skipped"]], ["Unknown Thing"])
        with self.assertRaises(ValueError):
            ind.fit_items(self.calc, "   ")

    def test_tree(self):
        p = self.pr.create("Hobgoblin II", self.s, now=1000)
        t = self.pr.tree(p, False)
        self.assertEqual((t[0]["n"], t[0]["q"]), ("Hobgoblin II", 10))
        self.assertEqual({c["n"]: c["built"] for c in t[0]["c"]}, {"Hobgoblin I": False, "Morphite": False, "Nocxium": False})
        full = self.pr.tree(p, True)                                         # до минералов: Hobgoblin I раскрыт
        hob = next(c for c in full[0]["c"] if c["n"] == "Hobgoblin I")
        self.assertTrue(hob["built"])
        self.assertEqual(next(c for c in hob["c"] if c["n"] == "Tritanium")["f"], "mineral")
        self.assertEqual({c["n"] for c in hob["c"]}, {"Tritanium", "Pyerite"})
        plan = self.pr.create("", self.s, "П", now=1000, items=[(2456, 2), (2454, 5)], mode="buy")
        self.assertEqual([r["n"] for r in self.pr.tree(plan, False)], ["Hobgoblin II", "Hobgoblin I"])

    def test_leftovers(self):
        # продукт из 50 Crystalline Carbonide, а реакция даёт 200 за прогон: строим сами — 150 остаётся
        data = json.loads(json.dumps(DATA))
        data["bp"]["9999"] = [9998, "m", 100, 1, [[16670, 50]], 10]
        data["types"]["9999"] = ["Test Widget", 100, 18, 1.0]
        data["index"]["test widget"] = 9999
        global PRICES
        old = dict(PRICES)
        PRICES[9999] = 200000
        try:
            calc = ind.Calculator(HistEsi(), data)
            pr = ind.Projects(calc, os.path.join(self.td.data, "lp.json"))
            p = pr.create("Test Widget", dict(self.s, runs=1, build=[16670], structure="tatara", security="null"), now=1000)
            d = pr.detail(p, now=1000)
            left = d["calc"]["leftovers"]
            self.assertEqual([(r["name"], r["qty"], r["made"]) for r in left], [("Crystalline Carbonide", 150, 200)])
            self.assertEqual(d["totals"]["leftovers"], 150 * 1000 * 0.9)          # по цене мгновенной продажи
            base = d["calc"]["compare"]["sell"]
            self.assertAlmostEqual(base["profit"] - base["leftovers"] + d["totals"]["leftovers"], base["profit"])
            pr.set_status(p, "building", now=1100)
            pr.set_status(p, "done", consume=True, now=1200)
            self.assertEqual(p["have"].get("16670"), 150)                         # остаток — на склад
        finally:
            PRICES.clear()
            PRICES.update(old)

    def test_market_groups_and_ru_search(self):
        data = json.loads(json.dumps({k: v for k, v in DATA.items() if k != "index"}))
        data.update({"mg": {"4": [None, "Корабли", "Ships"], "1367": [4, "Крейсеры", "Cruisers"]}, "pmg": {"2456": 1367}, "ru": {"2456": "Хобгоблин II"}})
        path = os.path.join(self.td.data, "d.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        try:
            d = ind.load_data(path)
            calc = ind.Calculator(None, d)
            self.assertEqual(calc.find("хобгоблин ii"), 2456)                  # русское название — без ESI
            self.assertEqual([x["name"] for x in calc.search("хобгоб")], ["Hobgoblin II"])
            self.assertEqual(len(calc.search("hobgoblin")), 2)                  # английское и русское — не дублируются
        finally:
            ind.load_data(os.path.join(os.path.dirname(ind.__file__), "industry_data.json"))

    def test_price_series_cached(self):
        ser = self.pr.price_series("jita", 2456, now=100)
        self.assertEqual(len(ser), 20)
        self.assertEqual(ser[-1], ["2026-10-20", 300020, 290000, 340000, 120])
        n = len(self.calc.esi.calls)
        self.pr.price_series("jita", 2456, now=200)
        self.assertEqual(len(self.calc.esi.calls), n)


class TestProjectsHttp(unittest.TestCase):
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

            def req(path, method="GET", body=None):
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                h = {"Host": f"localhost:{port}"}
                if method == "POST":
                    h.update({"Origin": f"http://localhost:{port}", "X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json"})
                c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
                r = c.getresponse()
                out = json.loads(r.read())
                c.close()
                return out

            r = req("/api/industry/projects", "POST", {"action": "create", "product": "Vexor", "settings": {"runs": 2}})
            self.assertTrue(r["ok"])
            pid = r["id"]
            self.assertEqual([x["name"] for x in req("/api/industry/projects")["projects"]], ["Vexor"])
            d = req(f"/api/industry/project?id={pid}")
            self.assertTrue(d["ok"])
            first = d["materials"][0]
            self.assertTrue(req("/api/industry/projects", "POST", {"action": "have", "id": pid, "have": {str(first["type_id"]): first["qty"]}})["ok"])
            d = req(f"/api/industry/project?id={pid}")
            self.assertEqual(d["materials"][0]["left"], 0)
            self.assertTrue(req("/api/industry/projects", "POST", {"action": "paste", "id": pid, "text": first["name"] + "\t5", "mode": "add"})["ok"])
            self.assertTrue(req("/api/industry/projects", "POST", {"action": "status", "id": pid, "status": "building"})["ok"])
            self.assertFalse(req("/api/industry/projects", "POST", {"action": "status", "id": pid, "status": "nope"})["ok"])
            self.assertTrue(os.path.exists(os.path.join(td.data, "industry_projects.json")))
            self.assertTrue(req("/api/industry/projects", "POST", {"action": "delete", "id": pid})["ok"])
            r = req("/api/industry/projects", "POST", {"action": "draft", "product": "Vexor", "settings": {"me": 5}})
            self.assertTrue(r["ok"])
            self.assertEqual(req(f"/api/industry/project?id={r['id']}")["calc"]["settings"]["me"], 5)
            self.assertEqual(req("/api/industry/projects")["projects"], [])          # черновика в списке нет
            self.assertTrue(req("/api/industry/projects", "POST", {"action": "pin", "id": r["id"]})["ok"])
            self.assertEqual(len(req("/api/industry/projects")["projects"]), 1)
            self.assertTrue(req("/api/industry/projects", "POST", {"action": "settings", "id": r["id"], "settings": {"structure": "raitaru"}, "as_default": True})["ok"])
            self.assertEqual(req("/api/industry/settings")["settings"]["structure"], "raitaru")
            fit = req("/api/industry/fit", "POST", {"text": "[Vexor, x]\nDamage Control II", "count": 3})
            self.assertEqual(fit["ship"], "Vexor")
            self.assertIn({"id": 626, "name": "Vexor", "qty": 3}, fit["items"])
            self.assertFalse(req(f"/api/industry/project?id={pid}")["ok"])
            srv.shutdown()
            srv.server_close()
        finally:
            td.cleanup()


class TestPlanetary(unittest.TestCase):
    """Планетарка: цепочка P4 → P0 по схемам из SDE (pi_data.json)."""

    D = {"schematics": {"10": [3600, 1, [[20, 6], [21, 6]]],        # P4 ← 2 × P3
                        "20": [3600, 3, [[30, 10], [31, 10]]],      # P3 ← 2 × P2
                        "21": [3600, 3, [[30, 10]]],
                        "30": [3600, 5, [[40, 40], [41, 40]]],      # P2 ← 2 × P1
                        "31": [3600, 5, [[40, 40]]],
                        "40": [1800, 20, [[50, 3000]]],             # P1 ← P0
                        "41": [1800, 20, [[51, 3000]]]},
         "types": {"10": ["Node", "", 4, 100], "20": ["Chip", "", 3, 6], "21": ["Neo", "", 3, 6], "30": ["Glass", "", 2, 1.5],
                   "31": ["Fiber", "", 2, 1.5], "40": ["Water", "", 1, 0.38], "41": ["Oxygen", "", 1, 0.38],
                   "50": ["Aqueous Liquids", "", 0, 0.01], "51": ["Noble Gas", "", 0, 0.01]},
         "planets": {"50": ["barren", "gas", "ice"], "51": ["gas", "ice", "storm"]}}

    def test_chain_sums_needs_before_rounding(self):
        r = ind.pi_plan(self.D, [(10, 2)], days=1)
        st = {s["type_id"]: s for s in r["steps"]}
        self.assertEqual((st[10]["runs"], st[20]["need"], st[21]["need"]), (2, 12, 12))
        self.assertEqual((st[20]["runs"], st[21]["runs"]), (4, 4))          # 12 / 3 за цикл
        self.assertEqual(st[30]["need"], 80)                                # Glass нужен обоим P3: 40 + 40 — сложили, потом округлили
        self.assertEqual((st[30]["runs"], st[31]["runs"]), (16, 8))
        self.assertEqual(st[40]["need"], 16 * 40 + 8 * 40)                  # Water — в Glass и в Fiber
        self.assertEqual(st[40]["runs"], 48)                                # 960 / 20
        raw = {x["type_id"]: x for x in r["raw"]}
        self.assertEqual(raw[50]["qty"], 48 * 3000)
        self.assertEqual(raw[50]["per_hour"], 6000)                         # за сутки
        self.assertEqual(st[40]["factories"], 1)                            # 48 циклов × 30 мин = 24 ч — одна фабрика за сутки
        self.assertEqual(r["cover"], ["gas"])                               # одна планета даёт оба сырья
        self.assertTrue(r["high_tech"])

    def test_leftovers_targets_and_factories(self):
        r = ind.pi_plan(self.D, [(30, 7), (40, 5)], days=0.5)
        st = {s["type_id"]: s for s in r["steps"]}
        self.assertEqual((st[30]["runs"], st[30]["produced"], st[30]["left"]), (2, 10, 3))
        self.assertEqual((st[40]["target"], st[40]["need"]), (5, 5 + 80))   # заказано 5 и нужно 80 на Glass
        self.assertEqual(st[40]["runs"], 5)
        self.assertEqual(st[30]["factories"], 1)
        self.assertFalse(r["high_tech"])
        self.assertEqual(ind.pi_plan(self.D, [(999, 5), (10, 0)])["steps"], [])   # неизвестное и ноль — пропускаем

    def test_layout_by_planet(self):
        r = ind.pi_plan(self.D, [(10, 2)], days=1)
        lay = ind.pi_layout(self.D, r, extract_h=6000, per_planet=5)
        ex = [p for p in lay["planets"] if p["role"] == "extract"]
        fa = [p for p in lay["planets"] if p["role"] == "factory"]
        # сырья 144 000 + 96 000 за сутки = 6000 + 4000 в час: Aqueous — ровно одна планета, Noble Gas — ещё одна (Gas)
        self.assertEqual([p["kind"] for p in ex], ["gas", "gas"])
        self.assertEqual(sorted(e["per_hour"] for p in ex for e in p["extract"]), [4000, 6000])
        self.assertEqual(sum(p["basic"] for p in ex), 2)
        exports = {e["name"]: e["per_day"] for p in ex for e in p["export"]}
        self.assertEqual(exports, {"Water": 960, "Oxygen": 640})            # 6000/ч → 40 P1/ч
        # заводы: фабрики P2 (Glass 1 + Fiber 1) + P3 (1 + 1) + P4 (1) = 5 — одна планета, и она Barren/Temperate (там P4)
        self.assertEqual(len(fa), 1)
        self.assertEqual((fa[0]["used"], fa[0]["kind"]), (5, "barren/temperate"))
        imp = {e["name"]: e["per_day"] for e in fa[0]["import"]}
        self.assertEqual(imp, {"Water": 960, "Oxygen": 640})                # Glass и Fiber берут Water; Oxygen — только Glass
        self.assertEqual({e["name"]: e["per_day"] for e in fa[0]["export"]}, {"Node": 2})   # промежуточное съедено тут же
        self.assertEqual((lay["count"], lay["characters"]), (3, 1))
        lay2 = ind.pi_layout(self.D, r, extract_h=2000, per_planet=2)
        self.assertEqual(sum(1 for p in lay2["planets"] if p["role"] == "extract"), 5)   # 6000 → 3 планеты, 4000 → 2
        self.assertEqual(sum(1 for p in lay2["planets"] if p["role"] == "factory"), 3)

    def test_layout_without_assembly_planets(self):
        r = ind.pi_plan(self.D, [(10, 2)], days=1)
        lay = ind.pi_layout(self.D, r, extract_h=6000, per_planet=5, mode="local", local_slots=3)
        self.assertEqual(lay["mode"], "local")
        roles = [p["role"] for p in lay["planets"]]
        # 5 сборочных фабрик, на двух добывающих по 3 места; P4 нельзя на Gas — его фабрика уходит на заводскую Barren/Temperate
        self.assertEqual((roles.count("extract"), roles.count("factory")), (2, 1))
        self.assertEqual(lay["spilled"], 1)
        fa = next(p for p in lay["planets"] if p["role"] == "factory")
        self.assertEqual([m["name"] for m in fa["make"]], ["Node"])
        self.assertEqual(fa["kind"], "barren/temperate")
        # Glass (из Water и Oxygen) встал туда, где оба P1 уже есть или где больше входов — и ввоз сходится с вывозом
        exp, imp = {}, {}
        for p in lay["planets"]:
            for e in p["export"]:
                exp[e["name"]] = exp.get(e["name"], 0) + e["per_day"]
            for e in p["import"]:
                imp[e["name"]] = imp.get(e["name"], 0) + e["per_day"]
        for k, v in imp.items():
            self.assertAlmostEqual(exp.get(k, 0) - (2 if k == "Node" else 0), v, delta=1, msg=k)
        self.assertEqual(exp.get("Node"), 2)
        full = ind.pi_layout(self.D, r, mode="local", local_slots=10, per_planet=5)
        self.assertEqual(full["spilled"], 1)                               # P4 на Gas нельзя — всегда завод
        d2 = dict(self.D, planets={"50": ["barren"], "51": ["barren"]})
        r2 = ind.pi_plan(d2, [(10, 2)], days=1)
        self.assertEqual(ind.pi_layout(d2, r2, mode="local", local_slots=10)["spilled"], 0)   # Barren — всё на месте

    def test_game_data(self):
        d = ind.load_pi()
        cat = ind.pi_catalog(d)
        self.assertEqual(len(cat), 68)                                      # 15 P1 + 24 P2 + 21 P3 + 8 P4
        self.assertEqual(sorted({r[2] for r in cat}), [1, 2, 3, 4])
        self.assertEqual(len(d["planets"]), 15)                             # у каждого сырья P0 — типы планет
        r = ind.pi_plan(d, [(cat[-1][0], 1)])
        self.assertTrue(r["raw"] and all(x["planets"] for x in r["raw"]))
