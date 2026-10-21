# -*- coding: utf-8 -*-
"""Оценка предметов (как Janice): разбор вставленного текста, цены хаба, итоги, история."""
import unittest
from urllib.parse import parse_qs

from helpers import TempDirs
from helpers import module

ap = module("appraisal")

TYPES = {"tritanium": 34, "pyerite": 35, "hobgoblin ii": 2456, "250mm railgun ii": 3082, "пирит": 35}
INFO = {34: ("Tritanium", 0.01, None), 35: ("Pyerite", 0.01, None), 2456: ("Hobgoblin II", 5.0, 5.0), 3082: ("250mm Railgun II", 20.0, 10.0)}
BOOK = {34: ([3.9, 4.0], [4.2, 4.5]), 35: ([15.0], [16.0]), 2456: ([], [900000.0]), 3082: ([], [])}


class FakeEsi:
    def __init__(self):
        self.calls = []

    def __call__(self, path, method="GET", body=None, **params):
        self.calls.append((path, params.get("language"), params.get("type_id")))
        if path == "/universe/ids/":
            found = [{"id": TYPES[n.lower()], "name": n} for n in body if n.lower() in TYPES and (params["language"] == "ru") == (n == "Пирит")]
            return {"inventory_types": found}, {}
        if path.startswith("/universe/types/"):
            tid = int(path.split("/")[3])
            n, v, pv = INFO[tid]
            return {"name": n, "volume": v, "packaged_volume": pv}, {}
        if path == "/markets/10000002/orders/":
            buys, sells = BOOK[params["type_id"]]
            orders = [{"is_buy_order": True, "price": p, "location_id": 60003760} for p in buys]
            orders += [{"is_buy_order": False, "price": p, "location_id": 60003760} for p in sells]
            orders.append({"is_buy_order": False, "price": 0.01, "location_id": 123})           # другая станция — не в счёт
            return orders, {"X-Pages": "1"}
        if path == "/markets/10000002/history/":
            return [{"date": f"2026-10-{d:02d}", "average": 4.0 if params["type_id"] == 34 else 16.0, "volume": 10} for d in range(1, 12)], {}
        raise RuntimeError(path)


class TestParse(unittest.TestCase):
    def test_formats(self):
        text = "\n".join([
            "Tritanium\t15 933\tМинерал\t\t159,33 м3",   # инвентарь из игры (русский клиент)
            "Pyerite\t1,000",
            "Hobgoblin II x 5",
            "3 x 250mm Railgun II",
            "250mm Railgun II x 2",
            "Tritanium 67",
            "[Vexor, PvE]",                            # заголовок EFT — пропуск
            "Hobgoblin II",                            # без количества = 1
            "Pyerite\t2.500",
            "500 Hobgoblin II",                        # количество впереди без «x»
            "1 000 Tritanium",
            "",
        ])
        items, bad = ap.parse(text)
        self.assertEqual(items, [("Tritanium", 17000), ("Pyerite", 3500), ("Hobgoblin II", 506), ("250mm Railgun II", 5)])
        self.assertEqual(ap.parse("250mm Railgun II")[0], [("250mm Railgun II", 1)])          # «250mm» — не количество
        self.assertEqual(bad, [])
        self.assertEqual([ap.parse_qty(x) for x in ("15 933", "15,933", "1.000.000", "2x", "12,5", "abc", "")],
                         [15933, 15933, 1000000, 2, 12, None, None])


class TestAppraise(unittest.TestCase):
    def setUp(self):
        self.td = TempDirs()
        self.esi = FakeEsi()
        self.a = ap.Appraiser(self.td.data, self.esi)

    def tearDown(self):
        self.td.cleanup()

    def test_prices_totals_history(self):
        r = self.a.appraise("Tritanium\t1000\nПирит 10\nHobgoblin II x 2\n250mm Railgun II\nNo Such Thing 5", "jita", "split", now=1000)
        self.assertTrue(r["ok"])
        rows = {x["name"]: x for x in r["rows"]}
        t = rows["Tritanium"]
        self.assertEqual((t["buy"], t["sell"], t["split"], t["buy_total"], t["sell_total"]), (4.0, 4.2, 4.1, 4000.0, 4200.0))
        self.assertAlmostEqual(t["volume"], 10.0)
        self.assertEqual((t["buy_change"], t["sell_change"]), (0.0, 5.0))           # к средней за 7 дней (4,0)
        self.assertEqual((rows["Pyerite"]["input"], rows["Pyerite"]["qty"]), ("Пирит", 10))   # русское название найдено
        h = rows["Hobgoblin II"]
        self.assertEqual((h["buy"], h["sell"], h["split"], h["volume"]), (None, 900000.0, 900000.0, 10.0))
        self.assertEqual(rows["250mm Railgun II"]["split"], None)                     # нет ордеров — без цены
        self.assertEqual(r["missing"], ["No Such Thing"])
        tot = r["totals"]
        self.assertEqual((tot["buy"], tot["sell"], tot["split"], tot["items"], tot["no_price"]), (4150.0, 1804360.0, 1804255.0, 4, 1))
        # сохранена и находится
        self.assertEqual(self.a.get(r["code"])["totals"], tot)
        self.assertEqual([x["code"] for x in self.a.list()], [r["code"]])
        self.assertIsNone(self.a.get("../../config"))
        # повторная оценка в течение 5 минут — без новых запросов к рынку
        n = sum(1 for c in self.esi.calls if c[0].endswith("/orders/"))
        self.a.appraise("Tritanium 5", now=1100)
        self.assertEqual(sum(1 for c in self.esi.calls if c[0].endswith("/orders/")), n)

    def test_empty_and_modes(self):
        r = self.a.appraise("   \n\n")
        self.assertFalse(r["ok"])
        r = self.a.appraise("Tritanium 1", market="nowhere", mode="weird", now=5)
        self.assertEqual((r["market"], r["mode"], r["market_name"]), ("jita", "split", "Jita 4-4"))


class TestAppraisalHttp(unittest.TestCase):
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
                try:
                    out = (r.status, json.loads(raw))
                except ValueError:
                    out = (r.status, raw.decode("utf-8", "replace"))
                c.close()
                return out
            ap.setup(ctx(app, "appraisal"))                                                           # онлайн выключен
            self.assertFalse(req("/api/appraise", "POST", {"text": "Tritanium 1"})[1]["ok"])
            app.online = types.SimpleNamespace(esi=FakeEsi(), cache={}, lock=threading.RLock())
            ap.setup(ctx(app, "appraisal"))
            code, r = req("/api/appraise", "POST", {"text": "Tritanium 100\nPyerite 10", "market": "jita", "mode": "sell"})
            self.assertEqual((code, r["ok"], r["totals"]["sell"]), (200, True, 580.0))
            self.assertEqual(req("/api/appraise", "POST", {"text": "x"}, origin=False)[0], 403)        # чужой сайт не может
            self.assertEqual(req(f"/api/appraisal?code={r['code']}")[1]["totals"]["items"], 2)
            self.assertEqual(req("/api/appraisal?code=../x")[0], 404)
            self.assertEqual([a["code"] for a in req("/api/appraisals")[1]["appraisals"]], [r["code"]])
            self.assertFalse(req("/api/appraise", "POST", {"nope": 1})[1]["ok"])
            srv.shutdown()
            srv.server_close()
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
