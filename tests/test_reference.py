# -*- coding: utf-8 -*-
"""Модуль «Справочник»: «Руда» (семейства, варианты, где добывается, ISK за м³), «Чертежи», «Фракционные войны»."""
import time
import unittest

from helpers import module

ref = module("reference")


class TestOres(unittest.TestCase):
    def test_split_name(self):
        self.assertEqual(ref.split_name("Batch Compressed Veldspar II-Grade"), ("Veldspar", "II", True))
        self.assertEqual(ref.split_name("Glistening Zeolites"), ("Zeolites", "Glistening", False))
        self.assertEqual(ref.split_name("Mordunium IV-Grade"), ("Mordunium", "IV", False))
        self.assertEqual(ref.split_name("Raspite X-Grade"), ("Raspite X-Grade", "", False))
        self.assertEqual(ref.split_name("Veldspar 0-Grade"), ("Veldspar", "0", False))

    def test_table_from_game_data(self):
        data = ref.load_data()
        self.assertGreater(len(data["ores"]), 300)                       # справочник игры внутри модуля
        t = ref.ore_table(data, {34: 4.0, 35: 10.0})
        ores = {r["name"]: r for r in t["ores"]}
        v = ores["Veldspar"]
        self.assertEqual((v["cat"], v["where"], v["portion"]), ("standard", ["hs", "ns"], 100))
        self.assertEqual(v["mats"], [[34, 400]])
        self.assertAlmostEqual(v["isk_m3"], 400 * 4.0 / (100 * 0.1))      # 1600 ISK за 10 м³ порции
        self.assertEqual([x["bonus"] for x in v["variants"] if not x["compressed"]], [-50, 5, 10, 15])   # 0-Grade — бедная
        self.assertTrue(any(x["compressed"] for x in v["variants"]))
        self.assertTrue(any("Deep Core" in p["text"] for p in ores["Mercoxit"]["places"]))
        self.assertEqual(ores["Mercoxit"]["where"], ["ns", "pv"])
        # где именно: Kernite и Omber — аномалии хай-сека любой империи (в т.ч. Калдари), пояса лоу-сека по империям
        k, o = ores["Kernite"], ores["Omber"]
        self.assertTrue(any(p["sec"] == "hs" and "Kernite and Omber Deposit" in p["text"] for p in k["places"]))
        self.assertIn("caldari", k["empires"])
        self.assertIn("caldari", o["empires"])
        self.assertEqual(next(p for p in o["places"] if p["sec"] == "ls")["empires"], ["gallente", "minmatar"])
        self.assertEqual(ores["Hedbergite"]["places"][0]["empires"], ["caldari", "minmatar"])   # пояса — Калдари и Минматар
        self.assertEqual(ores["Ytirium"]["where"], ["hs", "ls", "ns", "wh"])        # пограничные сайты
        self.assertIn("Zeolites", ores)                                  # лунные руды одной группы — разные семейства
        self.assertIn("Sylvite", ores)
        self.assertEqual(ores["Zeolites"]["rank"], "R4 · повсеместная")
        self.assertEqual(ores["Talassonite"]["where"], ["pv"])
        self.assertEqual(ores["Kylixium"]["cat"], "equinox")
        special = [r for r in t["ores"] if r["cat"] == "special"]
        self.assertTrue(special and all(r["where"] == [] for r in special))
        self.assertEqual(t["materials"]["34"], "Tritanium")
        self.assertEqual(ores["Banidine"]["cat"], "special")                  # не перерабатывается — не «обычная руда»
        self.assertNotIn("Veldspar 0-Grade", ores)



class TestBlueprints(unittest.TestCase):
    def test_sources_from_game_data(self):
        d = ref.load_bp()
        self.assertGreater(len(d["bp"]), 4000)
        cat = ref.bp_catalog(d)
        self.assertEqual(len(cat["items"]), len(d["bp"]))
        by = {r[1]: str(r[0]) for r in cat["items"]}
        car = ref.bp_detail(d, by["Caracal"])
        self.assertEqual(car["sources"], ["market"])                       # T1 — оригинал у NPC
        self.assertEqual(car["market_path"][-1], "Калдарские")
        self.assertTrue(car["materials"] and car["base_price"] > 0)
        hob = ref.bp_detail(d, by["Hobgoblin II"])
        self.assertEqual(hob["sources"], ["inv"])                          # T2 — изобретение из копии T1
        self.assertEqual(hob["invention"][0]["source_name"], "Hobgoblin I Blueprint")
        self.assertEqual(len(hob["invention"][0]["datacores"]), 2)
        tengu = ref.bp_detail(d, by["Tengu"])
        self.assertEqual(tengu["sources"], ["rev"])                        # T3 — из реликвий
        self.assertTrue(all(x["relic"] for x in tengu["invention"]))
        cni = ref.bp_detail(d, by["Caracal Navy Issue"])
        self.assertIn("lp", cni["sources"])                                # фракционная копия — LP-магазин
        self.assertTrue(cni["lp"] and cni["lp"][0]["corps"] and cni["lp"][0]["lp"] > 0)
        self.assertIsNone(ref.bp_detail(d, "0"))


