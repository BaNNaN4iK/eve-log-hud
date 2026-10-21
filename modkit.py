# -*- coding: utf-8 -*-
"""
Модули EVE Log HUD: поиск, включение и подключение к ядру.

Модуль — папка modules/<id>/ с файлом module.json:
  {
    "id": "fleet",                     латиница, цифры, «_»; совпадает с именем папки
    "name": "Флот",                    как показывать в приложении
    "description": "…",
    "version": "1.0.0",
    "entry": "fleet.py",               код для трекера: функция setup(ctx) (необязательно)
    "process": "overlay.py",           или отдельный процесс (оверлей): функция main()
    "web": ["tab.js"],                 файлы для страницы; tab.js добавляет свою вкладку через window.ELW
    "default": true                    включён ли сразу после установки (по умолчанию да)
  }

Установить модуль — положить папку в modules/. Удалить — убрать папку. Выключить, не удаляя, —
на вкладке «Модули» (запоминается в config.json, ключ "modules"). Подробно: modules/README.md.
"""
import importlib.util
import json
import logging
import os
import re
import sys
import threading
from typing import Callable, Dict, List, Optional

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
WEB_RE = re.compile(r"^[A-Za-z0-9_\-]+\.(js|css|png|svg)$")
log = logging.getLogger("modkit")


def modules_dir(core_dir: str) -> str:
    """Где лежат модули: рядом с exe в собранном приложении, рядом с ядром — в исходниках."""
    env = os.environ.get("ELW_MODULES_DIR")
    if env:
        return env
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "modules")
    return os.path.join(core_dir, "modules")


class Module:
    def __init__(self, path: str, meta: dict):
        self.path = path
        self.meta = meta
        self.id = meta["id"]
        self.enabled = False
        self.loaded = False
        self.error = ""
        self.py = None                                       # загруженный код (entry или process)

    def info(self) -> dict:
        m = self.meta
        return {"id": self.id, "name": m.get("name") or self.id, "description": m.get("description", ""),
                "version": m.get("version", ""), "enabled": self.enabled, "loaded": self.loaded, "error": self.error,
                "web": list(m.get("web") or []), "kind": "process" if m.get("process") else "tracker" if m.get("entry") else "data"}


def discover(root: str) -> List[Module]:
    """Все модули из папки; битые описания пропускаются с записью в журнал."""
    out = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for name in names:
        path = os.path.join(root, name)
        mf = os.path.join(path, "module.json")
        if not os.path.isfile(mf):
            continue
        try:
            with open(mf, encoding="utf-8-sig") as f:
                meta = json.load(f)
            if not isinstance(meta, dict) or meta.get("id") != name or not ID_RE.match(name):
                raise ValueError("id должен совпадать с именем папки (латиница, цифры, «_»)")
            for key in ("entry", "process"):
                if meta.get(key) and not re.fullmatch(r"[A-Za-z0-9_]+\.py", meta[key]):
                    raise ValueError(f"{key}: имя .py-файла в папке модуля")
            meta["web"] = [w for w in (meta.get("web") or []) if isinstance(w, str) and WEB_RE.match(w)]
        except (OSError, ValueError) as e:
            log.warning("Модуль %s пропущен: %s", name, e)
            continue
        out.append(Module(path, meta))
    return out


def apply_settings(mods: List[Module], cfg: dict) -> None:
    """Включён ли модуль: config.json → "modules": {"id": true/false}; нет записи — как в module.json."""
    chosen = cfg.get("modules") if isinstance(cfg.get("modules"), dict) else {}
    for m in mods:
        v = chosen.get(m.id)
        m.enabled = v if isinstance(v, bool) else bool(m.meta.get("default", True))


def import_file(m: Module, filename: str):
    """Загрузить .py модуля под уникальным именем (elw_mod_<id>), чтобы модули не мешали друг другу."""
    name = f"elw_mod_{m.id}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(m.path, filename))
    py = importlib.util.module_from_spec(spec)
    sys.modules[name] = py
    try:
        spec.loader.exec_module(py)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return py


class Html:
    """Ответ модуля HTML-страницей (например, «Готово» после входа через EVE)."""

    def __init__(self, code: int, text: str):
        self.code, self.text = code, text


class Context:
    """То, что ядро даёт модулю в setup(ctx)."""

    def __init__(self, module: Module, core, app, stop: threading.Event):
        self.module = module
        self.core = core                                     # само ядро (eve_log_watcher): функции, VERSION, …
        self.app = app
        self.cfg = app.cfg
        self.data_dir = app.data_dir
        self.watcher = app.watcher
        self.online = app.online                             # None, если онлайн-функции выключены
        self.port = app.port
        self.stop = stop
        self.dir = module.path
        self.log = logging.getLogger(f"elw.{module.id}")

    # ----- адреса страницы -----
    def get(self, path: str, fn: Callable) -> None:
        """GET path → fn(qs) → dict (200), (код, dict) или Html."""
        self.app.routes[("GET", path)] = (self.module.id, fn)

    def post(self, path: str, fn: Callable) -> None:
        """POST path → fn(body, qs): body — разобранный JSON или None."""
        self.app.routes[("POST", path)] = (self.module.id, fn)

    # ----- события трекера -----
    def on_session(self, fn: Callable[[dict], None]) -> None:
        """Новая завершённая сессия (не при пересборке истории)."""
        self.watcher.session_hooks.append(fn)

    def on_live(self, fn: Callable[[dict], None]) -> None:
        """Каждая живая сессия перед отдачей странице и оверлею — можно дописать поля."""
        self.watcher.live_hooks.append(fn)

    def status(self, key: str, fn: Callable[[], object]) -> None:
        """Поле в /api/live: live[key] = fn()."""
        self.watcher.status_hooks[key] = fn

    def thread(self, target: Callable, name: str = "") -> threading.Thread:
        t = threading.Thread(target=target, name=name or f"mod-{self.module.id}", daemon=True)
        t.start()
        return t

    def on_stop(self, fn: Callable[[], None]) -> None:
        self.app.stop_hooks.append(fn)


def activate(core, app, root: str, stop: threading.Event) -> List[Module]:
    """Найти модули, применить настройки и запустить setup() у включённых. Ошибка модуля не роняет трекер."""
    mods = discover(root)
    apply_settings(mods, app.cfg)
    for m in mods:
        if not m.enabled or not m.meta.get("entry"):
            continue
        try:
            m.py = import_file(m, m.meta["entry"])
            if hasattr(m.py, "setup"):
                m.py.setup(Context(m, core, app, stop))
            m.loaded = True
            log.info("Модуль %s %s подключён", m.id, m.meta.get("version", ""))
        except Exception as e:
            m.error = f"{type(e).__name__}: {e}"
            log.exception("Модуль %s не подключился", m.id)
    app.modules = mods
    return mods


def find(root: str, mid: str, cfg: Optional[dict] = None) -> Optional[Module]:
    """Модуль по id (для оболочки и командной строки); с cfg — только если включён."""
    for m in discover(root):
        if m.id == mid:
            if cfg is not None:
                apply_settings([m], cfg)
                if not m.enabled:
                    return None
            return m
    return None


def set_enabled(config_path: str, mid: str, enabled: bool, write_json: Callable) -> None:
    """Запомнить выбор в config.json (вступает в силу после перезапуска)."""
    try:
        with open(config_path, encoding="utf-8-sig") as f:
            user = json.load(f)
    except (OSError, ValueError):
        user = {}
    chosen = user.get("modules") if isinstance(user.get("modules"), dict) else {}
    chosen[mid] = bool(enabled)
    user["modules"] = chosen
    write_json(config_path, user)
