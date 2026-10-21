# -*- coding: utf-8 -*-
"""
Калькулятор переработки: что получится из руды, льда, модулей и кораблей и выгоднее ли перерабатывать, чем продать.

Только стандартная библиотека. Что из чего выходит — справочник игры (reprocess_data.json, собран из SDE скриптом
build_reprocess_data.py); работает и без интернета. Цены (если включены онлайн-функции) — лучшие ордера хаба из ESI.

Выход руды и льда (формула игры):
  (50 + риг) × (1 + безопасность) × (1 + бонус структуры) × (1 + 3%·Reprocessing) × (1 + 2%·Reprocessing Efficiency)
  × (1 + 2%·навык обработки этой руды) × (1 + имплант)
  риг: T1 +1, T2 +3; безопасность: low +6%, null/ВХ +12%; Athanor +2%, Tatara +5,5% — только в структуре.
Выход остального (модули, корабли, заряды): 50% × (1 + 2%·Scrapmetal Processing).
Перерабатываются целые порции (руда — по 100 шт.), остаток возвращается как есть.
"""
import concurrent.futures
import json
import math
import os
import re
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ORE_CATEGORY = 25                       # Asteroid: руда, лёд, лунная руда, сжатая руда
MARKETS = {
    "jita": ("Jita 4-4", 10000002, 60003760),
    "amarr": ("Amarr", 10000043, 60008494),
    "dodixie": ("Dodixie", 10000032, 60011866),
    "rens": ("Rens", 10000030, 60004588),
    "hek": ("Hek", 10000042, 60005686),
}
MODES = ("buy", "split", "sell")
PRICE_TTL = 300
MAX_LINES = 1000
NUM = r"\d[\d\s  .,']*"

RIGS = {"none": 0.0, "t1": 1.0, "t2": 3.0}
SECURITY = {"high": 0.0, "low": 0.06, "null": 0.12}
STRUCTURES = {"station": 0.0, "athanor": 0.02, "tatara": 0.055, "other": 0.0}
IMPLANTS = {"0": 0.0, "1": 0.01, "2": 0.02, "4": 0.04}
DEFAULTS = {"place": "station", "rig": "none", "security": "high", "reprocessing": 5, "efficiency": 5, "ore": 4,
            "scrap": 0, "implant": "0", "tax": 0.0, "ore_yield": None, "scrap_yield": None, "market": "jita", "mode": "buy"}


# ---------------------------------------------------------------------------
# Разбор списка (как во вкладке «Оценка»)
# ---------------------------------------------------------------------------

def parse_qty(s: str) -> Optional[int]:
    s = s.strip().lower().rstrip("x×").strip()
    if not s:
        return None
    s = re.sub(r"[\s  ']", "", s)
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        s = re.sub(r"[.,]", "", s)
    m = re.fullmatch(r"(\d+)(?:[.,]\d+)?", s)
    return int(m.group(1)) if m else None


def parse(text: str) -> Tuple[List[Tuple[str, int]], List[str]]:
    """Список из игры → [(название, количество)] и нераспознанные строки. Одинаковые названия складываются."""
    items: Dict[str, int] = {}
    order: List[str] = []
    bad: List[str] = []
    for raw in (text or "").splitlines()[:MAX_LINES]:
        line = raw.strip()
        if not line or line.startswith("[") and line.endswith("]"):
            continue
        if "\t" in line:
            cols = [c.strip() for c in line.split("\t")]
            name = cols[0]
            qty = (parse_qty(cols[1]) if len(cols) > 1 and cols[1] else 1) or 1
        else:
            after = re.fullmatch(r"(.+?)\s+[x×]\s*(%s)" % NUM, line, re.I)
            before = re.fullmatch(r"(%s)\s*[x×]\s+(.+)" % NUM, line, re.I)
            tail = re.fullmatch(r"(.+?)\s+(%s)" % NUM, line)
            lead = re.fullmatch(r"(\d[\d.,']*(?:[\s  ]\d{3})*)\s+(\D.*)", line)
            if after and parse_qty(after.group(2)) is not None:
                name, qty = after.group(1), parse_qty(after.group(2))
            elif before and parse_qty(before.group(1)) is not None:
                name, qty = before.group(2), parse_qty(before.group(1))
            elif tail and parse_qty(tail.group(2)) is not None:
                name, qty = tail.group(1), parse_qty(tail.group(2))
            elif lead and parse_qty(lead.group(1)) is not None:
                name, qty = lead.group(2), parse_qty(lead.group(1))
            else:
                name, qty = line, 1
        name = re.sub(r"\s+", " ", (name or "").strip().rstrip("*").strip())
        if not name or not qty or qty <= 0 or len(name) > 120:
            bad.append(raw.strip()[:200])
            continue
        key = name.casefold()
        if key not in items:
            order.append(name)
        items[key] = items.get(key, 0) + qty
    return [(n, items[n.casefold()]) for n in order], bad


