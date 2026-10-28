# -*- coding: utf-8 -*-
"""
ESS и выплаты баунти: журнал кошелька персонажа через ESI — выплаты ESS (доля баунти из банка ESS, приходит раз в ~3 ч)
и реальные выплаты баунти от CCP (раз в 20 минут), чтобы сверять с тем, что насчитано по логам.

Только стандартная библиотека. Вход через EVE — свой, отдельный от «Флота», со своим доступом:
esi-wallet.read_character_wallet.v1 (только чтение кошелька). Можно подключить несколько персонажей.
Всё хранится на этом компьютере, в папке данных трекера:
  esi_token_wallet.json — персонажи и их токены обновления (Windows: зашифрованы DPAPI; Linux: файл с правами 600)
  wallet_ess.json       — выплаты ESS и баунти из журнала кошелька, названия систем (ESI отдаёт журнал за 30 дней —
                          копим у себя, чтобы история не пропадала)
"""
import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

log = logging.getLogger("eve_ess")

SSO = "https://login.eveonline.com"
ESI = "https://esi.evetech.net/latest"
ALLOWED_HOSTS = {"login.eveonline.com", "esi.evetech.net"}
SCOPES = ["esi-wallet.read_character_wallet.v1"]
# То же приложение EVE, что у «Флота» (Client ID не секретный: вход по PKCE). Адрес возврата общий — /sso/callback;
# в настройках приложения на developers.eveonline.com должен быть включён доступ esi-wallet.read_character_wallet.v1.
BUILTIN_CLIENT_ID = "423ee1a0b115448f9e5ccf6b1514512d"
KINDS = {"ess_escrow_transfer": "ess", "bounty_prizes": "bounty", "bounty_prize": "bounty"}
SYNC_S = 30 * 60                       # ESI кэширует журнал кошелька на час — чаще смысла нет
KEEP_S = 400 * 86400


class EssError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def http(method: str, url: str, *, token: str = "", form: Optional[dict] = None, body=None, timeout: float = 20) -> Tuple[object, dict]:
    """Запрос к SSO или ESI → (JSON, заголовки). Другие адреса запрещены."""
    host = urllib.parse.urlsplit(url).hostname
    if host not in ALLOWED_HOSTS or not url.startswith("https://"):
        raise EssError(f"Адрес не разрешён: {host}")
    headers = {"Accept": "application/json", "User-Agent": "EVELogWatcher ess"}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "null"), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8"))
            detail = detail.get("error_description") or detail.get("error") or ""
        except Exception:
            detail = ""
        raise EssError(f"{host} ответил {e.code}" + (f": {detail}" if detail else ""), e.code) from e
    except (urllib.error.URLError, OSError) as e:
        raise EssError(f"нет связи с {host}: {getattr(e, 'reason', e)}") from e
    except ValueError as e:
        raise EssError(f"{host} вернул не JSON") from e


def protect(text: str) -> str:
    """Зашифровать строку для текущего пользователя Windows (DPAPI). Файл бесполезен на другом компьютере."""
    try:
        import ctypes
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [("n", wintypes.DWORD), ("p", ctypes.POINTER(ctypes.c_char))]
        raw = text.encode("utf-8")
        src, dst = Blob(len(raw), ctypes.cast(ctypes.create_string_buffer(raw, len(raw)), ctypes.POINTER(ctypes.c_char))), Blob()
        if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(dst)):
            raise OSError("CryptProtectData")
        out = ctypes.string_at(dst.p, dst.n)
        ctypes.windll.kernel32.LocalFree(dst.p)
        return "dpapi:" + base64.b64encode(out).decode()
    except Exception:                                        # не Windows — храним как есть (файл с правами 600)
        return "plain:" + text


def unprotect(stored: str) -> str:
    if stored.startswith("plain:"):
        return stored[6:]
    if not stored.startswith("dpapi:"):
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [("n", wintypes.DWORD), ("p", ctypes.POINTER(ctypes.c_char))]
        raw = base64.b64decode(stored[6:])
        src, dst = Blob(len(raw), ctypes.cast(ctypes.create_string_buffer(raw, len(raw)), ctypes.POINTER(ctypes.c_char))), Blob()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(dst)):
            return ""
        out = ctypes.string_at(dst.p, dst.n)
        ctypes.windll.kernel32.LocalFree(dst.p)
        return out.decode("utf-8")
    except Exception:
        return ""


