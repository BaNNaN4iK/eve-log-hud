# -*- coding: utf-8 -*-
"""
Флот без Alliance Auth: вход через EVE (SSO, PKCE — без секрета приложения) и чтение состава флота из ESI.

Только стандартная библиотека. Работает, когда вошедший персонаж — босс флота: состав флота игра отдаёт
только боссу. Всё хранится на этом компьютере, в папке данных трекера:
  esi_token.json   — кто вошёл и токен обновления (Windows: зашифрован DPAPI; Linux: файл с правами 600)
  fleet_names.json — названия кораблей, систем и имена пилотов (кэш)
  fleets/<id>.json — по файлу на флот: состав, время во флоте, маршруты, отметки ФК
  battles/<id>.json — отчёты о боях по киллмейлам (battle.py)

Ответы current()/get()/list() имеют тот же вид, что у плагина Fleet Watch, поэтому страница и оверлей
работают одинаково с обоими источниками.
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
from collections import Counter
from typing import Callable, Dict, List, Optional

log = logging.getLogger("eve_fleet")

SSO = "https://login.eveonline.com"
ESI = "https://esi.evetech.net/latest"
ALLOWED_HOSTS = {"login.eveonline.com", "esi.evetech.net"}
SCOPES = ["esi-fleets.read_fleet.v1"]
# Client ID приложения, зарегистрированного автором программы на developers.eveonline.com. Он не секретный
# (вход идёт по схеме PKCE, без секрета), поэтому вшит в программу: пилоту остаётся нажать «Подключить аккаунт EVE».
# Callback URL приложения: http://localhost:47322/sso/callback. В config.json можно задать свой (esi_client_id).
BUILTIN_CLIENT_ID = "423ee1a0b115448f9e5ccf6b1514512d"
POLL_S = 10                 # ESI обновляет состав флота раз в 5 секунд
MAX_ERRORS = 30             # столько опросов подряд без ответа — и отслеживание останавливается (5 минут)
MARKS = ("", "good", "warn", "bad")


class FleetError(Exception):
    """Ошибка с понятным пользователю текстом."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# HTTP и хранение секрета
# ---------------------------------------------------------------------------

def http(method: str, url: str, *, token: str = "", form: Optional[dict] = None, body=None, timeout: float = 15):
    """Запрос к SSO или ESI. Возвращает разобранный JSON. Другие адреса запрещены."""
    host = urllib.parse.urlsplit(url).hostname
    if host not in ALLOWED_HOSTS or not url.startswith("https://"):
        raise FleetError(f"Адрес не разрешён: {host}")
    headers = {"Accept": "application/json", "User-Agent": "EVELogWatcher fleet"}
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
            return json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8"))
            detail = detail.get("error_description") or detail.get("error") or ""
        except Exception:
            detail = ""
        raise FleetError(f"{host} ответил {e.code}" + (f": {detail}" if detail else ""), e.code) from e
    except (urllib.error.URLError, OSError) as e:
        raise FleetError(f"нет связи с {host}: {getattr(e, 'reason', e)}") from e
    except ValueError as e:
        raise FleetError(f"{host} вернул не JSON") from e


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
    except Exception:                                        # не Windows (тесты) — храним как есть
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


