# -*- coding: utf-8 -*-
"""Модуль «Справочник», раздел «Руда»: семейства руд, варианты и сжатая руда, где добывается, выход, ISK за м³."""
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
        self.assertEqual((v["cat"], v["where"], v["portion"]), ("standard", ["hs", "ls", "ns", "wh"], 100))
        self.assertEqual(v["mats"], [[34, 400]])
        self.assertAlmostEqual(v["isk_m3"], 400 * 4.0 / (100 * 0.1))      # 1600 ISK за 10 м³ порции
        self.assertEqual([x["bonus"] for x in v["variants"] if not x["compressed"]], [-50, 5, 10, 15])   # 0-Grade — бедная
        self.assertTrue(any(x["compressed"] for x in v["variants"]))
        self.assertIn("Deep Core", ores["Mercoxit"]["note"])
        self.assertEqual(ores["Mercoxit"]["where"], ["ns", "wh"])
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


if __name__ == "__main__":
    unittest.main()