# ---------------------------------------------------------------------------
# Выход переработки
# ---------------------------------------------------------------------------

def clean_settings(raw: Optional[dict]) -> dict:
    s = dict(DEFAULTS)
    for k, v in (raw or {}).items():
        if k in DEFAULTS:
            s[k] = v
    s["place"] = s["place"] if s["place"] in STRUCTURES else "station"
    s["rig"] = s["rig"] if s["rig"] in RIGS else "none"
    s["security"] = s["security"] if s["security"] in SECURITY else "high"
    s["implant"] = str(s["implant"]) if str(s["implant"]) in IMPLANTS else "0"
    s["market"] = s["market"] if s["market"] in MARKETS else "jita"
    s["mode"] = s["mode"] if s["mode"] in MODES else "buy"
    for k in ("reprocessing", "efficiency", "ore", "scrap"):
        try:
            s[k] = max(0, min(5, int(s[k])))
        except (TypeError, ValueError):
            s[k] = DEFAULTS[k]
    for k, hi in (("tax", 100.0), ("ore_yield", 100.0), ("scrap_yield", 100.0)):
        try:
            s[k] = None if s[k] in (None, "") else max(0.0, min(hi, float(str(s[k]).replace(",", "."))))
        except (TypeError, ValueError):
            s[k] = DEFAULTS[k]
    if s["tax"] is None:
        s["tax"] = 0.0
    return s


def yields(s: dict) -> Tuple[float, float]:
    """(выход руды и льда, выход остального) — доли от 0 до 1."""
    if s.get("ore_yield") is not None:
        ore = s["ore_yield"] / 100
    else:
        structure = s["place"] != "station"
        base = 50 + (RIGS[s["rig"]] if structure else 0)
        ore = base / 100 * (1 + (SECURITY[s["security"]] if structure else 0)) * (1 + STRUCTURES[s["place"]])
        ore *= (1 + 0.03 * s["reprocessing"]) * (1 + 0.02 * s["efficiency"]) * (1 + 0.02 * s["ore"]) * (1 + IMPLANTS[s["implant"]])
    scrap = s["scrap_yield"] / 100 if s.get("scrap_yield") is not None else 0.5 * (1 + 0.02 * s["scrap"])
    return min(ore, 1.0), min(scrap, 1.0)


_DATA = None
_DATA_LOCK = threading.Lock()


def load_data(path: Optional[str] = None) -> dict:
    """Справочник переработки + указатель «название → type_id» (англ. и рус., без учёта регистра)."""
    global _DATA
    with _DATA_LOCK:
        if _DATA is None or path:
            try:
                with open(path or os.path.join(HERE, "reprocess_data.json"), encoding="utf-8") as f:
                    d = json.load(f)
            except (OSError, ValueError):
                d = {"types": {}, "materials": {}}
            index = {}
            for tid, t in d.get("types", {}).items():
                for n in (t[0], t[1]):
                    if n:
                        index.setdefault(n.casefold(), int(tid))
            d["index"] = index
            _DATA = d
        return _DATA


