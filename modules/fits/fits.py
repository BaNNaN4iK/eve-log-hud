# -*- coding: utf-8 -*-
"""
Фиты альянса как дерево прокачки: плашка корабля, под ней — на сколько процентов изучены нужные навыки.

Только стандартная библиотека. Фиты и доктрины — выгрузка из Alliance Auth (плагин «Фиты и навыки», скрипт
build_fits_data.py) в файл fits_data.json в папке данных приложения (это внутренние доктрины альянса — в модуль и в
публичный репозиторий не входят; файл можно загрузить кнопкой на вкладке). Навыки и очередь обучения персонажей — ESI
через общий вход «Персонажи EVE» (eve_sso: esi-skills.read_skills.v1, esi-skills.read_skillqueue.v1).
Процент — в очках навыков (SP): уровень V весит намного больше уровня I.
"""
import json
import logging
import math
import os
import threading
import time
from typing import Dict, Optional

import eve_sso

log = logging.getLogger("eve_fits")

SKILLS = "esi-skills.read_skills.v1"
QUEUE = "esi-skills.read_skillqueue.v1"
SYNC_S = 30 * 60                       # ESI кэширует навыки на 2 минуты, очередь — на 2; чаще получаса не нужно
SP_PER_MINUTE = 30                     # средняя скорость обучения для оценки времени (без имплантов ~27–33)


def sp_for(rank: float, level: int) -> int:
    """Сколько SP нужно, чтобы выучить навык ранга rank до уровня level."""
    if level <= 0:
        return 0
    return int(math.ceil(250 * float(rank) * (32 ** ((level - 1) / 2))))


def check(required: Dict[int, int], minimum: set, have: Optional[Dict[int, int]], queue: Dict[int, int], skills: dict) -> dict:
    """Готовность к фиту: процент по SP, хватает ли минимума (сесть и поставить модули), чего не хватает, сколько учить."""
    if have is None:
        return {"known": False, "pct": None, "ok": False, "can_fly": False, "missing": [], "minutes_left": None}
    need_sp = done_sp = 0
    missing, can_fly = [], True
    for sid, need in required.items():
        name, rank = (skills.get(str(sid)) or [str(sid), 1])[:2]
        got = min(have.get(sid, 0), need)
        full = sp_for(rank, need)
        need_sp += full
        done_sp += sp_for(rank, got)
        if got < need:
            if sid in minimum:
                can_fly = False
            missing.append({"skill_id": sid, "name": name, "need": need, "have": have.get(sid, 0), "queued": min(queue.get(sid, 0), 5),
                            "minimum": sid in minimum, "sp_left": full - sp_for(rank, got)})
    missing.sort(key=lambda m: (not m["minimum"], m["sp_left"]))           # сначала то, без чего не сесть; короткие — раньше
    pct = 100 if not need_sp else int(100 * done_sp / need_sp)
    if missing and pct >= 100:
        pct = 99                                                        # не хватает уровня — не показываем «100%»
    sp_left = need_sp - done_sp
    return {"known": True, "pct": pct, "ok": not missing, "can_fly": can_fly, "missing": missing, "sp_left": sp_left,
            "minutes_left": int(sp_left / SP_PER_MINUTE)}


def fit_skills(f: dict) -> Dict[int, int]:
    """Минимум + план фита: {навык: уровень} (по каждому навыку — больший уровень)."""
    req = {int(k): int(v) for k, v in (f.get("required") or {}).items()}
    for k, v in (f.get("plan") or {}).items():
        req[int(k)] = max(req.get(int(k), 0), int(v))
    return req


def total_sp(req: Dict[int, int], skills: dict) -> int:
    return sum(sp_for((skills.get(str(s)) or ["", 1])[1], lv) for s, lv in req.items())


def extra_sp(req: Dict[int, int], base: Dict[int, int], skills: dict) -> int:
    """Сколько SP доучить для req, если навыки base уже выучены."""
    out = 0
    for s, lv in req.items():
        rank = (skills.get(str(s)) or ["", 1])[1]
        out += sp_for(rank, lv) - sp_for(rank, min(lv, base.get(s, 0)))
    return out


