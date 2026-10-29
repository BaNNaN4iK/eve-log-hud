# -*- coding: utf-8 -*-
"""
Вход через EVE для данных персонажа: кошелёк (выплаты ESS), склад, журнал добычи, свои киллмейлы, работы производства.

Отдельное приложение EVE (не то, что у «Флота»: у флота своё приложение и свой токен — только состав флота).
Один вход — все доступы ниже; можно подключить несколько персонажей. Только стандартная библиотека.
Секрета приложения нет (вход по PKCE). Client ID — в «Настройках» (config.json → esi_main_client_id).
Токены обновления — в папке данных: esi_token_main.json (Windows: зашифрованы DPAPI; Linux: файл с правами 600).

Модули берут токен так: app.eve.token(character_id); app.eve.chars — подключённые персонажи; has(cid, scope).
"""
import base64
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, Optional, Tuple

log = logging.getLogger("eve_sso")

SSO = "https://login.eveonline.com"
ESI = "https://esi.evetech.net/latest"
ALLOWED_HOSTS = {"login.eveonline.com", "esi.evetech.net"}
# доступы приложения «данные персонажа» — в приложении на developers.eveonline.com должны быть включены ровно эти
SCOPES = [
    "esi-wallet.read_character_wallet.v1",      # кошелёк: выплаты ESS и баунти
    "esi-assets.read_assets.v1",                # склад: что и где лежит
    "esi-industry.read_character_mining.v1",    # копка: журнал добычи
    "esi-killmails.read_killmails.v1",          # бой: свои киллмейлы
    "esi-industry.read_character_jobs.v1",      # производство: запущенные работы
    "esi-universe.read_structures.v1",          # названия структур (где лежит склад)
]
SCOPE_NAMES = {SCOPES[0]: "кошелёк", SCOPES[1]: "склад", SCOPES[2]: "журнал добычи", SCOPES[3]: "киллмейлы",
               SCOPES[4]: "работы производства", SCOPES[5]: "названия структур"}
BUILTIN_CLIENT_ID = ""                          # приложение «данные персонажа» автора; пока не задано — Client ID в «Настройках»
TOKEN_FILE = "esi_token_main.json"


class SsoError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def http(method: str, url: str, *, token: str = "", form: Optional[dict] = None, body=None, timeout: float = 20) -> Tuple[object, dict]:
    """Запрос к SSO или ESI → (JSON, заголовки). Другие адреса запрещены."""
    host = urllib.parse.urlsplit(url).hostname
    if host not in ALLOWED_HOSTS or not url.startswith("https://"):
        raise SsoError(f"Адрес не разрешён: {host}")
    headers = {"Accept": "application/json", "User-Agent": "EveLogHUD"}
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
        raise SsoError(f"{host} ответил {e.code}" + (f": {detail}" if detail else ""), e.code) from e
    except (urllib.error.URLError, OSError) as e:
        raise SsoError(f"нет связи с {host}: {getattr(e, 'reason', e)}") from e
    except ValueError as e:
        raise SsoError(f"{host} вернул не JSON") from e


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


