# -*- coding: utf-8 -*-
"""
Модуль «Alliance Auth»: отправка итогов сессий в плагин Fleet Watch на сервере Alliance Auth.

Включается адресом и личным ключом пилота (aa_url / aa_key в config.json, команда --aa-connect).
Очередь переживает перезапуск (aa_outbox.json), при ошибках связи отправка повторяется.
"""
import json
import logging
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

log = logging.getLogger("elw.alliance_auth")
CORE = None                       # ядро трекера (eve_log_watcher); задаётся в setup() или bind()


def bind(core) -> None:
    global CORE
    CORE = core



AA_API = "/fleetwatch/api/v1"
AA_BATCH = 50
AA_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class AAError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def check_aa_url(url: str) -> str:
    """Адрес AA: только https (ключ передаётся в заголовке); http разрешён лишь для localhost."""
    url = (url or "").strip().rstrip("/")
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("Адрес должен начинаться с https:// (например, https://auth.example.com)")
    if u.scheme == "http" and u.hostname not in AA_LOCAL_HOSTS:
        raise ValueError("Для внешнего сервера нужен https:// — иначе ключ уйдёт по сети открытым текстом")
    if u.path not in ("", "/"):
        raise ValueError("Укажите только адрес сайта AA, без пути (например, https://auth.example.com)")
    return f"{u.scheme}://{u.netloc}"


def aa_payload(rec: dict, live: bool = False) -> dict:
    """Запись для AA — полная, включая ряды для графиков (страница в AA та же, что у трекера)."""
    out = dict(rec)
    out["live"] = live
    return out


