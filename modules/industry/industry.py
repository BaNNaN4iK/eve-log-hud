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
    for k in ("industry", "adv_industry", "reactions"):
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
            self.indices = (float(c["indices"][0]), {int(k): v for k, v in c["indices"][1].items()})
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        tmp = self.cache_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"adjusted": [self.adjusted[0], self.adjusted[1]], "indices": [self.indices[0], self.indices[1]]}, f)
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
            if now - self.adjusted[0] >= ADJUSTED_TTL or not self.adjusted[1]:
                rows = self.big("/markets/prices/")
                self.adjusted = (now, {int(r["type_id"]): float(r.get("adjusted_price") or 0) for r in rows or []})
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
        if self.esi is None and self.big is None:
            return {}
        self._ensure_static(now, need_index=False)
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
        _, kind, base_time, out_qty, mats, max_runs = bp
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
            "unit_prices": {str(t): price(t, s["buy_mode"]) for t in ids},
            "cost_index": idx_used[0], "system": idx_used[1], "missing_price": missing_price,
            "market_name": MARKETS[s["market"]][0], "warning": note_hs, "data_built": self.data.get("built"),
        }


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

    ctx.post("/api/industry", run)
    ctx.get("/api/industry/search", lambda qs: {"ok": True, "items": calc.search((qs.get("q") or [""])[0])})
    ctx.get("/api/industry/settings", lambda qs: {"ok": True, **load_settings(), "prices": ctx.online is not None,
                                                  "data_built": data.get("built"), "blueprints": len(data.get("bp", {}))})
