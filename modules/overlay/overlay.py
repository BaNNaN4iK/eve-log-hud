#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EVE Log HUD — маленькое окно поверх игры с живыми данными EVE Log Watcher.

Только стандартная библиотека. Данные берёт у трекера: http://127.0.0.1:<web_port>/api/live.
Игру не трогает: это обычное окно Windows «поверх всех окон», поэтому EVE должна работать
в режиме «Окно» или «Окно без рамки» (в эксклюзивном полноэкранном режиме его не видно).

Запуск: start_overlay.bat  (или: pythonw eve_overlay.py; пример без трекера: python eve_overlay.py --demo)
"""
import argparse
import json
import os
import sys
import threading
import time
import urllib.request
from typing import Dict, List, Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# данные трекера: в собранном приложении — отдельно от программы; из исходников — в папке ядра (на две выше модуля)
_CORE_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DATA_DIR = os.environ.get("EVE_DATA_DIR") or _CORE_DIR      # в собранном приложении данные лежат отдельно от программы
STATE_FILE = os.environ.get("EVE_OVERLAY_STATE") or os.path.join(DATA_DIR, "overlay.json")
WINDOW_S = 10     # «текущий» DPS — среднее за последние 10 секунд
MINE_S = 300      # скорость добычи — за последние 5 минут: цикл лазера длится минуты, 10 секунд ничего не скажут
ACTIVE_S = 300    # персонаж считается активным 5 минут после последнего события в логе
MAX_ROWS = 4

# настройки по умолчанию (хранятся в overlay.json, меняются в окне настроек — кнопка ⚙)
DEFAULTS = {
    "alpha": 0.85, "max_rows": MAX_ROWS, "session_mode": "auto", "hotkeys": True,
    "fleet_enabled": True, "fleet_pilots": True, "fleet_max": 12,
    "show": {"system": True, "dps": True, "dps_in": True, "hps": True, "bounty": True, "bounty_h": True, "mining": True,
             "top_attacker": True, "ewar": True, "in_types": True,
             "t_dur": True, "t_out": True, "t_in": True, "t_rep": True, "t_rep_out": True,
             "t_peak": True, "t_bounty": True, "t_ore": True},
}


# ---------------------------------------------------------------------------
# Расчёты (без окна — их проверяет tests/test_overlay.py)
# ---------------------------------------------------------------------------

def fmt(n: float) -> str:
    n = int(round(n or 0))
    a = abs(n)
    if a >= 10 ** 9:
        return f"{n / 1e9:.2f}".replace(".", ",") + " млрд"
    if a >= 10 ** 6:
        return f"{n / 1e6:.{1 if a >= 10 ** 7 else 2}f}".replace(".", ",") + " млн"
    if a >= 10 ** 4:
        return f"{n / 1e3:.{0 if a >= 10 ** 5 else 1}f}".replace(".", ",") + " тыс"
    return f"{n:,}".replace(",", " ")


def fmt_dur(sec: float) -> str:
    sec = max(0, int(sec or 0))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def sum_hp(reps: Optional[dict]) -> float:
    return sum((v or {}).get("hp", 0) for v in (reps or {}).values())


def ore_worth(ore: Optional[dict], meta: Optional[dict]):
    """Объём (м³) и цена (ISK, скупка в Jita — как на странице трекера) добытой руды; None, если справочника нет."""
    meta = meta or {}
    types, aliases, over = meta.get("types") or {}, meta.get("aliases") or {}, meta.get("overrides") or {}
    prices = (meta.get("prices") or {}).get("types") or {}
    m3 = isk = 0.0
    know_m3 = know_isk = bool(ore)
    for name, units in (ore or {}).items():
        alias = aliases.get(name) or name
        t = types.get(alias) or types.get(name) or {}
        if isinstance(t.get("volume"), (int, float)):
            m3 += units * t["volume"]
        else:
            know_m3 = False
        unit = over.get(name, over.get(alias))
        if not isinstance(unit, (int, float)):
            unit = (prices.get(str(t.get("id"))) or {}).get("buy")
        if isinstance(unit, (int, float)):
            isk += units * unit
        else:
            know_isk = False
    return (m3 if know_m3 else None), (isk if know_isk else None)


class Rates:
    """Трекер копит итоги сессии; скорость считаем сами по разнице между опросами."""

    def __init__(self):
        self.samples: Dict[str, dict] = {}

    @staticmethod
    def _rate(lst: List[dict], key: str, now: float) -> float:
        first = lst[0]
        for i, smp in enumerate(lst):
            if smp["t"] >= now - WINDOW_S:
                first = lst[max(0, i - 1)]
                break
        gain = lst[-1][key] - first[key]
        return gain / max(WINDOW_S, lst[-1]["t"] - first["t"]) if gain > 0 else 0.0

    @staticmethod
    def _per_hour(lst: List[dict], key: str) -> float:
        """Прирост за всё окно выборок (до 5 минут) в пересчёте на час; первую минуту не разгоняем."""
        a, b = lst[0][key], lst[-1][key]
        if a is None or b is None or b <= a:
            return 0.0
        return (b - a) / max(60.0, lst[-1]["t"] - lst[0]["t"]) * 3600

    def update(self, live: dict, now: Optional[float] = None, meta: Optional[dict] = None,
               max_rows: int = MAX_ROWS) -> List[dict]:
        now = time.time() if now is None else now
        by_who: Dict[str, dict] = {}
        for s in live.get("sessions") or []:
            if s["who"] not in by_who or s["t1"] > by_who[s["who"]]["t1"]:
                by_who[s["who"]] = s
        rows = []
        for who, s in by_who.items():
            prev = self.samples.get(who)
            if prev and prev["id"] != s.get("id"):          # началась новая сессия — счётчики обнулились
                prev = None
            lst = prev["list"] if prev else []
            rep = sum_hp(s.get("reps_in"))
            ore = s.get("ore_total", 0)
            m3, isk = ore_worth(s.get("ore"), meta) if ore else (None, None)
            lst.append({"t": now, "out": s.get("out", 0), "in": s.get("in", 0), "rep": rep, "ore": ore, "m3": m3, "isk": isk})
            while len(lst) > 2 and lst[1]["t"] < now - MINE_S:
                lst.pop(0)
            dps = self._rate(lst, "out", now)
            peak = max(prev["peak"] if prev else 0.0, dps)    # свой пик — для ручной сессии, где пика трекера нет
            self.samples[who] = {"id": s.get("id"), "list": lst, "peak": peak}
            if live.get("now", now) - s["t1"] > ACTIVE_S:
                continue
            rows.append({
                "who": who, "system": (live.get("cur_sys") or {}).get(who) or "", "t1": s["t1"],
                "dps": dps, "dps_in": self._rate(lst, "in", now), "hps": self._rate(lst, "rep", now),
                "out": s.get("out", 0), "in": s.get("in", 0), "rep": rep, "rep_out": sum_hp(s.get("reps_out")),
                "bounty": s.get("bounty", 0), "ore": ore,
                "peak": peak if s.get("peak_dps") is None else s["peak_dps"],
                "dur": s["dur"] if s.get("dur") is not None else s["t1"] - s.get("t0", s["t1"]),
            })
            r = rows[-1]                                     # баунти в час — среднее за сессию; первую минуту не разгоняем
            r.update({"bounty_h": r["bounty"] / max(60.0, r["dur"]) * 3600 if r["bounty"] else 0.0,
                "ore_m3": m3, "ore_isk": isk, "ore_h": self._per_hour(lst, "ore"),
                "m3_h": self._per_hour(lst, "m3"), "isk_h": self._per_hour(lst, "isk"),
            })
        for who in list(self.samples):
            if who not in by_who:
                del self.samples[who]
        rows.sort(key=lambda r: (-r["t1"], r["who"]))
        return rows[:max(1, max_rows)]


# ---------------------------------------------------------------------------
# Угрозы: кто сейчас бьёт сильнее всех и кто держит эффектами (варп-глушение, нейтрализация, помехи)
# ---------------------------------------------------------------------------

ATTACK_S = 20     # «сейчас бьёт» — урон за последние ~20 секунд
THREAT_S = 30     # эффект считается действующим 30 секунд после последней записи в логе
BY_YOU = " — по вам"
DRAINS = (("neut_in", "Нейтрализация"), ("nos_in", "Откачка энергии"))
DMG_TYPES = (("em", "ЭМ"), ("therm", "терм"), ("kin", "кин"), ("exp", "взрыв"))   # порядок — как в prof трекера


def prof_text(prof) -> str:
    """«терм 80% · кин 20%» — чем бьёт враг; пусто, если трекер не знает."""
    if not prof:
        return ""
    parts = sorted(((share, label) for (_, label), share in zip(DMG_TYPES, prof) if share >= 0.05), reverse=True)
    return " · ".join(f"{label} {round(share * 100)}%" for share, label in parts)


class Threats:
    """Трекер отдаёт по эффектам только счётчики за сессию; «сейчас» — это рост счётчика между опросами."""

    def __init__(self):
        self.seen: Dict[str, dict] = {}

    def update(self, live: dict, now: Optional[float] = None) -> Dict[str, dict]:
        now = time.time() if now is None else now
        log_now = live.get("now", now)                       # часы трекера: по ним размечен урон
        start = (int(log_now) - ATTACK_S) // 10 * 10
        by_who: Dict[str, dict] = {}
        for s in live.get("sessions") or []:
            if s["who"] not in by_who or s["t1"] > by_who[s["who"]]["t1"]:
                by_who[s["who"]] = s
        out = {}
        for who, s in by_who.items():
            st = self.seen.get(who)
            baseline = st is None                            # оверлей только запустился: старое — не «сейчас»
            if st is None or st["id"] != s.get("id"):
                st = {"id": s.get("id"), "counts": {}, "at": {}}
            cur = {}
            for label, e in (s.get("ewar") or {}).items():
                if label.endswith(BY_YOU):
                    for name, n in (e.get("who") or {}).items():
                        cur[(label[:-len(BY_YOU)], name)] = n
            for key, label in DRAINS:
                for name, gj in ((s.get(key) or {}).get("from") or {}).items():
                    cur[(label, name)] = gj
            if not baseline:
                for k, n in cur.items():
                    if n > st["counts"].get(k, 0):
                        st["at"][k] = now
            st["counts"] = cur
            st["at"] = {k: t for k, t in st["at"].items() if now - t <= THREAT_S}
            self.seen[who] = st
            effects: Dict[str, List[str]] = {}
            for (kind, name), t in sorted(st["at"].items(), key=lambda kv: -kv[1]):
                effects.setdefault(kind, []).append(name)
            top = []
            types = {key: 0.0 for key, _ in DMG_TYPES}       # получаемый урон в секунду по типам (оценка)
            types["unknown"] = 0.0
            for name, a in (s.get("attackers") or {}).items():
                dmg = 0
                for ts, v in reversed(a.get("s10") or []):
                    if ts < start:
                        break
                    dmg += v
                if dmg > 0:
                    dps = dmg / max(10.0, log_now - start)
                    prof = a.get("prof")
                    top.append({"name": name, "dps": dps, "ship": a.get("ship") or "", "prof": prof})
                    known = 0.0
                    for (key, _), share in zip(DMG_TYPES, prof or ()):
                        types[key] += dps * share
                        known += share
                    types["unknown"] += dps * max(0.0, 1.0 - known)
            top.sort(key=lambda x: -x["dps"])
            out[who] = {"top": top[:2], "effects": effects, "types": types}
        for who in list(self.seen):
            if who not in by_who:
                del self.seen[who]
        return out


def attacker_text(th: Optional[dict], with_types: bool = False) -> str:
    top = (th or {}).get("top") or []
    if not top:
        return ""
    def one(a):
        types = prof_text(a.get("prof")) if with_types else ""
        return a["name"] + (f" ({a['ship']})" if a["ship"] else "") + f" — {fmt(a['dps'])}/с" + (f" · {types}" if types else "")
    return "бьёт сильнее всех: " + one(top[0]) + ("\nследом: " + one(top[1]) if len(top) > 1 else "")


def types_cells(th: Optional[dict]) -> List[tuple]:
    """[(подпись, урон в секунду, ключ)] — только типы, по которым сейчас идёт урон; пусто — показывать нечего."""
    types = (th or {}).get("types") or {}
    cells = [(label, types.get(key, 0.0), key) for key, label in DMG_TYPES + (("unknown", "неизв."),)]
    return [c for c in cells if c[1] >= 0.5]


def effects_text(th: Optional[dict]) -> str:
    return "\n".join(f"{kind}: {', '.join(names)}" for kind, names in ((th or {}).get("effects") or {}).items())


# ---------------------------------------------------------------------------
# Флот: кто во флоте, на чём и где (данные — Fleet Watch в Alliance Auth через трекер)
# ---------------------------------------------------------------------------

FLEET_STALE_S = 60    # Fleet Watch опрашивает флот раз в 10–30 секунд; минута без опроса — данные старые


def fleet_view(resp: Optional[dict], max_pilots: int = 12, now: Optional[float] = None) -> Optional[dict]:
    """Ответ /api/fleet → готовые строки окна флота; None — показывать нечего (не во флоте или нет связи)."""
    f = (resp or {}).get("fleet") if (resp or {}).get("ok") else None
    if not f:
        return None
    now = time.time() if now is None else now
    n = f.get("count", 0)
    word = "пилот" if n % 10 == 1 and n % 100 != 11 else "пилота" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "пилотов"
    head = f"{n} {word}"
    if f.get("boss"):
        head += f" · босс {f['boss']}" + (f" в {f['boss_system']}" if f.get("boss_system") else "")
    polled = f.get("polled_at")
    age = now - polled if polled else None
    pilots = f.get("pilots") or []
    rows = [{"name": ("★ " if p.get("boss") else "") + p["name"], "ship": p["ship"],
             "system": p["system"] + (" (док)" if p.get("docked") else ""), "me": bool(p.get("me"))}
            for p in pilots[:max_pilots]]
    return {
        "title": "Флот" + (f" · {f['name']}" if f.get("name") else ""),
        "head": head,
        "ships": "  ·  ".join(f"{s['n']} {s['name']}" for s in f.get("ships") or []),
        "systems": "  ·  ".join(f"{s['name']} {s['n']}" for s in f.get("systems") or []),
        "rows": rows, "more": max(0, len(pilots) - len(rows)),
        "stale": f"данные устарели: {fmt_dur(age)} назад" if age is not None and age > FLEET_STALE_S else "",
    }


def fleet_status(resp: Optional[dict]) -> str:
    """Одна строка для окна настроек: почему окна флота нет или что в нём."""
    if resp is None:
        return "ещё не запрашивался"
    if not resp.get("ok"):
        return resp.get("message") or "нет данных"
    f = resp.get("fleet")
    if not f:
        return "флот не отслеживается (вкладка «Флот» в окне приложения → «Отслеживать мой флот»)"
    return f"{f.get('name') or 'флот'}: пилотов — {f.get('count', 0)}"


DEMO_FLEET = {"ok": True, "fleet": {
    "name": "Домашняя оборона", "boss": "Test Pilot", "boss_system": "B6-XE8", "count": 14, "polled_at": None,
    "ships": [{"name": "Vulture", "n": 7}, {"name": "Oni", "n": 3}, {"name": "Scimitar", "n": 2},
              {"name": "Sabre", "n": 1}, {"name": "Capsule", "n": 1}],
    "systems": [{"name": "B6-XE8", "n": 12, "sec": -0.3}, {"name": "0FG-KS", "n": 2, "sec": -0.2}],
    "pilots": [{"name": "Test Pilot", "ship": "Vulture", "system": "B6-XE8", "boss": True, "me": True}] +
              [{"name": f"Pilot {i}", "ship": s, "system": y, "docked": d}
               for i, (s, y, d) in enumerate([("Capsule", "0FG-KS", True), ("Oni", "B6-XE8", False), ("Oni", "B6-XE8", False),
                                              ("Oni", "B6-XE8", False), ("Sabre", "0FG-KS", False), ("Scimitar", "B6-XE8", False),
                                              ("Scimitar", "B6-XE8", False)] + [("Vulture", "B6-XE8", False)] * 6, 1)]}}


def totals_text(r: dict, show: Optional[dict] = None) -> str:
    """Строка итогов; show — какие пункты включены в настройках (None — все). Нули не показываем."""
    on = lambda key: show is None or show.get(key, True)
    parts = [("t_out", "нанёс", r["out"], ""), ("t_in", "получил", r["in"], ""), ("t_rep", "ремонт", r["rep"], ""),
             ("t_rep_out", "починил", r["rep_out"], ""), ("t_peak", "пик", r["peak"], " /с"),
             ("t_bounty", "баунти", r["bounty"], " ISK"),
             ("t_ore", "руда", r["ore_m3"], " м³") if r.get("ore_m3") else ("t_ore", "руда", r["ore"], " ед."),
             ("t_ore", "≈", r.get("ore_isk") or 0, " ISK")]
    out = [f"{label} {fmt(v)}{unit}" for key, label, v, unit in parts if v > 0 and on(key)]
    if on("t_dur") and r.get("dur", 0) > 0:
        out.insert(0, "время " + fmt_dur(r["dur"]))
    return "   ".join(out)


# ---------------------------------------------------------------------------
# Ручная сессия: считаем только то, что случилось между «Старт» и «Стоп»
# ---------------------------------------------------------------------------

COUNTERS = ("out", "in", "rep", "rep_out", "bounty")


def _raw(s: dict) -> dict:
    return {"out": s.get("out", 0), "in": s.get("in", 0), "rep": sum_hp(s.get("reps_in")),
            "rep_out": sum_hp(s.get("reps_out")), "bounty": s.get("bounty", 0), "ore": dict(s.get("ore") or {})}


def _zero() -> dict:
    return {"out": 0, "in": 0, "rep": 0, "rep_out": 0, "bounty": 0, "ore": {}}


def _combine(a: dict, b: dict, sign: int) -> dict:
    r = {key: max(0, a[key] + sign * b[key]) for key in COUNTERS}
    r["ore"] = {n: max(0, a["ore"].get(n, 0) + sign * b["ore"].get(n, 0)) for n in set(a["ore"]) | set(b["ore"])}
    return r


class ManualSession:
    """Трекер ведёт свои сессии сам; здесь — вычитание: «сколько набежало с момента Старт».

    apply() отдаёт те же данные, что /api/live, но со счётчиками от старта — дальше их считает обычный Rates.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.state = "idle"                                  # idle → running → stopped
        self.t0 = self.t1 = None
        self.base: Dict[str, dict] = {}                      # счётчики трекера на момент старта
        self.acc: Dict[str, dict] = {}                       # набежало в уже закрытых сессиях трекера
        self.last: Dict[str, dict] = {}
        self.ids: Dict[str, object] = {}
        self.pending = False
        self.frozen: List[dict] = []

    FIELDS = ("state", "t0", "t1", "base", "acc", "last", "ids", "pending", "frozen")

    def dump(self) -> dict:
        """Состояние для файла: ручная сессия переживает перезапуск оверлея."""
        return {k: getattr(self, k) for k in self.FIELDS}

    def load(self, d) -> bool:
        if not isinstance(d, dict) or d.get("state") not in ("running", "stopped") or not isinstance(d.get("t0"), (int, float)):
            return False
        try:
            for k in self.FIELDS:
                setattr(self, k, d[k])
        except KeyError:
            self.reset()
            return False
        return True

    def start(self, now: float):
        self.reset()
        self.state, self.t0, self.pending = "running", now, True

    def stop(self, now: float):
        if self.state == "running":
            self.state, self.t1 = "stopped", now
            for s in self.frozen:
                s["dur"] = now - self.t0

    def elapsed(self, now: float) -> float:
        if self.state == "idle":
            return 0.0
        return (self.t1 if self.state == "stopped" else now) - self.t0

    def apply(self, live: dict, now: float) -> dict:
        if self.state == "idle":
            return dict(live, sessions=[])
        if self.state == "stopped":                          # итог остаётся на экране, пока не нажмут «Сброс»
            return dict(live, sessions=[dict(s, t1=live.get("now", now)) for s in self.frozen])
        by_who: Dict[str, dict] = {}
        for s in live.get("sessions") or []:
            if s["who"] not in by_who or s["t1"] > by_who[s["who"]]["t1"]:
                by_who[s["who"]] = s
        out = []
        for who, s in by_who.items():
            raw, sid = _raw(s), s.get("id")
            if self.pending:
                self.base[who] = raw                         # всё, что было до старта, не считается
            elif who not in self.ids:
                self.base[who] = _zero()                     # сессия трекера началась уже после старта
            elif self.ids[who] != sid:                       # трекер закрыл сессию и открыл новую
                self.acc[who] = _combine(self.acc.get(who, _zero()), _combine(self.last[who], self.base[who], -1), 1)
                self.base[who] = _zero()
            self.ids[who], self.last[who] = sid, raw
            v = _combine(self.acc.get(who, _zero()), _combine(raw, self.base[who], -1), 1)
            ore = {n: u for n, u in v["ore"].items() if u > 0}
            out.append({"id": f"manual|{self.t0}", "who": who, "t1": s["t1"], "dur": now - self.t0,
                        "out": v["out"], "in": v["in"], "reps_in": {"all": {"hp": v["rep"]}},
                        "reps_out": {"all": {"hp": v["rep_out"]}}, "bounty": v["bounty"],
                        "ore": ore, "ore_total": sum(ore.values()), "peak_dps": None})
        self.pending = False
        self.frozen = out
        return dict(live, sessions=out)