class TestFactionWarfare(unittest.TestCase):
    def test_factions_from_game_data(self):
        d = ref.load_fw()
        fs = ref.fw_factions(d)
        self.assertEqual({f["id"] for f in fs}, {500001, 500002, 500003, 500004, 500010, 500011})   # 4 империи и 2 пиратские
        amarr = next(f for f in fs if f["id"] == 500003)
        self.assertEqual((amarr["ru"], amarr["militia_id"]), ("Амаррская Империя", 1000179))
        self.assertIn("Республика Минматар", amarr["against_names"])
        self.assertGreater(amarr["offers"], 100)
        self.assertTrue(next(f for f in fs if f["id"] == 500010)["pirate"])

    def test_store_isk_per_lp(self):
        d = {"offers": {"7": [[100, 2, 1000, 50000, 0, [[200, 1]]], [300, 1, 500, 0, 0, []], [400, 1, 10, 0, 0, []]]},
             "types": {"100": ["Navy Thing", "Флотская вещь", 1, 7], "200": ["Tag", "", 2, 17], "300": ["Ship Blueprint", "", 3, 9],
                       "400": ["Odd", "", 1, 7]},
             "groups": {"1": "Модули"}, "cats": {"7": "Модули", "9": "Чертежи", "17": "Товары"}}
        s = ref.fw_store(d, "7", {100: 1_000_000, 200: 150_000, 300: 9e9})
        o = {x["type_id"]: x for x in s["offers"]}
        self.assertEqual(o[100]["value"], 2_000_000)
        self.assertEqual(o[100]["isk_lp"], 1800.0)                     # (2 млн − 50 тыс. − 150 тыс.) / 1000 LP
        self.assertIsNone(o[300]["isk_lp"])                             # копия чертежа — средней цены нет
        self.assertIsNone(o[400]["isk_lp"])                             # нет цены — нет оценки
        self.assertEqual(s["cats"][0], [7, "Модули", 2])
        self.assertIsNone(ref.fw_store(d, "8"))
        bp = {"bp": {"300": [587, "m", 1]}, "types": {"587": ["Rifter", "", 25, 6]}}
        o = {x["type_id"]: x for x in ref.fw_store(d, "7", {}, bp)["offers"]}
        self.assertEqual(o[300]["product"], {"type_id": 587, "name": "Rifter"})   # копия чертежа → что строить (в план производства)
        self.assertIsNone(o[100]["product"])

    def test_live_stats(self):
        stats = [{"faction_id": 500001, "systems_controlled": 60, "pilots": 100, "kills": {"yesterday": 5, "last_week": 40},
                  "victory_points": {"yesterday": 900, "last_week": 7000}}]
        systems = [{"occupier_faction_id": 500001, "contested": "contested"}, {"occupier_faction_id": 500001, "contested": "vulnerable"},
                   {"occupier_faction_id": 500001, "contested": "uncontested"}, {"occupier_faction_id": 500002, "contested": "contested"}]
        live = ref.fw_live(stats, systems)
        self.assertEqual(live[500001], {"systems": 60, "pilots": 100, "kills_day": 5, "kills_week": 40, "vp_day": 900, "vp_week": 7000,
                                        "contested": 2, "vulnerable": 1})
        self.assertNotIn(500002, live)

    def test_prices_refetch_for_new_items(self):
        calls = []
        p = ref.Prices(lambda path: (calls.append(path), ([{"type_id": 1, "average_price": 5.0}, {"type_id": 2, "average_price": 7.0}], {}))[1])
        p.prices, p.at = {1: 5.0}, int(time.time())                    # свежий кэш, но собран без предмета 2
        p.get({1, 2})
        for _ in range(50):
            if not p.busy and calls:
                break
            time.sleep(0.02)
        self.assertEqual(calls, ["/markets/prices/"])
        self.assertEqual(p.get({1, 2}), {1: 5.0, 2: 7.0})
        self.assertEqual(len(calls), 1)                                # перекачали один раз


if __name__ == "__main__":
    unittest.main()
