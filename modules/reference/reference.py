# -*- coding: utf-8 -*-
"""
Справочник EVE: разделы с таблицами по данным игры. Первый раздел — «Руда»: вся руда в игре, где добывается,
во что перерабатывается, варианты и сжатая руда.

Только стандартная библиотека. Данные — справочник игры (reference_data.json, собран из SDE скриптом
build_reference_data.py), работают без интернета. «Где добывается» в SDE нет — места записаны ниже (PLACES) по EVE University Wiki.
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

# где именно добывается: [зона, империи (None — любая), что именно] — по данным EVE University Wiki «Asteroids and ore»
# (таблица поясов по империям, списки рудных аномалий, массивы разведки Equinox). После патчей игры может меняться.
HS, LS, NS, WH, PV = "hs", "ls", "ns", "wh", "pv"
AM, CA, GA, MI = "amarr", "caldari", "gallente", "minmatar"
ALL4 = [AM, CA, GA, MI]
MOON = "бурение лун: структура Athanor или Tatara с модулем бурения"
PLACES = {
    462: [(HS, ALL4, "пояса астероидов 1.0–0.5"),
          (HS, None, "аномалия «Asteroid Belt Remnants» — стартовые системы и системы карьерных агентов"),
          (NS, None, "аномалии «Veldspar» / «Large Veldspar» — суверенные нули с массивом разведки Tritanium")],
    460: [(HS, ALL4, "пояса астероидов 1.0–0.5")],
    459: [(HS, [AM, CA], "пояса астероидов 0.9–0.5"),
          (LS, [AM, CA], "пояса астероидов 0.4–0.1"),
          (NS, None, "пояса астероидов в части регионов (зависит от класса безопасности региона)"),
          (WH, None, "рудные сайты червоточин")],
    458: [(HS, [CA], "пояса астероидов 0.7 и ниже"),
          (HS, [GA, MI], "пояса астероидов 0.9–0.5")],
    469: [(HS, None, "редкие аномалии «Omber Deposit» и «Kernite and Omber Deposit» — системы 0.8–0.5 любой империи"),
          (LS, [GA, MI], "пояса астероидов 0.4–0.1"),
          (WH, None, "рудные сайты червоточин")],
    457: [(HS, None, "редкая аномалия «Kernite and Omber Deposit» — системы 0.8–0.5 любой империи"),
          (LS, [AM, CA, MI], "пояса астероидов 0.4–0.1"),
          (NS, None, "пояса астероидов в части регионов (зависит от класса безопасности региона)"),
          (WH, None, "рудные сайты червоточин")],
    456: [(LS, [AM, GA], "пояса астероидов 0.4–0.1"),
          (LS, None, "аномалии «Average Jaspet Deposit» и «Hedbergite, Hemorphite and Jaspet»")],
    455: [(LS, [AM, GA], "пояса астероидов 0.2–0.1"),
          (LS, None, "аномалия «Hedbergite, Hemorphite and Jaspet»")],
    454: [(LS, [CA, MI], "пояса астероидов 0.2–0.1"),
          (LS, None, "аномалия «Hedbergite, Hemorphite and Jaspet»")],
    467: [(LS, None, "аномалии «Gneiss», «Dark Ochre and Gneiss», «Crokite, Dark Ochre and Gneiss»"),
          (WH, None, "рудные сайты червоточин")],
    453: [(LS, None, "аномалии «Dark Ochre and Gneiss», «Crokite and Dark Ochre», «Crokite, Dark Ochre and Gneiss»")],
    452: [(LS, None, "аномалии «Crokite and Dark Ochre», «Crokite, Dark Ochre and Gneiss»")],
    461: [(PV, None, "Почвен")],
    451: [(NS, None, "пояса астероидов — в нулях с низкой безопасностью; в Дронлендах — везде"),
          (NS, None, "аномалии «Bistot» и «Arkonor and Bistot»"),
          (WH, None, "рудные сайты червоточин")],
    450: [(NS, None, "пояса астероидов — в нулях с низкой безопасностью; в Дронлендах — везде"),
          (NS, None, "аномалии «Arkonor and Bistot»"),
          (WH, None, "рудные сайты червоточин")],
    468: [(NS, None, "пояса астероидов в системах с самой низкой безопасностью; в Дронлендах — везде"),
          (NS, None, "аномалии «Mercoxit Deposit» (small … enormous)"),
          (PV, None, "Почвен — только домашние системы триглавов"),
          (None, None, "добывается только лазером Deep Core (навык Deep Core Mining)")],
    1884: [(HS, None, MOON), (LS, None, MOON), (NS, None, MOON), (WH, None, MOON)],
    1920: [(HS, None, MOON), (LS, None, MOON), (NS, None, MOON), (WH, None, MOON)],
    1921: [(LS, None, MOON), (NS, None, MOON), (WH, None, MOON)],
    1922: [(LS, None, MOON), (NS, None, MOON), (WH, None, MOON)],
    1923: [(LS, None, MOON), (NS, None, MOON), (WH, None, MOON)],
    4029: [(PV, None, "Почвен — только там")],
    4030: [(PV, None, "Почвен — только там")],
    4031: [(PV, None, "Почвен — только там")],
    4513: [(HS, None, "редкая «Small Mordunium Deposit» — системы 0.5 на границе с лоу-секом"),
           (LS, None, "аномалия «Mordunium Deposit» — кроме систем фракционных войн"),
           (NS, None, "аномалии от массива разведки Pyerite (суверенные нули)"),
           (None, None, "редкие пограничные сайты: граница хай/лоу 0.5, граница нулей, синие A0 в нулях и ВХ")],
    4514: [(None, None, "редкие пограничные сайты: граница хай/лоу 0.5, граница нулей, синие A0 в нулях и ВХ")],
    4515: [(None, None, "редкие пограничные сайты: граница хай/лоу 0.5, граница нулей, синие A0 в нулях и ВХ")],
    4516: [(None, None, "редкие пограничные сайты: граница хай/лоу 0.5, граница нулей, синие A0 в нулях и ВХ")],
    4755: [(NS, None, "аномалии от массива разведки Mexallon (суверенные нули)")],
    4756: [(NS, None, "аномалии от массива разведки Nocxium (суверенные нули)")],
    4757: [(NS, None, "аномалии от массива разведки Megacyte (суверенные нули)")],
    4758: [(NS, None, "аномалии от массива разведки Zydrine (суверенные нули)")],
    4759: [(NS, None, "аномалии от массива разведки Isogen (суверенные нули)")],
}
# зоны пограничных руд (для фильтра «Где»): граница хай/лоу, нули, ВХ
BORDER = {4513, 4514, 4515, 4516}

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
        pl = [{"sec": sec, "empires": emp, "text": text} for sec, emp, text in PLACES.get(gid, [])]
        where = []
        for x in pl:
            if x["sec"] and x["sec"] not in where:
                where.append(x["sec"])
        if gid in BORDER:                                    # пограничные сайты: граница хай/лоу, нули, ВХ
            where = [HS, LS, NS, WH]
        empires = sorted({e for x in pl if x["sec"] in (HS, LS) for e in (x["empires"] or ALL4)})
        note = pl[0]["text"] if pl else SPECIAL_NOTE
        cat = category(gid)
        if not any(v["mats"] for v in vs):                    # в группе обычной руды, но не перерабатывается — служебный предмет
            cat, where, pl, empires = "special", [], [], []
            note = "не перерабатывается и не встречается в поясах — служебный или старый предмет игры"
        out.append({"name": f["name"], "type_id": base["type_id"], "ru": base["ru"], "group_id": gid,
                    "group": (data.get("groups", {}).get(str(gid)) or [""])[0], "cat": cat, "cat_name": CATS[cat][0] if cat in CATS else "Особая",
                    "rank": MOON_RANK.get(gid, ""), "where": where, "note": note, "places": pl, "empires": empires, "portion": base["portion"], "volume": base["volume"],
                    "mats": base["mats"], "value": base["value"], "isk_m3": base["isk_m3"],
                    "variants": [v for v in vs if v is not base]})
    order = {"standard": 0, "moon": 1, "equinox": 2, "pochven": 3, "special": 4}
    out.sort(key=lambda r: (order[r["cat"]], r["group_id"] if r["cat"] == "moon" else 0, r["name"]))
    return {"ores": out, "materials": {k: v[0] for k, v in data.get("materials", {}).items()},
            "cats": [[k, v[0]] for k, v in CATS.items()] + [["special", "Особая"]]}


# ---------------------------------------------------------------------------
# Чертежи: что производит и как получить
# ---------------------------------------------------------------------------

def load_bp(path: Optional[str] = None) -> dict:
    try:
        with open(path or os.path.join(HERE, "reference_bp.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"bp": {}, "inv": {}, "lp": {}, "corps": {}, "mg": {}, "pmg": {}, "types": {}}


def bp_sources(d: dict, b: str) -> List[str]:
    """Способы получения: market — оригинал продают NPC; inv — изобретение (T2); rev — реверс-инжиниринг из реликвий (T3);
    lp — копия в LP-магазине; rare — только копии (сайты исследований, дропы, события)."""
    row, out = d["bp"][b], []
    if row[6] and (row[11] in (None, 0, 1) or row[1] == "r") and b not in d["inv"]:
        out.append("market")
    for src in d["inv"].get(b, []):
        cat = (d["types"].get(str(src[0])) or [0, 0, 0, 0])[3]
        k = "inv" if cat == 9 else "rev"
        if k not in out:
            out.append(k)
    if b in d["lp"]:
        out.append("lp")
    return out or ["rare"]


def bp_catalog(d: dict) -> dict:
    T = d["types"]
    items = []
    for b, row in d["bp"].items():
        prod = T.get(str(row[0])) or [str(row[0]), "", 0, 0]
        items.append([int(b), prod[0], row[0], d["pmg"].get(b), row[1], bp_sources(d, b), prod[1]])
    items.sort(key=lambda r: r[1].casefold())
    return {"items": items, "groups": d["mg"]}


def bp_detail(d: dict, b: str) -> Optional[dict]:
    row = d["bp"].get(b)
    if not row:
        return None
    T = d["types"]
    name = lambda t: (T.get(str(t)) or [str(t)])[0]
    prod, kind, out_qty, t, lim, price, mg, mats, t_copy, t_me, t_te, tl = row
    path, g = [], mg
    while g and str(g) in d["mg"]:
        path.append(d["mg"][str(g)][1])
        g = d["mg"][str(g)][0]
    inv = [{"source": s[0], "source_name": name(s[0]), "relic": (T.get(str(s[0])) or [0, 0, 0, 0])[3] != 9, "chance": s[1], "runs": s[2],
            "datacores": [{"type_id": m, "name": name(m), "qty": q} for m, q in s[3]], "time": s[4]} for s in d["inv"].get(b, [])]
    inv.sort(key=lambda x: -x["chance"])
    offers: Dict[str, dict] = {}                              # одинаковые предложения разных корпораций — одной строкой
    for cid, lp, isk, qty, req in d["lp"].get(b, []):
        k = json.dumps([lp, isk, qty, req])
        o = offers.setdefault(k, {"lp": lp, "isk": isk, "qty": qty, "required": [{"type_id": m, "name": name(m), "qty": q} for m, q in req], "corps": []})
        o["corps"].append(d["corps"].get(str(cid)) or str(cid))
    return {"bp": int(b), "name": name(b), "product": prod, "product_name": name(prod), "product_ru": (T.get(str(prod)) or ["", ""])[1],
            "kind": kind, "out": out_qty, "time": t, "max_runs": lim, "base_price": price, "market_path": list(reversed(path)) if row[6] else [],
            "tech": tl, "materials": [{"type_id": m, "name": name(m), "qty": q} for m, q in mats],
            "copy_time": t_copy, "me_time": t_me, "te_time": t_te, "sources": bp_sources(d, b), "invention": inv,
            "lp": sorted(offers.values(), key=lambda o: (o["lp"], o["isk"]))}


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

    bpd = load_bp()

    def bp_cat(qs):
        return {"ok": True, **bp_catalog(bpd), "built": bpd.get("built")}

    def bp_one(qs):
        r = bp_detail(bpd, (qs.get("id") or [""])[0])
        if r is None:
            return {"ok": False, "message": "Нет такого чертежа."}
        if ctx.online is not None:
            ids = [r["bp"], r["product"]] + [m["type_id"] for m in r["materials"]] + [x["source"] for x in r["invention"]] +                   [c["type_id"] for x in r["invention"] for c in x["datacores"]] + [q["type_id"] for o in r["lp"] for q in o["required"]]
            threading.Thread(target=lambda: [ctx.online.fetch_icon(i) for i in ids[:150]], name="reference-icons", daemon=True).start()
        return {"ok": True, **r}

    def bp_icons(body, qs=None):
        try:
            ids = [int(x) for x in (body or {}).get("ids") or []][:200]
        except (TypeError, ValueError, AttributeError):
            return {"ok": False}
        if ctx.online is not None:
            threading.Thread(target=lambda: [ctx.online.fetch_icon(i) for i in ids], name="reference-icons", daemon=True).start()
        return {"ok": True}

    ctx.get("/api/reference/ores", ores)
    ctx.get("/api/reference/blueprints", bp_cat)
    ctx.get("/api/reference/blueprint", bp_one)
    ctx.post("/api/reference/icons", bp_icons)
