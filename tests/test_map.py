# -*- coding: utf-8 -*-
"""Модуль «Карта»: вселенная (поиск, прыжки), логи чата (где персонаж, разведка), активность ESI."""
import os
import tempfile
import time
import unittest

from helpers import module

mp = module("map")

MINI = {"regions": {"1": "Alpha"}, "constellations": {"10": ["C", 1]},
        "systems": {"100": ["Jita", 10, 0.95, 0, 0, 0, 0, 0], "101": ["Perimeter", 10, 0.95, 1, 0, 0, 0, 0],
                    "102": ["New Caldari", 10, 1.0, 2, 0, 0, 0, 0], "103": ["1DQ1-A", 10, -0.4, 3, 0, 0, 0, 0]},
        "gates": [[100, 101], [101, 102], [102, 103]]}


def chat_file(path, channel, listener, lines):
    head = ("﻿\r\n\r\n\r\n        ---------------------------------------------------------------\r\n\r\n"
            f"          Channel ID:      x\r\n          Channel Name:    {channel}\r\n          Listener:        {listener}\r\n"
            "          Session started: 2026.11.10 22:55:18\r\n        ---------------------------------------------------------------\r\n\r\n")
    with open(path, "wb") as f:
        f.write((head + "".join("﻿" + l + "\r\n" for l in lines)).encode("utf-16-le"))


class TestMap(unittest.TestCase):
    def test_universe(self):
        u = mp.Universe(MINI)
        self.assertEqual(u.find("jita*"), 100)
        self.assertEqual(u.jumps([100], 10), {100: 0, 101: 1, 102: 2, 103: 3})
        self.assertEqual(u.region(103), 1)
        self.assertEqual(u.systems_in("New Caldari*  Jita  hostile"), ([102, 100], False))
        self.assertEqual(u.systems_in("1dq1-a clr"), ([103], True))
        self.assertEqual(u.systems_in("Cassandra Cadelane"), ([], False))

    def test_game_data(self):
        u = mp.Universe(mp.load_map())
        self.assertGreater(len(u.sys), 5000)
        self.assertEqual(u.jumps([u.find("Jita")], 1)[u.find("Perimeter")], 1)

    def test_chat_location_and_intel(self):
        u = mp.Universe(MINI)
        with tempfile.TemporaryDirectory() as d:
            now = time.time()
            stamp = time.strftime("%Y.%m.%d %H:%M:%S", time.gmtime(now - 60))
            chat_file(os.path.join(d, "Local_1.txt"), "Локальный", "Pilot A",
                      [f"[ {stamp} ] Система EVE > Канал изменен на Локальный: Perimeter*"])
            chat_file(os.path.join(d, "Intel_1.txt"), "Dronelands_Intel", "Pilot A",
                      [f"[ {stamp} ] Scout > 1DQ1-A*  Enemy Pilot", f"[ {stamp} ] Scout > Jita clr"])
            c = mp.Chat(u, d, [])
            c.scan(now)
            self.assertEqual(c.where["Pilot A"][0], 101)
            self.assertEqual(c.recent(now), [])                         # канал не выбран
            c.set_intel(["Dronelands_Intel"])
            c.scan(now)
            r = c.recent(now)
            self.assertEqual([(x["systems"], x["clear"]) for x in r], [([103], False), ([100], True)])
            self.assertIn("Dronelands_Intel", c.channels)
            with open(os.path.join(d, "Intel_1.txt"), "ab") as f:      # дописали строку — читается только новое
                f.write(("﻿[ " + stamp + " ] Scout > New Caldari\r\n").encode("utf-16-le"))
            c.scan(now)
            self.assertEqual([x["systems"] for x in c.recent(now)], [[103], [100], [102]])

    def test_chat_dir(self):
        self.assertEqual(mp.chat_dir_for(os.path.join("C:", "EVE", "logs", "Gamelogs")), os.path.join("C:", "EVE", "logs", "Chatlogs"))
        self.assertEqual(mp.chat_dir_for(""), "")

    def test_activity(self):
        def esi(path, method="GET", body=None):
            return {"/universe/system_jumps/": [{"system_id": 100, "ship_jumps": 50}],
                    "/universe/system_kills/": [{"system_id": 100, "npc_kills": 3, "ship_kills": 2, "pod_kills": 1}],
                    "/incursions/": [{"infested_solar_systems": [101]}],
                    "/sovereignty/map/": [{"system_id": 103, "alliance_id": 99}],
                    "/universe/names/": [{"id": 99, "name": "Goonswarm"}]}[path], {}
        a = mp.Activity(esi)
        a.refresh()
        self.assertEqual((a.data[100], a.incursions, a.sov, a.names), ([50, 3, 2, 1], [101], {103: 99}, {99: "Goonswarm"}))


if __name__ == "__main__":
    unittest.main()
