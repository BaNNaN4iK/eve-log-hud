# -*- coding: utf-8 -*-
"""
Справочник EVE: разделы с таблицами по данным игры. Первый раздел — «Руда»: вся руда в игре, где добывается,
во что перерабатывается, варианты и сжатая руда.

Только стандартная библиотека. Данные — справочник игры (reference_data.json, собран из SDE скриптом
build_reference_data.py), работают без интернета. «Где добывается» в SDE нет — это правила игры, записанные ниже (WHERE).
Стоимость — по средним ценам игры (ESI /markets/prices/), если включены онлайн-функции.
"""
import json
import os
import re
import threading
import time
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
PRICES_TTL = 6 * 3600

# вид руды по группе игры
CATS = {
    "standard": ("Обычная", {450, 451, 452, 453, 454, 455, 456, 457, 458, 459, 460, 461, 462, 467, 468, 469}),
    "moon": ("Лунная", {1884, 1920, 1921, 1922, 1923}),
    "equinox": ("Equinox", {4513, 4514, 4515, 4516, 4755, 4756, 4757, 4758, 4759}),
    "pochven": ("Почвен", {4029, 4030, 4031}),
}
MOON_RANK = {1884: "R4 · повсеместная", 1920: "R8 · обычная", 1921: "R16 · необычная", 1922: "R32 · редкая", 1923: "R64 · исключительная"}

# где добывается: хай / лоу / нули / ВХ / Почвен + пояснение (по правилам игры; точный набор поясов зависит от региона)
HS, LS, NS, WH, PV = "hs", "ls", "ns", "wh", "pv"
BELT = "пояса астероидов и рудные аномалии"
WHERE: Dict[int, Tuple[List[str], str]] = {
    462: ([HS, LS, NS, WH], BELT + "; есть почти везде"),
    460: ([HS, LS, NS, WH], BELT),
    459: ([HS, LS, NS, WH], BELT),
    458: ([HS, LS, NS, WH], BELT),
    469: ([HS, LS, NS, WH], BELT + "; в хай-секе — в системах 0.7 и ниже"),
    457: ([HS, LS, NS, WH], BELT + "; в хай-секе — в системах 0.7 и ниже"),
    456: ([LS, NS, WH], BELT),
    455: ([LS, NS, WH], BELT),
    454: ([LS, NS, WH], BELT),
    467: ([NS, WH], BELT),
    453: ([NS, WH], BELT),
    461: ([NS, WH], BELT),
    452: ([NS, WH], BELT),
    451: ([NS, WH], BELT),
    450: ([NS, WH], BELT),
    468: ([NS, WH], BELT + "; добывается только лазером Deep Core с кристаллами для Mercoxit"),
    1884: ([HS, LS, NS, WH], "бурение лун (Athanor, Tatara)"),
    1920: ([HS, LS, NS, WH], "бурение лун (Athanor, Tatara)"),
    1921: ([LS, NS, WH], "бурение лун (Athanor, Tatara)"),
    1922: ([LS, NS, WH], "бурение лун (Athanor, Tatara)"),
    1923: ([LS, NS, WH], "бурение лун (Athanor, Tatara)"),
    4029: ([PV], "Почвен — триглавское пространство"),
    4030: ([PV], "Почвен — триглавское пространство"),
    4031: ([PV], "Почвен — триглавское пространство"),
}
for _g in CATS["equinox"][1]:
    WHERE[_g] = ([NS], "нули: рудные аномалии от улучшений систем (Equinox)")
SPECIAL_NOTE = "особые места: события, сайты, задания — в справочнике игры место не указано"

GRADE = re.compile(r"\s+(0|II|III|IV)-Grade$")
MOON_PLUS = {"Brimful": 15, "Copious": 15, "Lavish": 15, "Replete": 15, "Bountiful": 15,
             "Glistening": 100, "Twinkling": 100, "Shimmering": 100, "Glowing": 100, "Shining": 100}


