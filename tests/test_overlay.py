# -*- coding: utf-8 -*-
"""Оверлей: расчёт текущей скорости урона/ремонта, формат чисел, отбор активных персонажей."""
import unittest

import helpers  # noqa: F401  (добавляет корень в sys.path)
from helpers import module

ov = module("overlay")


def live(now, out, **extra):
    s = {"id": "P|1", "who": "P", "t1": now, "out": out, "in": 0, "reps_in": {}, "reps_out": {}, "bounty": 0, "ore_total": 0}
    s.update(extra)
    return {"now": now, "cur_sys": {"P": "Jita"}, "sessions": [s]}


class TestOverlay(unittest.TestCase):
    def test_fmt(self):
        self.assertEqual([ov.fmt(x) for x in (0, 1234, 12345, 250000, 1234567, 18400000, 2500000000)],
                         ["0", "1 234", "12,3 тыс", "250 тыс", "1,23 млн", "18,4 млн", "2,50 млрд"])
        self.assertEqual((ov.sum_hp({"armor": {"hp": 100}, "shield": {"hp": 50}}), ov.sum_hp(None)), (150, 0))

    def test_rate_follows_damage_and_falls_to_zero(self):
        r = ov.Rates()
        for i in range(16):
            rows = r.update(live(1000 + i, i * 100), 1000 + i)
        self.assertEqual((round(rows[0]["dps"]), rows[0]["who"], rows[0]["system"], rows[0]["out"]), (100, "P", "Jita", 1500))
        for i in range(16, 31):                               # стрельба прекратилась
            rows = r.update(live(1015, 1500), 1000 + i)
        self.assertEqual((rows[0]["dps"], rows[0]["out"]), (0, 1500))

    def test_new_session_resets(self):
        r = ov.Rates()
        r.update(live(1000, 5000), 1000)
        self.assertEqual(r.update(live(1001, 40, id="P|2"), 1001)[0]["dps"], 0)      # не отрицательная скорость
        self.assertEqual(r.update(live(1002, 140, id="P|2"), 1002)[0]["dps"], 10)

    def test_inactive_hidden_and_max_rows(self):
        r = ov.Rates()
        self.assertEqual(r.update({"now": 2000, "sessions": live(1000, 1)["sessions"]}, 2000), [])
        many = {"now": 500, "sessions": [{"id": f"c{n}", "who": f"c{n}", "t1": 400 + n, "out": 1} for n in range(1, 7)]}
        self.assertEqual([x["who"] for x in ov.Rates().update(many, 500)], ["c6", "c5", "c4", "c3"])

    def test_repairs_and_totals_text(self):
        r = ov.Rates()
        for i in range(13):
            rows = r.update(live(100 + i, 0, reps_in={"armor": {"hp": i * 50}}, bounty=18400000, ore_total=0), 100 + i)
        self.assertEqual(round(rows[0]["hps"]), 50)
        self.assertEqual(ov.totals_text(rows[0]), "ремонт 600   баунти 18,4 млн ISK")   # нули не показываем

    def test_mining_rate_volume_and_price(self):
        meta = {"types": {"Veldspar": {"id": 1230, "volume": 0.1}}, "aliases": {"Вельдспар": "Veldspar"},
                "prices": {"types": {"1230": {"buy": 10.0}}}}
        self.assertEqual(ov.ore_worth({"Вельдспар": 1000}, meta), (100.0, 10000.0))
        self.assertEqual(ov.ore_worth({"Unknown Ore": 5}, meta), (None, None))            # справочника нет — не выдумываем
        self.assertEqual(ov.ore_worth({"Veldspar": 10}, dict(meta, overrides={"Veldspar": 3})), (1.0, 30.0))
        r = ov.Rates()
        for i in range(0, 601, 60):                           # цикл лазера раз в минуту: +600 ед.
            n = i // 60 * 600
            rows = r.update(live(5000 + i, 0, ore={"Veldspar": n}, ore_total=n), 5000 + i, meta)
        x = rows[0]
        self.assertEqual((x["ore"], x["ore_m3"], x["ore_isk"]), (6000, 600.0, 60000.0))
        self.assertEqual((round(x["ore_h"]), round(x["m3_h"]), round(x["isk_h"])), (36000, 3600, 360000))
        self.assertEqual(ov.totals_text(x), "руда 600 м³   ≈ 60,0 тыс ISK")
        self.assertEqual(ov.totals_text(x, {"t_ore": False}), "")
        y = ov.Rates().update(live(1, 0, ore={"Veldspar": 500}, ore_total=500), 1, None)[0]   # трекер без онлайн-справочника
        self.assertEqual((y["ore_m3"], y["ore_isk"], ov.totals_text(y)), (None, None, "руда 500 ед."))
        self.assertEqual(y["ore_h"], 0)                       # одна выборка — скорости ещё нет

    def test_duration_and_show_switches(self):
        self.assertEqual([ov.fmt_dur(x) for x in (0, 59, 754, 3725)], ["0:00", "0:59", "12:34", "1:02:05"])
        row = ov.Rates().update(live(1600, 500, t0=1000, bounty=2000000), 1600)[0]
        self.assertEqual(ov.totals_text(row), "время 10:00   нанёс 500   баунти 2,00 млн ISK")
        self.assertEqual(round(row["bounty_h"]), 12000000)    # 2 млн за 10 минут = 12 млн в час
        first = ov.Rates().update(live(1010, 0, t0=1000, bounty=1000), 1010)[0]
        self.assertEqual(round(first["bounty_h"]), 60000)     # первые секунды не дают бешеных чисел: считаем как за минуту
        self.assertEqual(ov.Rates().update(live(1600, 5, t0=1000), 1600)[0]["bounty_h"], 0)
        self.assertEqual(ov.totals_text(row, {"t_dur": False, "t_bounty": False}), "нанёс 500")
        many = {"now": 500, "sessions": [{"id": f"c{n}", "who": f"c{n}", "t1": 400 + n, "out": 1} for n in range(1, 7)]}
        self.assertEqual([x["who"] for x in ov.Rates().update(many, 500, max_rows=2)], ["c6", "c5"])

    def test_manual_session_counts_only_from_start(self):
        m, r = ov.ManualSession(), ov.Rates()
        self.assertEqual(m.apply(live(100, 5000), 100)["sessions"], [])                 # не начата — пусто
        m.start(100)
        row = r.update(m.apply(live(100, 5000, bounty=900, ore={"Veldspar": 300}, ore_total=300), 100), 100)[0]
        self.assertEqual((row["out"], row["bounty"], row["ore"], row["dur"]), (0, 0, 0, 0))   # прошлое не считается
        for i in range(1, 21):
            src = m.apply(live(100 + i, 5000 + i * 100, bounty=900 + i, ore={"Veldspar": 300 + i}, ore_total=300 + i), 100 + i)
            row = r.update(src, 100 + i)[0]
        self.assertEqual((row["out"], row["bounty"], row["ore"], row["dur"]), (2000, 20, 20, 20))
        self.assertEqual((round(row["dps"]), round(row["peak"])), (100, 100))            # пик считаем сами
        # трекер закрыл сессию и открыл новую — ручная продолжается без скачка
        row = r.update(m.apply(live(130, 50, id="P|2"), 130), 130)[0]
        self.assertEqual(row["out"], 2050)
        # новый персонаж после старта считается с нуля своей сессии
        two = live(131, 60, id="P|2")
        two["sessions"].append({"id": "Q|1", "who": "Q", "t1": 131, "out": 7, "in": 0})
        self.assertEqual({x["who"]: x["out"] for x in r.update(m.apply(two, 131), 131)}, {"P": 2060, "Q": 7})
        # стоп: итог замирает и не пропадает, даже если трекер считает дальше
        m.stop(140)
        self.assertEqual((m.state, m.elapsed(999)), ("stopped", 40))
        rows = r.update(m.apply(live(900, 99999, id="P|2"), 900), 900)
        self.assertEqual({x["who"]: (x["out"], x["dur"]) for x in rows}, {"P": (2060, 40), "Q": (7, 40)})
        m.reset()
        self.assertEqual((m.state, m.apply(live(901, 1), 901)["sessions"]), ("idle", []))

    def test_manual_session_survives_restart(self):
        import json, os, tempfile
        old = ov.STATE_FILE
        ov.STATE_FILE = os.path.join(tempfile.mkdtemp(), "overlay.json")
        try:
            m = ov.ManualSession()
            self.assertFalse(ov.load_session(m))                                         # файла ещё нет
            m.start(100)
            m.apply(live(100, 5000), 100)
            m.apply(live(110, 5600), 110)
            ov.save_session(m)
            again = ov.ManualSession()
            self.assertTrue(ov.load_session(again))
            row = ov.Rates().update(again.apply(live(120, 6000), 120), 120)[0]
            self.assertEqual((again.state, row["out"], row["dur"]), ("running", 1000, 20))
            with open(ov.session_file(), "w", encoding="utf-8") as f:
                f.write("{broken")
            broken = ov.ManualSession()
            self.assertFalse(ov.load_session(broken))
            self.assertEqual(broken.state, "idle")
            self.assertFalse(ov.ManualSession().load({"state": "running"}))               # неполное — не грузим
        finally:
            import shutil
            shutil.rmtree(os.path.dirname(ov.STATE_FILE), ignore_errors=True)
            ov.STATE_FILE = old

    def test_settings_merge_ignores_garbage(self):
        import json, os, tempfile
        old = ov.STATE_FILE
        fd, ov.STATE_FILE = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            with open(ov.STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({"alpha": 5, "max_rows": 2, "session_mode": "weird", "x": 10, "y": "no",
                           "show": {"dps": False, "t_ore": "yes", "unknown": True}, "compact": True}, f)
            c = ov.load_settings()
            self.assertEqual((c["alpha"], c["max_rows"], c["session_mode"], c["x"], "y" in c), (0.85, 2, "auto", 10, False))
            self.assertEqual((c["show"]["dps"], c["show"]["t_ore"], "unknown" in c["show"]), (False, True, False))
            with open(ov.STATE_FILE, "w", encoding="utf-8") as f:
                f.write("not json")
            self.assertEqual(ov.load_settings(), ov.DEFAULTS)
            self.assertTrue(ov.DEFAULTS["show"]["dps"])                                   # умолчания не испорчены
        finally:
            os.remove(ov.STATE_FILE)
            ov.STATE_FILE = old

    def test_threats_top_attacker_and_active_effects(self):
        def lv(now, scram=1, neut=0, sid="P|1"):
            return {"now": now, "sessions": [{"id": sid, "who": "P", "t1": now, "attackers": {
                "Queen": {"ship": "", "s10": [[now - 500, 99999], [now - now % 10 - 10, 1500], [now - now % 10, 500]]},
                "Render": {"ship": "Vexor", "s10": [[now - now % 10, 300]]},
                "Old": {"ship": "", "s10": [[now - 300, 5000]]}},
                "ewar": {"Варп-глушение — по вам": {"n": scram, "who": {"Render": scram}},
                         "Варп-глушение — между другими": {"n": 9, "who": {"A → B": 9}}},
                "neut_in": {"gj": neut, "n": 1, "from": {"Queen": neut} if neut else {}}}]}
        t = ov.Threats()
        th = t.update(lv(1005), 1005)["P"]
        self.assertEqual([a["name"] for a in th["top"]], ["Queen", "Render"])            # старый урон не в счёт
        self.assertEqual(round(th["top"][0]["dps"]), 80)                                # 2000 за 25 секунд
        self.assertEqual(th["effects"], {})                                             # что было до запуска — не «сейчас»
        self.assertEqual(ov.attacker_text(th), "бьёт сильнее всех: Queen — 80/с\nследом: Render (Vexor) — 12/с")
        th = t.update(lv(1006, scram=2, neut=50), 1006)["P"]                             # счётчики выросли — эффект действует
        self.assertEqual(th["effects"], {"Варп-глушение": ["Render"], "Нейтрализация": ["Queen"]})
        self.assertEqual(ov.effects_text(th), "Варп-глушение: Render\nНейтрализация: Queen")
        self.assertEqual(t.update(lv(1030, scram=2, neut=50), 1030)["P"]["effects"],
                         {"Варп-глушение": ["Render"], "Нейтрализация": ["Queen"]})
        self.assertEqual(t.update(lv(1040, scram=2, neut=50), 1040)["P"]["effects"], {})   # 30 секунд тишины — снято
        th = t.update(lv(1041, scram=1, sid="P|2"), 1041)["P"]                           # новая сессия трекера: всё в ней свежее
        self.assertEqual(th["effects"], {"Варп-глушение": ["Render"]})
        self.assertEqual((ov.attacker_text(None), ov.effects_text({})), ("", ""))
        z = ov.Threats().update({"now": 5, "sessions": [{"id": 1, "who": "Z", "t1": 5}]}, 5)["Z"]
        self.assertEqual((z["top"], z["effects"], ov.types_cells(z)), ([], {}, []))

    def test_incoming_damage_by_type(self):
        now = 1005
        s = {"id": "P|1", "who": "P", "t1": now, "attackers": {
            "Rat": {"ship": "", "prof": [0.0, 0.8, 0.2, 0.0], "s10": [[1000, 2500]]},          # 100/с: терм 80, кин 20
            "Player": {"ship": "Drake", "prof": [0, 0, 0.5, 0], "s10": [[1000, 1000]]},          # 40/с: кин 20, неизвестно 20
            "Mystery": {"ship": "", "prof": None, "s10": [[1000, 250]]}}}                         # 10/с: неизвестно
        th = ov.Threats().update({"now": now, "sessions": [s]}, now)["P"]
        self.assertEqual({k: round(v) for k, v in th["types"].items()}, {"em": 0, "therm": 80, "kin": 40, "exp": 0, "unknown": 30})
        self.assertEqual([(c[0], round(c[1])) for c in ov.types_cells(th)], [("терм", 80), ("кин", 40), ("неизв.", 30)])
        self.assertEqual(ov.attacker_text(th, True), "бьёт сильнее всех: Rat — 100/с · терм 80% · кин 20%\nследом: Player (Drake) — 40/с · кин 50%")
        self.assertEqual(ov.attacker_text(th), "бьёт сильнее всех: Rat — 100/с\nследом: Player (Drake) — 40/с")
        self.assertEqual((ov.prof_text(None), ov.prof_text([0.31, 0.0, 0.12, 0.57])), ("", "взрыв 57% · ЭМ 31% · кин 12%"))

    def test_fleet_view(self):
        f = {"ok": True, "fleet": {"name": "Roam", "boss": "Boss", "boss_system": "Jita", "count": 3, "polled_at": 1000,
             "ships": [{"name": "Vulture", "n": 2}, {"name": "Oni", "n": 1}],
             "systems": [{"name": "Jita", "n": 2}, {"name": "Tama", "n": 1}],
             "pilots": [{"name": "Boss", "ship": "Vulture", "system": "Jita", "boss": True},
                        {"name": "Me", "ship": "Oni", "system": "Tama", "docked": True, "me": True},
                        {"name": "Z", "ship": "Vulture", "system": "Jita"}]}}
        v = ov.fleet_view(f, 2, now=1030)
        self.assertEqual((v["title"], v["head"]), ("Флот · Roam", "3 пилота · босс Boss в Jita"))
        self.assertEqual((v["ships"], v["systems"]), ("2 Vulture  ·  1 Oni", "Jita 2  ·  Tama 1"))
        self.assertEqual([(r["name"], r["ship"], r["system"], r["me"]) for r in v["rows"]],
                         [("★ Boss", "Vulture", "Jita", False), ("Me", "Oni", "Tama (док)", True)])
        self.assertEqual((v["more"], v["stale"]), (1, ""))
        self.assertEqual(ov.fleet_view(f, 12, now=1000 + 600)["stale"], "данные устарели: 10:00 назад")
        self.assertEqual(ov.fleet_view(f, 12, now=1000 + 59)["stale"], "")
        for n, word in ((1, "1 пилот"), (2, "2 пилота"), (5, "5 пилотов"), (11, "11 пилотов"), (21, "21 пилот"), (14, "14 пилотов")):
            self.assertTrue(ov.fleet_view({"ok": True, "fleet": {"count": n}}, now=1)["head"].startswith(word), word)
        for nothing in (None, {"ok": True, "fleet": None}, {"ok": False, "message": "нет связи"}):
            self.assertIsNone(ov.fleet_view(nothing))
        self.assertEqual(ov.fleet_status({"ok": False, "message": "AA ответил 401"}), "AA ответил 401")
        self.assertIn("не отслеживается", ov.fleet_status({"ok": True, "fleet": None}))
        self.assertEqual(ov.fleet_status(f), "Roam: пилотов — 3")
        self.assertEqual(ov.fleet_view(ov.DEMO_FLEET)["ships"].split("  ·  ")[:2], ["7 Vulture", "3 Oni"])

    def test_demo_shape_matches_tracker(self):
        rows = ov.Rates().update(ov.demo_live())
        self.assertEqual([x["who"] for x in rows], ["Test Pilot", "Second Pilot"])


if __name__ == "__main__":
    unittest.main()
