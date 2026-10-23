# -*- coding: utf-8 -*-
"""
Отчёт о бое по киллмейлам (как br.evetools.org): кто с кем дрался, кто что потерял, кто сколько настрелял.

Только стандартная библиотека. Киллмейлы — с zKillboard (публичный API, страницы по 200 штук, новые первыми,
киллмейл целиком: жертва, атакующие с уроном, время, стоимость по оценке zKillboard). Если zKillboard отдал
только номер и хэш — киллмейл дочитывается из ESI. Имена, тикеры и классы кораблей — из ESI, с кэшем.

Стороны: участники объединяются по альянсу (или корпорации, если альянса нет). Кто стрелял в кого — на разных
сторонах; сторона «A» — наша: флот из истории, вошедший персонаж или его альянс. Любую группу можно перенести
на другую сторону вручную. Всё хранится на этом компьютере: battles/<id>.json, кэш имён — battles/names.json.
"""
import concurrent.futures
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from calendar import timegm
from collections import Counter, defaultdict
from typing import Callable, Dict, Iterable, List, Optional, Tuple

log = logging.getLogger("eve_battle")

ZKB = "https://zkillboard.com/api"
ESI = "https://esi.evetech.net/latest"
HOSTS = {"zkillboard.com", "esi.evetech.net"}
UA = "EveLogHUD battle report (github.com/BaNNaN4iK/eve-log-hud)"
MAX_PAGES = 25                         # 25 × 200 = 5000 киллмейлов на систему
MAX_SPAN = 24 * 3600                   # один отчёт — не больше суток
MAX_SYSTEMS = 6
CAPSULES = {670, 33328}
PAGE_PAUSE = 1.1                       # zKillboard просит не чаще запроса в секунду


class BattleError(Exception):
    """Ошибка с понятным пользователю текстом."""