class AAUploader:
    """Очередь отправки в AA: переживает перезапуск (aa_outbox.json), повторяет при ошибках связи."""

    def __init__(self, cfg: dict, data_dir: str):
        self.cfg = cfg
        self.data_dir = data_dir
        self.outbox_path = os.path.join(data_dir, "aa_outbox.json")
        self.lock = threading.Lock()
        self.queue: Dict[str, dict] = {}
        self.wake = threading.Event()
        self.live_sent: Dict[str, int] = {}
        self.status = {"configured": False, "host": "", "queue": 0, "sent": 0, "rejected": 0,
                       "last_ok": 0, "last_error": "", "last_rejects": []}
        if os.path.exists(self.outbox_path):
            try:
                with open(self.outbox_path, "r", encoding="utf-8") as f:
                    self.queue = json.load(f)
            except (OSError, ValueError) as e:
                log.error("aa_outbox.json повреждён (%s) — очередь начата заново", e)
        self.reload_config()

    # ----- настройки -----
    def reload_config(self) -> None:
        url, key = self.cfg.get("aa_url") or "", self.cfg.get("aa_key") or ""
        try:
            self.url = check_aa_url(url) if url else ""
        except ValueError as e:
            log.error("aa_url в config.json: %s", e)
            self.url = ""
        self.key = key.strip()
        self.status["configured"] = bool(self.url and self.key)
        self.status["host"] = urllib.parse.urlsplit(self.url).netloc if self.url else ""
        self.status["queue"] = len(self.queue)

    @property
    def configured(self) -> bool:
        return self.status["configured"]

    # ----- HTTP -----
    def request(self, method: str, path: str, body=None, timeout: float = 30) -> dict:
        if not self.configured:
            raise AAError("AA не настроен (aa_url/aa_key в config.json)")
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {"Authorization": "Bearer " + self.key, "Content-Type": "application/json",
                   "Accept": "application/json", "User-Agent": f"EVELogWatcher/{CORE.VERSION}"}
        url, parts = self.url + AA_API + path, urllib.parse.urlsplit(self.url)
        if parts.hostname == "localhost":
            # Windows сначала пробует IPv6 (::1), а локальный AA слушает только 127.0.0.1 — каждая попытка стоила 2 секунды
            url = url.replace("//localhost", "//127.0.0.1", 1)
            headers["Host"] = parts.netloc
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if "/account/login" in resp.geturl():
                    raise AAError("сервер перенаправляет на вход — в local.py AA нужно "
                                  "APPS_WITH_PUBLIC_VIEWS += ['fleetwatch']")
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error") or ""
            except Exception:
                msg = ""
            if e.code == 404:
                msg = msg or "на сервере нет плагина Fleet Watch (или он старой версии)"
            raise AAError(f"AA ответил {e.code}: {msg or e.reason}", e.code) from e
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            raise AAError(f"нет связи с {self.status['host']}: {getattr(e, 'reason', e)}") from e
        except ValueError as e:
            raise AAError("AA вернул не JSON — проверьте адрес сайта") from e

    def ping(self) -> dict:
        return self.request("GET", "/ping/", timeout=15)

    # ----- очередь -----
    def _save(self) -> None:
        CORE.atomic_write_json(self.outbox_path, self.queue)
        self.status["queue"] = len(self.queue)

    def enqueue(self, rec: dict) -> None:
        if not self.configured:
            return
        with self.lock:
            self.queue[rec["id"]] = aa_payload(rec)
            self.live_sent.pop(rec["id"], None)
            self._save()
        self.wake.set()

    def send_batch(self, records: List[dict]) -> dict:
        res = self.request("POST", "/sessions/", {"sessions": records, "client": f"EVE Log Watcher {CORE.VERSION}"})
        if not isinstance(res, dict) or "accepted" not in res:
            raise AAError("неожиданный ответ AA")
        return res

    def flush(self) -> int:
        """Отправить всю очередь. Возвращает число принятых записей; при ошибке связи — AAError."""
        sent = 0
        while True:
            with self.lock:
                batch = list(self.queue.values())[:AA_BATCH]
            if not batch:
                return sent
            res = self.send_batch(batch)
            accepted = [x for x in res.get("accepted", []) if x]
            rejected = res.get("rejected", []) or []
            done = set(accepted) | {r["id"] for r in rejected if r.get("id")}
            with self.lock:
                for i in done:
                    self.queue.pop(i, None)
                if not done:   # сервер ничего не принял и не отклонил — не крутимся в цикле
                    raise AAError("AA не обработал записи")
                self._save()
            sent += len(accepted)
            self.status["sent"] += len(accepted)
            if rejected:
                self.status["rejected"] += len(rejected)
                self.status["last_rejects"] = [f"{r.get('id')}: {r.get('reason')}" for r in rejected[:5]]
                log.warning("AA отклонил %d сессий: %s", len(rejected),
                            "; ".join(f"{r.get('id')}: {r.get('reason')}" for r in rejected[:3]))
            self.status["last_ok"] = int(time.time())
            self.status["last_error"] = ""

    def send_live(self, sessions: List[dict]) -> int:
        """Идущие сессии — без очереди: потерялось обновление — придёт следующее."""
        todo = [s for s in sessions if self.live_sent.get(s["id"]) != s.get("events")]
        if not todo:
            return 0
        res = self.send_batch([aa_payload(s, live=True) for s in todo])
        for s in todo:
            if s["id"] in res.get("accepted", []):
                self.live_sent[s["id"]] = s.get("events")
        return len(todo)

    def tick(self, watcher: "CORE.Watcher", now: float, last_live: float) -> float:
        """Один шаг фоновой отправки. Возвращает время последней отправки «живых» сессий."""
        if self.queue:
            n = self.flush()
            if n:
                log.info("AA: отправлено сессий: %d", n)
        if self.cfg.get("aa_live_upload") and now - last_live >= 60:
            last_live = now
            with watcher.lock:
                live = [CORE.session_finalize(s, self.cfg["min_session_seconds"]) for s in watcher.open.values()]
            if live:
                self.send_live(live)
        self.status["last_error"] = ""
        return last_live

    def loop(self, watcher: "CORE.Watcher", stop: threading.Event) -> None:
        backoff = 0
        last_live = 0.0
        cfg_mtime = 0.0
        cfg_path = os.path.join(self.data_dir, "config.json")
        while not stop.is_set():
            # новый адрес/ключ из config.json подхватывается без перезапуска (после connect_aa.bat)
            try:
                m = os.path.getmtime(cfg_path)
                if m != cfg_mtime:
                    cfg_mtime = m
                    fresh = CORE.load_config(self.data_dir)
                    for k in ("aa_url", "aa_key", "aa_live_upload"):
                        self.cfg[k] = fresh[k]
                    was = self.configured
                    self.reload_config()
                    if self.configured and not was:
                        log.info("AA подключён: %s", self.status["host"])
            except OSError:
                pass
            if self.configured:
                try:
                    last_live = self.tick(watcher, time.time(), last_live)
                    backoff = 0
                except AAError as e:
                    self.status["last_error"] = str(e)
                    backoff = min(max(60, backoff * 2), 900)
                    log.warning("AA: %s (повтор через %d с)", e, backoff)
                except Exception:
                    log.exception("AA: ошибка отправки")
                    backoff = 300
            # ждём паузу повтора, но каждые 15 с смотрим config.json: новый ключ (connect_aa.bat)
            # применяется сразу, а не после многоминутной паузы после ошибки 401
            deadline = time.time() + (backoff or 15)
            while not stop.is_set() and time.time() < deadline:
                if self.wake.wait(min(15.0, max(0.1, deadline - time.time()))):
                    break
                try:
                    if os.path.getmtime(cfg_path) != cfg_mtime:
                        backoff = 0
                        break
                except OSError:
                    pass
            self.wake.clear()