def load_data(path: Optional[str] = None) -> dict:
    try:
        with open(path or os.path.join(HERE, "reference_data.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"ores": [], "groups": {}, "materials": {}}


def split_name(name: str) -> Tuple[str, str, bool]:
    """«Batch Compressed Veldspar II-Grade» → ("Veldspar", "II", True); «Glistening Zeolites» → ("Zeolites", "Glistening", False)."""
    compressed = False
    for pre in ("Batch Compressed ", "Compressed "):
        if name.startswith(pre):
            name, compressed = name[len(pre):], True
    grade = ""
    m = GRADE.search(name)
    if m:
        grade, name = m.group(1), name[:m.start()]
    first = name.split(" ", 1)
    if len(first) == 2 and first[0] in MOON_PLUS:
        grade, name = first[0], first[1]
    return name, grade, compressed


def category(gid: int) -> str:
    for key, (_, groups) in CATS.items():
        if gid in groups:
            return key
    return "special"


def ore_table(data: dict, prices: Optional[Dict[int, float]] = None) -> dict:
    """Семейства руд: базовая руда + варианты и сжатая; выход минералов на порцию, ISK за м³ по средним ценам."""
    prices = prices or {}
    fams: Dict[str, dict] = {}
    for tid, en, ru, gid, portion, vol, mats in data.get("ores", []):
        base, grade, comp = split_name(en)
        key = f"{gid}:{base}"
        f = fams.setdefault(key, {"name": base, "group_id": gid, "variants": []})
        value = sum((prices.get(m) or 0) * q for m, q in mats) if prices and mats else None
        f["variants"].append({"type_id": tid, "name": en, "ru": ru, "grade": grade, "compressed": comp, "portion": portion,
                              "volume": vol, "mats": mats, "value": value,
                              "isk_m3": value / (portion * vol) if value and vol else None})
    out = []
    for f in fams.values():
        vs = f["variants"]
        base = next((v for v in vs if not v["grade"] and not v["compressed"]), None) or next((v for v in vs if not v["compressed"]), vs[0])
        total = sum(q for _, q in base["mats"]) or 0
        for v in vs:                                          # прибавка к выходу относительно базовой руды
            vt = sum(q for _, q in v["mats"])
            v["bonus"] = round((vt / total - 1) * 100) if total and vt else 0
        vs.sort(key=lambda v: (v["compressed"], v["bonus"], v["name"]))
        gid = f["group_id"]
        where, note = WHERE.get(gid, ([], SPECIAL_NOTE))
        cat = category(gid)
        if not any(v["mats"] for v in vs):                    # в группе обычной руды, но не перерабатывается — служебный предмет
            cat, where, note = "special", [], "не перерабатывается и не встречается в поясах — служебный или старый предмет игры"
        out.append({"name": f["name"], "type_id": base["type_id"], "ru": base["ru"], "group_id": gid,
                    "group": (data.get("groups", {}).get(str(gid)) or [""])[0], "cat": cat, "cat_name": CATS[cat][0] if cat in CATS else "Особая",
                    "rank": MOON_RANK.get(gid, ""), "where": where, "note": note, "portion": base["portion"], "volume": base["volume"],
                    "mats": base["mats"], "value": base["value"], "isk_m3": base["isk_m3"],
                    "variants": [v for v in vs if v is not base]})
    order = {"standard": 0, "moon": 1, "equinox": 2, "pochven": 3, "special": 4}
    out.sort(key=lambda r: (order[r["cat"]], r["group_id"] if r["cat"] == "moon" else 0, r["name"]))
    return {"ores": out, "materials": {k: v[0] for k, v in data.get("materials", {}).items()},
            "cats": [[k, v[0]] for k, v in CATS.items()] + [["special", "Особая"]]}


class Prices:
    """Средние цены игры (ESI /markets/prices/) — одним запросом, кэш на диске на 6 часов."""

    def __init__(self, esi, path: str = ""):
        self.esi, self.path = esi, path
        self.lock = threading.Lock()
        self.at, self.prices = 0, {}
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            self.at, self.prices = d.get("at", 0), {int(k): v for k, v in (d.get("prices") or {}).items()}
        except (OSError, ValueError, AttributeError):
            pass
        self.busy = False

    def get(self, want: set, now: Optional[float] = None) -> Dict[int, float]:
        now = time.time() if now is None else now
        if self.esi is not None and now - self.at >= PRICES_TTL and not self.busy:
            threading.Thread(target=self.refresh, args=(want,), name="reference-prices", daemon=True).start()
        return {t: p for t, p in self.prices.items() if t in want}

    def refresh(self, want: set) -> None:
        with self.lock:
            if self.busy:
                return
            self.busy = True
        try:
            rows, _ = self.esi("/markets/prices/")
            self.prices = {r["type_id"]: r.get("average_price") or r.get("adjusted_price") for r in rows or [] if r.get("type_id") in want}
            self.at = int(time.time())
            if self.path:
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump({"at": self.at, "prices": self.prices}, f)
        except Exception:
            self.at = int(time.time()) - PRICES_TTL + 600       # не получилось — повторим через 10 минут
        finally:
            self.busy = False


def setup(ctx) -> None:
    data = load_data()
    want = {int(k) for k in data.get("materials", {})}
    prices = Prices(ctx.online.esi if ctx.online is not None else None, os.path.join(ctx.data_dir, "reference_prices.json"))
    icons_done = {"v": False}

    def ores(qs):
        res = ore_table(data, prices.get(want))
        if ctx.online is not None and not icons_done["v"]:
            icons_done["v"] = True
            ids = [r["type_id"] for r in res["ores"]] + [v["type_id"] for r in res["ores"] for v in r["variants"]] + sorted(want)
            threading.Thread(target=lambda: [ctx.online.fetch_icon(i) for i in ids], name="reference-icons", daemon=True).start()
        return {"ok": True, **res, "prices_at": prices.at or None, "online": ctx.online is not None, "built": data.get("built")}

    ctx.get("/api/reference/ores", ores)
