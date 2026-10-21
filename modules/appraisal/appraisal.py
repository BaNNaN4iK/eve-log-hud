# -*- coding: utf-8 -*-
"""
Оценка предметов (как Janice): вставили список — получили цены Jita (или другого хаба), объём и итог.

Только стандартная библиотека. Цены — прямо из рынка игры (ESI): лучший ордер на покупку и на продажу
на станции хаба; «середина» (split) — среднее между ними. Изменение — к средней цене за 7 дней по региону.
Оценки сохраняются на этом компьютере: appraisals/<код>.json.
"""
import concurrent.futures
import json
import os
import re
import secrets
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

# хаб: (название, регион, станция)
MARKETS = {
    "jita": ("Jita 4-4", 10000002, 60003760),
    "amarr": ("Amarr", 10000043, 60008494),
    "dodixie": ("Dodixie", 10000032, 60011866),
    "rens": ("Rens", 10000030, 60004588),
    "hek": ("Hek", 10000042, 60005686),
}
MODES = ("buy", "split", "sell")
PRICE_TTL = 300          # книга ордеров живёт 5 минут
HISTORY_TTL = 6 * 3600   # дневная история — несколько часов
MAX_LINES = 1000
NUM = r"\d[\d\s  .,']*"


def parse_qty(s: str) -> Optional[int]:
    """«15 933», «15,933», «15.933», «1'000», «2x» → число; дробная часть отбрасывается."""
    s = s.strip().lower().rstrip("x×").strip()
    if not s:
        return None
    s = re.sub(r"[\s  ']", "", s)
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):              # разделители тысяч
        s = re.sub(r"[.,]", "", s)
    m = re.fullmatch(r"(\d+)(?:[.,]\d+)?", s)
    return int(m.group(1)) if m else None


def parse(text: str) -> Tuple[List[Tuple[str, int]], List[str]]:
    """Текст из игры (инвентарь, контракт, грузовой скан, EFT) → [(название, количество)] и нераспознанные строки.

    Понимает: «Название<TAB>число<TAB>…», «Название x 10», «10 x Название», «Название 10», «Название» (= 1).
    Одинаковые названия складываются.
    """
    items: Dict[str, int] = {}
    order: List[str] = []
    bad: List[str] = []
    for raw in (text or "").splitlines()[:MAX_LINES]:
        line = raw.strip()
        if not line or line.startswith("[") and line.endswith("]"):          # заголовок фита EFT
            continue
        name, qty = None, None
        if "\t" in line:
            cols = [c.strip() for c in line.split("\t")]
            name = cols[0]
            qty = parse_qty(cols[1]) if len(cols) > 1 and cols[1] else 1
            if qty is None:                                                 # «Название<TAB>Группа<TAB>…» без количества
                qty = 1
        else:
            after = re.fullmatch(r"(.+?)\s+[x×]\s*(%s)" % NUM, line, re.I)          # «Название x 10»
            before = re.fullmatch(r"(%s)\s*[x×]\s+(.+)" % NUM, line, re.I)        # «10 x Название»
            tail = re.fullmatch(r"(.+?)\s+(%s)" % NUM, line)                        # «Название 10»
            if after and parse_qty(after.group(2)) is not None:
                name, qty = after.group(1), parse_qty(after.group(2))
            elif before and parse_qty(before.group(1)) is not None:
                name, qty = before.group(2), parse_qty(before.group(1))
            elif tail and parse_qty(tail.group(2)) is not None:
                name, qty = tail.group(1), parse_qty(tail.group(2))
            elif re.fullmatch(r"\d[\d\s  .,']*\s+[^\d\s].*", line):     # «500 Hobgoblin II» (но не «250mm …»)
                lead = re.fullmatch(r"(\d[\d.,']*(?:[\s  ]\d{3})*)\s+(\D.*)", line)
                name, qty = (lead.group(2), parse_qty(lead.group(1))) if lead else (line, 1)
            else:
                name, qty = line, 1
        name = re.sub(r"\s+", " ", (name or "").strip().rstrip("*").strip())
        if not name or qty is None or qty <= 0 or len(name) > 120:
            bad.append(raw.strip()[:200])
            continue
        key = name.lower()
        if key not in items:
            order.append(name)
        items[key] = items.get(key, 0) + qty
    return [(n, items[n.lower()]) for n in order], bad