class Auth:
    """Персонажи, подключённые к приложению «данные персонажа»: токены обновления, доступы, свежий токен доступа."""

    def __init__(self, data_dir: str, client_id: str, write: Callable, request: Callable = http, scopes=None):
        self.path = os.path.join(data_dir, TOKEN_FILE)
        self.client_id = (client_id or "").strip()
        self.scopes = list(scopes or SCOPES)
        self.write, self.request = write, request
        self.lock = threading.RLock()
        self.pending: Dict[str, dict] = {}                   # state → {verifier, redirect, at}
        self.access: Dict[int, Tuple[str, float]] = {}
        d = _read(self.path, {})
        self.chars: Dict[int, dict] = {}
        for cid, c in ((d.get("chars") or {}) if isinstance(d, dict) else {}).items():
            ref = unprotect(c.get("refresh", ""))
            if ref:
                self.chars[int(cid)] = {"name": c.get("name") or str(cid), "refresh": ref, "scopes": c.get("scopes") or []}

    def owns(self, state: str) -> bool:
        with self.lock:
            return state in self.pending

    def has(self, cid: int, scope: str) -> bool:
        c = self.chars.get(int(cid))
        return bool(c and scope in (c.get("scopes") or []))

    def _save(self) -> None:
        self.write(self.path, {"chars": {str(k): {"name": v["name"], "refresh": protect(v["refresh"]), "scopes": v.get("scopes") or []}
                                         for k, v in self.chars.items()}})
        if os.name != "nt":
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    def login_url(self, redirect: str) -> str:
        if not self.client_id:
            raise SsoError("Не задан Client ID приложения EVE «данные персонажа» — впишите его в «Настройках».")
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = "me-" + secrets.token_urlsafe(16)
        with self.lock:
            now = time.time()
            self.pending = {k: v for k, v in self.pending.items() if now - v["at"] < 900}
            self.pending[state] = {"verifier": verifier, "redirect": redirect, "at": now}
        q = urllib.parse.urlencode({"response_type": "code", "redirect_uri": redirect, "client_id": self.client_id,
                                    "scope": " ".join(self.scopes), "code_challenge": challenge,
                                    "code_challenge_method": "S256", "state": state})
        return f"{SSO}/v2/oauth/authorize/?{q}"

    def _store(self, tok: dict) -> Tuple[int, str]:
        access = tok.get("access_token") or ""
        try:                                                 # кто вошёл и какие доступы дал — из тела токена (получен от CCP по TLS)
            part = access.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            cid = int(str(claims["sub"]).rsplit(":", 1)[1])
            name = claims.get("name") or str(cid)
            scp = claims.get("scp") or []
            scp = [scp] if isinstance(scp, str) else list(scp)
        except Exception as e:
            raise SsoError("EVE вернул токен, который не удалось разобрать.") from e
        with self.lock:
            old = self.chars.get(cid, {})
            self.chars[cid] = {"name": name, "refresh": tok.get("refresh_token") or old.get("refresh", ""), "scopes": scp}
            self.access[cid] = (access, time.time() + float(tok.get("expires_in") or 0) - 60)
            self._save()
        return cid, name

    def finish(self, code: str, state: str) -> str:
        with self.lock:
            p = self.pending.pop(state or "", None)
        if p is None or not code:
            raise SsoError("Вход устарел или начат не из этого приложения. Нажмите «Подключить персонажа» ещё раз.")
        tok, _ = self.request("POST", f"{SSO}/v2/oauth/token", form={
            "grant_type": "authorization_code", "code": code, "client_id": self.client_id, "code_verifier": p["verifier"]})
        return self._store(tok)[1]

    def token(self, cid: int) -> str:
        """Действующий токен доступа персонажа (обновляется сам)."""
        cid = int(cid)
        with self.lock:
            c = self.chars.get(cid)
            if not c:
                raise SsoError("Персонаж не подключён.")
            acc = self.access.get(cid)
            if acc and time.time() < acc[1]:
                return acc[0]
            try:
                tok, _ = self.request("POST", f"{SSO}/v2/oauth/token", form={
                    "grant_type": "refresh_token", "refresh_token": c["refresh"], "client_id": self.client_id})
            except SsoError as e:
                if e.status in (400, 401):                   # доступ отозван — персонажа нужно подключить заново
                    self.remove(cid)
                    raise SsoError(f"{c['name']}: доступ отозван или устарел — подключите персонажа заново.", e.status) from e
                raise
            self._store(tok)
            return self.access[cid][0]

    def remove(self, cid: int) -> None:
        with self.lock:
            self.chars.pop(int(cid), None)
            self.access.pop(int(cid), None)
            self._save()

    def status(self) -> dict:
        return {"client_id_set": bool(self.client_id), "client_id": self.client_id, "scopes": [[s, SCOPE_NAMES.get(s, s)] for s in self.scopes],
                "all_scopes": [[s, SCOPE_NAMES.get(s, s), s in self.scopes] for s in SCOPES],
                "chars": [{"id": k, "name": v["name"], "missing": [SCOPE_NAMES.get(s, s) for s in self.scopes if s not in (v.get("scopes") or [])]}
                          for k, v in self.chars.items()]}


CALLBACK_PAGE = ("<!doctype html><meta charset='utf-8'><title>EVE Log HUD</title><body style=\"margin:0;background:#0f1115;"
                 "color:#e8edf2;font:16px 'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center;"
                 "height:100vh\"><div style='max-width:540px;text-align:center'><div style='font-size:22px;color:%s;"
                 "margin-bottom:10px'>%s</div>%s<div style='color:#9aa7b4;font-size:13px;margin-top:14px'>Эту вкладку "
                 "можно закрыть.</div></div></body>")