def progression(fits: list, skills: dict) -> list:
    """Дерево прокачки фитов: первым — фит, который дешевле всего выучить с нуля; дальше на каждом шаге добавляется фит,
    который проще всего докачать после одного из уже поставленных (больше всего общих навыков). Каждый фит висит на том,
    после которого его докачать дешевле. → [{"id", "parent", "extra", "total", "depth"}] в порядке добавления."""
    reqs = {f["id"]: fit_skills(f) for f in fits}
    totals = {i: total_sp(r, skills) for i, r in reqs.items()}
    left = set(reqs)
    if not left:
        return []
    root = min(left, key=lambda i: (totals[i], str(i)))
    out, depth = [{"id": root, "parent": None, "extra": totals[root], "total": totals[root], "depth": 0}], {root: 0}
    left.discard(root)
    best = {i: (extra_sp(reqs[i], reqs[root], skills), root) for i in left}   # дешевле всего от уже поставленных
    while left:
        i = min(left, key=lambda k: (best[k][0], totals[k], str(k)))
        cost, parent = best.pop(i)
        left.discard(i)
        depth[i] = depth[parent] + 1
        out.append({"id": i, "parent": parent, "extra": cost, "total": totals[i], "depth": depth[i]})
        for k in left:
            c = extra_sp(reqs[k], reqs[i], skills)
            if c < best[k][0]:
                best[k] = (c, i)
    return out


def load_fits(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("fits"), list) else {}
    except (OSError, ValueError):
        return {}


def valid_dataset(d) -> Optional[str]:
    """None — файл фитов годится; иначе — что не так."""
    if not isinstance(d, dict) or not isinstance(d.get("fits"), list) or not isinstance(d.get("skills"), dict):
        return "Это не файл фитов: нужен fits_data.json, выгруженный из Alliance Auth."
    for f in d["fits"][:2000]:
        if not isinstance(f, dict) or not isinstance(f.get("ship_type_id"), int) or not isinstance(f.get("required", {}), dict):
            return "В файле фитов неверная запись фита."
    return None


