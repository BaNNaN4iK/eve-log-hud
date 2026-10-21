# -*- coding: utf-8 -*-
"""Разбор строк лога: по тесту на каждый формат (реальные строки русского клиента + строки из ТЗ)."""
import calendar
import unittest

from helpers import elw
from fixtures.real_lines import REAL


def P(raw_line):
    ev = elw.parse_line(raw_line)
    assert ev is not None, raw_line
    return ev


def C(text, typ="combat"):
    """Строка из ТЗ (уже без тегов) с префиксом времени."""
    return P(f"[ 2026.10.08 17:42:58 ] ({typ}) {text}")


class TestCleaning(unittest.TestCase):
    def test_clean_tags_nbsp_star(self):
        raw = '<color=0x77ffffff>Вы добыли <font size=12>1&nbsp;234<b> ед.</b> <localized hint="Omber">Omber*</localized>'
        self.assertEqual(elw.clean_text(raw), "Вы добыли 1 234 ед. Omber")

    def test_entities_after_tags(self):
        # &lt;ENEMY&gt; — часть имени, не тег
        self.assertEqual(elw.clean_text("<b>Tengu* &lt;ENEMY&gt;[X.RED] Pipo</b>"), "Tengu <ENEMY>[X.RED] Pipo")

    def test_timestamp_is_utc(self):
        ev = C("Вы добыли 492 ед. ресурса Omber", "mining")
        self.assertEqual(ev.ts, calendar.timegm((2026, 10, 8, 17, 42, 58)))

    def test_hints(self):
        h = elw.extract_hints(REAL["undock"])
        self.assertIn("Jita", h)
        self.assertTrue(any(v.endswith("Caldari Navy Assembly Plant") and "Сборочный комплекс" in k for k, v in h.items()), h)


class TestHeader(unittest.TestCase):
    def test_russian(self):
        txt = "-" * 60 + "\n  Игровой журнал\n  Слушатель: Test Pilot\n  Сеанс начат: 2026.10.08 17:21:52\n" + "-" * 60 + "\n"
        self.assertEqual(elw.parse_header(txt), (True, "Test Pilot"))

    def test_english(self):
        txt = "-" * 60 + "\n  Gamelog\n  Listener: Some Pilot\n  Session Started: 2026.10.08 17:21:52\n" + "-" * 60 + "\n"
        self.assertEqual(elw.parse_header(txt), (True, "Some Pilot"))

    def test_login_screen_without_listener(self):
        txt = "-" * 60 + "\n  Игровой журнал\n  Сеанс начат: 2026.10.09 14:35:49\n" + "-" * 60 + "\n"
        self.assertEqual(elw.parse_header(txt), (True, None))

    def test_incomplete_header(self):
        self.assertEqual(elw.parse_header("-" * 60 + "\n  Игровой журнал\n"), (False, None))

    def test_header_lines_are_not_events(self):
        self.assertIsNone(elw.parse_line("  Слушатель: Test Pilot"))
        self.assertIsNone(elw.parse_line("-" * 60))


class TestDamageFromSpec(unittest.TestCase):
    """Строки из раздела «Формат логов» ТЗ (без тегов — работает разбор с конца)."""

    def test_out_structure_with_dash(self):
        d = C("195 на Z19-B8 - ENM Sotyo[ENM.](Sotiyo) - Caldari Navy Scourge Light Missile - Попал").data
        self.assertEqual((d["dir"], d["amount"], d["refl"]), ("out", 195, 0))
        self.assertEqual((d["target"], d["ticker"], d["ship"]), ("Z19-B8 - ENM Sotyo", "ENM.", "Sotiyo"))
        self.assertEqual(d["weapon"], "Caldari Navy Scourge Light Missile")
        self.assertEqual(d["quality"], "Попал")

    def test_reflected(self):
        d = C("195 на Z19-B8 - ENM Sotyo[ENM.](Sotiyo) - Caldari Navy Scourge Light Missile - Попал - Попал (Отражено 195)").data
        self.assertEqual((d["amount"], d["refl"]), (195, 195))
        self.assertEqual(d["target"], "Z19-B8 - ENM Sotyo")
        self.assertEqual(d["weapon"], "Caldari Navy Scourge Light Missile")

    def test_out_npc(self):
        d = C("131 на Defeater Drone - Caldari Navy Inferno Light Missile - Попал").data
        self.assertEqual((d["target"], d["weapon"], d["amount"]), ("Defeater Drone", "Caldari Navy Inferno Light Missile", 131))

    def test_in_drone_without_weapon(self):
        d = C("18 из Strain Hunter Drone - Царапнул").data
        self.assertEqual((d["dir"], d["target"], d["weapon"], d["quality"]), ("in", "Strain Hunter Drone", None, "Царапнул"))

    def test_in_player(self):
        d = C("533 из Qvatra[.RO.](Vedmak) - Heavy Entropic Disintegrator II - Попал").data
        self.assertEqual((d["target"], d["ticker"], d["ship"], d["weapon"]), ("Qvatra", ".RO.", "Vedmak", "Heavy Entropic Disintegrator II"))

    def test_in_structure_without_weapon(self):
        d = C("195 из Z19-B8 - ENM Sotyo[ENM.](Sotiyo) - Попал").data
        self.assertEqual((d["target"], d["weapon"]), ("Z19-B8 - ENM Sotyo", None))

    def test_all_qualities(self):
        for q in ["Попал", "Царапнул", "Пробил", "Скользнул", "Сокрушил", "Раздробил",
                  "Hits", "Grazes", "Penetrates", "Glances Off", "Smashes", "Wrecks", "Barely Scratches"]:
            d = C(f"10 на Target - Gun - {q}").data
            self.assertEqual((d["quality"], d["weapon"]), (q, "Gun"), q)

    def test_english_direction(self):
        d = C("120 to Drone Ruler - Hobgoblin I - Smashes").data
        self.assertEqual((d["dir"], d["quality"]), ("out", "Smashes"))
        d = C("55 from Drone Ruler - Hits").data
        self.assertEqual((d["dir"], d["target"]), ("in", "Drone Ruler"))

    def test_number_with_nbsp(self):
        d = P("[ 2026.10.08 17:42:58 ] (combat) 1 234 на Target - Gun - Попал").data
        self.assertEqual(d["amount"], 1234)


