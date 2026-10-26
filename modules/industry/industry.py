# -*- coding: utf-8 -*-
"""
Калькулятор производства: что нужно, сколько стоит, сколько длится и сколько принесёт.

Только стандартная библиотека. Чертежи — справочник игры (industry_data.json, собран из SDE скриптом
build_industry_data.py), работает без интернета. Цены материалов и продукта — лучшие ордера хаба (ESI),
стоимость работы — по «ориентировочной цене» (adjusted price) и индексу системы (ESI /industry/systems/).

Формулы (как в игре):
  материалы на прогоны = max(прогоны, ⌈прогоны × база × (1 − ME%) × (1 − бонус структуры) × (1 − бонус рига)⌉)
    структура: инженерный комплекс (Raitaru, Azbel, Sotiyo) −1% материалов; риг T1 2%, T2 2,4% × безопасность
    (хай ×1, лоу ×1,9, нули/ВХ ×2,1). Реакции: ME нет, риги реакций — те же проценты (в хайсеке реакций нет).
  время = база × прогоны × (1 − TE%) × (1 − бонус структуры) × (1 − риг) × (1 − 4%·Industry) × (1 − 3%·Advanced Industry)
    (реакции: × (1 − 4%·Reactions)); комплексы −15/−20/−30%, Tatara −25% для реакций; риг времени T1 20%, T2 24% × безопасность.
  стоимость работы = EIV × (индекс системы × (1 − бонус структуры) + налог сооружения + сбор SCC),
    EIV = Σ база × adjusted price × прогоны; бонус к стоимости у комплексов 3/4/5%.
Компоненты можно не покупать, а строить: тогда считается их собственное производство (рекурсивно).
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
MARKETS = {
    "jita": ("Jita 4-4", 10000002, 60003760),
    "amarr": ("Amarr", 10000043, 60008494),
    "dodixie": ("Dodixie", 10000032, 60011866),
    "rens": ("Rens", 10000030, 60004588),
    "hek": ("Hek", 10000042, 60005686),
}
HUB_SYSTEMS = {"jita": 30000142, "amarr": 30002187, "dodixie": 30002659, "rens": 30002510, "hek": 30002053}
HUB_TTL = 3600                         # цены всего хаба (сканер) — не чаще раза в час
HISTORY_TTL = 12 * 3600
SUSPICIOUS = 4.0
LP_MARGIN = 85.0                       # маржа выше — почти всегда чертёж из LP-магазина или редкая копия (цена не в материалах)                       # цена продукта дороже средней по игре в столько раз — скорее всего «ордер-ловушка»
CATEGORIES = {"ships": (6,), "modules": (7,), "charges": (8,), "drones": (18, 87), "components": (17,),
              "implants": (20,), "structures": (22, 23, 65, 66), "materials": (4, 43)}
PRICE_TTL = 300
INDEX_TTL = 3600                       # индексы систем CCP пересчитывает раз в час
ADJUSTED_TTL = 6 * 3600                # ориентировочные цены — раз в сутки
WAIT_STATIC = 40                       # первый запуск: подождать загрузку больших списков ESI, потом считать без них
ESI_BASE = "https://esi.evetech.net/latest"


def esi_big(path: str) -> list:
    """Большие списки ESI (все цены, все системы) — со сжатием: без него ESI отдаёт их минутами."""
    import urllib.request
    import zlib
    req = urllib.request.Request(f"{ESI_BASE}{path}?datasource=tranquility",
                                 headers={"Accept": "application/json", "Accept-Encoding": "gzip",
                                          "User-Agent": "EveLogHUD industry (github.com/BaNNaN4iK/eve-log-hud)"})
    with urllib.request.urlopen(req, timeout=90) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = zlib.decompress(raw, 16 + zlib.MAX_WBITS)
    return json.loads(raw.decode("utf-8"))
MAX_DEPTH = 6

# структура: (материалы, время производства, время реакций, стоимость работы)
STRUCTURES = {
    "station": (0.0, 0.0, 0.0, 0.0),
    "raitaru": (0.01, 0.15, 0.0, 0.03),
    "azbel": (0.01, 0.20, 0.0, 0.04),
    "sotiyo": (0.01, 0.30, 0.0, 0.05),
    "athanor": (0.0, 0.0, 0.0, 0.0),
    "tatara": (0.0, 0.0, 0.25, 0.0),
    "other": (0.0, 0.0, 0.0, 0.0),
}
RIG_ME = {"none": 0.0, "t1": 0.02, "t2": 0.024}
RIG_TE = {"none": 0.0, "t1": 0.20, "t2": 0.24}
SECURITY = {"high": 1.0, "low": 1.9, "null": 2.1}
DEFAULTS = {
    "runs": 1, "me": 10, "te": 20, "structure": "station", "rig": "none", "security": "high",
    "system": "", "cost_index": None, "facility_tax": 0.25, "scc": 4.0,
    "industry": 5, "adv_industry": 4, "reactions": 4,
    "market": "jita", "buy_mode": "sell", "sell_mode": "sell", "sales_tax": 3.6, "broker": 1.5,
    "comp_me": 10, "comp_te": 20, "build": [],
    "inv_sci": 4, "inv_enc": 4,
}


def clean_settings(raw: Optional[dict]) -> dict:
    s = dict(DEFAULTS)
    for k, v in (raw or {}).items():
        if k in DEFAULTS:
            s[k] = v

    def num(k, lo, hi, cast=float):
        try:
            v = s[k]
            v = cast(str(v).replace(",", ".").replace(" ", "")) if v not in (None, "") else None
        except (TypeError, ValueError):
            v = DEFAULTS[k]
        s[k] = None if v is None else max(lo, min(hi, v))

    num("runs", 1, 100000, lambda x: int(float(x)))
    num("me", 0, 10, lambda x: int(float(x)))
    num("te", 0, 20, lambda x: int(float(x)))
    num("comp_me", 0, 10, lambda x: int(float(x)))
    num("comp_te", 0, 20, lambda x: int(float(x)))
    for k in ("industry", "adv_industry", "reactions", "inv_sci", "inv_enc"):
        num(k, 0, 5, lambda x: int(float(x)))
    for k, hi in (("cost_index", 100.0), ("facility_tax", 50.0), ("scc", 20.0), ("sales_tax", 20.0), ("broker", 20.0)):
        num(k, 0.0, hi)
    for k in ("facility_tax", "scc", "sales_tax", "broker"):
        if s[k] is None:
            s[k] = DEFAULTS[k]
    s["structure"] = s["structure"] if s["structure"] in STRUCTURES else "station"
    s["rig"] = s["rig"] if s["rig"] in RIG_ME else "none"
    s["security"] = s["security"] if s["security"] in SECURITY else "high"
    s["market"] = s["market"] if s["market"] in MARKETS else "jita"
    s["buy_mode"] = s["buy_mode"] if s["buy_mode"] in ("buy", "sell", "split") else "sell"
    s["sell_mode"] = s["sell_mode"] if s["sell_mode"] in ("buy", "sell", "split") else "sell"
    s["system"] = str(s["system"] or "")[:60]
    try:
        s["build"] = sorted({int(x) for x in (s["build"] or [])})[:200]
    except (TypeError, ValueError):
        s["build"] = []
    return s


_DATA = None
_LOCK = threading.Lock()


def load_data(path: Optional[str] = None) -> dict:
    global _DATA
    with _LOCK:
        if _DATA is None or path:
            try:
                with open(path or os.path.join(HERE, "industry_data.json"), encoding="utf-8") as f:
                    d = json.load(f)
            except (OSError, ValueError):
                d = {"bp": {}, "types": {}, "groups": {}}
            d["index"] = {d["types"][k][0].casefold(): int(k) for k in d["bp"] if k in d["types"]}
            _DATA = d
        return _DATA


def bonuses(s: dict, kind: str, top: bool) -> dict:
    """Множители для одного уровня производства."""
    st = STRUCTURES[s["structure"]]
    sec = SECURITY[s["security"]]
    rig_me = RIG_ME[s["rig"]] * sec if s["structure"] not in ("station",) else 0.0
    rig_te = RIG_TE[s["rig"]] * sec if s["structure"] not in ("station",) else 0.0
    if kind == "r":
        me = 0
        te = 0
        t_struct = st[2]
        skill = 1 - 0.04 * s["reactions"]
    else:
        me = s["me"] if top else s["comp_me"]
        te = s["te"] if top else s["comp_te"]
        t_struct = st[1]
        skill = (1 - 0.04 * s["industry"]) * (1 - 0.03 * s["adv_industry"])
    return {"mat": (1 - me / 100) * (1 - (st[0] if kind == "m" else 0)) * (1 - rig_me),
            "time": (1 - te / 100) * (1 - t_struct) * (1 - rig_te) * skill, "cost": 1 - st[3]}


def mat_qty(base: int, runs: int, mult: float) -> int:
    return max(runs, math.ceil(round(runs * base * mult, 2)))


class Calculator:
    """esi(path, method, body, **params) → (данные, заголовки), как Online.esi трекера; None — без цен."""

    def __init__(self, esi: Optional[Callable] = None, data: Optional[dict] = None, cache_path: str = "",
                 big: Optional[Callable] = None):
        self.esi = esi
        self.data = data or load_data()
        self.books: Dict[Tuple[str, int], Tuple[float, dict]] = {}
        self.adjusted: Tuple[float, Dict[int, float]] = (0, {})
        self.average: Dict[int, float] = {}
        self.average_loaded = False            # старый кэш без средних цен — перекачать один раз
        self.indices: Tuple[float, Dict[int, dict]] = (0, {})
        self.systems: Dict[str, Optional[int]] = {}
        self.lock = threading.Lock()
        self.cache_path = cache_path
        self.big = big if big is not None else (esi_big if esi is not None else None)
        self.static_lock = threading.Lock()
        self.static_done = threading.Event()
        self.static_error = ""
        self._load_cache()

    # ----- большие списки ESI: на диске и в фоне -----
    def _load_cache(self) -> None:
        if not self.cache_path:
            return
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                c = json.load(f)
            self.adjusted = (float(c["adjusted"][0]), {int(k): float(v) for k, v in c["adjusted"][1].items()})
            self.average = {int(k): float(v) for k, v in (c.get("average") or {}).items()}
            self.average_loaded = "average" in c
            self.indices = (float(c["indices"][0]), {int(k): v for k, v in c["indices"][1].items()})
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        tmp = self.cache_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"adjusted": [self.adjusted[0], self.adjusted[1]], "average": self.average,
                           "indices": [self.indices[0], self.indices[1]]}, f)
            try:
                os.replace(tmp, self.cache_path)
            except OSError:
                import shutil
                shutil.copyfile(tmp, self.cache_path)
                os.remove(tmp)
        except OSError:
            pass

    def refresh_static(self, now: Optional[float] = None) -> None:
        """Обновить ориентировочные цены и индексы систем, если устарели (вызывается в фоне)."""
        now = time.time() if now is None else now
        if self.big is None or not self.static_lock.acquire(blocking=False):
            return
        try:
            changed = False
            if now - self.adjusted[0] >= ADJUSTED_TTL or not self.adjusted[1] or not self.average_loaded:
                rows = self.big("/markets/prices/")
                self.adjusted = (now, {int(r["type_id"]): float(r.get("adjusted_price") or 0) for r in rows or []})
                self.average = {int(r["type_id"]): float(r["average_price"]) for r in rows or [] if r.get("average_price")}
                self.average_loaded = True
                changed = True
            if now - self.indices[0] >= INDEX_TTL or not self.indices[1]:
                rows = self.big("/industry/systems/")
                self.indices = (now, {int(r["solar_system_id"]): {c["activity"]: c["cost_index"] for c in r.get("cost_indices") or []}
                                      for r in rows or []})
                changed = True
            if changed:
                self._save_cache()
            self.static_error = ""
        except Exception as e:
            self.static_error = str(e)
        finally:
            self.static_lock.release()
            self.static_done.set()

    def _ensure_static(self, now: float, need_index: bool) -> None:
        """Есть кэш — считаем по нему и обновляем в фоне; нет — ждём первую загрузку (до WAIT_STATIC секунд)."""
        if self.big is None:
            return
        stale = now - self.adjusted[0] >= ADJUSTED_TTL or (need_index and now - self.indices[0] >= INDEX_TTL)
        if not stale:
            return
        missing = not self.adjusted[1] or (need_index and not self.indices[1])
        t = threading.Thread(target=self.refresh_static, name="industry-static", daemon=True)
        if missing:
            self.static_done.clear()
            t.start()
            self.static_done.wait(WAIT_STATIC)
        else:
            t.start()

    # ----- поиск -----
    def find(self, text: str) -> Optional[int]:
        t = (text or "").strip()
        if t.isdigit() and t in self.data["bp"]:
            return int(t)
        tid = self.data["index"].get(t.casefold())
        if tid is None and self.esi is not None and t:                      # русское название — через ESI
            try:
                res, _ = self.esi("/universe/ids/", "POST", [t], language="ru")
                for e in (res or {}).get("inventory_types") or []:
                    if str(e["id"]) in self.data["bp"]:
                        return int(e["id"])
            except Exception:
                pass
        return tid

    def search(self, text: str, limit: int = 15) -> List[dict]:
        t = (text or "").strip().casefold()
        if len(t) < 2:
            return []
        out = []
        for name, tid in self.data["index"].items():
            if t in name:
                out.append((0 if name.startswith(t) else 1, len(name), self.data["types"][str(tid)][0], tid))
        out.sort()
        return [{"id": x[3], "name": x[2], "kind": self.data["bp"][str(x[3])][1]} for x in out[:limit]]

    def name(self, tid: int) -> str:
        t = self.data["types"].get(str(tid))
        return t[0] if t else str(tid)

    # ----- цены и индексы -----
    def _book(self, market: str, tid: int, now: float) -> dict:
        key = (market, tid)
        with self.lock:
            hit = self.books.get(key)
        if hit and now - hit[0] < PRICE_TTL:
            return hit[1]
        _, region, station = MARKETS[market]
        orders, page, pages = [], 1, 1
        while page <= pages and page <= 10:
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

    def prices(self, ids, market: str, now: float) -> Dict[int, dict]:
        hub = getattr(self, "hub", None)
        if hub is not None and hub.fresh(market, now):
            book = hub.book(market)
            return {t: book.get(t) or {"buy": None, "sell": None, "split": None} for t in set(ids)}
        if self.esi is None:
            return {}
        out = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futs = {t: pool.submit(self._book, market, t, now) for t in set(ids)}
            for t, f in futs.items():
                try:
                    out[t] = f.result()
                except Exception:
                    out[t] = {"buy": None, "sell": None, "split": None}
        return out

    def adjusted_prices(self, now: float) -> Dict[int, float]:
        self._ensure_static(now, need_index=False)               # без сети — то, что уже сохранено
        return self.adjusted[1]

    def cost_index(self, system: str, kind: str, now: float) -> Tuple[Optional[float], str]:
        """Индекс системы (%) для производства или реакций и найденное название системы."""
        if self.esi is None or not system:
            return None, ""
        key = system.strip().casefold()
        if key not in self.systems:
            try:
                res, _ = self.esi("/universe/ids/", "POST", [system.strip()])
                hit = (res or {}).get("systems") or []
                self.systems[key] = hit[0]["id"] if hit else None
            except Exception:
                return None, ""
        sid = self.systems.get(key)
        if not sid:
            return None, ""
        self._ensure_static(now, need_index=True)
        idx = self.indices[1].get(sid, {}).get("reaction" if kind == "r" else "manufacturing")
        return (idx * 100 if idx is not None else None), system.strip()

    # ----- расчёт -----
    def plan(self, tid: int, units: int, s: dict, build: set, depth: int = 0, top: bool = True) -> dict:
        """Дерево производства на units штук продукта (округляется до целых прогонов)."""
        bp = self.data["bp"][str(tid)]
        _, kind, base_time, out_qty, mats, max_runs = bp[:6]
        runs = max(1, math.ceil(units / out_qty))
        b = bonuses(s, kind, top)
        node = {"type_id": tid, "name": self.name(tid), "kind": kind, "runs": runs, "out": runs * out_qty,
                "per_run": out_qty, "time": base_time * runs * b["time"], "max_runs": max_runs, "materials": [],
                "eiv_base": [(m, q) for m, q in mats]}
        for m, q in mats:
            need = mat_qty(q, runs, b["mat"])
            row = {"type_id": m, "name": self.name(m), "qty": need, "base": q,
                   "buildable": str(m) in self.data["bp"] and depth < MAX_DEPTH,
                   "kind": self.data["bp"][str(m)][1] if str(m) in self.data["bp"] else ""}
            if row["buildable"] and m in build:
                row["build"] = self.plan(m, need, s, build, depth + 1, top=False)
            node["materials"].append(row)
        return node

    def calculate(self, product: str, settings: Optional[dict] = None, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now
        s = clean_settings(settings)
        tid = self.find(product)
        if tid is None or str(tid) not in self.data["bp"]:
            return {"ok": False, "message": "Не нашёл, что строить. Выберите из подсказки — например «Vexor» или «Hobgoblin II»."}
        kind = self.data["bp"][str(tid)][1]
        if kind == "r" and s["security"] == "high" and s["structure"] != "station":
            note_hs = "Реакции в хайсеке запрещены — выберите лоу или нули."
        else:
            note_hs = ""
        build = set(s["build"])
        units = s["runs"] * self.data["bp"][str(tid)][3]
        tree = self.plan(tid, units, s, build)

        # сбор: что покупать, какие работы запускать
        shopping: Dict[int, int] = {}
        jobs: List[dict] = []

        def walk(node, depth):
            jobs.append({"type_id": node["type_id"], "name": node["name"], "kind": node["kind"], "runs": node["runs"],
                         "out": node["out"], "time": node["time"], "depth": depth, "eiv_base": node["eiv_base"]})
            for m in node["materials"]:
                if "build" in m:
                    walk(m["build"], depth + 1)
                else:
                    shopping[m["type_id"]] = shopping.get(m["type_id"], 0) + m["qty"]
        walk(tree, 0)

        ids = set(shopping) | {tid} | {j["type_id"] for j in jobs}
        prices = self.prices(ids, s["market"], now)
        adj = self.adjusted_prices(now)
        have_prices = bool(prices)
        index_cache: Dict[str, Tuple[Optional[float], str]] = {}

        def price(t, mode):
            p = prices.get(t) or {}
            return p.get(mode)

        total_mat = 0.0
        missing_price = []
        buy_rows = []
        for t, q in sorted(shopping.items(), key=lambda kv: self.name(kv[0])):
            p = price(t, s["buy_mode"])
            if have_prices and p is None:
                missing_price.append(self.name(t))
            cost = p * q if p is not None else None
            total_mat += cost or 0
            vol = (self.data["types"].get(str(t)) or [0, 0, 0, 0])[3]
            buy_rows.append({"type_id": t, "name": self.name(t), "qty": q, "price": p, "total": cost, "volume": vol * q})
        total_job = 0.0
        for j in jobs:
            k = j["kind"]
            if k not in index_cache:
                idx, sysname = (s["cost_index"], "") if s["cost_index"] is not None else self.cost_index(s["system"], k, now)
                index_cache[k] = (idx, sysname)
            idx, _ = index_cache[k]
            eiv = sum(q * adj.get(m, 0) for m, q in j.pop("eiv_base")) * j["runs"]
            b = bonuses(s, k, j["depth"] == 0)
            j["eiv"] = eiv
            if idx is None:
                j["cost"] = None
            else:
                j["cost"] = eiv * (idx / 100 * b["cost"] + s["facility_tax"] / 100 + s["scc"] / 100)
                total_job += j["cost"]
        product_price = price(tid, s["sell_mode"])
        compare = {}
        for mode in ("sell", "buy"):                              # продажа своим ордером и мгновенно — рядом
            pp = price(tid, mode)
            rev = pp * tree["out"] if pp is not None else None
            fee = rev * (s["sales_tax"] + (s["broker"] if mode == "sell" else 0)) / 100 if rev is not None else None
            pr = rev - fee - (total_mat + total_job) if rev is not None and have_prices else None
            tt = sum(j["time"] for j in jobs)
            compare[mode] = {"price": pp, "revenue": rev, "fees": fee, "profit": pr,
                             "per_run": pr / tree["runs"] if pr is not None else None,
                             "margin": round(pr * 100 / rev, 1) if pr is not None and rev else None,
                             "isk_hour": pr / (tt / 3600) if pr is not None and tt else None}
        out_units = tree["out"]
        revenue = product_price * out_units if product_price is not None else None
        fees = revenue * (s["sales_tax"] + s["broker"] * (s["sell_mode"] == "sell")) / 100 if revenue is not None else None
        cost_total = total_mat + total_job
        profit = revenue - fees - cost_total if revenue is not None and have_prices else None
        total_time = sum(j["time"] for j in jobs)
        idx_used = index_cache.get(kind, (None, ""))
        return {
            "ok": True, "settings": s, "product": {"type_id": tid, "name": self.name(tid), "kind": kind, "units": out_units,
                                                   "price": product_price},
            "tree": tree, "jobs": jobs, "shopping": buy_rows, "prices": have_prices,
            "totals": {"materials": total_mat if have_prices else None, "jobs": total_job if any(j["cost"] is not None for j in jobs) else None,
                       "cost": cost_total if have_prices else None, "per_unit": cost_total / out_units if have_prices and out_units else None,
                       "revenue": revenue, "fees": fees, "profit": profit,
                       "margin": round(profit * 100 / revenue, 1) if profit is not None and revenue else None,
                       "time": total_time, "top_time": tree["time"],
                       "isk_hour": profit / (total_time / 3600) if profit is not None and total_time else None,
                       "volume": sum(r["volume"] for r in buy_rows)},
            "unit_prices": {str(t): price(t, s["buy_mode"]) for t in ids}, "compare": compare,
            "cost_index": idx_used[0], "system": idx_used[1], "missing_price": missing_price,
            "market_name": MARKETS[s["market"]][0], "warning": note_hs, "data_built": self.data.get("built"),
        }


# ---------------------------------------------------------------------------
# План производства: несколько продуктов, общие компоненты, полный цикл или закупка
# ---------------------------------------------------------------------------

INV_BASE_COST = 0.02                   # стоимость запуска изобретения — 2% от ориентировочной стоимости предмета T1


def invention_chance(base: float, s: dict) -> float:
    """Шанс изобретения: база × (1 + (наука₁ + наука₂)/30 + шифрование/40). Обе науки — на уровне inv_sci."""
    return min(1.0, base * (1 + 2 * s["inv_sci"] / 30 + s["inv_enc"] / 40))


def plan_order(calc: "Calculator", items: List[Tuple[int, int]], s: dict, mode: str = "full", now: Optional[float] = None,
               price_ids: Optional[set] = None, _prices: Optional[dict] = None) -> dict:
    """Заказ из нескольких продуктов. mode="full" — всё, что строится по чертежу, строим сами (компоненты, реакции,
    изобретение T2); "buy" — строим только сами продукты, компоненты покупаем. Общие компоненты складываются,
    округление до целых прогонов даёт остатки."""
    now = time.time() if now is None else now
    data = calc.data
    bps, invs = data["bp"], data.get("inv", {})
    top: Dict[int, int] = {}
    for tid, qty in items:
        if str(tid) in bps and qty > 0:
            top[tid] = top.get(tid, 0) + int(qty)

    def buildable(t):
        return str(t) in bps and (t in top or mode == "full")

    # граф: кто из строящегося что потребляет (чтобы общий компонент считался один раз, после всех потребителей)
    seen, stack, consumers = set(), list(top), defaultdict_int()
    while stack:
        t = stack.pop()
        if t in seen:
            continue
        seen.add(t)
        for m, _ in bps[str(t)][4]:
            if buildable(m):
                consumers[m] += 1
                stack.append(m)
    need: Dict[int, float] = dict(top)
    queue = [t for t in seen if consumers.get(t, 0) == 0]
    buy: Dict[int, int] = {}
    jobs, inv_rows, left = [], [], {}
    while queue:
        t = queue.pop(0)
        bp = bps[str(t)]
        bp_id, kind, base_time, out_qty, mats = bp[0], bp[1], bp[2], bp[3], bp[4]
        src = bp[6] if len(bp) > 6 else "bpo"
        if t in top:
            me, te = (2, 4) if src == "inv" else (s["me"], s["te"])
        else:
            me, te = s["comp_me"], s["comp_te"]
        b = bonuses(dict(s, me=me, te=te), kind, True)
        runs = max(1, math.ceil(need.get(t, 0) / out_qty))
        made = runs * out_qty
        left[t] = made - need.get(t, 0)
        jobs.append({"type_id": t, "name": calc.name(t), "kind": kind, "runs": runs, "made": made, "need": need.get(t, 0),
                     "time": base_time * runs * b["time"], "top": t in top, "eiv_base": [(m, q) for m, q in mats], "me": me, "te": te})
        for m, q in mats:
            qty = mat_qty(q, runs, b["mat"])
            if m in seen and buildable(m):
                need[m] = need.get(m, 0) + qty
                consumers[m] -= 1
                if consumers[m] == 0:
                    queue.append(m)
            else:
                buy[m] = buy.get(m, 0) + qty
        # изобретение копий T2 (полный цикл)
        inv = invs.get(str(bp_id)) if src == "inv" else None         # копия T2 нужна в любом режиме
        if inv:
            t1_bp, t1_product, base_p, inv_runs, dcs, inv_time = inv
            chance = invention_chance(base_p, s)
            attempts = math.ceil(runs / max(1e-9, chance * inv_runs))
            for m, q in dcs:
                buy[m] = buy.get(m, 0) + q * attempts
            inv_rows.append({"type_id": t, "name": calc.name(t), "runs": runs, "chance": chance, "per_copy": inv_runs,
                             "attempts": attempts, "t1": t1_product, "datacores": [[m, q * attempts] for m, q in dcs],
                             "time": inv_time * attempts})

    # цены
    ids = set(buy) | set(top) | {t for t, v in left.items() if v > 0}
    prices = _prices if _prices is not None else calc.prices(ids | (price_ids or set()), s["market"], now)
    have = bool(prices)
    adj = calc.adjusted_prices(now)

    def price(t, mode_):
        return (prices.get(t) or {}).get(mode_)

    idx_cache: Dict[str, Optional[float]] = {}

    def index(activity):
        if activity not in idx_cache:
            if s["cost_index"] is not None and activity != "invention":
                idx_cache[activity] = s["cost_index"] / 100
            else:
                calc._ensure_static(now, need_index=True)
                sid = HUB_SYSTEMS.get(s["market"], 0)
                if s["system"]:
                    calc.cost_index(s["system"], "m", now)
                    sid = calc.systems.get(s["system"].strip().casefold()) or sid
                idx_cache[activity] = calc.indices[1].get(sid, {}).get(activity)
        return idx_cache[activity]

    job_total = 0.0
    for j in jobs:
        idx = index("reaction" if j["kind"] == "r" else "manufacturing")
        eiv = sum(q * adj.get(m, 0) for m, q in j.pop("eiv_base")) * j["runs"]
        b = bonuses(s, j["kind"], True)
        j["eiv"], j["cost"] = eiv, eiv * ((idx or 0) * b["cost"] + s["facility_tax"] / 100 + s["scc"] / 100)
        job_total += j["cost"]
    inv_total = 0.0
    for r in inv_rows:
        t1 = r["t1"]
        eiv_t1 = sum(q * adj.get(m, 0) for m, q in (bps.get(str(t1)) or [0, 0, 0, 0, []])[4]) if t1 else 0
        r["job"] = eiv_t1 * INV_BASE_COST * ((index("invention") or 0) + s["facility_tax"] / 100 + s["scc"] / 100) * r["attempts"]
        r["datacores_cost"] = sum((price(m, s["buy_mode"]) or 0) * q for m, q in r["datacores"])
        r["cost"] = r["job"] + r["datacores_cost"]
        inv_total += r["job"]
    dc_ids = {m for r in inv_rows for m, _ in r["datacores"]}
    groups = data.get("groups", {})
    shopping, buy_total, no_price = [], 0.0, []
    for t, q in buy.items():
        pr = price(t, s["buy_mode"])
        if have and pr is None:
            no_price.append(calc.name(t))
        tinfo = data["types"].get(str(t)) or [str(t), 0, 0, 0]
        group = "Изобретение: датакоры" if t in dc_ids else groups.get(str(tinfo[1]), "Прочее")
        shopping.append({"type_id": t, "name": calc.name(t), "qty": q, "price": pr, "total": pr * q if pr is not None else None,
                         "volume": tinfo[3] * q, "group": group})
        buy_total += pr * q if pr is not None else 0
    shopping.sort(key=lambda r: (r["group"], -(r["total"] or 0)))
    leftovers, left_total = [], 0.0
    for t, v in left.items():
        if v <= 0:
            continue
        pr = price(t, "buy")
        leftovers.append({"type_id": t, "name": calc.name(t), "qty": v, "price": pr, "total": pr * v if pr is not None else None,
                          "top": t in top})
        left_total += pr * v if pr is not None else 0
    leftovers.sort(key=lambda r: -(r["total"] or 0))
    revenue = 0.0
    products = []
    fee = (s["sales_tax"] + (s["broker"] if s["sell_mode"] == "sell" else 0)) / 100
    for t, q in top.items():
        pr = price(t, s["sell_mode"])
        net = pr * q * (1 - fee) if pr is not None else None
        revenue += net or 0
        job = next((j for j in jobs if j["type_id"] == t), {})
        products.append({"type_id": t, "name": calc.name(t), "qty": q, "made": job.get("made", q), "time": job.get("time", 0),
                         "price": pr, "net": net, "src": (bps[str(t)][6] if len(bps[str(t)]) > 6 else "bpo"),
                         "kind": bps[str(t)][1]})
    dc_total = sum(r["datacores_cost"] for r in inv_rows)
    buy_total -= dc_total                                      # датакоры — в строке «Изобретение», не в закупке
    inv_total += dc_total
    spend = buy_total + job_total + inv_total
    cost = spend - left_total
    profit = revenue - cost if have else None
    return {"top": top, "jobs": jobs, "invention": inv_rows, "shopping": shopping, "leftovers": leftovers, "products": products,
            "prices": have, "no_price": no_price, "mode": mode,
            "totals": {"buy": buy_total if have else None, "jobs": job_total, "invention": inv_total, "spend": spend if have else None,
                       "leftovers": left_total if have else None, "cost": cost if have else None, "revenue": revenue if have else None,
                       "profit": profit, "roi": round(profit * 100 / cost, 1) if profit is not None and cost else None,
                       "volume": sum(r["volume"] for r in shopping), "time": sum(j["time"] for j in jobs)}}


def defaultdict_int():
    from collections import defaultdict
    return defaultdict(int)


def plan_with_products(calc: "Calculator", items: List[Tuple[int, int]], s: dict, mode: str, now: Optional[float] = None) -> dict:
    """Общий план + каждый продукт отдельно (его себестоимость за штуку, маржа, ROI) — на одних и тех же ценах."""
    now = time.time() if now is None else now
    whole = plan_order(calc, items, s, mode, now)
    prices = calc.prices(set().union(*[{r["type_id"] for r in whole["shopping"]}, set(whole["top"]),
                                     {r["type_id"] for r in whole["leftovers"]}]), s["market"], now) if whole["prices"] else {}
    for p in whole["products"]:
        one = plan_order(calc, [(p["type_id"], p["qty"])], s, mode, now, _prices=prices or None)
        t = one["totals"]
        p["cost"] = t["cost"]
        p["unit_cost"] = t["cost"] / p["qty"] if t["cost"] is not None and p["qty"] else None
        p["unit_net"] = p["net"] / p["qty"] if p["net"] is not None and p["qty"] else None
        p["profit"] = p["net"] - t["cost"] if p["net"] is not None and t["cost"] is not None else None
        p["margin"] = round(p["profit"] * 100 / p["net"], 1) if p["profit"] is not None and p["net"] else None
        p["roi"] = round(p["profit"] * 100 / t["cost"], 1) if p["profit"] is not None and t["cost"] else None
        p["chain_time"] = t["time"]
    return whole


# ---------------------------------------------------------------------------
# Сканер: цены всего хаба и прибыльность всех чертежей
# ---------------------------------------------------------------------------

class Hub:
    """Лучшие цены всех предметов на станции хаба — из всех ордеров региона (сотни страниц ESI, в фоне)."""

    def __init__(self, data_dir: str = "", get_page: Optional[Callable] = None, workers: int = 8):
        self.dir = data_dir
        self.get_page = get_page or self._esi_page
        self.workers = workers
        self.books: Dict[str, Tuple[float, Dict[int, dict]]] = {}
        self.status: Dict[str, dict] = {}
        self.lock = threading.Lock()

    @staticmethod
    def _esi_page(region: int, page: int) -> Tuple[list, int]:
        import urllib.request
        import zlib
        req = urllib.request.Request(f"{ESI_BASE}/markets/{region}/orders/?datasource=tranquility&order_type=all&page={page}",
                                     headers={"Accept": "application/json", "Accept-Encoding": "gzip",
                                              "User-Agent": "EveLogHUD industry (github.com/BaNNaN4iK/eve-log-hud)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            pages = int(r.headers.get("X-Pages") or 1)
            if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                raw = zlib.decompress(raw, 16 + zlib.MAX_WBITS)
        return json.loads(raw.decode("utf-8")), pages

    def _path(self, market: str) -> str:
        return os.path.join(self.dir, f"industry_hub_{market}.json") if self.dir else ""

    def book(self, market: str) -> Dict[int, dict]:
        with self.lock:
            hit = self.books.get(market)
        if hit is None and self._path(market):
            try:
                with open(self._path(market), encoding="utf-8") as f:
                    d = json.load(f)
                hit = (float(d["at"]), {int(k): {"buy": v[0], "sell": v[1], "split": v[2], "bv": v[3], "sv": v[4]}
                                        for k, v in d["prices"].items()})
                with self.lock:
                    self.books[market] = hit
            except (OSError, ValueError, KeyError, TypeError):
                return {}
        return hit[1] if hit else {}

    def age(self, market: str) -> Optional[float]:
        self.book(market)
        with self.lock:
            hit = self.books.get(market)
        return hit[0] if hit else None

    def fresh(self, market: str, now: float) -> bool:
        at = self.age(market)
        return at is not None and now - at < HUB_TTL

    def state(self, market: str) -> dict:
        with self.lock:
            st = dict(self.status.get(market) or {})
        st["at"] = self.age(market)
        return st

    def refresh(self, market: str, now: Optional[float] = None) -> None:
        """Скачать все ордера региона и оставить лучшие цены на станции хаба. Идёт в фоне, с прогрессом."""
        now = time.time() if now is None else now
        _, region, station = MARKETS[market]
        with self.lock:
            if (self.status.get(market) or {}).get("running"):
                return
            self.status[market] = {"running": True, "done": 0, "pages": 0, "error": ""}
        try:
            first, pages = self.get_page(region, 1)
            with self.lock:
                self.status[market].update(pages=pages, done=1)
            acc: Dict[int, list] = {}

            def take(orders):
                for o in orders or []:
                    if o.get("location_id") != station:
                        continue
                    a = acc.setdefault(int(o["type_id"]), [None, None, 0, 0])
                    if o.get("is_buy_order"):
                        a[0] = o["price"] if a[0] is None else max(a[0], o["price"])
                        a[2] += int(o.get("volume_remain") or 0)
                    else:
                        a[1] = o["price"] if a[1] is None else min(a[1], o["price"])
                        a[3] += int(o.get("volume_remain") or 0)
            take(first)

            def one(pg):
                for attempt in range(3):
                    try:
                        return self.get_page(region, pg)[0]
                    except Exception:
                        if attempt == 2:
                            raise
                        time.sleep(2 + attempt * 3)
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
                for orders in pool.map(one, range(2, pages + 1)):
                    take(orders)
                    with self.lock:
                        self.status[market]["done"] += 1
            prices = {}
            for t, (b, sl, bv, sv) in acc.items():
                split = (b + sl) / 2 if b is not None and sl is not None else (b if sl is None else sl)
                prices[t] = {"buy": b, "sell": sl, "split": split, "bv": bv, "sv": sv}
            with self.lock:
                self.books[market] = (now, prices)
            if self._path(market):
                tmp = self._path(market) + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"at": now, "prices": {str(t): [v["buy"], v["sell"], v["split"], v["bv"], v["sv"]] for t, v in prices.items()}},
                              f, separators=(",", ":"))
                try:
                    os.replace(tmp, self._path(market))
                except OSError:
                    import shutil
                    shutil.copyfile(tmp, self._path(market))
                    os.remove(tmp)
            with self.lock:
                self.status[market].update(running=False, error="")
        except Exception as e:
            with self.lock:
                self.status[market].update(running=False, error=f"Цены не загружены: {e}")


def category_of(data: dict, tid: int) -> str:
    t = data["types"].get(str(tid))
    cat = t[2] if t else None
    for key, cats in CATEGORIES.items():
        if cat in cats:
            return key
    return "other"


def scan(calc: "Calculator", market: str, s: dict, now: float, reactions: bool = True) -> List[dict]:
    """Прибыль за один прогон каждого чертежа по ценам хаба. Без цены продукта или материала — пропуск."""
    book = calc.hub.book(market) if getattr(calc, "hub", None) else {}
    if not book:
        return []
    data = calc.data
    adj = calc.adjusted_prices(now)
    calc._ensure_static(now, need_index=True)
    idx_all = calc.indices[1].get(HUB_SYSTEMS.get(market, 0), {})
    out = []
    for key, bp in data["bp"].items():
        _, kind, base_time, out_qty, mats, _ = bp[:6]
        src = bp[6] if len(bp) > 6 else "bpo"
        if kind == "r" and not reactions:
            continue
        tid = int(key)
        pp = book.get(tid)
        if not pp or (pp["sell"] is None and pp["buy"] is None):
            continue
        b = bonuses(dict(s, me=2, te=4) if src == "inv" else s, kind, True)    # копия после изобретения — обычно ME 2 / TE 4
        cost = 0.0
        missing = False
        for m, q in mats:
            mp = (book.get(m) or {}).get(s["buy_mode"])
            if mp is None:
                missing = True
                break
            cost += mp * mat_qty(q, 1, b["mat"])
        if missing:
            continue
        idx = s["cost_index"] / 100 if s["cost_index"] is not None else idx_all.get("reaction" if kind == "r" else "manufacturing")
        eiv = sum(q * adj.get(m, 0) for m, q in mats)
        job = eiv * ((idx or 0) * b["cost"] + s["facility_tax"] / 100 + s["scc"] / 100)
        total = cost + job
        t_run = base_time * b["time"]
        row = {"id": tid, "name": data["types"][key][0], "kind": kind, "cat": category_of(data, tid), "time": t_run, "out": out_qty,
               "cost": total, "job": job, "src": src}
        avg = calc.average.get(tid)
        row["avg"] = avg
        for mode, tax in (("sell", s["sales_tax"] + s["broker"]), ("buy", s["sales_tax"])):
            price = pp[mode]
            if price is None:
                row[mode] = None
                continue
            rev = price * out_qty
            profit = rev * (1 - tax / 100) - total
            row[mode] = {"price": price, "profit": profit, "margin": profit * 100 / rev if rev else None,
                         "isk_hour": profit / (t_run / 3600) if t_run else None,
                         "odd": bool(avg and price > avg * SUSPICIOUS)}
        if src == "bpo" and any(row[m] and (row[m]["margin"] or 0) > LP_MARGIN for m in ("sell", "buy")):
            row["src"] = "lp"                                     # навигационные модули Navy, спецвыпуски и т. п.
        row["sure"] = bool(row["sell"] and row["buy"] and row["sell"]["profit"] > 0 and row["buy"]["profit"] > 0
                           and not row["sell"]["odd"] and not row["buy"]["odd"])
        row["supply"] = pp.get("sv", 0)
        out.append(row)
    return out


class History:
    """Сколько продаётся за неделю и вчера (история рынка региона по предмету) — только для видимых карточек."""

    def __init__(self, esi: Optional[Callable], data_dir: str = ""):
        self.esi = esi
        self.path = os.path.join(data_dir, "industry_history.json") if data_dir else ""
        self.d: Dict[str, list] = {}
        self.lock = threading.Lock()
        try:
            with open(self.path, encoding="utf-8") as f:
                self.d = json.load(f)
        except (OSError, ValueError):
            self.d = {}

    def week(self, market: str, tid: int) -> Optional[int]:
        v = self.d.get(f"{MARKETS[market][1]}:{tid}")
        return v[1] if v else None

    def fill(self, market: str, ids: List[int]) -> None:
        """Проверить спрос у всех кандидатов сканера (в фоне, порциями)."""
        with self.lock:
            if getattr(self, "running", False):
                return
            self.running = True
            self.todo = len(ids)
            self.done = 0
        try:
            for i in range(0, len(ids), 60):
                self.get(market, ids[i:i + 60])
                with self.lock:
                    self.done = min(self.todo, i + 60)
        finally:
            with self.lock:
                self.running = False

    def get(self, market: str, ids: List[int], now: Optional[float] = None) -> Dict[str, dict]:
        now = time.time() if now is None else now
        region = MARKETS[market][1]
        need = [t for t in ids if now - (self.d.get(f"{region}:{t}") or [0])[0] >= HISTORY_TTL]
        if need and self.esi is not None:
            def one(t):
                try:
                    rows, _ = self.esi(f"/markets/{region}/history/", type_id=t)
                    rows = sorted(rows or [], key=lambda r: r.get("date", ""))
                    since = time.strftime("%Y-%m-%d", time.gmtime(now - 7 * 86400))
                    week = sum(int(r.get("volume") or 0) for r in rows if r.get("date", "") > since)
                    return t, [now, week, int(rows[-1].get("volume") or 0) if rows else 0, rows[-1].get("date", "") if rows else ""]
                except Exception:
                    return t, None
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                for t, v in pool.map(one, need[:60]):
                    if v is not None:
                        with self.lock:
                            self.d[f"{region}:{t}"] = v
            if self.path:
                try:
                    with self.lock:
                        snap = dict(self.d)
                    with open(self.path, "w", encoding="utf-8") as f:
                        json.dump(snap, f, separators=(",", ":"))
                except OSError:
                    pass
        out = {}
        for t in ids:
            v = self.d.get(f"{region}:{t}")
            if v:
                out[str(t)] = {"week": v[1], "last": v[2], "date": v[3]}
        return out


# ---------------------------------------------------------------------------
# Ведение производства: закреплённые чертежи, что есть на складе, что докупить, ход работ, история цен
# ---------------------------------------------------------------------------

PROJECT_STATUSES = ("collect", "building", "done")
MINERAL_GROUP = 18
PROJECT_MAX = 50
PROJECT_SNAP = 3600                    # снимок себестоимости и цены продукта для графика — не чаще раза в час
PROJECT_SNAPS = 400
SERIES_TTL = 6 * 3600
QTY_MAX = 10 ** 12
_SEP = re.compile(r"[\s  ',.]")


def _qty(text: str) -> Optional[int]:
    s = _SEP.sub("", text or "")
    return int(s) if s.isdigit() and int(s) <= QTY_MAX else None


def parse_stock(text: str) -> List[Tuple[str, int]]:
    """Склад, вставленный из игры: «Название<Tab>Количество<Tab>…» (копия списка ангара), «Название 1000»,
    «Название x1000», «1000 x Название». Строка без количества — 1 шт. Одинаковые названия складываются."""
    got: Dict[str, int] = {}
    order: List[str] = []
    for raw in (text or "").splitlines()[:2000]:
        line = raw.strip()
        if not line:
            continue
        name, qty = None, None
        cols = [c.strip() for c in line.split("\t")]
        if len(cols) > 1 and cols[0]:
            name, qty = cols[0], _qty(cols[1]) if cols[1] else 1
        if qty is None:
            m = re.match(r"^(.+?)\s+[x×х*]?\s*(\d[\d\s  ',.]*)$", line) or None
            if m and _qty(m.group(2)) is not None:
                name, qty = m.group(1).strip(), _qty(m.group(2))
            else:
                m = re.match(r"^(\d[\d\s  ',.]*?)\s*[x×х*]?\s+(.+)$", line)
                if m and _qty(m.group(1)) is not None:
                    name, qty = m.group(2).strip(), _qty(m.group(1))
                else:
                    name, qty = line, 1
        name = name.rstrip("*").strip()                          # «*» — предмет в ремонте/сборке
        if not name or qty is None:
            continue
        key = name.casefold()
        if key not in got:
            order.append(name)
            got[key] = 0
        got[key] += qty
    return [(n, got[n.casefold()]) for n in order]


class Projects:
    """Закреплённые чертежи: настройки расчёта, сколько материалов уже есть, ход работ и снимки цен."""

    def __init__(self, calc: "Calculator", path: str = "", write: Optional[Callable] = None):
        self.calc = calc
        self.path = path
        self.write = write
        self.lock = threading.Lock()
        self.series: Dict[Tuple[int, int], Tuple[float, list]] = {}
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            self.items: List[dict] = d if isinstance(d, list) else []
        except (OSError, ValueError):
            self.items = []

    def save(self) -> None:
        if not self.path:
            return
        with self.lock:
            snap = json.loads(json.dumps(self.items))
        if self.write is not None:
            self.write(self.path, snap)
        else:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False)

    def get(self, pid: str) -> Optional[dict]:
        return next((p for p in self.items if p.get("id") == pid), None)

    def create(self, product: str, settings: Optional[dict], name: str = "", now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now
        tid = self.calc.find(product)
        if tid is None or str(tid) not in self.calc.data["bp"]:
            raise ValueError("Не нашёл, что строить — выберите из подсказки.")
        if len(self.items) >= PROJECT_MAX:
            raise ValueError(f"Закреплено уже {PROJECT_MAX} чертежей — удалите ненужные.")
        s = clean_settings(settings)
        pid = f"{int(now * 1000):x}"
        while self.get(pid):
            pid += "a"
        p = {"id": pid, "type_id": tid, "product": self.calc.name(tid), "name": (name or "").strip()[:80] or self.calc.name(tid),
             "settings": s, "have": {}, "jobs_done": [], "status": "collect", "created": int(now), "started": None,
             "finished": None, "snaps": [], "batches": [], "log": [[int(now), "Чертёж закреплён"]]}
        with self.lock:
            self.items.insert(0, p)
        self.save()
        return p

    def _log(self, p: dict, text: str, now: float) -> None:
        p["log"] = (p.get("log") or [])[-99:] + [[int(now), text[:200]]]

    def raw(self, p: dict, now: float) -> Optional[dict]:
        """Сырьё: если строить самому все компоненты (производство; продукты реакций покупаются), — сколько каких материалов нужно.
        None — строить нечего: закупка и так состоит из сырья."""
        bp = self.calc.data["bp"]
        res = self.calc.calculate(str(p["type_id"]), p["settings"], now)
        if not res.get("ok") or not any(bp.get(str(r["type_id"]), [0, ""])[1] == "m" for r in res["shopping"]):
            return None
        build = set(p["settings"].get("build") or [])
        for _ in range(8):                                       # раскрываем дерево слой за слоем
            found = set()

            def walk(node):
                for m in node["materials"]:
                    if "build" in m:
                        walk(m["build"])
                    elif m.get("buildable") and m.get("kind") == "m":   # реакции не раскрываем: их продукты покупают
                        found.add(m["type_id"])
            walk(res["tree"])
            if not found - build:
                break
            build |= found
            res = self.calc.calculate(str(p["type_id"]), dict(p["settings"], build=sorted(build)), now)
        return res

    def _rows(self, shopping: list, have: dict) -> Tuple[list, dict]:
        rows, need_cost, have_cost, left_cost, left_vol, ready = [], 0.0, 0.0, 0.0, 0.0, 0
        for r in shopping:
            h = int(have.get(str(r["type_id"]), 0))
            use = min(h, r["qty"])
            left = r["qty"] - use
            price = r["price"]
            vol1 = r["volume"] / r["qty"] if r["qty"] else 0
            rows.append(dict(r, have=h, left=left, extra=max(0, h - r["qty"]), pct=round(100 * use / r["qty"], 1) if r["qty"] else 100.0,
                             have_cost=use * price if price is not None else None, left_cost=left * price if price is not None else None,
                             left_volume=left * vol1))
            if price is not None:
                need_cost += r["qty"] * price
                have_cost += use * price
                left_cost += left * price
            left_vol += left * vol1
            ready += 1 if left == 0 else 0
        qty = sum(r["qty"] for r in rows) or 1
        progress = round(100 * have_cost / need_cost, 1) if need_cost else round(100 * sum(min(r["have"], r["qty"]) for r in rows) / qty, 1)
        return rows, {"need_cost": need_cost, "have_cost": have_cost, "left_cost": left_cost, "left_volume": left_vol,
                      "progress": progress, "ready": ready, "positions": len(rows),
                      "progress_qty": round(100 * sum(min(r["have"], r["qty"]) for r in rows) / qty, 1)}

    def detail(self, p: dict, now: Optional[float] = None, snap: bool = True, with_raw: bool = True) -> dict:
        """Расчёт проекта: материалы (нужно / есть / осталось / докупить), работы, итоги, время."""
        now = time.time() if now is None else now
        res = self.calc.calculate(str(p["type_id"]), p["settings"], now)
        if not res.get("ok"):
            return res
        have = p.get("have") or {}
        priced = res.get("prices")
        mats, mt = self._rows(res["shopping"], have)
        need_cost, have_cost, left_cost, left_vol, ready = mt["need_cost"], mt["have_cost"], mt["left_cost"], mt["left_volume"], mt["ready"]
        progress_value = mt["progress"] if priced else mt["progress_qty"]
        raw = None
        if with_raw:
            rr = self.raw(p, now)
            if rr is not None:
                rows, rt = self._rows(rr["shopping"], have)
                types = self.calc.data["types"]
                for r in rows:                                   # минералы (группа Mineral) — то, что дают руды
                    r["mineral"] = (types.get(str(r["type_id"])) or [0, 0])[1] == MINERAL_GROUP
                mins = [r for r in rows if r["mineral"]]
                _, mt2 = self._rows([{k: r[k] for k in ("type_id", "name", "qty", "price", "total", "volume")} for r in mins], have)
                raw = {"materials": rows, "totals": dict(rt, progress=rt["progress"] if priced else rt["progress_qty"],
                                                         need_cost=rt["need_cost"] if priced else None,
                                                         left_cost=rt["left_cost"] if priced else None,
                                                         jobs=rr["totals"]["jobs"], cost=rr["totals"]["cost"],
                                                         per_unit=rr["totals"]["per_unit"], time=rr["totals"]["time"],
                                                         minerals=dict(mt2, progress=mt2["progress"] if priced else mt2["progress_qty"]) if mins else None),
                       "jobs": len(rr["jobs"])}
        done = set(p.get("jobs_done") or [])
        jobs = []
        for i, j in enumerate(res["jobs"]):
            key = f"{j['type_id']}:{j['depth']}"
            jobs.append(dict(j, key=key, done=key in done))
        t = res["totals"]
        cs = (res.get("compare") or {}).get(p["settings"].get("sell_mode") if p["settings"].get("sell_mode") in ("sell", "buy") else "sell") or {}
        # ход работ: главная работа запущена — когда будет готово
        eta = None
        if p.get("status") == "building" and p.get("started"):
            left_jobs = sum(j["time"] for j in jobs if not j["done"] and j["depth"] > 0)
            eta = p["started"] + (t.get("top_time") or 0) + left_jobs
        out = {
            "ok": True, "project": {k: v for k, v in p.items() if k not in ("snaps",)}, "calc": {
                "product": res["product"], "settings": res["settings"], "market_name": res["market_name"], "warning": res["warning"],
                "cost_index": res["cost_index"], "system": res["system"], "missing_price": res["missing_price"], "compare": res["compare"]},
            "materials": mats, "jobs": jobs, "prices": priced,
            "totals": dict(t, need_cost=need_cost if priced else None, have_cost=have_cost if priced else None,
                           left_cost=left_cost if priced else None, left_volume=left_vol, progress=progress_value,
                           ready=ready, positions=len(mats), jobs_done=sum(1 for j in jobs if j["done"]), jobs_total=len(jobs),
                           # прибыль, если докупить недостающее; уже купленное — по рыночной цене (могли бы продать)
                           profit=cs.get("profit"), margin=cs.get("margin"), revenue=cs.get("revenue"), fees=cs.get("fees"),
                           isk_hour=cs.get("isk_hour")),
            "eta": eta, "now": int(now), "snaps": p.get("snaps") or [], "raw": raw,
        }
        if snap and priced and t.get("cost") is not None:
            snaps = p.get("snaps") or []
            if not snaps or now - snaps[-1][0] >= PROJECT_SNAP:
                p["snaps"] = (p.get("snaps") or [])[-(PROJECT_SNAPS - 1):] + [[int(now), round(t["cost"], 2),
                                                                             round(t["per_unit"] or 0, 2),
                                                                             res["product"]["price"], round(left_cost, 2)]]
                out["snaps"] = p["snaps"]
                self.save()
        return out

    def summary(self, p: dict, now: Optional[float] = None) -> dict:
        try:
            d = self.detail(p, now, with_raw=False)
        except Exception as e:                                  # нет сети и т. п. — карточка без цифр
            d = {"ok": False, "message": str(e)}
        base = {"id": p["id"], "name": p["name"], "product": p["product"], "type_id": p["type_id"], "status": p["status"],
                "runs": p["settings"].get("runs"), "created": p["created"], "started": p.get("started"),
                "batches": len(p.get("batches") or [])}
        if not d.get("ok"):
            return dict(base, error=d.get("message"))
        t = d["totals"]
        return dict(base, units=d["calc"]["product"]["units"], progress=t["progress"], left_cost=t["left_cost"], cost=t["cost"],
                    profit=t["profit"], margin=t["margin"], ready=t["ready"], positions=t["positions"], eta=d["eta"],
                    time=t.get("top_time"), spark=[s[2] for s in (d["snaps"] or [])[-30:]])

    def price_series(self, market: str, tid: int, now: Optional[float] = None) -> list:
        """История цены продукта на рынке региона: [дата, средняя, мин, макс, объём] за 90 дней (ESI, кэш 6 ч)."""
        now = time.time() if now is None else now
        region = MARKETS[market][1]
        hit = self.series.get((region, tid))
        if hit and now - hit[0] < SERIES_TTL:
            return hit[1]
        if self.calc.esi is None:
            return hit[1] if hit else []
        try:
            rows, _ = self.calc.esi(f"/markets/{region}/history/", type_id=tid)
        except Exception:
            return hit[1] if hit else []
        rows = sorted(rows or [], key=lambda r: r.get("date", ""))[-90:]
        out = [[r.get("date", ""), r.get("average"), r.get("lowest"), r.get("highest"), int(r.get("volume") or 0)] for r in rows]
        self.series[(region, tid)] = (now, out)
        return out

    # ----- изменения -----
    def set_have(self, p: dict, have: dict, merge: bool = False) -> None:
        cur = dict(p.get("have") or {}) if merge else {}
        for k, v in (have or {}).items():
            try:
                tid, q = int(k), int(float(v))
            except (TypeError, ValueError):
                continue
            q = max(0, min(q, QTY_MAX))
            cur[str(tid)] = cur.get(str(tid), 0) + q if merge else q
        p["have"] = {k: v for k, v in cur.items() if v > 0}

    def paste(self, p: dict, text: str, mode: str = "set", now: Optional[float] = None) -> dict:
        """Вставка из игры: найти материалы проекта по названиям (англ. или русским через ESI) и записать количество."""
        now = time.time() if now is None else now
        rows = parse_stock(text)
        if not rows:
            raise ValueError("Не нашёл ни одной строки с предметом. Скопируйте предметы в игре (Ctrl+A, Ctrl+C) и вставьте сюда.")
        res = self.calc.calculate(str(p["type_id"]), p["settings"], now)
        if not res.get("ok"):
            raise ValueError(res.get("message") or "Расчёт не удался")
        shop = list(res["shopping"])
        rr = self.raw(p, now)
        if rr is not None:
            shop += rr["shopping"]
        wanted = {r["name"].casefold(): r["type_id"] for r in shop}
        got: Dict[str, int] = {}
        unknown = []
        for name, q in rows:
            tid = wanted.get(name.casefold())
            if tid is None:
                unknown.append((name, q))
                continue
            got[str(tid)] = got.get(str(tid), 0) + q
        if unknown and self.calc.esi is not None:                  # русские названия из клиента на русском
            try:
                ids, _ = self.calc.esi("/universe/ids/", "POST", [n for n, _ in unknown][:500], language="ru")
                by = {e["name"].casefold(): e["id"] for e in (ids or {}).get("inventory_types") or []}
                need = {r["type_id"] for r in shop}
                rest = []
                for name, q in unknown:
                    tid = by.get(name.casefold())
                    if tid in need:
                        got[str(tid)] = got.get(str(tid), 0) + q
                    else:
                        rest.append((name, q))
                unknown = rest
            except Exception:
                pass
        if mode == "set":
            self.set_have(p, got)
        else:
            self.set_have(p, got, merge=True)
        self._log(p, f"Склад из игры: {len(got)} материалов" + (" (добавлено)" if mode != "set" else ""), now)
        self.save()
        return {"matched": len(got), "skipped": [n for n, _ in unknown][:30], "lines": len(rows)}

    def set_status(self, p: dict, status: str, consume: bool = True, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        if status not in PROJECT_STATUSES:
            raise ValueError("Неизвестный этап")
        if status == "building":
            p["started"], p["finished"] = int(now), None
            self._log(p, "Производство запущено", now)
        elif status == "done":
            d = self.detail(p, now, snap=False, with_raw=False)
            t = d.get("totals") or {}
            p["finished"] = int(now)
            p["batches"] = (p.get("batches") or [])[-199:] + [{
                "t": int(now), "units": (d.get("calc") or {}).get("product", {}).get("units"), "cost": t.get("cost"),
                "per_unit": t.get("per_unit"), "price": (d.get("calc") or {}).get("product", {}).get("price"),
                "profit": t.get("profit"), "time": (now - p["started"]) if p.get("started") else None}]
            if consume:                                          # материалы ушли в работу — списать со склада
                have = dict(p.get("have") or {})
                for r in d.get("materials") or []:
                    left = have.get(str(r["type_id"]), 0) - r["qty"]
                    if left > 0:
                        have[str(r["type_id"])] = left
                    else:
                        have.pop(str(r["type_id"]), None)
                p["have"] = have
            self._log(p, "Готово" + (f": {(d.get('calc') or {}).get('product', {}).get('units')} шт." if d.get("ok") else ""), now)
        else:
            p["started"] = p["finished"] = None
            p["jobs_done"] = []
            self._log(p, "Новая партия: сбор материалов", now)
        p["status"] = status
        self.save()

    def toggle_job(self, p: dict, key: str, done: bool) -> None:
        cur = set(p.get("jobs_done") or [])
        (cur.add if done else cur.discard)(str(key)[:40])
        p["jobs_done"] = sorted(cur)
        self.save()

    def update_settings(self, p: dict, settings: dict, name: Optional[str] = None, now: Optional[float] = None) -> None:
        p["settings"] = clean_settings(dict(p["settings"], **settings))
        if name is not None and name.strip():
            p["name"] = name.strip()[:80]
        self._log(p, f"Настройки: {p['settings']['runs']} прог., ME {p['settings']['me']} / TE {p['settings']['te']}",
                  time.time() if now is None else now)
        self.save()

    def delete(self, pid: str) -> bool:
        with self.lock:
            n = len(self.items)
            self.items = [p for p in self.items if p.get("id") != pid]
            changed = len(self.items) != n
        if changed:
            self.save()
        return changed


# ---------------------------------------------------------------------------
# Подключение к трекеру
# ---------------------------------------------------------------------------

def setup(ctx) -> None:
    data = load_data()
    if not data.get("bp"):
        ctx.log.warning("Производство: нет справочника industry_data.json")
    calc = Calculator(ctx.online.esi if ctx.online is not None else None, data,
                      cache_path=os.path.join(ctx.data_dir, "industry_cache.json"))
    if ctx.online is not None:                                  # большие списки ESI — заранее, пока никто не ждёт
        ctx.thread(lambda: calc.refresh_static(), "industry-static")
    path = os.path.join(ctx.data_dir, "industry_settings.json")

    def load_settings() -> dict:
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            return {"settings": clean_settings(d.get("settings")), "product": str(d.get("product") or "")[:120]}
        except (OSError, ValueError, AttributeError):
            return {"settings": clean_settings(None), "product": ""}

    def run(body, qs):
        if not isinstance(body, dict) or not isinstance(body.get("product"), str):
            return {"ok": False, "message": "Укажите, что строить."}
        s = clean_settings(body.get("settings") if isinstance(body.get("settings"), dict) else None)
        try:
            ctx.core.atomic_write_json(path, {"settings": s, "product": body["product"][:120]})
        except Exception as e:
            ctx.log.info("Производство: настройки не сохранены: %s", e)
        try:
            res = calc.calculate(body["product"], s)
        except Exception as e:
            ctx.log.warning("Производство: расчёт не удался: %s", e)
            return {"ok": False, "message": f"Не удалось посчитать: {e}"}
        if res.get("ok") and ctx.online is not None:
            ids = [res["product"]["type_id"]] + [r["type_id"] for r in res["shopping"]] + [j["type_id"] for j in res["jobs"]]
            threading.Thread(target=lambda: [ctx.online.fetch_icon(i) for i in ids[:120]], name="industry-icons", daemon=True).start()
        if ctx.online is None and res.get("ok"):
            res["note"] = "Цены и стоимость работ не показаны: онлайн-функции выключены (online_enabled в config.json)."
        return res

    hub = Hub(ctx.data_dir)
    calc.hub = hub
    hist = History(calc.esi, ctx.data_dir)
    SORTS = {"isk_hour": lambda r, m: (r[m] or {}).get("isk_hour") or -1e30,
             "profit": lambda r, m: (r[m] or {}).get("profit") or -1e30,
             "margin": lambda r, m: (r[m] or {}).get("margin") or -1e30,
             "volume": lambda r, m: r.get("supply") or 0}
    cache = {"key": None, "rows": []}

    def scanner(qs):
        g = lambda k, d="": (qs.get(k) or [d])[0]
        market = g("market", "jita") if g("market", "jita") in MARKETS else "jita"
        s = load_settings()["settings"]
        now = time.time()
        st = hub.state(market)
        key = (market, st.get("at"), json.dumps(s, sort_keys=True), calc.indices[0], calc.adjusted[0], len(calc.average))
        if cache["key"] != key:
            cache["rows"], cache["key"] = scan(calc, market, s, now), key
        rows = cache["rows"]
        mode = "buy" if g("mode") == "buy" else "sell"
        for r in rows:
            r["week"] = hist.week(market, r["id"])
        region = MARKETS[market][1]
        cands = [r["id"] for r in rows if r["src"] not in ("bpc", "lp") and any(r[m] and r[m]["profit"] > 0 and not r[m]["odd"] for m in ("sell", "buy"))
                 and now - (hist.d.get(f"{region}:{r['id']}") or [0])[0] >= HISTORY_TTL]
        if cands and ctx.online is not None and not getattr(hist, "running", False):
            threading.Thread(target=hist.fill, args=(market, cands), name="industry-history", daemon=True).start()
        q, cat = g("q").strip().casefold(), g("cat")
        sel = [r for r in rows if (r[mode] and r[mode]["profit"] > 0) or g("all") == "1"]
        odd = sum(1 for r in sel if r[mode] and r[mode]["odd"])
        if g("odd") != "1":
            sel = [r for r in sel if not (r[mode] and r[mode]["odd"])]
        rare = sum(1 for r in sel if r["src"] in ("bpc", "lp"))
        if g("bpc") != "1":                                       # редкие копии и чертежи из LP-магазина — по желанию
            sel = [r for r in sel if r["src"] not in ("bpc", "lp")]
        thin = sum(1 for r in sel if r["week"] is not None and r["week"] < 7)
        if g("thin") != "1":                                      # продаётся реже раза в день — по желанию
            sel = [r for r in sel if r["week"] is None or r["week"] >= 7]
        if g("sure") == "1":
            sel = [r for r in sel if r["sure"]]
        if q:
            sel = [r for r in sel if q in r["name"].casefold()]
        if cat in CATEGORIES or cat == "other":
            sel = [r for r in sel if r["cat"] == cat]
        sort = g("sort", "isk_hour") if g("sort", "isk_hour") in SORTS else "isk_hour"
        sel.sort(key=lambda r: SORTS[sort](r, mode), reverse=True)
        try:
            page = max(1, int(g("page", "1")))
        except ValueError:
            page = 1
        per = 20
        counts = {}
        for m in MARKETS:
            if m == market:
                counts[m] = sum(1 for r in rows if r["sell"] and r["sell"]["profit"] > 0)
        shown = sel[(page - 1) * per: page * per]
        if ctx.online is not None and shown:                       # иконки видимых карточек
            ids = [r["id"] for r in shown]
            threading.Thread(target=lambda: [ctx.online.fetch_icon(i) for i in ids], name="industry-icons", daemon=True).start()
        return {"ok": True, "market": market, "market_name": MARKETS[market][0], "status": st, "total": len(sel),
                "page": page, "pages": max(1, -(-len(sel) // per)), "rows": shown,
                "counts": counts, "scanned": len(rows), "settings": s, "prices": ctx.online is not None, "odd": odd,
                "rare": rare, "thin": thin, "demand": {"running": getattr(hist, "running", False), "done": getattr(hist, "done", 0),
                                                       "todo": getattr(hist, "todo", 0)},
                "ages": {m: hub.age(m) for m in MARKETS}}

    def scan_refresh(body, qs=None):
        market = str((body or {}).get("market") or "jita") if isinstance(body, dict) else "jita"
        if market not in MARKETS:
            return {"ok": False, "message": "Неизвестный хаб"}
        if ctx.online is None:
            return {"ok": False, "message": "Онлайн-функции выключены (online_enabled в config.json)."}
        threading.Thread(target=hub.refresh, args=(market,), name="industry-hub", daemon=True).start()
        threading.Thread(target=calc.refresh_static, name="industry-static", daemon=True).start()
        return {"ok": True, "message": "Загружаю цены хаба…"}

    def history(qs):
        market = (qs.get("market") or ["jita"])[0]
        market = market if market in MARKETS else "jita"
        try:
            ids = [int(x) for x in (qs.get("ids") or [""])[0].split(",") if x.strip()][:40]
        except ValueError:
            ids = []
        return {"ok": True, "history": hist.get(market, ids)}

    def save_settings(body, qs=None):
        if not isinstance(body, dict) or not isinstance(body.get("settings"), dict):
            return {"ok": False, "message": "Неверный запрос"}
        cur = load_settings()
        s = clean_settings(body["settings"])
        try:
            ctx.core.atomic_write_json(path, {"settings": s, "product": cur["product"]})
        except Exception as e:
            return {"ok": False, "message": str(e)}
        return {"ok": True, "settings": s}

    plans_path = os.path.join(ctx.data_dir, "industry_plans.json")

    def read_plans() -> list:
        try:
            with open(plans_path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, list) else []
        except (OSError, ValueError):
            return []

    def catalog(qs):
        out = []
        for key, bp in data["bp"].items():
            t = data["types"].get(key)
            if t:
                out.append([int(key), t[0], category_of(data, int(key)), bp[6] if len(bp) > 6 else "bpo", bp[1]])
        out.sort(key=lambda r: r[1].casefold())
        return {"ok": True, "items": out}

    def clean_items(raw) -> List[Tuple[int, int]]:
        items = []
        for it in raw if isinstance(raw, list) else []:
            try:
                tid, qty = int(it.get("id")), int(float(it.get("qty") or 1))
            except (TypeError, ValueError, AttributeError):
                continue
            if str(tid) in data["bp"] and 0 < qty <= 10_000_000:
                items.append((tid, qty))
        return items[:60]

    def plan(body, qs=None):
        if not isinstance(body, dict):
            return {"ok": False, "message": "Неверный запрос"}
        items = clean_items(body.get("items"))
        if not items:
            return {"ok": False, "message": "Добавьте в план хотя бы один продукт."}
        s = clean_settings(dict(load_settings()["settings"], **(body.get("settings") or {})) if isinstance(body.get("settings"), dict)
                           else load_settings()["settings"])
        mode = "buy" if body.get("mode") == "buy" else "full"
        try:
            res = plan_with_products(calc, items, s, mode)
        except Exception as e:
            ctx.log.warning("Производство: план не посчитан: %s", e)
            return {"ok": False, "message": f"Не удалось посчитать: {e}"}
        if ctx.online is not None:
            ids = [p["type_id"] for p in res["products"]] + [r["type_id"] for r in res["shopping"]][:80] + [j["type_id"] for j in res["jobs"]][:80]
            threading.Thread(target=lambda: [ctx.online.fetch_icon(i) for i in ids], name="industry-icons", daemon=True).start()
        res["top"] = {str(k): v for k, v in res["top"].items()}
        return {"ok": True, "settings": s, "market_name": MARKETS[s["market"]][0], **res}

    def plans(qs):
        return {"ok": True, "plans": read_plans()}

    def plans_save(body, qs=None):
        if not isinstance(body, dict):
            return {"ok": False, "message": "Неверный запрос"}
        name = str(body.get("name") or "").strip()[:80]
        if not name:
            return {"ok": False, "message": "Назовите план."}
        cur = [p for p in read_plans() if p.get("name") != name]
        if body.get("action") != "delete":
            items = clean_items(body.get("items"))
            if not items:
                return {"ok": False, "message": "В плане нет продуктов."}
            cur.insert(0, {"name": name, "items": [{"id": t, "qty": q} for t, q in items],
                           "mode": "buy" if body.get("mode") == "buy" else "full", "updated": int(time.time())})
        try:
            ctx.core.atomic_write_json(plans_path, cur[:100])
        except Exception as e:
            return {"ok": False, "message": str(e)}
        return {"ok": True, "plans": cur[:100]}

    projects = Projects(calc, os.path.join(ctx.data_dir, "industry_projects.json"), ctx.core.atomic_write_json)

    def icons(ids):
        if ctx.online is not None and ids:
            threading.Thread(target=lambda: [ctx.online.fetch_icon(i) for i in list(ids)[:120]], name="industry-icons", daemon=True).start()

    def projects_list(qs):
        rows = [projects.summary(p) for p in list(projects.items)]
        icons([r["type_id"] for r in rows])
        return {"ok": True, "projects": rows, "prices": ctx.online is not None}

    def project_get(qs):
        p = projects.get((qs.get("id") or [""])[0])
        if p is None:
            return {"ok": False, "message": "Такого проекта нет — возможно, его удалили."}
        try:
            d = projects.detail(p)
        except Exception as e:
            ctx.log.warning("Производство: проект не посчитан: %s", e)
            return {"ok": False, "message": f"Не удалось посчитать: {e}"}
        if d.get("ok"):
            market = d["calc"]["settings"]["market"]
            d["series"] = projects.price_series(market, p["type_id"]) if (qs.get("series") or ["1"])[0] == "1" else None
            icons([p["type_id"]] + [m["type_id"] for m in d["materials"]] + [j["type_id"] for j in d["jobs"]])
        return d

    def projects_post(body, qs=None):
        if not isinstance(body, dict):
            return {"ok": False, "message": "Неверный запрос"}
        action = body.get("action")
        try:
            if action == "create":
                if not isinstance(body.get("product"), str):
                    return {"ok": False, "message": "Укажите, что строить."}
                p = projects.create(body["product"], body.get("settings") if isinstance(body.get("settings"), dict) else None,
                                    str(body.get("name") or ""))
                return {"ok": True, "id": p["id"], "message": f"Закреплено: {p['name']}"}
            p = projects.get(str(body.get("id") or ""))
            if p is None:
                return {"ok": False, "message": "Такого проекта нет — возможно, его удалили."}
            if action == "have":
                projects.set_have(p, dict(p.get("have") or {}, **(body.get("have") if isinstance(body.get("have"), dict) else {})))
                projects.save()
            elif action == "paste":
                r = projects.paste(p, str(body.get("text") or "")[:200_000], "add" if body.get("mode") == "add" else "set")
                return {"ok": True, **r}
            elif action == "clear":
                p["have"] = {}
                projects.save()
            elif action == "status":
                projects.set_status(p, str(body.get("status") or ""), consume=body.get("consume") is not False)
            elif action == "job":
                projects.toggle_job(p, str(body.get("key") or ""), bool(body.get("done")))
            elif action == "settings":
                projects.update_settings(p, body.get("settings") if isinstance(body.get("settings"), dict) else {},
                                         str(body["name"]) if isinstance(body.get("name"), str) else None)
            elif action == "delete":
                projects.delete(p["id"])
            else:
                return {"ok": False, "message": "Неизвестное действие"}
        except ValueError as e:
            return {"ok": False, "message": str(e)}
        return {"ok": True}

    ctx.get("/api/industry/projects", projects_list)
    ctx.get("/api/industry/project", project_get)
    ctx.post("/api/industry/projects", projects_post)
    ctx.get("/api/industry/catalog", catalog)
    ctx.post("/api/industry/plan", plan)
    ctx.get("/api/industry/plans", plans)
    ctx.post("/api/industry/plans", plans_save)
    ctx.get("/api/industry/scan", scanner)
    ctx.post("/api/industry/scan/refresh", scan_refresh)
    ctx.get("/api/industry/history", history)
    ctx.post("/api/industry/settings", save_settings)
    ctx.post("/api/industry", run)
    ctx.get("/api/industry/search", lambda qs: {"ok": True, "items": calc.search((qs.get("q") or [""])[0])})
    ctx.get("/api/industry/settings", lambda qs: {"ok": True, **load_settings(), "prices": ctx.online is not None,
                                                  "data_built": data.get("built"), "blueprints": len(data.get("bp", {}))})