def replace_file(tmp: str, path: str) -> None:
    """os.replace, который переживает защищённые папки Windows.

    На компьютерах с корпоративной защитой данных (шифрование EFS / Windows Information Protection) переименование
    поверх существующего файла падает с WinError 17 «нельзя переместить на другой диск», хотя папка одна.
    Тогда переписываем содержимое поверх (не атомарно, но данные не теряются) и убираем временный файл.
    """
    try:
        os.replace(tmp, path)
    except OSError as e:
        if getattr(e, "winerror", None) != 17:
            raise
        import shutil
        shutil.copyfile(tmp, path)
        os.remove(tmp)


class Appraiser:
    """Оценка через ESI. esi(path, method, body, **params) → (данные, заголовки) — как Online.esi трекера."""

    def __init__(self, data_dir: str, esi: Callable, types_cache: Optional[dict] = None, lock=None):
        self.dir = os.path.join(data_dir, "appraisals")
        self.esi = esi
        self.types = types_cache if types_cache is not None else {}        # общий с трекером кэш справочника
        self.lock = lock or threading.RLock()
        self.books: Dict[Tuple[str, int], Tuple[float, dict]] = {}
        self.hist: Dict[Tuple[int, int], Tuple[float, Optional[float]]] = {}
        self.ids: Dict[str, Optional[int]] = {}                             # название (нижний регистр) → type_id

    # ----- справочник -----
    def _resolve(self, names: List[str]) -> Dict[str, Optional[int]]:
        need = [n for n in names if n.lower() not in self.ids]
        for lang in ("en", "ru"):                                           # предметы из русского клиента — по-русски
            left = [n for n in need if n.lower() not in self.ids]
            for i in range(0, len(left), 250):
                try:
                    data, _ = self.esi("/universe/ids/", "POST", left[i:i + 250], language=lang)
                except Exception:
                    data = {}
                for e in (data or {}).get("inventory_types") or []:
                    self.ids[e["name"].lower()] = e["id"]
        for n in need:
            self.ids.setdefault(n.lower(), None)
        return {n: self.ids.get(n.lower()) for n in names}

    def _type(self, tid: int) -> dict:
        key = f"#{tid}"
        with self.lock:
            t = self.types.get(key)
        if t is None:
            info, _ = self.esi(f"/universe/types/{tid}/", language="en")
            t = {"id": tid, "name_en": info.get("name", str(tid)), "volume": info.get("volume"),
                 "packaged_volume": info.get("packaged_volume")}
            with self.lock:
                self.types[key] = t
        return t

    # ----- рынок -----
    def _book(self, market: str, tid: int, now: float) -> dict:
        key = (market, tid)
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
        book = {"buy": max(buys) if buys else None, "sell": min(sells) if sells else None}
        self.books[key] = (now, book)
        return book

    def _avg7(self, region: int, tid: int, now: float) -> Optional[float]:
        key = (region, tid)
        hit = self.hist.get(key)
        if hit and now - hit[0] < HISTORY_TTL:
            return hit[1]
        try:
            data, _ = self.esi(f"/markets/{region}/history/", type_id=tid)
            last = sorted(data or [], key=lambda d: d.get("date", ""))[-7:]
            vol = sum(d.get("volume", 0) for d in last)
            avg = sum(d.get("average", 0) * d.get("volume", 0) for d in last) / vol if vol else None
        except Exception:
            avg = None
        self.hist[key] = (now, avg)
        return avg

    # ----- оценка -----
    def appraise(self, text: str, market: str = "jita", mode: str = "split", now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now
        market = market if market in MARKETS else "jita"
        mode = mode if mode in MODES else "split"
        items, bad = parse(text)
        if not items:
            return {"ok": False, "message": "Не нашёл ни одного предмета. Вставьте список из игры: инвентарь, контракт, фит.",
                    "unparsed": bad}
        ids = self._resolve([n for n, _ in items])
        missing = [n for n, _ in items if not ids.get(n)]
        known = [(n, q, ids[n]) for n, q in items if ids.get(n)]
        _, region, _ = MARKETS[market]

        def one(entry):
            name, qty, tid = entry
            t = self._type(tid)
            book = self._book(market, tid, now)
            avg = self._avg7(region, tid, now)
            vol = t.get("packaged_volume") or t.get("volume") or 0
            buy, sell = book["buy"], book["sell"]
            split = (buy + sell) / 2 if buy is not None and sell is not None else (buy if sell is None else sell)
            pct = lambda p: round((p / avg - 1) * 100, 1) if p and avg else None
            return {"name": t["name_en"], "input": name, "type_id": tid, "qty": qty, "volume": vol * qty, "unit_volume": vol,
                    "buy": buy, "sell": sell, "split": split,
                    "buy_total": buy * qty if buy is not None else None, "sell_total": sell * qty if sell is not None else None,
                    "split_total": split * qty if split is not None else None,
                    "buy_change": pct(buy), "sell_change": pct(sell), "avg7": avg}

        rows, errors = [], []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for entry, fut in [(e, pool.submit(one, e)) for e in known]:
                try:
                    rows.append(fut.result())
                except Exception as e:
                    errors.append(f"{entry[0]}: {e}")
        total = lambda k: sum(r[k] for r in rows if r[k] is not None)
        result = {
            "ok": True, "code": secrets.token_urlsafe(5).replace("-", "").replace("_", "")[:6] or "x",
            "created": int(now), "market": market, "market_name": MARKETS[market][0], "mode": mode,
            "rows": rows, "missing": missing, "unparsed": bad, "errors": errors,
            "totals": {"buy": total("buy_total"), "sell": total("sell_total"), "split": total("split_total"),
                       "volume": sum(r["volume"] for r in rows), "items": len(rows),
                       "no_price": sum(1 for r in rows if r["buy"] is None and r["sell"] is None)},
            "text": text[:65536],
        }
        self.save(result)
        return result

    # ----- история -----
    def save(self, result: dict) -> None:
        os.makedirs(self.dir, exist_ok=True)
        path = os.path.join(self.dir, f"{result['code']}.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
        replace_file(tmp, path)

    def get(self, code: str) -> Optional[dict]:
        if not re.fullmatch(r"[A-Za-z0-9]{1,16}", code or ""):
            return None
        try:
            with open(os.path.join(self.dir, f"{code}.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def list(self, limit: int = 50) -> list:
        out = []
        try:
            names = [f for f in os.listdir(self.dir) if f.endswith(".json")]
        except OSError:
            return out
        for f in names:
            a = self.get(f[:-5])
            if a:
                out.append({"code": a["code"], "created": a["created"], "market_name": a["market_name"], "mode": a["mode"],
                            "items": a["totals"]["items"], "split": a["totals"]["split"], "buy": a["totals"]["buy"],
                            "sell": a["totals"]["sell"]})
        out.sort(key=lambda a: -a["created"])
        return out[:limit]



# ---------------------------------------------------------------------------
# Подключение к трекеру
# ---------------------------------------------------------------------------

def setup(ctx) -> None:
    if ctx.online is None:
        msg = {"ok": False, "message": "Оценка работает только с включёнными онлайн-функциями (online_enabled в config.json)."}
        ctx.post("/api/appraise", lambda body, qs: dict(msg))
        ctx.get("/api/appraisals", lambda qs: {"ok": True, "appraisals": []})
        return
    a = Appraiser(ctx.data_dir, ctx.online.esi, ctx.online.cache.setdefault("appraisal_types", {}), ctx.online.lock)

    def appraise(body, qs):
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            return {"ok": False, "message": "Вставьте список предметов."}
        try:
            return a.appraise(body["text"], str(body.get("market") or "jita"), str(body.get("mode") or "split"))
        except Exception as e:
            ctx.log.warning("Оценка не удалась: %s", e)
            return {"ok": False, "message": f"Не удалось получить цены: {e}"}

    def one(qs):
        found = a.get((qs.get("code") or [""])[0])
        return found if found else (404, {"ok": False, "message": "Оценка не найдена"})

    ctx.post("/api/appraise", appraise)
    ctx.get("/api/appraisals", lambda qs: {"ok": True, "appraisals": a.list()})
    ctx.get("/api/appraisal", one)