class TestRealLines(unittest.TestCase):
    """Настоящие строки из логов (с тегами)."""

    def test_out_structure(self):
        e = P(REAL["out_struct"])
        self.assertEqual(e.kind, "dmg")
        self.assertEqual((e.data["target"], e.data["ship"], e.data["weapon"], e.data["refl"]),
                         ("Z19-B8 - ENM Sotyo", "Sotiyo", "Caldari Navy Scourge Light Missile", 0))

    def test_out_reflected(self):
        d = P(REAL["out_refl"]).data
        self.assertEqual((d["amount"], d["refl"], d["quality"]), (195, 195, "Попал"))

    def test_out_npc(self):
        d = P(REAL["out_npc"]).data
        self.assertEqual((d["dir"], d["target"], d["weapon"], d["quality"]), ("out", "Pithum Inferno", "Hornet I", "Раздробил"))

    def test_in_no_weapon(self):
        d = P(REAL["in_noweapon"]).data
        self.assertEqual((d["dir"], d["target"], d["weapon"]), ("in", "Hostile Frigate", None))

    def test_in_player(self):
        d = P(REAL["in_player"]).data
        self.assertEqual((d["target"], d["ticker"], d["ship"], d["weapon"], d["amount"]),
                         ("Enemy Pilot", "X.RED", "Tengu", "Heavy Electron Blaster II", 709))

    def test_wreck_and_asteroid_targets(self):
        self.assertEqual(P(REAL["out_wreck"]).data["target"], "Остов Angel Rookie")
        d = P(REAL["out_asteroid"]).data
        self.assertEqual((d["target"], d["ship"], d["amount"]), ("Астероид", "Kernite", 0))

    def test_miss_in(self):
        self.assertEqual(P(REAL["miss_in"]).data, {"attacker": "Moth Apis", "weapon": None})
        self.assertEqual(P(REAL["miss_in_w"]).data, {"attacker": "Old Pirate Sly", "weapon": "Light Neutron Blaster II"})
        self.assertEqual(P(REAL["miss_in_pilot"]).data, {"attacker": "Drone Pilot", "weapon": "Praetor II"})
        self.assertEqual(C("Domination Drone: промах мимо вашего корабля").data["attacker"], "Domination Drone")
        self.assertEqual(C("Qvatra: промах мимо вашего корабля - Heavy Entropic Disintegrator II").data["weapon"],
                         "Heavy Entropic Disintegrator II")

    def test_miss_out(self):
        e = P(REAL["miss_out"])
        self.assertEqual((e.kind, e.data["weapon"], e.data["target"]), ("miss_out", "Civilian Gatling Pulse Laser", "Hostile Frigate"))
        e = P(REAL["miss_out_grp"])
        self.assertEqual((e.kind, e.data["weapon"], e.data["target"]), ("miss_out", "150mm Light AutoCannon I", "Gistii Hijacker"))

    def test_neut_in(self):
        e = P(REAL["neut_in_player"])
        self.assertEqual((e.kind, e.data["amount"], e.data["source"], e.data["module"]),
                         ("neut_in", 55, "NeutPilot NEUTS (Pioneer)", "Small Energy Neutralizer II"))
        self.assertEqual(P(REAL["neut_in_npc"]).data["source"], "Harvest Sage")

    def test_neut_unknown_color_is_unparsed(self):
        # цвет исходящих нейтов неизвестен — не угадываем, строка идёт в «нераспознанные»
        raw = REAL["neut_in_npc"].replace("0xffe57f7f", "0xff7fe57f")
        self.assertEqual(P(raw).kind, "unparsed")
        # строка из ТЗ без цвета — тоже не угадываем
        self.assertEqual(C("3 ГДж энергии нейтрализовано Vedmak // Qvatra FNT / - Small Energy Neutralizer II").kind, "unparsed")

    def test_nos_in(self):
        e = P(REAL["nos_in"])
        self.assertEqual((e.kind, e.data["module"]), ("nos_in", "Small Energy Nosferatu II"))

    def test_reps(self):
        e = P(REAL["rep_in_shield"])
        self.assertEqual((e.kind, e.data["amount"], e.data["layer"], e.data["source"]), ("rep_in", 129, "щиты", "Балин Феррус"))
        e = P(REAL["rep_in_armor"])
        self.assertEqual((e.kind, e.data["amount"], e.data["layer"]), ("rep_in", 188, "броня"))
        e = P(REAL["rep_out_shield"])
        self.assertEqual((e.kind, e.data["amount"], e.data["target"], e.data["module"]),
                         ("rep_out", 95, "FleetMate 3200 (Brutix Navy Issue)", "Small Ancillary Remote Shield Booster"))

    def test_warp(self):
        d = P(REAL["warp_me"]).data
        self.assertEqual((d["kind"], d["target_me"], d["source"]), ("Варп-глушение", True, "Hostile Battleship"))
        d = P(REAL["warp_src_me"]).data
        self.assertTrue(d["source_me"])
        d = P(REAL["warp_others"]).data
        self.assertEqual((d["kind"], d["source_me"], d["target_me"]), ("Варп-подавление", False, False))
        self.assertTrue(P(REAL["warp_entity"]).data["source"].startswith("Tengu <ENEMY>"))
        d = C("Попытка варп-глушения: источник Eris // Ewok Treen STUGH /, цель вы!").data
        self.assertEqual((d["source"], d["target_me"]), ("Ewok Treen STUGH (Eris)", True))
        d = C("Попытка варп-подавления: источник Arazu // Okela Anneto PROB /, цель Sotiyo // Z19-B8 - ENM Sotyo SB-SQ /").data
        self.assertEqual(d["target"], "Z19-B8 - ENM Sotyo SB-SQ (Sotiyo)")

    def test_jam(self):
        e = P(REAL["jam_in"])
        self.assertEqual((e.kind, e.data["module"]), ("jam_in", "Hornet EC-300"))
        e = C("Вы под действием помех сопровождению целей от Hornet EC-300 // Hornet EC-300 FNT / - Hornet EC-300")
        self.assertEqual(e.kind, "jam_in")
        e = P(REAL["jam_out"])
        self.assertEqual((e.kind, e.data["target"], e.data["module"]), ("jam_out", "Hostile Cruiser", "Multispectral ECM I"))

    def test_mining(self):
        e = P(REAL["mine"])
        self.assertEqual(e.kind, "mine")
        self.assertGreater(e.data["units"], 0)
        e = C("Вы добыли 492 ед. ресурса Omber", "mining")
        self.assertEqual(e.data, {"ore": "Omber", "units": 492, "residue": 0})
        e = C("Вы добыли 7 ед. руды Nephrite и утратили 3 ед. отходов.", "mining")
        self.assertEqual(e.data, {"ore": "Nephrite", "units": 7, "residue": 3})
        self.assertEqual(P(REAL["mine_residue"]).data["ore"], "Nephrite")

    def test_mining_crit_and_residue(self):
        e = P(REAL["mine_crit"])
        self.assertEqual((e.kind, e.data), ("mine_crit", {"ore": "Veldspar", "units": 837}))
        e = P(REAL["residue"])
        self.assertEqual((e.kind, e.data), ("residue", {"units": 353}))

    def test_bounty(self):
        self.assertEqual(P(REAL["bounty"]).data["isk"], 8250.0)
        self.assertEqual(P(REAL["bounty_adj"]).data["isk"], 79688.0)
        e = C("5 163 ISK добавлено к следующей награде за голову (оплата скорректирована)", "bounty")
        self.assertEqual(e.data["isk"], 5163.0)

    def test_location(self):
        self.assertEqual(P(REAL["jump"]).data["system"], "Arbaz")
        self.assertEqual(C("Осуществляется прыжок из Jita в Perimeter", "None").data["system"], "Perimeter")
        e = C("Выход из дока Jita IV - Moon 4 - Сборочный комплекс Caldari Navy в звездную систему Jita.", "None")
        self.assertEqual((e.kind, e.data["system"]), ("system", "Jita"))

    def test_ignored_types(self):
        for typ in ("hint", "info", "notify", "question", "warning"):
            self.assertIsNone(elw.parse_line(f"[ 2026.10.08 17:42:58 ] ({typ}) что угодно"))
        self.assertIsNone(elw.parse_line("[ 2026.10.08 17:42:58 ] (None) Пилот X запрашивает связь."))

    def test_unknown_combat_is_unparsed(self):
        e = C("15 единиц запаса прочности брони отремонтировано Кто-то - Small Remote Armor Repairer")
        self.assertEqual(e.kind, "unparsed")
        self.assertIn("отремонтировано", e.data["text"])


if __name__ == "__main__":
    unittest.main()