def install(app, write: Callable, open_url: Optional[Callable] = None) -> Auth:
    """Подключить вход «данные персонажа» к трекеру (один раз): адреса /api/eve/* и свой ответ на общем /sso/callback."""
    if getattr(app, "eve", None) is not None:
        return app.eve
    import html
    import modkit
    cfg = app.cfg
    chosen = [x for x in (cfg.get("esi_main_scopes") or SCOPES) if x in SCOPES] or list(SCOPES)
    auth = Auth(app.data_dir, cfg.get("esi_main_client_id") or BUILTIN_CLIENT_ID, write, scopes=chosen)
    redirect = f"http://localhost:{app.port}/sso/callback"
    hooks = []                                                # модули: новый персонаж подключён (например, сразу обновить кошелёк)
    if open_url is None:
        import webbrowser
        open_url = webbrowser.open

    def callback(qs):
        if qs.get("error"):
            ok, text = False, "EVE отклонил вход: " + str(qs["error"][0])[:200]
        else:
            try:
                name = auth.finish((qs.get("code") or [""])[0], (qs.get("state") or [""])[0])
                ok, text = True, f"Персонаж {name} подключён. Вернитесь в приложение."
                for fn in list(hooks):
                    threading.Thread(target=fn, name="eve-linked", daemon=True).start()
            except SsoError as e:
                ok, text = False, str(e)
                if "invalid_scope" in text:
                    text += (" — этот доступ не включён в приложении EVE. Либо включите его на developers.eveonline.com, "
                             "либо снимите галочку с него в «Настройках» → «Персонажи EVE» и войдите снова.")
        return modkit.Html(200 if ok else 400, CALLBACK_PAGE % ("#18bc9c" if ok else "#e74c3c", "Готово" if ok else "Вход не выполнен", html.escape(text)))

    def status(qs):
        return {"ok": True, **auth.status(), "callback": redirect}

    def login(body=None, qs=None):
        try:
            url = auth.login_url(redirect)
        except SsoError as e:
            return {"ok": False, "message": str(e)}
        try:
            open_url(url)
        except Exception as e:
            return {"ok": False, "message": f"Не удалось открыть браузер: {e}"}
        return {"ok": True, "message": "Открыл вход EVE в браузере. Войдите персонажем и подтвердите доступы."}

    def logout(body, qs=None):
        try:
            cid = int((body or {}).get("id"))
        except (TypeError, ValueError, AttributeError):
            return {"ok": False, "message": "Неверный запрос"}
        auth.remove(cid)
        return {"ok": True, "message": "Персонаж отключён, его токен удалён с этого компьютера."}

    def set_client(body, qs=None):
        """Client ID и какие доступы включены в приложении EVE (запрашиваем ровно их — иначе EVE отклонит вход: invalid_scope)."""
        body = body if isinstance(body, dict) else {}
        path = os.path.join(app.data_dir, "config.json")
        user = _read(path, {})
        user = user if isinstance(user, dict) else {}
        if "client_id" in body:
            cid = str(body.get("client_id") or "").strip()
            if not re.fullmatch(r"[0-9a-fA-F]{32}", cid):
                return {"ok": False, "message": "Client ID — это 32 знака: цифры и буквы a–f. Скопируйте его со страницы приложения."}
            user["esi_main_client_id"] = cfg["esi_main_client_id"] = auth.client_id = cid
        if isinstance(body.get("scopes"), list):
            sc = [x for x in SCOPES if x in body["scopes"]]
            if not sc:
                return {"ok": False, "message": "Отметьте хотя бы один доступ."}
            user["esi_main_scopes"] = cfg["esi_main_scopes"] = auth.scopes = sc
        write(path, user)
        return {"ok": True, "message": "Сохранено."}

    modkit._install_sso(app)
    app.sso_handlers.append(("core", auth.owns, callback))
    app.routes[("GET", "/api/eve/status")] = ("core", status)
    app.routes[("POST", "/api/eve/login")] = ("core", login)
    app.routes[("POST", "/api/eve/logout")] = ("core", logout)
    app.routes[("POST", "/api/eve/client")] = ("core", set_client)
    auth.on_linked = hooks.append
    app.eve = auth
    return auth