def demo_live() -> dict:
    now = int(time.time())
    k = now % 1000
    return {"now": now, "logs_dir_exists": True, "cur_sys": {"Test Pilot": "Jita", "Second Pilot": "Perimeter"}, "sessions": [
        {"id": "a", "who": "Test Pilot", "t0": now - 1800, "t1": now,
         "attackers": {"Alvus Queen": {"ship": "", "prof": [0.31, 0.0, 0.12, 0.57],
                                       "s10": [[now - now % 10 - 10, 1900], [now - now % 10, 900]]},
                       "Strain Render Alvi": {"ship": "", "prof": [0.0, 0.8, 0.2, 0.0], "s10": [[now - now % 10 - 10, 420]]}},
         "ewar": {"Варп-глушение — по вам": {"n": now // 7, "who": {"Strain Render Alvi": now // 7}}}, "out": 500000 + k * 640, "in": 90000 + k * 210,
         "reps_in": {"armor": {"hp": 20000 + k * 150}}, "reps_out": {}, "bounty": 18400000, "ore_total": 0, "peak_dps": 912},
        {"id": "b", "who": "Second Pilot", "t1": now - 40, "out": 0, "in": 0, "reps_in": {}, "reps_out": {},
         "bounty": 0, "ore": {"Veldspar": 48210 + k // 5 * 160}, "ore_total": 48210 + k // 5 * 160, "peak_dps": 0}]}


DEMO_META = {"types": {"Veldspar": {"id": 1230, "volume": 0.1}}, "prices": {"types": {"1230": {"buy": 14.2}}}}


def read_port() -> int:
    try:
        with open(os.path.join(DATA_DIR, "config.json"), encoding="utf-8") as f:
            return int(json.load(f).get("web_port") or 47322)
    except (OSError, ValueError, TypeError):
        return 47322


def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def load_settings() -> dict:
    """overlay.json поверх значений по умолчанию; мусор и неизвестные ключи не ломают запуск."""
    st = load_state()
    cfg = json.loads(json.dumps(DEFAULTS))
    a = st.get("alpha")
    if isinstance(a, (int, float)) and 0.3 <= a <= 1:
        cfg["alpha"] = float(a)
    if st.get("max_rows") in range(1, MAX_ROWS + 1):
        cfg["max_rows"] = st["max_rows"]
    if st.get("session_mode") in ("auto", "manual"):
        cfg["session_mode"] = st["session_mode"]
    for key in ("hotkeys", "fleet_enabled", "fleet_pilots"):
        if isinstance(st.get(key), bool):
            cfg[key] = st[key]
    if st.get("fleet_max") in range(3, 41):
        cfg["fleet_max"] = st["fleet_max"]
    for key, value in (st.get("show") or {}).items() if isinstance(st.get("show"), dict) else ():
        if key in cfg["show"] and isinstance(value, bool):
            cfg["show"][key] = value
    if st.get("compact") is True and "show" not in st:       # прежняя кнопка «коротко» = итоги выключены
        for key in cfg["show"]:
            if key.startswith("t_"):
                cfg["show"][key] = False
    for key in ("x", "y", "fleet_x", "fleet_y"):
        if isinstance(st.get(key), int):
            cfg[key] = st[key]
    return cfg


def save_state(d: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except OSError:
        pass


def session_file() -> str:
    return os.path.splitext(STATE_FILE)[0] + "_session.json"


def load_session(manual: "ManualSession") -> bool:
    try:
        with open(session_file(), encoding="utf-8") as f:
            return manual.load(json.load(f))
    except (OSError, ValueError):
        return False


def save_session(manual: "ManualSession") -> None:
    try:
        with open(session_file(), "w", encoding="utf-8") as f:
            json.dump(manual.dump(), f)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Опрос трекера (в отдельном потоке, чтобы окно не подвисало)
# ---------------------------------------------------------------------------

class Poller(threading.Thread):
    def __init__(self, port: int, demo: bool):
        super().__init__(daemon=True)
        self.url = f"http://127.0.0.1:{port}/api/live"
        self.demo = demo
        self.live: Optional[dict] = None
        self.meta: Optional[dict] = DEMO_META if demo else None      # справочник: объёмы и цены руды
        self.meta_at = 0.0
        self.fleet: Optional[dict] = DEMO_FLEET if demo else None    # ответ /api/fleet
        self.fleet_at = 0.0
        self.want_fleet = True
        self.fails = 0
        self.seq = 0

    def get(self, url: str, timeout: float) -> dict:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # локальный адрес — мимо прокси
        with opener.open(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def fetch(self) -> dict:
        if self.demo:
            return demo_live()
        live = self.get(self.url, 0.9)
        if self.want_fleet and time.time() - self.fleet_at > 3:        # состав флота — раз в 3 секунды
            self.fleet_at = time.time()
            try:
                self.fleet = self.get(self.url.replace("/api/live", "/api/fleet"), 8)
            except Exception:
                self.fleet = {"ok": False, "message": "модуль «Флот» не установлен или выключен"}
        mining = any(s.get("ore_total") for s in live.get("sessions") or [])
        if mining and time.time() - self.meta_at > 60:                 # справочник нужен только шахтёрам, раз в минуту
            self.meta_at = time.time()
            try:
                self.meta = self.get(self.url.replace("/api/live", "/api/meta"), 3)
            except Exception:
                pass
        return live

    def run(self):
        while True:
            t = time.time()
            try:
                self.live, self.fails = self.fetch(), 0
            except Exception:
                self.fails += 1
            self.seq += 1
            time.sleep(max(0.05, 1.0 - (time.time() - t)))


# ---------------------------------------------------------------------------
# Окно
# ---------------------------------------------------------------------------

BG, BAR, LINE = "#0c1016", "#1c222b", "#262d37"
FG, MUTED, IDLE = "#e8edf2", "#9aa7b4", "#6c7986"
C_OUT, C_IN, C_REP = "#5ad1ba", "#ff8a7a", "#7ab8ff"
C_ORE, C_ISK = "#e8c46a", "#b9e07a"
BIG_KEYS = ("dps", "dps_in", "hps", "bounty", "bounty_h")
TOTAL_OF = {"hps": "rep", "bounty": "bounty", "bounty_h": "bounty"}               # число показываем, только если по нему что-то набежало
FONT = "Segoe UI"

# что можно включать и выключать в настройках: (ключ, подпись)
SHOW_BIG = (("dps", "Урон в секунду"), ("dps_in", "Входящий урон в секунду"), ("hps", "Ремонт в секунду"),
            ("bounty", "Баунти за сессию"), ("bounty_h", "Баунти в час"), ("mining", "Добыча: м³ и ISK в час"))
SHOW_TOTALS = (("t_dur", "Длительность сессии"), ("t_out", "Нанесённый урон"), ("t_in", "Полученный урон"),
               ("t_rep", "Полученный ремонт"), ("t_rep_out", "Отданный ремонт"), ("t_peak", "Пиковый урон в секунду"),
               ("t_bounty", "Баунти"), ("t_ore", "Добытая руда и её цена"))
SHOW_OTHER = (("system", "Текущая система"),)
SHOW_THREATS = (("top_attacker", "Кто сейчас бьёт сильнее всех"), ("ewar", "Кто держит: варп-глушение, нейтрализация, помехи"),
                ("in_types", "Получаемый урон по типам и чем бьёт враг"))
TYPE_COLORS = {"em": "#5aa9ff", "therm": "#ff6b5a", "kin": "#c0c8d0", "exp": "#ffb347", "unknown": "#6c7986"}

HOTKEYS = {1: (0x0003, 0x53, "Ctrl+Alt+S"), 2: (0x0003, 0x48, "Ctrl+Alt+H")}   # MOD_CONTROL|MOD_ALT + S / H


class Hotkeys(threading.Thread):
    """Глобальные клавиши Windows: работают, когда в фокусе игра. Нажатия забирает окно через pop()."""

    def __init__(self):
        super().__init__(daemon=True)
        self.pressed: List[int] = []
        self.failed: List[str] = []
        self.thread_id = 0

    def run(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        for hid, (mod, vk, name) in HOTKEYS.items():
            if not user32.RegisterHotKey(None, hid, mod | 0x4000, vk):      # MOD_NOREPEAT
                self.failed.append(name)                                    # клавиша занята другой программой
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:                                       # WM_HOTKEY
                self.pressed.append(int(msg.wParam))
        for hid in HOTKEYS:
            user32.UnregisterHotKey(None, hid)

    def stop(self):
        if self.thread_id:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)   # WM_QUIT

    def pop(self) -> List[int]:
        out, self.pressed = self.pressed, []
        return out


def run_window(port: int, demo: bool) -> int:
    import ctypes
    import tkinter as tk

    user32 = ctypes.windll.user32
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "EveLogHudOverlay" + ("Demo" if demo else ""))
    if ctypes.windll.kernel32.GetLastError() == 183:         # второй экземпляр не нужен
        return 0
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    cfg = load_settings()
    show = cfg["show"]
    root = tk.Tk()
    root.title("EVE Log HUD")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", cfg["alpha"])
    root.configure(bg=LINE)
    k = root.winfo_fpixels("1i") / 96.0                     # масштаб экрана
    px = lambda v: int(round(v * k))
    width = px(300)

    manual = ManualSession()
    if cfg["session_mode"] == "manual":
        load_session(manual)                                 # продолжить сессию, начатую до перезапуска
    rates = Rates()
    poller = Poller(port, demo)
    hot = Hotkeys() if cfg["hotkeys"] else None
    seen = {"seq": -1, "ticks": 0, "hidden": False, "threats": {}}
    threats = Threats()

    box = tk.Frame(root, bg=BG)
    box.pack(padx=1, pady=1, fill="both", expand=True)
    bar = tk.Frame(box, bg=BAR, cursor="fleur")
    bar.pack(fill="x")
    dot = tk.Canvas(bar, width=px(9), height=px(9), bg=BAR, highlightthickness=0)
    dot_id = dot.create_oval(1, 1, px(8), px(8), fill="#7b8a8b", outline="")
    dot.pack(side="left", padx=(px(8), px(5)))
    title = tk.Label(bar, text="EVE Log HUD", bg=BAR, fg=MUTED, font=(FONT, 8))
    title.pack(side="left")

    def flat_button(parent, text, command, side="right", font=(FONT, 10), **kw):
        b = tk.Label(parent, text=text, bg=BAR, fg=MUTED, font=font, cursor="hand2", **kw)
        b.bind("<Button-1>", lambda e: command())
        b.bind("<Enter>", lambda e: b.configure(fg="#ffffff", bg="#39424e"))
        b.bind("<Leave>", lambda e: b.configure(fg=MUTED, bg=BAR))
        b.pack(side=side)
        return b

    # полоса ручной сессии: «Старт / Стоп / Сброс» и время
    strip = tk.Frame(box, bg=BAR)
    strip_sep = tk.Frame(strip, bg=LINE, height=1)
    strip_sep.pack(fill="x")
    strip_in = tk.Frame(strip, bg=BAR)
    strip_in.pack(fill="x", padx=px(6), pady=px(2))
    strip_buttons: List = []
    strip_status = tk.Label(strip_in, bg=BAR, fg=MUTED, font=(FONT, 8), anchor="e")
    strip_status.pack(side="right")

    body = tk.Frame(box, bg=BG)
    body.pack(fill="both", expand=True)
    note = tk.Label(body, bg=BG, fg="#c8d1da", font=(FONT, 9), justify="left", anchor="w", wraplength=width - px(20))
    rows_ui: Dict[str, dict] = {}
    order: List[str] = []

    def remember():
        cfg["x"], cfg["y"] = root.winfo_x(), root.winfo_y()
        save_state(cfg)

    def refresh():
        seen["seq"] = -1                                     # перерисовать на ближайшем тике

    def quit_app():
        remember()
        if hot:
            hot.stop()
        root.destroy()

    # --- ручная сессия ---
    def session_start():
        nonlocal rates
        manual.start(time.time())
        rates = Rates()
        save_session(manual)
        build_strip()
        refresh()

    def session_stop():
        manual.stop(time.time())
        save_session(manual)
        build_strip()
        refresh()

    def session_reset():
        nonlocal rates
        manual.reset()
        rates = Rates()
        save_session(manual)
        build_strip()
        refresh()

    def session_toggle():
        if cfg["session_mode"] == "manual":
            (session_stop if manual.state == "running" else session_start)()

    def build_strip():
        for b in strip_buttons:
            b.destroy()
        strip_buttons.clear()
        if cfg["session_mode"] != "manual":
            strip.pack_forget()
            return
        strip.pack(fill="x", after=bar)
        if manual.state == "running":
            items = (("■ Стоп", session_stop),)
        elif manual.state == "stopped":
            items = (("▶ Новая", session_start), ("↺ Сброс", session_reset))
        else:
            items = (("▶ Старт", session_start),)
        for text, command in items:
            strip_buttons.append(flat_button(strip_in, text, command, side="left", font=(FONT, 9), padx=px(6)))
        update_strip()

    def update_strip():
        if cfg["session_mode"] != "manual":
            return
        el = fmt_dur(manual.elapsed(time.time()))
        strip_status.configure(text={"running": f"идёт  {el}", "stopped": f"остановлена  {el}"}.get(manual.state, "не начата"),
                               fg=C_OUT if manual.state == "running" else MUTED)

    # --- настройки ---
    settings_win = {"w": None}

    def open_settings():
        if settings_win["w"] is not None and settings_win["w"].winfo_exists():
            settings_win["w"].lift()
            return
        w = tk.Toplevel(root)
        settings_win["w"] = w
        w.title("Настройки EVE Log HUD")
        w.configure(bg=BG, padx=px(16), pady=px(12))
        w.resizable(False, False)
        w.attributes("-topmost", True)

        def header(text, parent=w):
            tk.Label(parent, text=text, bg=BG, fg=FG, font=(FONT, 10, "bold"), anchor="w").pack(fill="x", pady=(px(10), px(2)))

        def hint(text, parent=w):
            tk.Label(parent, text=text, bg=BG, fg=MUTED, font=(FONT, 8), anchor="w", justify="left",
                     wraplength=px(330)).pack(fill="x")

        style = dict(bg=BG, fg=FG, selectcolor=BAR, activebackground=BG, activeforeground="#ffffff", font=(FONT, 9),
                     anchor="w", highlightthickness=0, bd=0)

        def checks(parent, items):
            for key, label in items:
                var = tk.BooleanVar(w, value=bool(show.get(key)))

                def on(key=key, var=var):
                    show[key] = bool(var.get())
                    save_state(cfg)
                    refresh()
                cb = tk.Checkbutton(parent, text=label, variable=var, command=on, **style)
                cb.var = var
                cb.pack(fill="x")

        cols = tk.Frame(w, bg=BG)
        cols.pack(fill="x")
        left = tk.Frame(cols, bg=BG)
        left.pack(side="left", anchor="n", padx=(0, px(24)))
        right = tk.Frame(cols, bg=BG)
        right.pack(side="left", anchor="n")

        header("Крупные числа", left)
        checks(left, SHOW_BIG)
        header("Прочее", left)
        checks(left, SHOW_OTHER)
        header("Угрозы", left)
        checks(left, SHOW_THREATS)
        header("Строка итогов", right)
        checks(right, SHOW_TOTALS)

        header("Сессия")
        mode = tk.StringVar(w, value=cfg["session_mode"])

        def on_mode():
            nonlocal rates
            cfg["session_mode"] = mode.get()
            manual.reset()
            rates = Rates()
            save_state(cfg)
            build_strip()
            refresh()
        for value, label, text in (
                ("auto", "Автоматически", "Как в трекере: сессия начинается с первым событием в логе и закрывается после паузы."),
                ("manual", "Вручную", "Считается только то, что произошло между «Старт» и «Стоп». "
                                      "История в трекере при этом пишется как обычно.")):
            rb = tk.Radiobutton(w, text=label, value=value, variable=mode, command=on_mode, **style)
            rb.pack(fill="x")
            hint(text)

        header("Окно")
        scale_style = dict(orient="horizontal", bg=BG, fg=FG, troughcolor=BAR, highlightthickness=0, bd=0,
                           font=(FONT, 8), length=px(330), sliderlength=px(18))

        def on_alpha(v):
            cfg["alpha"] = int(v) / 100.0
            root.attributes("-alpha", cfg["alpha"])
            fw.attributes("-alpha", cfg["alpha"])
        tk.Label(w, text="Непрозрачность, %", bg=BG, fg=MUTED, font=(FONT, 8), anchor="w").pack(fill="x")
        sc = tk.Scale(w, from_=30, to=100, command=on_alpha, **scale_style)
        sc.set(int(round(cfg["alpha"] * 100)))
        sc.pack(anchor="w")
        sc.bind("<ButtonRelease-1>", lambda e: save_state(cfg))

        def on_rows(v):
            cfg["max_rows"] = int(v)
            refresh()
        tk.Label(w, text="Сколько персонажей показывать", bg=BG, fg=MUTED, font=(FONT, 8), anchor="w").pack(fill="x", pady=(px(6), 0))
        sr = tk.Scale(w, from_=1, to=MAX_ROWS, command=on_rows, **scale_style)
        sr.set(cfg["max_rows"])
        sr.pack(anchor="w")
        sr.bind("<ButtonRelease-1>", lambda e: save_state(cfg))

        header("Окно флота")
        for key, label in (("fleet_enabled", "Показывать окно флота, когда я во флоте"),
                           ("fleet_pilots", "Список пилотов (без него — только сводка по кораблям и системам)")):
            var = tk.BooleanVar(w, value=cfg[key])

            def on_fleet(key=key, var=var):
                cfg[key] = bool(var.get())
                poller.want_fleet = cfg["fleet_enabled"]
                save_state(cfg)
                seen["fleet_key"] = None
            cb = tk.Checkbutton(w, text=label, variable=var, command=on_fleet, **style)
            cb.var = var
            cb.pack(fill="x")
        hint("Сейчас: " + fleet_status(poller.fleet) + ".\nСостав читается напрямую из игры: войдите через EVE "
             "на вкладке «Флот» в окне приложения и будьте боссом флота.")

        header("Горячие клавиши")
        hk = tk.BooleanVar(w, value=cfg["hotkeys"])

        def on_hk():
            cfg["hotkeys"] = bool(hk.get())
            save_state(cfg)
        cb = tk.Checkbutton(w, text="Включить (применится после перезапуска оверлея)", variable=hk, command=on_hk, **style)
        cb.var = hk
        cb.pack(fill="x")
        text = "Ctrl+Alt+H — скрыть или показать окно.   Ctrl+Alt+S — старт или стоп ручной сессии."
        if hot and hot.failed:
            text += "\nНе удалось занять: " + ", ".join(hot.failed) + " (клавиша используется другой программой)."
        hint(text)

        close = tk.Label(w, text="Готово", bg=BAR, fg=FG, font=(FONT, 9), padx=px(18), pady=px(5), cursor="hand2")
        close.bind("<Button-1>", lambda e: w.destroy())
        close.pack(anchor="e", pady=(px(12), 0))
        w.update_idletasks()
        w.geometry(f"+{max(0, (w.winfo_screenwidth() - w.winfo_width()) // 2)}+{max(0, (w.winfo_screenheight() - w.winfo_height()) // 3)}")

    flat_button(bar, "×", quit_app, width=2)
    flat_button(bar, "⚙", open_settings, width=2)

    # перетаскивание за заголовок
    drag = {}

    def drag_start(e):
        drag.update(x=e.x_root - root.winfo_x(), y=e.y_root - root.winfo_y())

    def drag_move(e):
        if drag:
            root.geometry(f"+{e.x_root - drag['x']}+{e.y_root - drag['y']}")

    def drag_end(e):
        drag.clear()
        remember()

    for wdg in (bar, title, dot):
        wdg.bind("<Button-1>", drag_start)
        wdg.bind("<B1-Motion>", drag_move)
        wdg.bind("<ButtonRelease-1>", drag_end)

    def make_row(who: str) -> dict:
        f = tk.Frame(body, bg=BG)
        tk.Frame(f, bg=LINE, height=1).pack(fill="x")
        inner = tk.Frame(f, bg=BG)
        inner.pack(fill="x", padx=px(9), pady=(px(5), px(7)))
        head = tk.Frame(inner, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text=who, bg=BG, fg=FG, font=(FONT, 9, "bold"), anchor="w").pack(side="left")
        system = tk.Label(head, bg=BG, fg=MUTED, font=(FONT, 8), anchor="e")
        system.pack(side="right")
        cells = {}

        def cell(parent, key, color, label, share):
            c = tk.Frame(parent, bg=BG, width=(width - px(20)) // share, height=px(46))
            c.pack_propagate(False)
            v = tk.Label(c, bg=BG, fg=color, font=(FONT, 16, "bold"), anchor="w")
            v.pack(fill="x")
            lab = tk.Label(c, text=label, bg=BG, fg=MUTED, font=(FONT, 7), anchor="w")
            lab.pack(fill="x")
            cells[key] = {"frame": c, "value": v, "color": color, "label": lab}

        big = tk.Frame(inner, bg=BG)
        for key, label, color in (("dps", "УРОН/С", C_OUT), ("dps_in", "ПО МНЕ/С", C_IN), ("hps", "РЕМОНТ/С", C_REP),
                                  ("bounty", "БАУНТИ, ISK", C_ISK), ("bounty_h", "ISK В ЧАС", C_ISK)):
            cell(big, key, color, label, 3)
        big2 = tk.Frame(inner, bg=BG)                        # баунти уходит на вторую строку, если в первой тесно
        for key, label in (("bounty", "БАУНТИ, ISK"), ("bounty_h", "ISK В ЧАС")):
            cell(big2, key + "_2", C_ISK, label, 2)
        mine = tk.Frame(inner, bg=BG)                        # строка добычи — только у тех, кто копает
        for key, color in (("mine_vol", C_ORE), ("mine_isk", C_ISK)):
            cell(mine, key, color, "", 2)
            cells[key]["frame"].pack(side="left")
        totals = tk.Label(inner, bg=BG, fg=MUTED, font=(FONT, 8), justify="left", anchor="w", wraplength=width - px(20))
        effects = tk.Label(inner, bg=BG, fg="#ffb347", font=(FONT, 9, "bold"), justify="left", anchor="w", wraplength=width - px(20))
        attacker = tk.Label(inner, bg=BG, fg=C_IN, font=(FONT, 8), justify="left", anchor="w", wraplength=width - px(20))
        types_row = tk.Frame(inner, bg=BG)                   # «ЭМ 12 · терм 120 …» — каждый тип своим цветом
        type_labels = {}
        for key, _ in DMG_TYPES + (("unknown", ""),):
            type_labels[key] = tk.Label(types_row, bg=BG, fg=TYPE_COLORS[key], font=(FONT, 9, "bold"), anchor="w")
        return {"effects": effects, "attacker": attacker, "types_row": types_row, "type_labels": type_labels,"frame": f, "system": system, "cells": cells, "totals": totals, "big": big, "big2": big2, "mine": mine, "layout": None}

    def render(rows: List[dict]):
        nonlocal order
        names = [r["who"] for r in rows]
        if names != order:                                   # состав изменился — пересобрать строки
            for ui in rows_ui.values():
                ui["frame"].destroy()
            rows_ui.clear()
            for n in names:
                rows_ui[n] = make_row(n)
                rows_ui[n]["frame"].pack(fill="x")
            order = names
        for r in rows:
            ui = rows_ui[r["who"]]
            ui["system"].configure(text=r["system"] if show["system"] else "")
            bigs = tuple(key for key in BIG_KEYS if show[key] and (key not in TOTAL_OF or r[TOTAL_OF[key]] > 0))
            mining = show["mining"] and r["ore"] > 0
            text = totals_text(r, dict(show, t_bounty=False) if "bounty" in bigs else show)   # баунти — не дважды
            second = ()
            if len(bigs) > 4:                                # пять чисел в ряд не читаются — баунти на свою строку
                second = tuple(key for key in bigs if key.startswith("bounty"))
                bigs = tuple(key for key in bigs if not key.startswith("bounty"))
            th = seen["threats"].get(r["who"])
            eff = effects_text(th) if show["ewar"] else ""
            att = attacker_text(th, show["in_types"]) if show["top_attacker"] else ""
            tcells = types_cells(th) if show["in_types"] else []
            layout = (bigs, second, mining, bool(text), bool(eff), bool(att), tuple(c[2] for c in tcells))
            if layout != ui["layout"]:                       # набор блоков изменился — переложить
                ui["layout"] = layout
                for key in BIG_KEYS + ("bounty_2", "bounty_h_2"):
                    ui["cells"][key]["frame"].pack_forget()
                for part in (ui["big"], ui["big2"], ui["mine"], ui["totals"], ui["effects"], ui["attacker"], ui["types_row"]):
                    part.pack_forget()
                for lab in ui["type_labels"].values():
                    lab.pack_forget()
                if eff:                                      # кто держит — первым делом, это срочнее цифр
                    ui["effects"].pack(fill="x", pady=(px(2), 0))
                if att:
                    ui["attacker"].pack(fill="x", pady=(px(1), px(1)))
                if tcells:
                    ui["types_row"].pack(fill="x", pady=(0, px(1)))
                    for _, _, key in tcells:
                        ui["type_labels"][key].pack(side="left", padx=(0, px(9)))
                if bigs:
                    ui["big"].pack(fill="x")
                    for key in bigs:                        # четыре числа в ряд — шрифт мельче, чтобы поместились
                        c = ui["cells"][key]
                        c["frame"].configure(width=(width - px(20)) // max(3, len(bigs)))
                        c["value"].configure(font=(FONT, 12 if len(bigs) == 4 else 16, "bold"))
                        c["frame"].pack(side="left")
                if second:
                    ui["big2"].pack(fill="x")
                    for key in second:
                        ui["cells"][key + "_2"]["frame"].pack(side="left")
                if mining:
                    ui["mine"].pack(fill="x")
                if text:
                    ui["totals"].pack(fill="x", pady=(px(3), 0))
            for key, c in [(key, ui["cells"][key]) for key in bigs] + [(key, ui["cells"][key + "_2"]) for key in second]:
                c["value"].configure(text=fmt(r[key]), fg=c["color"] if r[key] >= 0.5 else IDLE)
            if mining:
                vol, vol_label = (r["m3_h"], "М³ В ЧАС") if r["ore_m3"] is not None else (r["ore_h"], "ЕД. РУДЫ В ЧАС")
                for key, value, label in (("mine_vol", vol, vol_label), ("mine_isk", r["isk_h"], "ISK В ЧАС")):
                    c = ui["cells"][key]
                    known = key != "mine_isk" or r["ore_isk"] is not None
                    c["value"].configure(text=fmt(value) if known else "—", fg=c["color"] if value >= 0.5 else IDLE)
                    c["label"].configure(text=label)
            ui["totals"].configure(text=text)
            ui["effects"].configure(text=eff)
            ui["attacker"].configure(text=att)
            for label, value, key in tcells:
                ui["type_labels"][key].configure(text=f"{label} {fmt(value)}")

    def set_note(text: str):
        if text:
            note.configure(text=text)
            note.pack(fill="x", padx=px(9), pady=px(8))
        else:
            note.pack_forget()

    # --- окно флота ---
    fw = tk.Toplevel(root)
    fw.overrideredirect(True)
    fw.attributes("-topmost", True)
    fw.attributes("-alpha", cfg["alpha"])
    fw.configure(bg=LINE)
    fw.withdraw()
    fbox = tk.Frame(fw, bg=BG)
    fbox.pack(padx=1, pady=1, fill="both", expand=True)
    fbar = tk.Frame(fbox, bg=BAR, cursor="fleur")
    fbar.pack(fill="x")
    ftitle = tk.Label(fbar, text="Флот", bg=BAR, fg=MUTED, font=(FONT, 8), anchor="w")
    ftitle.pack(side="left", padx=(px(8), 0))

    def fleet_off():
        cfg["fleet_enabled"] = False
        poller.want_fleet = False
        save_state(cfg)
        seen["fleet_key"] = None
    flat_button(fbar, "×", fleet_off, width=2)
    fbody = tk.Frame(fbox, bg=BG)
    fbody.pack(fill="both", expand=True, padx=px(9), pady=(px(5), px(7)))
    fdrag = {}

    def fdrag_start(e):
        fdrag.update(x=e.x_root - fw.winfo_x(), y=e.y_root - fw.winfo_y())

    def fdrag_move(e):
        if fdrag:
            fw.geometry(f"+{e.x_root - fdrag['x']}+{e.y_root - fdrag['y']}")

    def fdrag_end(e):
        fdrag.clear()
        cfg["fleet_x"], cfg["fleet_y"] = fw.winfo_x(), fw.winfo_y()
        save_state(cfg)
    for wdg in (fbar, ftitle):
        wdg.bind("<Button-1>", fdrag_start)
        wdg.bind("<B1-Motion>", fdrag_move)
        wdg.bind("<ButtonRelease-1>", fdrag_end)

    def cut(text: str, n: int) -> str:
        return text if len(text) <= n else text[:n - 1] + "…"

    def update_fleet():
        view = fleet_view(poller.fleet, cfg["fleet_max"]) if cfg["fleet_enabled"] else None
        key = json.dumps([view, cfg["fleet_pilots"], seen["hidden"]], ensure_ascii=False, sort_keys=True)
        if key == seen.get("fleet_key"):
            return
        seen["fleet_key"] = key
        if view is None or seen["hidden"]:
            fw.withdraw()
            return
        for child in fbody.winfo_children():
            child.destroy()
        ftitle.configure(text=cut(view["title"], 40))
        wrap = width - px(20)
        tk.Label(fbody, text=view["head"], bg=BG, fg=FG, font=(FONT, 9, "bold"), anchor="w", justify="left", wraplength=wrap).pack(fill="x")
        tk.Label(fbody, text=view["ships"], bg=BG, fg=C_ORE, font=(FONT, 10, "bold"), anchor="w", justify="left", wraplength=wrap).pack(fill="x", pady=(px(3), 0))
        tk.Label(fbody, text=view["systems"], bg=BG, fg=C_REP, font=(FONT, 9), anchor="w", justify="left", wraplength=wrap).pack(fill="x", pady=(px(1), 0))
        if view["stale"]:
            tk.Label(fbody, text=view["stale"], bg=BG, fg="#ffb347", font=(FONT, 8), anchor="w").pack(fill="x")
        if cfg["fleet_pilots"] and view["rows"]:
            tk.Frame(fbody, bg=LINE, height=1).pack(fill="x", pady=(px(5), px(3)))
            grid = tk.Frame(fbody, bg=BG)
            grid.pack(fill="x")
            grid.columnconfigure(0, weight=1)
            for i, r in enumerate(view["rows"]):
                fg = "#ffffff" if r["me"] else FG
                tk.Label(grid, text=cut(r["name"], 20), bg=BG, fg=fg, font=(FONT, 8, "bold" if r["me"] else "normal"), anchor="w").grid(row=i, column=0, sticky="w")
                tk.Label(grid, text=cut(r["ship"], 16), bg=BG, fg=C_ORE, font=(FONT, 8), anchor="w").grid(row=i, column=1, sticky="w", padx=(px(6), px(6)))
                tk.Label(grid, text=cut(r["system"], 14), bg=BG, fg=MUTED, font=(FONT, 8), anchor="e").grid(row=i, column=2, sticky="e")
            if view["more"]:
                tk.Label(fbody, text=f"… ещё {view['more']}", bg=BG, fg=MUTED, font=(FONT, 8), anchor="w").pack(fill="x")
        fw.deiconify()
        fw.attributes("-topmost", True)
        if not seen.get("fleet_styled"):                     # не забирать фокус у игры, не светиться в панели задач
            seen["fleet_styled"] = True
            fw.update_idletasks()
            no_activate(fw)

    def toggle_hidden():
        seen["hidden"] = not seen["hidden"]
        (root.withdraw if seen["hidden"] else root.deiconify)()
        if not seen["hidden"]:
            root.attributes("-topmost", True)

    def tick():
        for hid in (hot.pop() if hot else ()):
            (session_toggle if hid == 1 else toggle_hidden)()
        if poller.seq != seen["seq"]:
            seen["seq"] = poller.seq
            update_strip()
            update_fleet()
            if poller.fails >= 3 or (poller.live is None and poller.fails):
                dot.itemconfigure(dot_id, fill="#e74c3c")
                render([])
                set_note("EVE Log Watcher не запущен.\nЗапустите трекер — данные появятся сами.")
            elif poller.live is not None and not poller.fails:
                dot.itemconfigure(dot_id, fill="#18bc9c")
                is_manual = cfg["session_mode"] == "manual"
                seen["threats"] = threats.update(poller.live)
                src = manual.apply(poller.live, time.time()) if is_manual else poller.live
                if is_manual and manual.state == "running" and seen["ticks"] % 20 == 0:
                    save_session(manual)                     # раз в 5 секунд — на случай внезапного закрытия
                rows = rates.update(src, meta=poller.meta, max_rows=cfg["max_rows"])
                render(rows)
                if rows:
                    set_note("")
                elif is_manual and manual.state == "idle":
                    set_note("Ручная сессия не начата.\nНажмите «Старт»" + (" или Ctrl+Alt+S." if hot else "."))
                elif not poller.live.get("logs_dir_exists", True):
                    set_note("Трекер не нашёл папку логов EVE.\nПроверьте logs_dir в config.json.")
                else:
                    set_note("Пока нет событий.\nВ игре: Esc → Чат → «Вести журнал в файле».")
        seen["ticks"] += 1
        if seen["ticks"] % 8 == 0 and not seen["hidden"]:    # игра может перекрыть окно — возвращаемся наверх
            root.attributes("-topmost", True)
            if fw.state() == "normal":
                fw.attributes("-topmost", True)
        root.after(250, tick)

    # стартовая позиция (если сохранённая оказалась за пределами экрана — вернуть в угол)
    x, y = cfg.get("x"), cfg.get("y")
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    if not (isinstance(x, int) and isinstance(y, int) and -50 <= x <= sw - 60 and 0 <= y <= sh - 40):
        x, y = px(24), px(140)
    root.minsize(width, 1)
    root.maxsize(width, sh)
    root.geometry(f"+{x}+{y}")
    build_strip()
    root.update_idletasks()

    # окна не забирают фокус у игры и не показываются в панели задач
    def no_activate(win):
        try:
            hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
            get, put = user32.GetWindowLongPtrW, user32.SetWindowLongPtrW
            get.restype = ctypes.c_ssize_t
            get.argtypes = [ctypes.c_void_p, ctypes.c_int]
            put.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
            put(hwnd, -20, get(hwnd, -20) | 0x08000000 | 0x00000080)     # WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        except Exception:
            pass
    no_activate(root)
    fx, fy = cfg.get("fleet_x"), cfg.get("fleet_y")
    if not (isinstance(fx, int) and isinstance(fy, int) and -50 <= fx <= sw - 60 and 0 <= fy <= sh - 40):
        fx, fy = x + width + px(12), y                        # по умолчанию — справа от основного окна
    fw.minsize(width, 1)
    fw.maxsize(width, sh)
    fw.geometry(f"+{fx}+{fy}")
    poller.want_fleet = cfg["fleet_enabled"]

    poller.start()
    if hot:
        hot.start()
    if os.environ.get("EVE_OVERLAY_OPEN_SETTINGS"):          # для проверки вида: сразу открыть настройки
        root.after(600, open_settings)
    tick()
    root.mainloop()
    del mutex
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="EVE Log HUD — окно поверх игры с данными EVE Log Watcher")
    ap.add_argument("--demo", action="store_true", help="показать пример с выдуманными числами, без трекера")
    ap.add_argument("--port", type=int, default=0, help="порт трекера (по умолчанию — web_port из config.json)")
    a = ap.parse_args()
    if sys.platform != "win32":
        print("Оверлей работает только в Windows.")
        return 1
    return run_window(a.port or read_port(), a.demo)


if __name__ == "__main__":
    sys.exit(main())