def http_json(method: str, url: str, body=None, timeout: float = 40):
    """GET/POST JSON только к zKillboard и ESI (gzip понимает)."""
    import zlib                                        # не gzip: zlib встроен в любую сборку приложения
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.hostname not in HOSTS:
        raise BattleError(f"Адрес не разрешён: {u.hostname}")
    headers = {"User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "gzip"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                raw = zlib.decompress(raw, 16 + zlib.MAX_WBITS)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise BattleError(f"{u.hostname} просит подождать — слишком много запросов. Попробуйте через минуту.") from e
        raise BattleError(f"{u.hostname} ответил {e.code}") from e
    except (urllib.error.URLError, OSError) as e:
        raise BattleError(f"Нет связи с {u.hostname}: {getattr(e, 'reason', e)}") from e
    try:
        return json.loads(raw.decode("utf-8") or "null")
    except ValueError as e:
        raise BattleError(f"{u.hostname} вернул не JSON") from e


def parse_time(text: str) -> int:
    """«2026-10-23 18:05» или «2026-10-23T18:05:00Z» (время EVE = UTC) → секунды."""
    t = (text or "").strip().replace("T", " ").rstrip("Z").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M"):
        try:
            return timegm(time.strptime(t, fmt))
        except ValueError:
            pass
    raise BattleError(f"Не понял время «{text}». Нужно так: 2026-10-23 18:05 (время EVE).")


def km_time(km: dict) -> int:
    return timegm(time.strptime(km["killmail_time"].rstrip("Z")[:19], "%Y-%m-%dT%H:%M:%S"))


def compact(km: dict) -> dict:
    """Только нужное из киллмейла (без предметов и координат)."""
    v, z = km.get("victim") or {}, km.get("zkb") or {}
    return {
        "id": km["killmail_id"], "t": km_time(km), "sys": km.get("solar_system_id"), "hash": z.get("hash", ""),
        "value": float(z.get("totalValue") or 0), "dropped": float(z.get("droppedValue") or 0),
        "npc": bool(z.get("npc")), "solo": bool(z.get("solo")), "awox": bool(z.get("awox")),
        "v": {"c": v.get("character_id"), "co": v.get("corporation_id"), "a": v.get("alliance_id"),
              "f": v.get("faction_id"), "s": v.get("ship_type_id"), "d": int(v.get("damage_taken") or 0)},
        "att": [{"c": a.get("character_id"), "co": a.get("corporation_id"), "a": a.get("alliance_id"),
                 "f": a.get("faction_id"), "s": a.get("ship_type_id"), "w": a.get("weapon_type_id"),
                 "d": int(a.get("damage_done") or 0), "fb": bool(a.get("final_blow"))} for a in km.get("attackers") or []],
    }


def is_npc_corp(corp) -> bool:
    return bool(corp) and 1_000_000 <= int(corp) < 2_000_000


def entity(p: dict) -> str:
    """Группа участника: альянс, иначе корпорация; NPC — отдельно."""
    if p.get("a"):
        return f"a{p['a']}"
    if p.get("co") and not (is_npc_corp(p["co"]) and not p.get("c")):
        return f"c{p['co']}"
    return "npc"


# ---------------------------------------------------------------------------
# Загрузка
# ---------------------------------------------------------------------------

class Loader:
    """Киллмейлы систем за время боя. get(url) → JSON; sleep — пауза между страницами (в тестах — 0)."""

    def __init__(self, get: Optional[Callable] = None, cache_dir: str = "", sleep: Callable = time.sleep,
                 page_size: int = 200):
        self.get = get or (lambda url, body=None: http_json("POST" if body is not None else "GET", url, body))
        self.cache_dir = cache_dir
        self.sleep = sleep
        self.page_size = page_size             # zKillboard отдаёт по 200; короче — последняя страница

    def _esi_km(self, kid: int, khash: str) -> Optional[dict]:
        path = os.path.join(self.cache_dir, f"km_{kid}.json") if self.cache_dir else ""
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, ValueError):
                pass
        km = self.get(f"{ESI}/killmails/{kid}/{khash}/")
        if path and isinstance(km, dict):
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(km, f)
            except OSError:
                pass
        return km

    def system(self, system_id: int, start: int, end: int, progress: Callable = lambda **kw: None) -> List[dict]:
        out: Dict[int, dict] = {}
        recent = time.time() - start < 7 * 86400 - 3600
        for page in range(1, MAX_PAGES + 1):
            span = "" if not recent else f"pastSeconds/{min(604800, int((time.time() - start) // 3600 + 2) * 3600)}/"
            rows = self.get(f"{ZKB}/systemID/{int(system_id)}/{span}page/{page}/")
            if isinstance(rows, dict) and rows.get("error"):
                raise BattleError("zKillboard: " + str(rows["error"]))
            if not rows:
                break
            oldest = None
            need_esi = []
            for r in rows:
                if not isinstance(r, dict) or "killmail_id" not in r:
                    continue
                if "killmail_time" not in r:                          # старый формат — только номер и хэш
                    need_esi.append(r)
                    continue
                t = km_time(r)
                oldest = t if oldest is None else min(oldest, t)
                if start <= t <= end:
                    out[r["killmail_id"]] = compact(r)
            if need_esi:
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    fulls = list(pool.map(lambda r: self._esi_km(r["killmail_id"], (r.get("zkb") or {}).get("hash", "")), need_esi))
                for r, full in zip(need_esi, fulls):
                    if isinstance(full, dict) and full.get("killmail_time"):
                        full["zkb"] = r.get("zkb") or {}
                        t = km_time(full)
                        oldest = t if oldest is None else min(oldest, t)
                        if start <= t <= end:
                            out[full["killmail_id"]] = compact(full)
            progress(page=page, found=len(out))
            if oldest is not None and oldest < start or len(rows) < self.page_size:
                break
            self.sleep(PAGE_PAUSE)
        return sorted(out.values(), key=lambda k: (k["t"], k["id"]))


# ---------------------------------------------------------------------------
# Стороны
# ---------------------------------------------------------------------------

