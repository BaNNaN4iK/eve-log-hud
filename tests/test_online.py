# -*- coding: utf-8 -*-
"""Онлайн-часть на поддельном локальном ESI: справочники, иконки, цены Jita, список разрешённых хостов."""
import json
import os
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from helpers import TempDirs, elw, make_cfg

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
CALLS = []


class FakeESI(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, headers=None):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        CALLS.append(("POST", u.path, self.headers.get("User-Agent")))
        names = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        known_t = {"Veldspar": 1230, "Hobgoblin I": 2454}
        known_s = {"Jita": 30000142}
        self._json({"inventory_types": [{"id": known_t[n], "name": n} for n in names if n in known_t],
                    "systems": [{"id": known_s[n], "name": n} for n in names if n in known_s]})

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        CALLS.append(("GET", u.path, self.headers.get("User-Agent")))
        p = u.path
        if p == "/latest/universe/types/1230/":
            return self._json({"name": "Вельдспар", "volume": 0.1, "packaged_volume": 0.1, "group_id": 462})
        if p == "/latest/universe/types/2454/":
            return self._json({"name": "Hobgoblin I", "volume": 5.0, "group_id": 100})
        if p == "/latest/universe/groups/462/":
            return self._json({"name": "Вельдспар", "category_id": 25})
        if p == "/latest/universe/groups/100/":
            return self._json({"name": "Боевой дрон", "category_id": 18})
        if p.startswith("/latest/universe/categories/"):
            return self._json({"name": "Категория"})
        if p == "/latest/universe/systems/30000142/":
            return self._json({"name": "Jita", "security_status": 0.9459, "constellation_id": 20000020})
        if p == "/latest/universe/constellations/20000020/":
            return self._json({"name": "Kimotoro", "region_id": 10000002})
        if p == "/latest/universe/regions/10000002/":
            return self._json({"name": "The Forge"})
        if p == "/latest/markets/prices/":
            return self._json([{"type_id": 1230, "average_price": 20.5}, {"type_id": 34, "average_price": 4}])
        if p == "/latest/markets/10000002/orders/":
            page = int(q.get("page", ["1"])[0])
            if page == 1:
                orders = [{"is_buy_order": True, "location_id": 60003760, "price": 18.0, "volume_remain": 100},
                          {"is_buy_order": True, "location_id": 60008494, "price": 99.0, "volume_remain": 100},
                          {"is_buy_order": False, "location_id": 60003760, "price": 22.0, "volume_remain": 5}]
            else:
                orders = [{"is_buy_order": True, "location_id": 60003760, "price": 19.5, "volume_remain": 50,
                           "min_volume": 1},
                          {"is_buy_order": False, "location_id": 60003760, "price": 21.0, "volume_remain": 5}]
            return self._json(orders, {"X-Pages": "2"})
        if p.startswith("/types/") and p.endswith("/icon"):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(PNG)
            return
        self.send_response(404)
        self.end_headers()


class TestOnline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeESI)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        elw.ALLOWED_HOSTS.add("127.0.0.1")

    @classmethod
    def tearDownClass(cls):
        elw.ALLOWED_HOSTS.discard("127.0.0.1")
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.td = TempDirs()
        CALLS.clear()
        base = f"http://127.0.0.1:{self.port}"
        self.on = elw.Online(self.td.data, make_cfg(self.td.logs, esi_contact="test@example.invalid"),
                             esi_base=base + "/latest", img_base=base)

    def tearDown(self):
        self.td.cleanup()

    def test_resolve_types_systems_icons(self):
        added = self.on.resolve({"Veldspar", "Hobgoblin I", "Unknown Thing"}, {"Jita"}, {})
        self.assertEqual(added, 3)
        t = self.on.cache["types"]
        self.assertEqual((t["Veldspar"]["id"], t["Veldspar"]["volume"], t["Veldspar"]["name_ru"]), (1230, 0.1, "Вельдспар"))
        self.assertEqual(t["Hobgoblin I"]["category_id"], 18)
        self.assertTrue(t["Unknown Thing"]["missing"])
        s = self.on.cache["systems"]["Jita"]
        self.assertEqual((s["region"], s["constellation"], round(s["sec"], 2)), ("The Forge", "Kimotoro", 0.95))
        self.assertTrue(os.path.exists(self.on.icon_path(1230)))
        self.assertTrue(os.path.exists(os.path.join(self.td.data, "esi_cache.json")))
        # повторно ничего не запрашивается
        n = len(CALLS)
        self.assertEqual(self.on.resolve({"Veldspar", "Unknown Thing"}, {"Jita"}, {}), 0)
        self.assertEqual(len(CALLS), n)
        # User-Agent с названием приложения и контактом
        self.assertTrue(all("EVELogWatcher/" in c[2] and "test@example.invalid" in c[2] for c in CALLS))

    def test_aliases_used_for_lookup(self):
        self.on.resolve({"Вельдспар-рус"}, set(), {"Вельдспар-рус": "Veldspar"})
        self.assertEqual(self.on.cache["types"]["Veldspar"]["id"], 1230)
        self.assertEqual(self.on.ore_type_ids(["Вельдспар-рус"], {"Вельдспар-рус": "Veldspar"}), [1230])

    def test_prices_jita_only_and_pagination(self):
        ok, msg = self.on.start_price_refresh([1230])
        self.assertTrue(ok, msg)
        end = time.time() + 10
        while self.on.price_status["state"] == "running" and time.time() < end:
            time.sleep(0.05)
        self.assertEqual(self.on.price_status["state"], "ok", self.on.price_status)
        p = self.on.prices["types"]["1230"]
        self.assertEqual(p["buy"], 19.5)             # ордер другой станции (99) не учитывается
        self.assertEqual(p["sell"], 21.0)
        self.assertEqual(p["avg"], 20.5)
        self.assertEqual([b[0] for b in p["buy_book"]], [19.5, 18.0])
        self.assertTrue(os.path.exists(os.path.join(self.td.data, "prices.json")))
        # не чаще раза в 5 минут
        ok, msg = self.on.start_price_refresh([1230])
        self.assertFalse(ok)
        self.assertIn("5 минут", msg)

    def test_disallowed_host(self):
        with self.assertRaises(elw.OnlineError):
            self.on.request("https://example.com/x")
        with self.assertRaises(elw.OnlineError):
            self.on.request("https://evil.evetech.net.example.org/x")

    def test_network_error_is_online_error(self):
        dead = elw.Online(self.td.data, make_cfg(self.td.logs), esi_base="http://127.0.0.1:9/latest")
        with self.assertRaises(elw.OnlineError):
            dead.resolve({"Veldspar"}, set(), {})


if __name__ == "__main__":
    unittest.main()