def _write(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    replace_file(tmp, path)


def _read(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Вход через EVE
# ---------------------------------------------------------------------------

class EsiAuth:
    """Вход персонажа через EVE SSO по схеме PKCE: секрет приложения не нужен и нигде не хранится."""

    def __init__(self, data_dir: str, client_id: str = "", request: Callable = http):
        self.path = os.path.join(data_dir, "esi_token.json")
        self.client_id = (client_id or "").strip()
        self.request = request
        self.lock = threading.RLock()
        self.pending: Dict[str, dict] = {}                   # state → {verifier, redirect, at}
        self.access, self.access_until = "", 0.0
        d = _read(self.path, {})
        self.character_id = d.get("character_id") if isinstance(d, dict) else None
        self.character = d.get("character", "") if isinstance(d, dict) else ""
        self.refresh = unprotect(d.get("refresh", "")) if isinstance(d, dict) else ""
        if not self.refresh:
            self.character_id, self.character = None, ""

    @property
    def logged_in(self) -> bool:
        return bool(self.refresh and self.character_id and self.client_id)

    def status(self) -> dict:
        return {"client_id_set": bool(self.client_id), "logged_in": self.logged_in,
                "character": self.character if self.logged_in else "", "character_id": self.character_id if self.logged_in else None}

    def login_url(self, redirect: str) -> str:
        if not self.client_id:
            raise FleetError("Не задан Client ID приложения EVE.")
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        with self.lock:
            now = time.time()
            self.pending = {k: v for k, v in self.pending.items() if now - v["at"] < 900}
            self.pending[state] = {"verifier": verifier, "redirect": redirect, "at": now}
        q = urllib.parse.urlencode({"response_type": "code", "redirect_uri": redirect, "client_id": self.client_id,
                                    "scope": " ".join(SCOPES), "code_challenge": challenge,
                                    "code_challenge_method": "S256", "state": state})
        return f"{SSO}/v2/oauth/authorize/?{q}"

    def _store(self, tok: dict) -> None:
        self.access = tok.get("access_token") or ""
        self.access_until = time.time() + float(tok.get("expires_in") or 0) - 60
        if tok.get("refresh_token"):
            self.refresh = tok["refresh_token"]
        try:                                                 # кто вошёл — из тела токена (получен напрямую от CCP по TLS)
            part = self.access.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            self.character_id = int(str(claims["sub"]).rsplit(":", 1)[1])
            self.character = claims.get("name") or str(self.character_id)
        except Exception as e:
            raise FleetError("EVE вернул токен, который не удалось разобрать.") from e
        _write(self.path, {"character_id": self.character_id, "character": self.character, "refresh": protect(self.refresh)})
        if os.name != "nt":                                  # Linux: шифрования Windows нет — файл читает только владелец
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    def finish(self, code: str, state: str) -> str:
        """Вторая половина входа (после возврата из браузера). Возвращает имя персонажа."""
        with self.lock:
            p = self.pending.pop(state or "", None)
            if p is None or not code:
                raise FleetError("Вход устарел или начат не из этого приложения. Нажмите «Войти через EVE» ещё раз.")
            tok = self.request("POST", f"{SSO}/v2/oauth/token", form={
                "grant_type": "authorization_code", "code": code, "client_id": self.client_id, "code_verifier": p["verifier"]})
            self._store(tok)
            return self.character

    def token(self) -> str:
        """Действующий токен доступа (обновляется сам)."""
        with self.lock:
            if not self.logged_in:
                raise FleetError("Вход через EVE не выполнен.")
            if self.access and time.time() < self.access_until:
                return self.access
            try:
                tok = self.request("POST", f"{SSO}/v2/oauth/token", form={
                    "grant_type": "refresh_token", "refresh_token": self.refresh, "client_id": self.client_id})
            except FleetError as e:
                if e.status in (400, 401):                   # разрешение отозвано — нужен новый вход
                    self.logout()
                    raise FleetError("Разрешение отозвано или устарело. Войдите через EVE заново.", e.status) from e
                raise
            self._store(tok)
            return self.access

    def logout(self) -> None:
        with self.lock:
            self.refresh, self.access, self.character_id, self.character = "", "", None, ""
            try:
                os.remove(self.path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Флот
# ---------------------------------------------------------------------------

def _timeline(m: dict) -> list:
    """Маршрут пилота → [(с, по, система)]: отрезок длится до начала следующего, последний — до last_seen отрезка."""
    route = m.get("route") or []
    out = []
    for i, seg in enumerate(route):
        end = route[i + 1]["at"] if i + 1 < len(route) else seg["until"]
        if end > seg["at"]:
            out.append((seg["at"], end, seg["system"]))
    return out


def away_episodes(tl: list, boss_tl: list) -> list:
    """[(с, по)] — когда пилот был не в одной системе с боссом (соседние отрезки склеены)."""
    raw = []
    for ms, me, msys in tl:
        for bs, be, bsys in boss_tl:
            a, b = max(ms, bs), min(me, be)
            if b > a and msys != bsys:
                raw.append([a, b])
    raw.sort()
    merged: List[list] = []
    for r in raw:
        if merged and r[0] - merged[-1][1] <= 1:
            merged[-1][1] = max(merged[-1][1], r[1])
        else:
            merged.append(r)
    return merged


class LocalFleet:
    """Отслеживание своего флота прямо из приложения: опрос ESI, история, отметки."""

    def __init__(self, data_dir: str, client_id: str = "", request: Callable = http):
        self.dir = os.path.join(data_dir, "fleets")
        self.names_path = os.path.join(data_dir, "fleet_names.json")
        self.request = request
        self.auth = EsiAuth(data_dir, client_id, request)
        self.lock = threading.RLock()
        self.names: Dict[str, str] = _read(self.names_path, {})
        self.cur: Optional[dict] = None
        self.errors = 0
        self.last_error = ""
        self._stop = threading.Event()
        os.makedirs(self.dir, exist_ok=True)
        for rec in self._all():                              # приложение закрыли при идущем флоте — продолжим следить
            if rec.get("is_active"):
                self.cur = rec

    # ----- хранение -----
    def _file(self, fid) -> str:
        return os.path.join(self.dir, f"{int(fid)}.json")

    def _save(self, rec: dict) -> None:
        _write(self._file(rec["id"]), rec)

    def _all(self) -> list:
        out = []
        try:
            files = [f for f in os.listdir(self.dir) if f.endswith(".json")]
        except OSError:
            return out
        for f in files:
            rec = _read(os.path.join(self.dir, f), None)
            if isinstance(rec, dict) and "id" in rec and "members" in rec:
                out.append(rec)
        out.sort(key=lambda r: -r.get("started_at", 0))
        return out

    # ----- ESI -----
    def _esi(self, method: str, path: str, body=None):
        return self.request(method, ESI + path, token=self.auth.token(), body=body)

    def _resolve(self, ids) -> None:
        """Имена для ID (пилоты, корабли, системы) — одним запросом, с кэшем."""
        need = sorted({int(i) for i in ids if i and str(i) not in self.names})
        for i in range(0, len(need), 500):
            try:
                rows = self.request("POST", ESI + "/universe/names/", body=need[i:i + 500]) or []
            except FleetError as e:
                log.info("Имена не получены: %s", e)
                return
            for r in rows:
                self.names[str(r["id"])] = r["name"]
        if need:
            _write(self.names_path, self.names)

    def _name(self, ident, fallback: str = "?") -> str:
        return self.names.get(str(ident), fallback) if ident else fallback

    # ----- отслеживание -----
    def start(self, now: Optional[float] = None) -> dict:
        """Кнопка «Отслеживать мой флот»."""
        now = time.time() if now is None else now
        with self.lock:
            if not self.auth.logged_in:
                return {"ok": False, "reason": "no_login", "message": "Сначала войдите через EVE."}
            if self.cur is not None:
                self.poll(now)
                if self.cur is not None:
                    return {"ok": True, "message": "Флот уже отслеживается."}
            me = self.auth.character_id
            try:
                info = self._esi("GET", f"/characters/{me}/fleet/")
            except FleetError as e:
                if e.status == 404:
                    return {"ok": False, "reason": "not_in_fleet", "message": f"{self.auth.character} сейчас не во флоте."}
                return {"ok": False, "reason": "esi", "message": str(e)}
            if info.get("fleet_boss_id") != me:
                self._resolve([info.get("fleet_boss_id")])
                return {"ok": False, "reason": "not_boss",
                        "message": f"{self.auth.character} во флоте, но не босс (босс — {self._name(info.get('fleet_boss_id'))}). "
                                   "Состав флота игра отдаёт только боссу."}
            self.cur = {"id": int(now), "fleet_id": info["fleet_id"], "name": "", "boss_id": me, "boss": self.auth.character,
                        "started_at": int(now), "ended_at": None, "end_reason": "", "polled_at": None, "is_active": True,
                        "members": {}, "marks": {}}
            self.errors = 0
            self.poll(now)
            return {"ok": True, "message": f"Отслеживание включено ({self.auth.character}). Состав обновляется раз в {POLL_S} секунд."}

    def _end(self, reason: str, now: float) -> None:
        rec = self.cur
        if rec is None:
            return
        for m in rec["members"].values():
            if m["present"]:
                m["closed"] += max(0, m["last_seen"] - m["stint"])
                m["present"] = False
                m["at_end"] = True                           # был во флоте до самого конца
        rec.update(is_active=False, ended_at=int(now), end_reason=reason)
        self._save(rec)
        self.cur = None
        log.info("Флот %s завершён: %s", rec["fleet_id"], reason)

    def poll(self, now: Optional[float] = None) -> str:
        """Один опрос ESI. Возвращает краткий итог для журнала."""
        now = time.time() if now is None else now
        with self.lock:
            rec = self.cur
            if rec is None:
                return "нет флота"
            if not self.auth.logged_in:
                self._end("Вход через EVE отменён", now)
                return "флот завершён"
            try:
                info = self._esi("GET", f"/characters/{rec['boss_id']}/fleet/")
                if info.get("fleet_id") != rec["fleet_id"]:
                    self._end("Вы перешли в другой флот", now)
                    return "флот завершён"
                if info.get("fleet_boss_id") != rec["boss_id"]:
                    self._resolve([info.get("fleet_boss_id")])
                    self._end(f"Босс флота сменился на {self._name(info.get('fleet_boss_id'))}", now)
                    return "флот завершён"
                members = self._esi("GET", f"/fleets/{rec['fleet_id']}/members/")
            except FleetError as e:
                if e.status == 404:
                    self._end("Флот распущен или вы из него вышли", now)
                    return "флот завершён"
                if not self.auth.logged_in:
                    self._end("Разрешение EVE отозвано", now)
                    return "флот завершён"
                self.errors += 1
                self.last_error = str(e)
                if self.errors >= MAX_ERRORS:
                    self._end(f"Нет ответа от ESI: {e}", now)
                    return "флот завершён"
                return "ошибка"
            self.errors, self.last_error = 0, ""
            self._apply(rec, members or [], now)
            self._save(rec)
            return f"участников: {len(members or [])}"

    def _apply(self, rec: dict, members: list, now: float) -> None:
        t = int(now)
        seen = set()
        for d in members:
            cid = str(d["character_id"])
            seen.add(cid)
            m = rec["members"].get(cid)
            sysid, ship, station = d.get("solar_system_id"), d.get("ship_type_id"), d.get("station_id")
            if m is None:
                m = rec["members"][cid] = {"id": int(cid), "first_seen": t, "last_seen": t, "stint": t, "closed": 0,
                                           "present": True, "rejoins": 0, "route": []}
            elif not m["present"]:                           # выходил и вернулся
                m.update(present=True, stint=t, rejoins=m["rejoins"] + 1)
            m.update(last_seen=t, system=sysid, ship=ship, station=station, role=d.get("role", ""))
            route = m["route"]
            if route and route[-1]["system"] == sysid and route[-1].get("station") == station and route[-1].get("ship") == ship:
                route[-1]["until"] = t
            else:
                route.append({"system": sysid, "station": station, "ship": ship, "at": t, "until": t})
        for cid, m in rec["members"].items():
            if cid not in seen and m["present"]:
                m["closed"] += max(0, m["last_seen"] - m["stint"])
                m["present"] = False
        rec["polled_at"] = t
        ids = set()
        for d in members:
            ids.update((d.get("character_id"), d.get("ship_type_id"), d.get("solar_system_id")))
        self._resolve(ids)

    def run(self) -> None:
        """Фоновый цикл: пока есть отслеживаемый флот — опрос раз в POLL_S секунд."""
        while not self._stop.wait(POLL_S):
            try:
                if self.cur is not None:
                    self.poll()
            except Exception:
                log.exception("Ошибка опроса флота")

    def stop_thread(self) -> None:
        self._stop.set()

    def stop(self, now: Optional[float] = None) -> dict:
        with self.lock:
            if self.cur is None:
                return {"ok": False, "message": "Флот не отслеживается."}
            self._end("Отслеживание остановлено вручную", time.time() if now is None else now)
            return {"ok": True, "message": "Отслеживание остановлено."}

    # ----- выдача (тот же вид, что у Fleet Watch) -----
    def describe(self, rec: dict) -> dict:
        active = bool(rec.get("is_active"))
        boss = rec["members"].get(str(rec["boss_id"]))
        boss_tl = _timeline(boss) if boss else []
        marks = rec.get("marks") or {}
        me = self.auth.character_id

        def row(m: dict) -> dict:
            eps = away_episodes(_timeline(m), boss_tl) if m["id"] != rec["boss_id"] else []
            last = m["route"][-1]["until"] if m.get("route") else 0
            away_now = eps[-1][1] - eps[-1][0] if active and m["present"] and eps and eps[-1][1] >= last else 0
            seconds = m["closed"] + (max(0, m["last_seen"] - m["stint"]) if m["present"] else 0)
            k = marks.get(str(m["id"])) or {}
            return {"id": m["id"], "name": self._name(m["id"], str(m["id"])), "joined": m["first_seen"], "seconds": seconds,
                    "rejoins": m["rejoins"], "away_now": away_now, "away_eps": [b - a for a, b in eps if b - a >= 60],
                    "boss": m["id"] == rec["boss_id"], "me": m["id"] == me,
                    "mark": k.get("mark", ""), "comment": k.get("comment", "")}

        def here(m: dict) -> bool:
            return m["present"] if active else bool(m.get("at_end"))

        pilots, left = [], []
        for m in rec["members"].values():
            r = row(m)
            if here(m):
                r.update(ship=self._name(m.get("ship")), system=self._name(m.get("system")),
                         docked=m.get("station") is not None, role=m.get("role", ""))
                pilots.append(r)
            else:
                r["left"] = m["last_seen"]
                left.append(r)
        pilots.sort(key=lambda p: (not p["boss"], p["ship"].lower(), p["name"].lower()))
        left.sort(key=lambda p: -p["left"])
        by_ship, by_sys = Counter(p["ship"] for p in pilots), Counter(p["system"] for p in pilots)
        b = next((p for p in pilots if p["boss"]), None)
        end = rec.get("ended_at") or rec.get("polled_at") or rec["started_at"]
        return {
            "id": rec["id"], "name": rec.get("name", ""), "boss": rec.get("boss", ""), "boss_system": b["system"] if b else "",
            "started_at": rec["started_at"], "is_active": active, "ended_at": rec.get("ended_at"),
            "end_reason": rec.get("end_reason", ""), "duration": max(0, end - rec["started_at"]),
            "polled_at": rec.get("polled_at"), "count": len(pilots), "can_manage": True,
            "ships": [{"name": n, "n": c} for n, c in sorted(by_ship.items(), key=lambda kv: (-kv[1], kv[0].lower()))],
            "systems": [{"name": n, "n": c, "sec": None} for n, c in sorted(by_sys.items(), key=lambda kv: (-kv[1], kv[0].lower()))],
            "pilots": pilots, "left": left,
        }

    def current(self) -> Optional[dict]:
        with self.lock:
            return self.describe(self.cur) if self.cur is not None else None

    def get(self, fid) -> Optional[dict]:
        with self.lock:
            try:
                fid = int(fid)
            except (TypeError, ValueError):
                return None
            if self.cur is not None and self.cur["id"] == fid:
                return self.describe(self.cur)
            rec = _read(self._file(fid), None)
            return self.describe(rec) if isinstance(rec, dict) and "members" in rec else None

    def list(self, limit: int = 60) -> list:
        with self.lock:
            out = []
            for rec in self._all()[:limit]:
                if self.cur is not None and rec["id"] == self.cur["id"]:
                    rec = self.cur
                end = rec.get("ended_at") or rec.get("polled_at") or rec["started_at"]
                out.append({"id": rec["id"], "name": rec.get("name", ""), "boss": rec.get("boss", ""),
                            "is_active": bool(rec.get("is_active")), "started_at": rec["started_at"],
                            "ended_at": rec.get("ended_at"), "duration": max(0, end - rec["started_at"]),
                            "pilots": len(rec["members"]), "max": len(rec["members"])})
            return out

    def mark(self, character_id, mark, comment, fleet_id=None) -> dict:
        with self.lock:
            if fleet_id in (None, ""):
                rec = self.cur
            elif self.cur is not None and str(self.cur["id"]) == str(fleet_id):
                rec = self.cur
            else:
                try:
                    rec = _read(self._file(fleet_id), None)
                except (TypeError, ValueError):
                    rec = None
            if not isinstance(rec, dict):
                return {"ok": False, "reason": "no_fleet", "message": "Флот не найден."}
            cid = str(character_id)
            if mark not in MARKS:
                return {"ok": False, "reason": "bad", "message": "Неизвестная отметка."}
            if cid not in rec["members"]:
                return {"ok": False, "reason": "bad", "message": "Этого пилота нет в составе флота."}
            comment = str(comment or "").strip()[:500]
            marks = rec.setdefault("marks", {})
            if not mark and not comment:
                marks.pop(cid, None)
            else:
                marks[cid] = {"mark": mark, "comment": comment}
            self._save(rec)
            return {"ok": True, "message": "Сохранено."}


# ---------------------------------------------------------------------------
# Подключение к трекеру: адреса страницы и оверлея
# ---------------------------------------------------------------------------

NO_LOGIN = {"ok": False, "reason": "no_login", "message": "Чтобы видеть флот, подключите аккаунт EVE на вкладке «Флот»."}
CALLBACK_PAGE = ("<!doctype html><meta charset='utf-8'><title>EVE Log HUD</title><body style=\"margin:0;background:#0f1115;"
                 "color:#e8edf2;font:16px 'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center;"
                 "height:100vh\"><div style='max-width:520px;text-align:center'><div style='font-size:22px;color:%s;"
                 "margin-bottom:10px'>%s</div>%s<div style='color:#9aa7b4;font-size:13px;margin-top:14px'>Эту вкладку "
                 "можно закрыть.</div></div></body>")


class FleetApi:
    """Адреса модуля. Флот читается только напрямую из ESI (вход через EVE в самом приложении)."""

    def __init__(self, local: "LocalFleet", port: int, cfg: dict, data_dir: str, write_json=None, open_url=None):
        import webbrowser
        self.local, self.port, self.cfg, self.data_dir = local, port, cfg, data_dir
        self.write_json = write_json or _write
        self.open_url = open_url or webbrowser.open

    def logged_in(self) -> bool:
        return self.local.auth.logged_in

    def sso(self, qs=None) -> dict:
        st = self.local.auth.status()
        return {"ok": True, "source": "local" if st["logged_in"] else "", "available": True,
                "client_id_set": st["client_id_set"], "logged_in": st["logged_in"], "character": st["character"],
                "callback": f"http://localhost:{self.port}/sso/callback", "scope": " ".join(SCOPES),
                "tracking": self.local.cur is not None}

    def set_client(self, body, qs=None) -> dict:
        import re
        cid = str((body or {}).get("client_id") or "").strip() if isinstance(body, dict) else ""
        if not re.fullmatch(r"[0-9a-fA-F]{32}", cid):
            return {"ok": False, "message": "Client ID — это 32 знака: цифры и буквы a–f. Скопируйте его со страницы приложения."}
        path = os.path.join(self.data_dir, "config.json")
        user = _read(path, {})
        user = user if isinstance(user, dict) else {}
        user["esi_client_id"] = cid
        self.write_json(path, user)
        self.cfg["esi_client_id"] = cid
        self.local.auth.client_id = cid
        return {"ok": True, "message": "Client ID сохранён."}

    def login(self, body=None, qs=None) -> dict:
        try:
            url = self.local.auth.login_url(f"http://localhost:{self.port}/sso/callback")
        except FleetError as e:
            return {"ok": False, "message": str(e)}
        try:
            self.open_url(url)
        except Exception as e:
            return {"ok": False, "message": f"Не удалось открыть браузер: {e}"}
        return {"ok": True, "message": "Открыл страницу входа EVE в браузере. Войдите персонажем — боссом флота."}

    def callback(self, qs):
        import html
        from modkit import Html
        if qs.get("error"):
            ok, text = False, "EVE отклонил вход: " + str(qs["error"][0])[:200]
        else:
            try:
                name = self.local.auth.finish((qs.get("code") or [""])[0], (qs.get("state") or [""])[0])
                ok, text = True, f"Вы вошли как {name}. Вернитесь в приложение: вкладка «Флот» → «Отслеживать мой флот»."
            except FleetError as e:
                ok, text = False, str(e)
        page = CALLBACK_PAGE % ("#18bc9c" if ok else "#e74c3c", "Готово" if ok else "Вход не выполнен", html.escape(text))
        return Html(200 if ok else 400, page)

    def logout(self, body=None, qs=None) -> dict:
        self.local.stop()
        self.local.auth.logout()
        return {"ok": True, "message": "Вход через EVE отменён, токен удалён с этого компьютера."}

    def fleet(self, qs) -> dict:
        if qs.get("id"):
            try:
                pk = int(qs["id"][0])
            except (TypeError, ValueError):
                return {"ok": False, "reason": "bad", "message": "Неверный номер флота"}
            return {"ok": True, "fleet": self.local.get(pk), "at": int(time.time())}
        if not self.logged_in():
            return dict(NO_LOGIN)
        return {"ok": True, "fleet": self.local.current(), "at": int(time.time())}

    def fleets(self, qs=None) -> dict:
        return {"ok": True, "fleets": self.local.list(), "at": int(time.time())}

    def track(self, body=None, qs=None) -> dict:
        if not self.logged_in():
            return dict(NO_LOGIN)
        return self.local.start()

    def stop(self, body=None, qs=None) -> dict:
        return self.local.stop()

    def mark(self, body, qs=None) -> dict:
        if not isinstance(body, dict):
            return {"ok": False, "reason": "bad", "message": "Неверный запрос"}
        return self.local.mark(body.get("character_id"), str(body.get("mark") or ""), body.get("comment"), body.get("fleet_id"))

    def register(self, ctx) -> None:
        for path, fn in (("/api/sso", self.sso), ("/sso/callback", self.callback), ("/api/fleet", self.fleet),
                         ("/api/fleets", self.fleets)):
            ctx.get(path, fn)
        for path, fn in (("/api/sso/client", self.set_client), ("/api/sso/login", self.login), ("/api/sso/logout", self.logout),
                         ("/api/fleet/track", self.track), ("/api/fleet/stop", self.stop), ("/api/fleet/mark", self.mark)):
            ctx.post(path, fn)


def load_battle():
    """battle.py лежит рядом (отчёт о бое по киллмейлам) — загружаем по пути: модуль подключается не как пакет."""
    import importlib.util
    import sys
    name = "elw_mod_fleet_battle"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)), "battle.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class BattleApi:
    """Отчёт о бое: собрать по системам и времени (или по флоту из истории), список, перенос групп между сторонами."""

    def __init__(self, local: "LocalFleet", battles):
        self.local, self.b = local, battles
        self.mod = load_battle()

    def _raw_fleet(self, fid: int) -> Optional[dict]:
        with self.local.lock:
            if self.local.cur is not None and self.local.cur["id"] == fid:
                return self.local.cur
            rec = _read(self.local._file(fid), None)
            return rec if isinstance(rec, dict) and "members" in rec else None

    def _wrap(self, fn):
        try:
            return fn()
        except self.mod.BattleError as e:
            return {"ok": False, "message": str(e)}

    def list(self, qs) -> dict:
        return {"ok": True, "battles": self.b.list()}

    def one(self, qs):
        rec = self.b.load((qs.get("id") or [""])[0])
        return self.b.view(rec) if rec else (404, {"ok": False, "message": "Отчёт не найден"})

    def job(self, qs) -> dict:
        return {"ok": True, **self.b.job((qs.get("id") or [""])[0])}

    def prefill(self, qs) -> dict:
        return self._wrap(lambda: self.b.prefill((qs.get("fleet_id") or ["0"])[0]))

    def build(self, body, qs=None) -> dict:
        return self._wrap(lambda: self.b.start(body))

    def move(self, body, qs=None) -> dict:
        body = body if isinstance(body, dict) else {}
        return self._wrap(lambda: self.b.move(str(body.get("id") or ""), str(body.get("entity") or ""), str(body.get("side") or "")))

    def register(self, ctx) -> None:
        for path, fn in (("/api/battles", self.list), ("/api/battle", self.one), ("/api/battle/job", self.job),
                         ("/api/battle/prefill", self.prefill)):
            ctx.get(path, fn)
        for path, fn in (("/api/battle/build", self.build), ("/api/battle/move", self.move)):
            ctx.post(path, fn)


def setup(ctx) -> None:
    local = LocalFleet(ctx.data_dir, ctx.cfg.get("esi_client_id") or BUILTIN_CLIENT_ID)
    FleetApi(local, ctx.port, ctx.cfg, ctx.data_dir, ctx.core.atomic_write_json).register(ctx)
    bmod = load_battle()
    api = BattleApi(local, None)
    def icons(type_ids):
        if ctx.online is not None:
            threading.Thread(target=lambda: [ctx.online.fetch_icon(t) for t in list(type_ids)[:400]],
                             name="battle-icons", daemon=True).start()
    api.b = bmod.Battles(ctx.data_dir, me=lambda: local.auth.character_id, fleet=api._raw_fleet, on_built=icons)
    api.register(ctx)
    ctx.thread(local.run, "fleet")
    ctx.on_stop(local.stop_thread)