class Reprocessor:
    """Расчёт переработки. esi(path, method, body, **params) → (данные, заголовки) — как Online.esi трекера; None — без цен."""

    def __init__(self, esi: Optional[Callable] = None, data: Optional[dict] = None):
        self.esi = esi
        self.data = data or load_data()
        self.books: Dict[Tuple[str, int], Tuple[float, dict]] = {}
        self.ids: Dict[str, Optional[int]] = {}
        self.lock = threading.Lock()

    # ----- названия -----
    def resolve(self, names: List[str]) -> Dict[str, Optional[int]]:
        index = self.data["index"]
        out = {n: index.get(n.casefold()) for n in names}
        need = [n for n in names if out[n] is None and n.casefold() not in self.ids]
        if need and self.esi is not None:                              # русские названия — через ESI
            for lang in ("ru", "en"):
                left = [n for n in need if n.casefold() not in self.ids]
                for i in range(0, len(left), 250):
                    try:
                        data, _ = self.esi("/universe/ids/", "POST", left[i:i + 250], language=lang)
                    except Exception:
                        data = {}
                    for e in (data or {}).get("inventory_types") or []:
                        self.ids[e["name"].casefold()] = e["id"]
        for n in names:
            if out[n] is None:
                out[n] = self.ids.get(n.casefold())
        return out

    # ----- цены -----
    def _book(self, market: str, tid: int, now: float) -> dict:
        key = (market, tid)
        with self.lock:
            hit = self.books.get(key)
        if hit and now - hit[0] < PRICE_TTL:
            return hit[1]
        _, region, station = MARKETS[market]
        orders, page, pages = [], 1, 1
        while page <= pages and page <= 20:
            data, hdrs = self.esi(f"/markets/{region}/orders/", order_type="all", type_id=tid, page=page)
            orders += data or []
            try:
                pages = int((hdrs or {}).get("X-Pages", "1"))
            except (TypeError, ValueError):
                pages = 1
            page += 1
        buys = [o["price"] for o in orders if o.get("is_buy_order") and o.get("location_id") == station]
        sells = [o["price"] for o in orders if not o.get("is_buy_order") and o.get("location_id") == station]
        buy, sell = (max(buys) if buys else None), (min(sells) if sells else None)
        split = (buy + sell) / 2 if buy is not None and sell is not None else (buy if sell is None else sell)
        book = {"buy": buy, "sell": sell, "split": split}
        with self.lock:
            self.books[key] = (now, book)
        return book

    def prices(self, type_ids, market: str, mode: str, now: float) -> Tuple[Dict[int, Optional[float]], List[str]]:
        if self.esi is None or not type_ids:
            return {}, []
        out, errors = {}, []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futs = {tid: pool.submit(self._book, market, tid, now) for tid in set(type_ids)}
            for tid, fut in futs.items():
                try:
                    out[tid] = fut.result()[mode]
                except Exception as e:
                    out[tid] = None
                    errors.append(f"{tid}: {e}")
        return out, errors

    # ----- расчёт -----
    def calculate(self, text: str, settings: Optional[dict] = None, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now
        s = clean_settings(settings)
        ore_y, scrap_y = yields(s)
        items, bad = parse(text)
        if not items:
            return {"ok": False, "message": "Не нашёл ни одного предмета. Вставьте список из игры или возьмите добычу из сессии.",
                    "unparsed": bad}
        types, mats_ref = self.data["types"], self.data["materials"]
        ids = self.resolve([n for n, _ in items])
        missing = [n for n, _ in items if not ids.get(n)]
        cannot = [n for n, _ in items if ids.get(n) and str(ids[n]) not in types]
        rows, out_total = [], {}
        for name, qty in items:
            tid = ids.get(name)
            t = types.get(str(tid)) if tid else None
            if not t:
                continue
            en, _, cat, _, portion, vol, mats = t
            is_ore = cat == ORE_CATEGORY
            y = ore_y if is_ore else scrap_y
            batches, left = divmod(qty, portion)
            out = {}
            for mid, q in mats:
                n = math.floor(batches * q * y)
                if n > 0:
                    out[mid] = n
                    out_total[mid] = out_total.get(mid, 0) + n
            rows.append({"type_id": tid, "name": en, "input": name, "qty": qty, "portion": portion, "batches": batches,
                         "left": left, "ore": is_ore, "yield": round(y * 100, 2), "volume": vol * qty, "out": out})

        prices, errors = self.prices([r["type_id"] for r in rows] + list(out_total), s["market"], s["mode"], now)
        have_prices = bool(prices)
        tax = s["tax"] / 100
        for r in rows:
            p = prices.get(r["type_id"])
            r["as_is"] = p * r["qty"] if p is not None else None
            values = [prices.get(m) for m in r["out"]]
            if not have_prices:
                r["value"] = None
            else:
                gross = sum(prices.get(m) * n for m, n in r["out"].items() if prices.get(m) is not None)
                left_value = p * r["left"] if p is not None else 0
                r["value"] = gross * (1 - tax) + left_value
                r["no_price"] = any(v is None for v in values)
            if r["as_is"] is not None and r["value"] is not None:
                r["gain"] = r["value"] - r["as_is"]
                r["verdict"] = "reprocess" if r["gain"] > 0 else "sell"
            else:
                r["gain"], r["verdict"] = None, None
            r["out"] = [{"type_id": m, "name": mats_ref.get(str(m), [str(m)])[0], "qty": n} for m, n in
                        sorted(r["out"].items(), key=lambda kv: -kv[1])]

        materials = []
        for mid, n in sorted(out_total.items(), key=lambda kv: -kv[1]):
            ref = mats_ref.get(str(mid), [str(mid), "", 0])
            p = prices.get(mid)
            materials.append({"type_id": mid, "name": ref[0], "qty": n, "volume": ref[2] * n,
                              "price": p, "value": p * n if p is not None else None})
        known = lambda key: [r[key] for r in rows if r.get(key) is not None]
        gross = sum(m["value"] for m in materials if m["value"] is not None)
        totals = {
            "items": len(rows), "volume_in": sum(r["volume"] for r in rows), "volume_out": sum(m["volume"] for m in materials),
            "as_is": sum(known("as_is")) if have_prices else None,
            "gross": gross if have_prices else None, "tax": gross * tax if have_prices else None,
            "value": sum(known("value")) if have_prices else None,
            "best": sum(max(r["as_is"] or 0, r["value"] or 0) for r in rows) if have_prices else None,
            "leftover": sum(1 for r in rows if r["left"]),
        }
        return {"ok": True, "created": int(now), "settings": s, "ore_yield": round(ore_y * 100, 2),
                "scrap_yield": round(scrap_y * 100, 2), "market_name": MARKETS[s["market"]][0], "prices": have_prices,
                "rows": rows, "materials": materials, "totals": totals, "missing": missing, "cannot": cannot,
                "unparsed": bad, "errors": errors[:5], "data_built": self.data.get("built")}


# ---------------------------------------------------------------------------
# Подключение к трекеру
# ---------------------------------------------------------------------------

def setup(ctx) -> None:
    data = load_data()
    if not data.get("types"):
        ctx.log.warning("Переработка: нет справочника reprocess_data.json")
    r = Reprocessor(ctx.online.esi if ctx.online is not None else None, data)
    path = os.path.join(ctx.data_dir, "reprocess_settings.json")

    def load_settings() -> dict:
        try:
            with open(path, encoding="utf-8") as f:
                return clean_settings(json.load(f))
        except (OSError, ValueError):
            return clean_settings(None)

    def save_settings(s: dict) -> None:
        try:
            ctx.core.atomic_write_json(path, s)
        except Exception as e:
            ctx.log.warning("Переработка: настройки не сохранены: %s", e)

    def calc(body, qs):
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            return {"ok": False, "message": "Вставьте список предметов."}
        s = clean_settings(body.get("settings") if isinstance(body.get("settings"), dict) else load_settings())
        save_settings(s)
        try:
            res = r.calculate(body["text"], s)
        except Exception as e:
            ctx.log.warning("Переработка не удалась: %s", e)
            return {"ok": False, "message": f"Не удалось посчитать: {e}"}
        if ctx.online is not None and res.get("ok"):
            ids = [x["type_id"] for x in res["rows"]] + [m["type_id"] for m in res["materials"]]
            threading.Thread(target=lambda: [ctx.online.fetch_icon(i) for i in ids[:80]], name="reprocess-icons",
                             daemon=True).start()
        if ctx.online is None and res.get("ok"):
            res["note"] = "Цены не показаны: онлайн-функции выключены (online_enabled в config.json)."
        return res

    def info(qs):
        s = load_settings()
        ore_y, scrap_y = yields(s)
        return {"ok": True, "settings": s, "ore_yield": round(ore_y * 100, 2), "scrap_yield": round(scrap_y * 100, 2),
                "prices": ctx.online is not None, "data_built": data.get("built"), "types": len(data.get("types", {}))}

    ctx.post("/api/reprocess", calc)
    ctx.get("/api/reprocess/settings", info)