def _read(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _iso(ts: str) -> int:
    """«2026-10-29T12:00:00Z» → unix-время."""
    import calendar
    try:
        return int(calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")))
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Вход через EVE: несколько персонажей, только доступ к кошельку
# ---------------------------------------------------------------------------

class Auth:
    def __init__(self, data_dir: str, client_id: str, write: Callable, request: Callable = http):
        self.path = os.path.join(data_dir, "esi_token_wallet.json")
        self.client_id = (client_id or "").strip()
        self.write, self.request = write, request
        self.lock = threading.RLock()
        self.pending: Dict[str, dict] = {}                   # state → {verifier, redirect, at}
        self.access: Dict[int, Tuple[str, float]] = {}
        d = _read(self.path, {})
        self.chars: Dict[int, dict] = {}
        for cid, c in ((d.get("chars") or {}) if isinstance(d, dict) else {}).items():
            ref = unprotect(c.get("refresh", ""))
            if ref:
                self.chars[int(cid)] = {"name": c.get("name") or str(cid), "refresh": ref}

    def owns(self, state: str) -> bool:
        with self.lock:
            return state in self.pending

    def _save(self) -> None:
        self.write(self.path, {"chars": {str(k): {"name": v["name"], "refresh": protect(v["refresh"])} for k, v in self.chars.items()}})
        if os.name != "nt":
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    def login_url(self, redirect: str) -> str:
        if not self.client_id:
            raise EssError("Не задан Client ID приложения EVE.")
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = "ess-" + secrets.token_urlsafe(16)
        with self.lock:
            now = time.time()
            self.pending = {k: v for k, v in self.pending.items() if now - v["at"] < 900}
            self.pending[state] = {"verifier": verifier, "redirect": redirect, "at": now}
        q = urllib.parse.urlencode({"response_type": "code", "redirect_uri": redirect, "client_id": self.client_id,
                                    "scope": " ".join(SCOPES), "code_challenge": challenge,
                                    "code_challenge_method": "S256", "state": state})
        return f"{SSO}/v2/oauth/authorize/?{q}"

    def _store(self, tok: dict, cid_hint: Optional[int] = None) -> Tuple[int, str]:
        access = tok.get("access_token") or ""
        try:                                                 # кто вошёл и какие права — из тела токена (получен от CCP по TLS)
            part = access.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            cid = int(str(claims["sub"]).rsplit(":", 1)[1])
            name = claims.get("name") or str(cid)
            scp = claims.get("scp") or []
            scp = [scp] if isinstance(scp, str) else scp
        except Exception as e:
            raise EssError("EVE вернул токен, который не удалось разобрать.") from e
        if SCOPES[0] not in scp:
            raise EssError("EVE не дал доступ к кошельку: в приложении на developers.eveonline.com включите "
                           "esi-wallet.read_character_wallet.v1 и войдите снова.")
        with self.lock:
            old = self.chars.get(cid, {})
            self.chars[cid] = {"name": name, "refresh": tok.get("refresh_token") or old.get("refresh", "")}
            self.access[cid] = (access, time.time() + float(tok.get("expires_in") or 0) - 60)
            self._save()
        return cid, name

    def finish(self, code: str, state: str) -> str:
        with self.lock:
            p = self.pending.pop(state or "", None)
        if p is None or not code:
            raise EssError("Вход устарел или начат не из этого приложения. Нажмите «Подключить персонажа» ещё раз.")
        tok, _ = self.request("POST", f"{SSO}/v2/oauth/token", form={
            "grant_type": "authorization_code", "code": code, "client_id": self.client_id, "code_verifier": p["verifier"]})
        return self._store(tok)[1]

    def token(self, cid: int) -> str:
        with self.lock:
            c = self.chars.get(cid)
            if not c:
                raise EssError("Персонаж не подключён.")
            acc = self.access.get(cid)
            if acc and time.time() < acc[1]:
                return acc[0]
            try:
                tok, _ = self.request("POST", f"{SSO}/v2/oauth/token", form={
                    "grant_type": "refresh_token", "refresh_token": c["refresh"], "client_id": self.client_id})
            except EssError as e:
                if e.status in (400, 401):                   # доступ отозван — персонажа нужно подключить заново
                    self.remove(cid)
                    raise EssError(f"{c['name']}: доступ к кошельку отозван или устарел — подключите персонажа заново.", e.status) from e
                raise
            self._store(tok)
            return self.access[cid][0]

    def remove(self, cid: int) -> None:
        with self.lock:
            self.chars.pop(cid, None)
            self.access.pop(cid, None)
            self._save()


# ---------------------------------------------------------------------------
# Журнал кошелька: выплаты ESS и баунти
# ---------------------------------------------------------------------------

class Wallet:
    def __init__(self, data_dir: str, auth: Auth, write: Callable, request: Callable = http):
        self.path = os.path.join(data_dir, "wallet_ess.json")
        self.auth, self.write, self.request = auth, write, request
        self.lock = threading.Lock()
        d = _read(self.path, {})
        d = d if isinstance(d, dict) else {}
        self.data = {"chars": d.get("chars") or {}, "names": d.get("names") or {}}
        self.busy = False

    def save(self) -> None:
        with self.lock:
            snap = json.loads(json.dumps(self.data))
        self.write(self.path, snap)

    def sync(self, now: Optional[float] = None) -> dict:
        """Забрать журнал кошелька всех подключённых персонажей (все страницы), сохранить выплаты ESS и баунти."""
        now = time.time() if now is None else now
        if self.busy:
            return {"ok": False, "message": "Уже обновляю."}
        self.busy = True
        added = 0
        try:
            for cid, c in list(self.auth.chars.items()):
                rec = self.data["chars"].setdefault(str(cid), {"name": c["name"], "entries": {}, "synced": 0, "error": ""})
                rec["name"] = c["name"]
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
                except EssError as e:
                    rec["error"] = str(e)
                    log.info("ESS: журнал %s не получен: %s", c["name"], e)
                cut = now - KEEP_S
                rec["entries"] = {k: v for k, v in rec["entries"].items() if v[0] >= cut}
            for cid in list(self.data["chars"]):                 # отключённые персонажи — история остаётся (помечаем)
                self.data["chars"][cid]["linked"] = int(cid) in self.auth.chars
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
        except EssError as e:
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
            out.append({"id": cid, "name": c["name"], "synced": rec.get("synced") or 0, "error": rec.get("error") or ""})
        return out


CALLBACK_PAGE = ("<!doctype html><meta charset='utf-8'><title>EVE Log HUD</title><body style=\"margin:0;background:#0f1115;"
                 "color:#e8edf2;font:16px 'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center;"
                 "height:100vh\"><div style='max-width:540px;text-align:center'><div style='font-size:22px;color:%s;"
                 "margin-bottom:10px'>%s</div>%s<div style='color:#9aa7b4;font-size:13px;margin-top:14px'>Эту вкладку "
                 "можно закрыть.</div></div></body>")


def setup(ctx) -> None:
    import html
    import webbrowser
    from modkit import Html
    auth = Auth(ctx.data_dir, ctx.cfg.get("esi_client_id") or BUILTIN_CLIENT_ID, ctx.core.atomic_write_json)
    wallet = Wallet(ctx.data_dir, auth, ctx.core.atomic_write_json)
    redirect = f"http://localhost:{ctx.port}/sso/callback"

    def callback(qs):
        if qs.get("error"):
            ok, text = False, "EVE отклонил вход: " + str(qs["error"][0])[:200]
        else:
            try:
                name = auth.finish((qs.get("code") or [""])[0], (qs.get("state") or [""])[0])
                ok, text = True, f"Персонаж {name} подключён к выплатам ESS. Вернитесь в приложение — вкладка «Баунти»."
                threading.Thread(target=wallet.sync, name="ess-sync", daemon=True).start()
            except EssError as e:
                ok, text = False, str(e)
        return Html(200 if ok else 400, CALLBACK_PAGE % ("#18bc9c" if ok else "#e74c3c", "Готово" if ok else "Вход не выполнен", html.escape(text)))

    def status(qs):
        return {"ok": True, "client_id_set": bool(auth.client_id), "chars": wallet.status(), "busy": wallet.busy,
                "scope": " ".join(SCOPES), "callback": redirect}

    def report(qs):
        g = lambda k, d="": (qs.get(k) or [d])[0]
        try:
            t0, t1 = int(g("from", "0")), int(g("to", str(int(time.time()) + 86400)))
        except ValueError:
            return {"ok": False, "message": "Неверный период"}
        return {"ok": True, "linked": bool(auth.chars), **wallet.report(t0, t1, g("who"))}

    def login(body=None, qs=None):
        try:
            url = auth.login_url(redirect)
        except EssError as e:
            return {"ok": False, "message": str(e)}
        try:
            webbrowser.open(url)
        except Exception as e:
            return {"ok": False, "message": f"Не удалось открыть браузер: {e}"}
        return {"ok": True, "message": "Открыл вход EVE в браузере. Войдите персонажем, который фармит, — доступ только к кошельку (чтение)."}

    def logout(body, qs=None):
        try:
            cid = int((body or {}).get("id"))
        except (TypeError, ValueError, AttributeError):
            return {"ok": False, "message": "Неверный запрос"}
        auth.remove(cid)
        return {"ok": True, "message": "Персонаж отключён, его токен удалён с этого компьютера. Сохранённые выплаты остались."}

    def sync(body=None, qs=None):
        if not auth.chars:
            return {"ok": False, "message": "Сначала подключите персонажа."}
        threading.Thread(target=wallet.sync, name="ess-sync", daemon=True).start()
        return {"ok": True, "message": "Обновляю журнал кошелька…"}

    def loop():
        while not ctx.stop.wait(15):
            if auth.chars and time.time() - min([wallet.data["chars"].get(str(c), {}).get("synced", 0) for c in auth.chars] or [0]) >= SYNC_S:
                try:
                    wallet.sync()
                except Exception as e:
                    log.warning("ESS: обновление не удалось: %s", e)
            ctx.stop.wait(60)

    ctx.sso(auth.owns, callback)
    ctx.get("/api/ess/status", status)
    ctx.get("/api/ess", report)
    ctx.post("/api/ess/login", login)
    ctx.post("/api/ess/logout", logout)
    ctx.post("/api/ess/sync", sync)
    ctx.thread(loop, "ess")