def assign_sides(kms: List[dict], seeds: Iterable[str], overrides: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """{группа: "A"|"B"}. Сторона A — seeds (наши). Кто дрался с A — B, кто с B — A; ручные переносы важнее."""
    w: Dict[str, Counter] = defaultdict(Counter)
    involvement = Counter()
    for k in kms:
        ve = entity(k["v"])
        ents = {entity(a) for a in k["att"]} - {"npc"}
        involvement[ve] += 1
        for e in ents:
            involvement[e] += 1
            if e != ve and ve != "npc":
                w[ve][e] += 1
                w[e][ve] += 1
    side: Dict[str, str] = {}
    for e in seeds:
        if e in involvement:
            side[e] = "A"
    for e, s in (overrides or {}).items():
        if s in ("A", "B"):
            side[e] = s
    if not any(s == "A" for s in side.values()) and involvement:          # своих не нашли — самая активная группа
        top = max((e for e in involvement if e != "npc"), key=lambda e: involvement[e], default=None)
        if top:
            side[top] = "A"
    order = sorted((e for e in involvement if e != "npc"), key=lambda e: -involvement[e])
    for _ in range(len(order) + 1):
        changed = False
        for e in order:
            if e in side and e not in (overrides or {}):
                continue
            if e in (overrides or {}):
                continue
            vs_a = sum(c for o, c in w[e].items() if side.get(o) == "A")
            vs_b = sum(c for o, c in w[e].items() if side.get(o) == "B")
            if vs_a or vs_b:
                side[e] = "B" if vs_a >= vs_b else "A"
                changed = True
        if not changed:
            break
    for e in order:
        side.setdefault(e, "B")
    side["npc"] = "npc"
    return side


# ---------------------------------------------------------------------------
# Статистика
# ---------------------------------------------------------------------------

def analyze(kms: List[dict], side: Dict[str, str], fleet_ids: Iterable[int] = ()) -> dict:
    """Вся статистика боя в ID (имена подставляет страница из names)."""
    fleet_ids = {int(i) for i in fleet_ids}
    sides = {s: {"pilots": set(), "kills": 0, "losses": 0, "ships_lost": 0, "pods_lost": 0, "isk_lost": 0.0,
                 "isk_destroyed": 0.0, "damage_done": 0, "damage_taken": 0,
                 "ships": defaultdict(lambda: {"fielded": set(), "lost": 0, "isk_lost": 0.0, "damage": 0}),
                 "weapons": defaultdict(lambda: {"uses": 0, "damage": 0})} for s in ("A", "B")}
    pilots: Dict[int, dict] = {}
    ent_stats: Dict[str, dict] = defaultdict(lambda: {"pilots": set(), "kills": 0, "losses": 0, "isk_lost": 0.0, "damage": 0})

    def pilot(p: dict) -> Optional[dict]:
        cid = p.get("c")
        if not cid:
            return None
        e = entity(p)
        rec = pilots.get(cid)
        if rec is None:
            rec = pilots[cid] = {"id": cid, "corp": p.get("co"), "alliance": p.get("a"), "entity": e,
                                 "side": side.get(e, "B"), "ships": Counter(), "kills": 0, "final_blows": 0,
                                 "damage": 0, "top_damage": 0, "solo": 0, "losses": [], "isk_lost": 0.0,
                                 "isk_involved": 0.0, "in_fleet": cid in fleet_ids, "first": None, "last": None}
        return rec

    timeline = []
    for k in kms:
        ve = entity(k["v"])
        vs = side.get(ve, "B")
        real_att = [a for a in k["att"] if a.get("c")]
        all_npc = not real_att
        top = max(k["att"], key=lambda a: a["d"], default=None)
        fb = next((a for a in k["att"] if a["fb"]), None)
        # жертва
        vp = pilot(k["v"])
        if vs in sides:
            S = sides[vs]
            S["losses"] += 1
            S["isk_lost"] += k["value"]
            S["damage_taken"] += k["v"]["d"]
            if k["v"]["s"] in CAPSULES:
                S["pods_lost"] += 1
            else:
                S["ships_lost"] += 1
            if k["v"]["s"]:
                sh = S["ships"][k["v"]["s"]]
                sh["lost"] += 1
                sh["isk_lost"] += k["value"]
            if k["v"].get("c"):
                S["pilots"].add(k["v"]["c"])
            other = "B" if vs == "A" else "A"
            if not all_npc:
                sides[other]["kills"] += 1
                sides[other]["isk_destroyed"] += k["value"]
        es = ent_stats[ve]
        es["losses"] += 1
        es["isk_lost"] += k["value"]
        if vp is not None:
            if k["v"]["s"] and k["v"]["s"] not in CAPSULES:
                vp["ships"][k["v"]["s"]] += 0
            vp["losses"].append({"km": k["id"], "ship": k["v"]["s"], "value": k["value"], "t": k["t"]})
            vp["isk_lost"] += k["value"]
            vp["first"] = k["t"] if vp["first"] is None else min(vp["first"], k["t"])
            vp["last"] = k["t"] if vp["last"] is None else max(vp["last"], k["t"])
            if vs in sides and k["v"]["s"] and k["v"]["s"] not in CAPSULES:
                sides[vs]["ships"][k["v"]["s"]]["fielded"].add(k["v"]["c"])
            es["pilots"].add(k["v"]["c"])
        # атакующие
        for a in k["att"]:
            ae = entity(a)
            as_ = side.get(ae, "B")
            ent_stats[ae]["damage"] += a["d"]
            p = pilot(a)
            if as_ in sides:
                S = sides[as_]
                if as_ != vs:
                    S["damage_done"] += a["d"]
                if a.get("c"):
                    S["pilots"].add(a["c"])
                    if a.get("s") and a["s"] not in CAPSULES:
                        S["ships"][a["s"]]["fielded"].add(a["c"])
                        if as_ != vs:
                            S["ships"][a["s"]]["damage"] += a["d"]
                    if a.get("w") and a["w"] != a.get("s"):
                        S["weapons"][a["w"]]["uses"] += 1
                        S["weapons"][a["w"]]["damage"] += a["d"]
            if p is None:
                continue
            ent_stats[ae]["pilots"].add(a["c"])
            if a.get("s") and a["s"] not in CAPSULES:
                p["ships"][a["s"]] += 1
            p["kills"] += 1
            p["damage"] += a["d"]
            p["isk_involved"] += k["value"]
            p["final_blows"] += 1 if a["fb"] else 0
            p["top_damage"] += 1 if top is a and a["d"] > 0 else 0
            p["solo"] += 1 if k["solo"] and len(real_att) == 1 else 0
            p["first"] = k["t"] if p["first"] is None else min(p["first"], k["t"])
            p["last"] = k["t"] if p["last"] is None else max(p["last"], k["t"])
        if not all_npc:
            for e in {entity(a) for a in real_att}:
                ent_stats[e]["kills"] += 1
        timeline.append({
            "id": k["id"], "t": k["t"], "sys": k["sys"], "value": k["value"], "dropped": k["dropped"],
            "side": vs, "victim": k["v"]["c"], "victim_corp": k["v"]["co"], "victim_entity": ve, "ship": k["v"]["s"],
            "damage_taken": k["v"]["d"], "attackers": len(k["att"]), "pilots": len(real_att), "npc": all_npc,
            "solo": k["solo"], "awox": k["awox"],
            "final_blow": {"c": fb.get("c"), "s": fb.get("s"), "e": entity(fb)} if fb else None,
            "top": {"c": top.get("c"), "s": top.get("s"), "d": top["d"], "e": entity(top)} if top else None,
        })

    t0 = kms[0]["t"] if kms else 0
    t1 = kms[-1]["t"] if kms else 0
    # ISK по минутам (нарастающим итогом) для графика
    series = []
    if kms:
        acc = {"A": 0.0, "B": 0.0}
        bucket = {}
        for k in kms:
            s = side.get(entity(k["v"]), "B")
            if s in acc:
                acc[s] += k["value"]
            bucket[(k["t"] - t0) // 60] = dict(acc)
        last = {"A": 0.0, "B": 0.0}
        for m in range(0, (t1 - t0) // 60 + 1):
            last = bucket.get(m, last)
            series.append({"m": m, "A": last["A"], "B": last["B"]})

    out_sides = {}
    for s, S in sides.items():
        total = S["isk_lost"] + S["isk_destroyed"]
        out_sides[s] = {
            "pilots": len(S["pilots"]), "kills": S["kills"], "losses": S["losses"], "ships_lost": S["ships_lost"],
            "pods_lost": S["pods_lost"], "isk_lost": S["isk_lost"], "isk_destroyed": S["isk_destroyed"],
            "efficiency": round(S["isk_destroyed"] * 100 / total, 1) if total else None,
            "damage_done": S["damage_done"], "damage_taken": S["damage_taken"],
            "ships": sorted([{"type": t, "fielded": len(v["fielded"]), "lost": v["lost"], "isk_lost": v["isk_lost"],
                              "damage": v["damage"]} for t, v in S["ships"].items()],
                            key=lambda r: (-r["fielded"], -r["lost"])),
            "weapons": sorted([{"type": t, **v} for t, v in S["weapons"].items()], key=lambda r: -r["damage"])[:25],
        }
    entities = []
    for e, st in ent_stats.items():
        if e == "npc":
            continue
        entities.append({"key": e, "side": side.get(e, "B"), "pilots": len(st["pilots"]), "kills": st["kills"],
                         "losses": st["losses"], "isk_lost": st["isk_lost"], "damage": st["damage"]})
    entities.sort(key=lambda r: (r["side"], -r["pilots"], -r["damage"]))
    plist = []
    for p in pilots.values():
        plist.append({**p, "ships": [t for t, _ in p["ships"].most_common()]})
    plist.sort(key=lambda p: (p["side"], -p["damage"], -p["kills"]))

    real = [x for x in timeline if not x["npc"]]
    hi = {}
    if real:
        hi["most_expensive"] = max(real, key=lambda x: x["value"])["id"]
        hi["first_blood"] = real[0]["id"]
    for key, field in (("top_damage", "damage"), ("top_final_blows", "final_blows"), ("top_kills", "kills"),
                       ("top_lost", "isk_lost")):
        best = max(plist, key=lambda p: p[field], default=None)
        if best and best[field]:
            hi[key] = {"id": best["id"], "value": best[field]}
    fleet_missing = sorted(fleet_ids - set(pilots)) if fleet_ids else []
    return {"t0": t0, "t1": t1, "duration": t1 - t0, "kms": len(kms), "sides": out_sides, "entities": entities,
            "pilots": plist, "timeline": timeline, "series": series, "highlights": hi, "fleet_missing": fleet_missing,
            "systems": sorted({k["sys"] for k in kms if k["sys"]})}


# ---------------------------------------------------------------------------
# Имена, тикеры, классы кораблей
# ---------------------------------------------------------------------------

class Names:
    def __init__(self, path: str = "", get: Optional[Callable] = None):
        self.path = path
        self.get = get or (lambda url, body=None: http_json("POST" if body is not None else "GET", url, body))
        self.lock = threading.Lock()
        self.d: Dict[str, object] = {}
        if path:
            try:
                with open(path, encoding="utf-8") as f:
                    self.d = json.load(f)
            except (OSError, ValueError):
                self.d = {}

    def save(self) -> None:
        if not self.path:
            return
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.d, f, ensure_ascii=False)
            try:
                os.replace(tmp, self.path)
            except OSError:
                import shutil
                shutil.copyfile(tmp, self.path)
                os.remove(tmp)
        except OSError as e:
            log.info("Кэш имён не сохранён: %s", e)

    def resolve(self, ids: Iterable[int]) -> None:
        need = sorted({int(i) for i in ids if i and str(i) not in self.d})
        for i in range(0, len(need), 900):
            chunk = need[i:i + 900]
            try:
                rows = self.get(f"{ESI}/universe/names/", chunk) or []
            except BattleError:
                rows = []
                for one in chunk:                                   # один битый ID ломает весь запрос — по одному
                    try:
                        rows += self.get(f"{ESI}/universe/names/", [one]) or []
                    except BattleError:
                        pass
            for r in rows:
                self.d[str(r["id"])] = r["name"]

    def tickers(self, keys: Iterable[str]) -> None:
        todo = [k for k in keys if k[0] in "ac" and f"tk{k}" not in self.d]

        def one(k):
            try:
                info = self.get(f"{ESI}/{'alliances' if k[0] == 'a' else 'corporations'}/{k[1:]}/")
                return k, (info or {}).get("ticker", "")
            except BattleError:
                return k, None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for k, t in pool.map(one, todo[:150]):
                if t is not None:
                    self.d[f"tk{k}"] = t

    def groups(self, type_ids: Iterable[int]) -> None:
        todo = [t for t in {int(x) for x in type_ids if x} if f"g{t}" not in self.d]

        def one(t):
            try:
                return t, (self.get(f"{ESI}/universe/types/{t}/") or {}).get("group_id")
            except BattleError:
                return t, None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for t, g in pool.map(one, todo):
                if g:
                    self.d[f"g{t}"] = g
        gids = {self.d.get(f"g{t}") for t in type_ids if t} - {None}
        todo_g = [g for g in gids if f"gn{g}" not in self.d]

        def gname(g):
            try:
                return g, (self.get(f"{ESI}/universe/groups/{g}/") or {}).get("name")
            except BattleError:
                return g, None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for g, n in pool.map(gname, todo_g):
                if n:
                    self.d[f"gn{g}"] = n

    def table(self, report: dict, kms: List[dict]) -> dict:
        """Имена для страницы: {id: имя}, {группа: {имя, тикер}}, {корабль: класс}."""
        ids, ships = set(), set()
        for k in kms:
            for p in [k["v"]] + k["att"]:
                ids.update(x for x in (p.get("c"), p.get("co"), p.get("a"), p.get("s"), p.get("w")) if x)
                if p.get("s"):
                    ships.add(p["s"])
            ids.add(k["sys"])
        self.resolve(ids)
        ents = [e["key"] for e in report["entities"]]
        self.tickers(ents)
        self.groups(ships)
        self.save()
        names = {str(i): self.d.get(str(i), str(i)) for i in ids if i}
        ent = {e: {"name": self.d.get(e[1:], e) if e != "npc" else "NPC", "ticker": self.d.get(f"tk{e}", ""),
                   "kind": "alliance" if e[0] == "a" else "corp"} for e in ents}
        classes = {str(t): self.d.get(f"gn{self.d.get(f'g{t}')}", "") for t in ships}
        return {"names": names, "entities": ent, "classes": classes}


# ---------------------------------------------------------------------------
# Отчёты: сборка в фоне, хранение, перенос групп между сторонами
# ---------------------------------------------------------------------------

class Battles:
    def __init__(self, data_dir: str, loader: Optional[Loader] = None, names: Optional[Names] = None,
                 get: Optional[Callable] = None, me: Callable[[], Optional[int]] = lambda: None,
                 fleet: Callable[[int], Optional[dict]] = lambda fid: None,
                 on_built: Callable[[set], None] = lambda type_ids: None):
        self.dir = os.path.join(data_dir, "battles")
        os.makedirs(self.dir, exist_ok=True)
        self.get = get or (lambda url, body=None: http_json("POST" if body is not None else "GET", url, body))
        self.loader = loader or Loader(self.get, os.path.join(self.dir, "km"))
        os.makedirs(os.path.join(self.dir, "km"), exist_ok=True)
        self.names = names or Names(os.path.join(self.dir, "names.json"), self.get)
        self.me = me
        self.fleet = fleet                     # fleet_id → запись флота (members, started_at, ended_at …)
        self.on_built = on_built               # после сборки: ID кораблей и оружия (трекер скачает иконки)
        self.jobs: Dict[str, dict] = {}
        self.lock = threading.Lock()

    # ----- хранение -----
    def _path(self, bid: str) -> str:
        if not re.fullmatch(r"[0-9a-z_]{4,40}", bid or ""):
            raise BattleError("Неверный номер отчёта")
        return os.path.join(self.dir, f"{bid}.json")

    def _save(self, rec: dict) -> None:
        path = self._path(rec["id"])
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, separators=(",", ":"))
        try:
            os.replace(tmp, path)
        except OSError:
            import shutil
            shutil.copyfile(tmp, path)
            os.remove(tmp)

    def load(self, bid: str) -> Optional[dict]:
        try:
            with open(self._path(bid), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError, BattleError):
            return None

    def list(self) -> list:
        out = []
        for f in sorted(os.listdir(self.dir), reverse=True):
            if not f.endswith(".json") or f == "names.json":
                continue
            rec = self.load(f[:-5])
            if not rec:
                continue
            sA, sB = rec["report"]["sides"]["A"], rec["report"]["sides"]["B"]
            out.append({"id": rec["id"], "title": rec.get("title", ""), "created": rec["created"], "t0": rec["report"]["t0"],
                        "t1": rec["report"]["t1"], "kms": rec["report"]["kms"], "systems": rec.get("system_names", []),
                        "isk_A": sA["isk_lost"], "isk_B": sB["isk_lost"], "eff_A": sA["efficiency"]})
        return out[:100]

    # ----- подготовка: системы и время из истории флота -----
    def prefill(self, fleet_id) -> dict:
        rec = self.fleet(int(fleet_id))
        if not rec:
            raise BattleError("Флот не найден в истории.")
        weight = Counter()
        for m in rec.get("members", {}).values():
            for r in m.get("route") or []:
                if r.get("system"):
                    weight[int(r["system"])] += max(1, int(r.get("until", 0)) - int(r.get("at", 0)))
        systems = [s for s, _ in weight.most_common(MAX_SYSTEMS)]
        self.names.resolve(systems)
        end = rec.get("ended_at") or rec.get("polled_at") or rec.get("started_at")
        return {"ok": True, "fleet_id": rec["id"], "systems": [{"id": s, "name": self.names.d.get(str(s), str(s))} for s in systems],
                "start": time.strftime("%Y-%m-%d %H:%M", time.gmtime(rec["started_at"] - 300)),
                "end": time.strftime("%Y-%m-%d %H:%M", time.gmtime(end + 600)), "pilots": len(rec.get("members", {}))}

    def _system_ids(self, systems) -> List[Tuple[int, str]]:
        if isinstance(systems, str):
            systems = [s.strip() for s in re.split(r"[,;\n]+", systems) if s.strip()]
        ids, names = [], []
        for s in systems or []:
            if isinstance(s, int) or str(s).isdigit():
                ids.append(int(s))
            else:
                names.append(str(s))
        if names:
            res = self.get(f"{ESI}/universe/ids/", names) or {}
            found = {r["name"].lower(): r["id"] for r in res.get("systems") or []}
            missing = [n for n in names if n.lower() not in found]
            if missing:
                raise BattleError("Не нашёл систему: " + ", ".join(missing) + ". Пишите как в игре, например «1DQ1-A».")
            ids += [found[n.lower()] for n in names]
        ids = list(dict.fromkeys(ids))
        if not ids:
            raise BattleError("Укажите систему боя.")
        if len(ids) > MAX_SYSTEMS:
            raise BattleError(f"Не больше {MAX_SYSTEMS} систем в одном отчёте.")
        self.names.resolve(ids)
        return [(i, str(self.names.d.get(str(i), i))) for i in ids]

    # ----- сборка -----
    def start(self, body: dict) -> dict:
        if not isinstance(body, dict):
            raise BattleError("Неверный запрос")
        start, end = parse_time(str(body.get("start", ""))), parse_time(str(body.get("end", "")))
        if end <= start:
            raise BattleError("Конец боя должен быть позже начала.")
        if end - start > MAX_SPAN:
            raise BattleError("Один отчёт — не больше суток.")
        if start > time.time() + 600:
            raise BattleError("Начало боя в будущем — проверьте дату (время EVE).")
        fleet_id = body.get("fleet_id")
        systems = self._system_ids(body.get("systems"))
        jid = time.strftime("%Y%m%d_%H%M%S", time.gmtime(start)) + "_" + format(int(time.time() * 1000) % 1_000_000, "x")
        job = {"id": jid, "state": "running", "phase": "Загружаю киллмейлы с zKillboard…", "found": 0, "error": ""}
        with self.lock:
            self.jobs[jid] = job
        params = {"systems": systems, "start": start, "end": end, "fleet_id": fleet_id,
                  "title": str(body.get("title") or "")[:120]}
        threading.Thread(target=self._build, args=(jid, params), name="battle", daemon=True).start()
        return {"ok": True, "job": jid}

    def build_now(self, params: dict, jid: str = "") -> dict:
        """Синхронная сборка (для тестов и фона)."""
        jid = jid or "test_" + format(int(time.time() * 1000) % 10**9, "x")
        job = self.jobs.setdefault(jid, {"id": jid, "state": "running", "phase": "", "found": 0, "error": ""})
        kms: Dict[int, dict] = {}
        for sid, sname in params["systems"]:
            def prog(page, found, _n=sname):
                job.update(phase=f"{_n}: страница {page}", found=len(kms) + found)
            for k in self.loader.system(sid, params["start"], params["end"], prog):
                kms[k["id"]] = k
        kms_list = sorted(kms.values(), key=lambda k: (k["t"], k["id"]))
        if not kms_list:
            raise BattleError("За это время в этих системах на zKillboard нет ни одного киллмейла.")
        job.update(phase="Определяю стороны и считаю…", found=len(kms_list))
        fleet_ids, seeds = [], set()
        if params.get("fleet_id"):
            rec = self.fleet(int(params["fleet_id"]))
            if rec:
                fleet_ids = [int(i) for i in rec.get("members", {})]
        me = self.me()
        char_ent = {}
        for k in kms_list:
            for p in [k["v"]] + k["att"]:
                if p.get("c"):
                    char_ent[p["c"]] = entity(p)
        votes = Counter(char_ent[c] for c in fleet_ids if c in char_ent)
        if votes:
            seeds = {e for e, n in votes.items() if n >= max(1, votes.most_common(1)[0][1] // 4)}
        elif me and me in char_ent:
            seeds = {char_ent[me]}
        elif me:
            try:
                aff = (self.get(f"{ESI}/characters/affiliation/", [int(me)]) or [{}])[0]
                seeds = {entity({"c": me, "co": aff.get("corporation_id"), "a": aff.get("alliance_id")})}
            except (BattleError, IndexError, TypeError):
                pass
        side = assign_sides(kms_list, seeds)
        report = analyze(kms_list, side, fleet_ids)
        job.update(phase="Имена, тикеры и классы кораблей…")
        lookup = self.names.table(report, kms_list)
        rec = {"id": jid, "created": int(time.time()), "title": params.get("title", ""), "params": {
                   "systems": [s for s, _ in params["systems"]], "start": params["start"], "end": params["end"],
                   "fleet_id": params.get("fleet_id")},
               "system_names": [n for _, n in params["systems"]], "seeds": sorted(seeds), "overrides": {},
               "kms": kms_list, "side": side, "report": report, "lookup": lookup}
        self._save(rec)
        try:
            self.on_built({p["s"] for k in kms_list for p in [k["v"]] + k["att"] if p.get("s")}
                          | {a["w"] for k in kms_list for a in k["att"] if a.get("w")})
        except Exception as e:
            log.info("Иконки не запрошены: %s", e)
        job.update(state="done", phase="Готово", battle=jid)
        return rec

    def _build(self, jid: str, params: dict) -> None:
        job = self.jobs[jid]
        try:
            self.build_now(params, jid)
        except BattleError as e:
            job.update(state="error", error=str(e))
        except Exception as e:
            log.exception("Отчёт о бое")
            job.update(state="error", error=f"Не получилось: {e}")

    def job(self, jid: str) -> dict:
        with self.lock:
            j = self.jobs.get(jid)
        return dict(j) if j else {"state": "unknown"}

    def move(self, bid: str, ent: str, to: str) -> dict:
        rec = self.load(bid)
        if not rec:
            raise BattleError("Отчёт не найден.")
        if to not in ("A", "B") or not re.fullmatch(r"(a|c)\d+", ent or ""):
            raise BattleError("Неверный запрос")
        rec["overrides"][ent] = to
        side = assign_sides(rec["kms"], rec["seeds"], rec["overrides"])
        fleet_ids = []
        if rec["params"].get("fleet_id"):
            f = self.fleet(int(rec["params"]["fleet_id"]))
            fleet_ids = [int(i) for i in (f or {}).get("members", {})]
        rec["side"] = side
        rec["report"] = analyze(rec["kms"], side, fleet_ids)
        self._save(rec)
        return self.view(rec)

    @staticmethod
    def view(rec: dict) -> dict:
        """Отчёт для страницы (без сырых киллмейлов)."""
        return {"ok": True, "id": rec["id"], "title": rec.get("title", ""), "created": rec["created"],
                "params": rec["params"], "system_names": rec.get("system_names", []), "overrides": rec.get("overrides", {}),
                "report": rec["report"], "lookup": rec["lookup"],
                "zkill_related": [f"https://zkillboard.com/related/{s}/{time.strftime('%Y%m%d%H00', time.gmtime(rec['report']['t0']))}/"
                                  for s in rec["params"]["systems"]]}
