# -*- coding: utf-8 -*-
"""
ESS и выплаты баунти: журнал кошелька персонажа через ESI — выплаты ESS (доля баунти из банка ESS, приходит раз в ~3 ч)
и реальные выплаты баунти от CCP (раз в 20 минут), чтобы сверять с тем, что насчитано по логам.

Только стандартная библиотека. Вход — общий «данные персонажа» из ядра (eve_sso: отдельное приложение EVE, не флотское):
персонажи подключаются в «Настройках» или кнопкой во вкладке «Баунти», модуль берёт их токены (доступ к кошельку).
Выплаты копятся на этом компьютере: wallet_ess.json (ESI отдаёт журнал за 30 дней — история не пропадает).
"""
import json
import logging
import os
import threading
import time
from typing import Callable, Optional

import eve_sso

log = logging.getLogger("eve_ess")

ESI = eve_sso.ESI
WALLET = "esi-wallet.read_character_wallet.v1"
KINDS = {"ess_escrow_transfer": "ess", "bounty_prizes": "bounty", "bounty_prize": "bounty"}
SYNC_S = 30 * 60                       # ESI кэширует журнал кошелька на час — чаще смысла нет
KEEP_S = 400 * 86400


def _iso(ts: str) -> int:
    """«2026-10-29T12:00:00Z» → unix-время."""
    import calendar
    try:
        return int(calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")))
    except (ValueError, TypeError):
        return 0


class Wallet:
    def __init__(self, data_dir: str, auth, write: Callable, request: Callable = eve_sso.http):
        self.path = os.path.join(data_dir, "wallet_ess.json")
        self.auth, self.write, self.request = auth, write, request
        self.lock = threading.Lock()
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        d = d if isinstance(d, dict) else {}
        self.data = {"chars": d.get("chars") or {}, "names": d.get("names") or {}}
        self.busy = False

    def save(self) -> None:
        with self.lock:
            snap = json.loads(json.dumps(self.data))
        self.write(self.path, snap)

    def sync(self, now: Optional[float] = None) -> dict:
        """Забрать журнал кошелька подключённых персонажей (все страницы), сохранить выплаты ESS и баунти."""
        now = time.time() if now is None else now
        if self.busy:
            return {"ok": False, "message": "Уже обновляю."}
        self.busy = True
        added = 0
        try:
            for cid, c in list(self.auth.chars.items()):
                rec = self.data["chars"].setdefault(str(cid), {"name": c["name"], "entries": {}, "synced": 0, "error": ""})
                rec["name"] = c["name"]
                if not self.auth.has(cid, WALLET):
                    rec["error"] = "нет доступа к кошельку — подключите персонажа заново"
                    continue
                try:
                    tok = self.auth.token(cid)
                    page, pages = 1, 1
                    while page <= pages and page <= 50:
                        rows, hdrs = self.request("GET", f"{ESI}/characters/{cid}/wallet/journal/?datasource=tranquility&page={page}", token=tok)
                        try:
                            pages = int((hdrs or {}).get("X-Pages") or (hdrs or {}).get("x-pages") or 1)
                        except ValueError:
                            pages = 1
                        for r in rows or []:
                            kind = KINDS.get(r.get("ref_type"))
                            if not kind or str(r.get("id")) in rec["entries"]:
                                continue
                            rec["entries"][str(r["id"])] = [_iso(r.get("date", "")), kind, float(r.get("amount") or 0),
                                                            r.get("context_id") if r.get("context_id_type") == "system_id" else None,
                                                            (r.get("description") or "")[:160]]
                            added += 1
                        page += 1
                    rec["synced"], rec["error"] = int(now), ""
                except eve_sso.SsoError as e:
                    rec["error"] = str(e)
                    log.info("ESS: журнал %s не получен: %s", c["name"], e)
                cut = now - KEEP_S
                rec["entries"] = {k: v for k, v in rec["entries"].items() if v[0] >= cut}
            self._names()
            self.save()
        finally:
            self.busy = False
        return {"ok": True, "added": added}

    def _names(self) -> None:
        ids = {v[3] for c in self.data["chars"].values() for v in c["entries"].values() if v[3]} - {int(k) for k in self.data["names"]}
        ids = sorted(ids)[:500]
        if not ids:
            return
        try:
            rows, _ = self.request("POST", f"{ESI}/universe/names/?datasource=tranquility", body=ids)
            for r in rows or []:
                self.data["names"][str(r["id"])] = r.get("name") or str(r["id"])
        except eve_sso.SsoError as e:
            log.info("ESS: названия систем не получены: %s", e)

    def report(self, t0: int, t1: int, who: str = "") -> dict:
        """Выплаты за период [t0, t1): по персонажу (имя как в логах) или по всем."""
        payments, ess, paid, by_day = [], 0.0, 0.0, {}
        for cid, c in self.data["chars"].items():
            if who and c.get("name") != who:
                continue
            for eid, (ts, kind, amount, sys_id, desc) in c["entries"].items():
                if not (t0 <= ts < t1):
                    continue
                day = time.strftime("%Y-%m-%d", time.localtime(ts))
                d = by_day.setdefault(day, {"ess": 0.0, "bounty": 0.0})
                d[kind] += amount
                if kind == "ess":
                    ess += amount
                    payments.append({"t": ts, "who": c.get("name"), "amount": amount, "system": self.data["names"].get(str(sys_id), "") if sys_id else "",
                                     "desc": desc})
                else:
                    paid += amount
        payments.sort(key=lambda p: -p["t"])
        return {"ess": round(ess, 2), "bounty_paid": round(paid, 2), "payments": payments[:300], "count": len(payments), "by_day": by_day}

    def status(self) -> list:
        out = []
        for cid, c in self.auth.chars.items():
            rec = self.data["chars"].get(str(cid)) or {}
            err = rec.get("error") or ("" if self.auth.has(cid, WALLET) else "нет доступа к кошельку — подключите персонажа заново")
            out.append({"id": cid, "name": c["name"], "synced": rec.get("synced") or 0, "error": err})
        return out


def setup(ctx) -> None:
    auth = eve_sso.install(ctx.app, ctx.core.atomic_write_json)
    wallet = Wallet(ctx.data_dir, auth, ctx.core.atomic_write_json)
    auth.on_linked(wallet.sync)                              # новый персонаж — сразу забрать журнал

    def status(qs):
        return {"ok": True, "client_id_set": bool(auth.client_id), "chars": wallet.status(), "busy": wallet.busy}

    def report(qs):
        g = lambda k, d="": (qs.get(k) or [d])[0]
        try:
            t0, t1 = int(g("from", "0")), int(g("to", str(int(time.time()) + 86400)))
        except ValueError:
            return {"ok": False, "message": "Неверный период"}
        return {"ok": True, "linked": bool(auth.chars), **wallet.report(t0, t1, g("who"))}

    def sync(body=None, qs=None):
        if not auth.chars:
            return {"ok": False, "message": "Сначала подключите персонажа."}
        threading.Thread(target=wallet.sync, name="ess-sync", daemon=True).start()
        return {"ok": True, "message": "Обновляю журнал кошелька…"}

    def loop():
        while not ctx.stop.wait(15):
            ids = [c for c in auth.chars if auth.has(c, WALLET)]
            if ids and time.time() - min(wallet.data["chars"].get(str(c), {}).get("synced", 0) for c in ids) >= SYNC_S:
                try:
                    wallet.sync()
                except Exception as e:
                    log.warning("ESS: обновление не удалось: %s", e)
            ctx.stop.wait(60)

    ctx.get("/api/ess/status", status)
    ctx.get("/api/ess", report)
    ctx.post("/api/ess/sync", sync)
    ctx.thread(loop, "ess")