def _tmp_dir() -> str:
    import tempfile
    return tempfile.mkdtemp(prefix="elw_aa_")


def aa_connect(cfg: dict, data_dir: str, url: str, key: str) -> int:
    """Проверить адрес и ключ и записать их в config.json."""
    try:
        url = check_aa_url(url)
    except ValueError as e:
        print("Ошибка:", e)
        return 2
    key = (key or "").strip()
    if not key:
        print("Ошибка: ключ пустой. Создайте его на странице «Мои логи» в AA.")
        return 2
    test = AAUploader(dict(cfg, aa_url=url, aa_key=key), _tmp_dir())
    try:
        info = test.ping()
    except AAError as e:
        print("Не удалось подключиться:", e)
        return 1
    path = os.path.join(data_dir, "config.json")
    with open(path, "r", encoding="utf-8-sig") as f:
        user_cfg = json.load(f)
    user_cfg.update(aa_url=url, aa_key=key)
    CORE.atomic_write_json(path, user_cfg, indent=2)
    chars = info.get("characters") or []
    print(f"Подключено к {url} как {info.get('user')}.")
    print("Сервер примет сессии персонажей:", ", ".join(chars) if chars else "(в AA нет ваших персонажей!)")
    local = sorted({r.get("who") for r in CORE.History(data_dir).records() if r.get("who")})
    missing = [c for c in local if c.lower() not in {x.lower() for x in chars}]
    if missing:
        print("Внимание: сессии этих персонажей будут отклонены — добавьте их в AA:", ", ".join(missing))
    print("Новые сессии будут отправляться автоматически. Накопленная история: upload_history.bat")
    return 0


def aa_upload_history(cfg: dict, data_dir: str, days: Optional[int]) -> int:
    """Отправить накопленную историю (повторная отправка безопасна — сервер не создаёт дублей)."""
    up = AAUploader(cfg, _tmp_dir())
    if not up.configured:
        print("AA не подключён. Сначала запустите connect_aa.bat.")
        return 2
    days = days if days is not None else cfg["import_days"]
    since = time.time() - days * 86400
    recs = [aa_payload(r) for r in CORE.History(data_dir).records(light=False) if r.get("t1", 0) >= since]
    if not recs:
        print(f"За {days} дн. сессий нет.")
        return 0
    print(f"Отправляю {len(recs)} сессий за {days} дн. на {up.status['host']}…")
    accepted, reasons = 0, {}
    for i in range(0, len(recs), AA_BATCH):
        try:
            res = up.send_batch(recs[i:i + AA_BATCH])
        except AAError as e:
            print("Ошибка:", e)
            return 1
        accepted += len(res.get("accepted", []))
        for r in res.get("rejected", []):
            reasons[r.get("reason")] = reasons.get(r.get("reason"), 0) + 1
        print(f"  {min(i + AA_BATCH, len(recs))}/{len(recs)}")
    print(f"Принято: {accepted}. Отклонено: {sum(reasons.values())}.")
    for reason, n in reasons.items():
        print(f"  ×{n}: {reason}")
    return 0 if not reasons else 3


def setup(ctx) -> None:
    """Подключение к трекеру: новые сессии — в очередь, фоновая отправка, состояние — в /api/live (поле aa)."""
    bind(ctx.core)
    up = AAUploader(ctx.cfg, ctx.data_dir)
    ctx.on_session(up.enqueue)
    ctx.status("aa", lambda: dict(up.status))
    ctx.thread(lambda: up.loop(ctx.watcher, ctx.stop), "aa")
    ctx.on_stop(up.wake.set)
    if up.configured:
        log.info("Отправка итогов в AA включена: %s (в очереди %d)", up.status["host"], len(up.queue))