class Skills:
    """Навыки и очередь обучения подключённых персонажей (ESI), с кэшем на диске."""

    def __init__(self, data_dir: str, auth, write, request=eve_sso.http):
        self.path = os.path.join(data_dir, "fits_skills.json")
        self.auth, self.write, self.request = auth, write, request
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}
        self.busy = False

    def sync(self, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        if self.busy:
            return
        self.busy = True
        try:
            for cid, c in list(self.auth.chars.items()):
                rec = self.data.setdefault(str(cid), {"name": c["name"], "skills": {}, "queue": {}, "synced": 0, "error": ""})
                rec["name"] = c["name"]
                if not self.auth.has(cid, SKILLS):
                    rec["error"] = "нет доступа к навыкам — отметьте «навыки» в «Персонажах EVE» и подключите персонажа заново"
                    continue
                try:
                    tok = self.auth.token(cid)
                    sk, _ = self.request("GET", f"{eve_sso.ESI}/characters/{cid}/skills/?datasource=tranquility", token=tok)
                    rec["skills"] = {str(s["skill_id"]): int(s.get("active_skill_level") or s.get("trained_skill_level") or 0)
                                     for s in (sk or {}).get("skills") or []}
                    rec["total_sp"] = (sk or {}).get("total_sp")
                    queue = {}
                    if self.auth.has(cid, QUEUE):
                        q, _ = self.request("GET", f"{eve_sso.ESI}/characters/{cid}/skillqueue/?datasource=tranquility", token=tok)
                        for e in q or []:
                            sid = str(e.get("skill_id"))
                            queue[sid] = max(queue.get(sid, 0), int(e.get("finished_level") or 0))
                    rec["queue"], rec["synced"], rec["error"] = queue, int(now), ""
                except eve_sso.SsoError as e:
                    rec["error"] = str(e)
                    log.info("Фиты: навыки %s не получены: %s", c["name"], e)
            self.write(self.path, self.data)
        finally:
            self.busy = False

    def of(self, cid) -> tuple:
        rec = self.data.get(str(cid))
        if not rec or not rec.get("synced"):
            return None, {}
        return {int(k): v for k, v in rec["skills"].items()}, {int(k): v for k, v in (rec.get("queue") or {}).items()}


def setup(ctx) -> None:
    auth = eve_sso.install(ctx.app, ctx.core.atomic_write_json)
    data_path = os.path.join(ctx.data_dir, "fits_data.json")
    state = {"data": load_fits(data_path)}
    sk = Skills(ctx.data_dir, auth, ctx.core.atomic_write_json)
    auth.on_linked(sk.sync)
    icons_done = {"v": False}

    def fits(qs):
        d = state["data"]
        chars = []
        for cid, c in auth.chars.items():
            rec = sk.data.get(str(cid)) or {}
            chars.append({"id": cid, "name": c["name"], "skills": auth.has(cid, SKILLS), "synced": rec.get("synced") or 0,
                          "error": rec.get("error") or ("" if auth.has(cid, SKILLS) else "нет доступа к навыкам"), "total_sp": rec.get("total_sp")})
        try:
            want = int((qs.get("char") or ["0"])[0])
        except ValueError:
            want = 0
        cid = want if want in auth.chars else (next(iter(auth.chars)) if auth.chars else 0)
        have, queue = sk.of(cid) if cid else (None, {})
        skills = d.get("skills") or {}
        ready = {}
        for f in d.get("fits") or []:
            ready[str(f["id"])] = check(fit_skills(f), {int(k) for k in (f.get("required") or {})}, have, queue, skills)
        if state.get("trees_for") is not d:                    # деревья прокачки по доктринам — не зависят от персонажа
            groups = {}
            for f in d.get("fits") or []:
                for doc in f.get("doctrines") or ["none"]:
                    groups.setdefault(str(doc), []).append(f)
            state["trees"] = {k: progression(v, skills) for k, v in groups.items()}
            state["trees_for"] = d
        if ctx.online is not None and not icons_done["v"] and d.get("fits"):
            icons_done["v"] = True
            ids = sorted({f["ship_type_id"] for f in d["fits"]} | {i["type_id"] for f in d["fits"] for i in f.get("items") or [] if i.get("type_id")})
            threading.Thread(target=lambda: [ctx.online.fetch_icon(i) for i in ids], name="fits-icons", daemon=True).start()
        return {"ok": True, "has_data": bool(d.get("fits")), "built": d.get("built"), "source": d.get("source", ""),
                "doctrines": d.get("doctrines") or [], "fits": d.get("fits") or [], "skills": skills,
                "characters": chars, "char": cid, "ready": ready, "busy": sk.busy, "client_id_set": bool(auth.client_id),
                "trees": state.get("trees") or {}}

    def refresh(body=None, qs=None):
        if not auth.chars:
            return {"ok": False, "message": "Подключите персонажа: «Настройки» → «Персонажи EVE»."}
        threading.Thread(target=sk.sync, name="fits-skills", daemon=True).start()
        return {"ok": True, "message": "Обновляю навыки…"}

    def import_data(body, qs=None):
        d = (body or {}).get("data") if isinstance(body, dict) else None
        err = valid_dataset(d)
        if err:
            return {"ok": False, "message": err}
        ctx.core.atomic_write_json(data_path, d)
        state["data"] = d
        icons_done["v"] = False
        return {"ok": True, "message": f"Загружено фитов: {len(d['fits'])}, доктрин: {len(d.get('doctrines') or [])}."}

    def loop():
        while not ctx.stop.wait(20):
            ids = [c for c in auth.chars if auth.has(c, SKILLS)]
            if ids and time.time() - min((sk.data.get(str(c)) or {}).get("synced", 0) for c in ids) >= SYNC_S:
                try:
                    sk.sync()
                except Exception as e:
                    log.warning("Фиты: обновление навыков не удалось: %s", e)
            ctx.stop.wait(60)

    ctx.get("/api/fits", fits)
    ctx.post("/api/fits/refresh", refresh)
    ctx.post("/api/fits/import", import_data)
    ctx.thread(loop, "fits")
