#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EVE Log HUD — настольное приложение: значок в трее, своё окно, оверлей и трекер логов в одном exe.

Один исполняемый файл играет четыре роли (каждая — отдельный процесс, чтобы сбой окна не ронял сбор логов):
  EveLogHUD.exe             — значок в трее; запускает трекер и открывает окно
  EveLogHUD.exe --tracker   — сбор логов и локальный сервер (eve_log_watcher.py, принимает его аргументы)
  EveLogHUD.exe --window    — окно со страницей трекера
  EveLogHUD.exe --overlay   — оверлей поверх игры

Данные (настройки, история сессий, ключ Alliance Auth) лежат отдельно от программы:
  папка data рядом с exe, если она есть (переносной режим), иначе %LOCALAPPDATA%\\EveLogHUD.
При запуске из исходников (python eve_log_app.py) — рядом со скриптами, как раньше.
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Optional

APP_NAME = "EVE Log HUD"
FROZEN = bool(getattr(sys, "frozen", False))
HERE = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
RES = getattr(sys, "_MEIPASS", HERE)          # где лежат dashboard.html, значок и справочники


def data_dir() -> str:
    env = os.environ.get("EVE_DATA_DIR")
    if env:
        return os.path.abspath(env)
    if not FROZEN:
        return HERE
    portable = os.path.join(HERE, "data")
    if os.path.isdir(portable):
        return portable
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "EveLogHUD")


def port(data: str) -> int:
    try:
        with open(os.path.join(data, "config.json"), encoding="utf-8") as f:
            return int(json.load(f).get("web_port") or 47322)
    except (OSError, ValueError, TypeError):
        return 47322


def role_cmd(role: str, *args: str) -> list:
    """Команда запуска этого же приложения в другой роли."""
    base = [sys.executable] if FROZEN else [sys.executable, os.path.abspath(__file__)]
    return base + ["--" + role] + list(args)


def spawn(role: str, data: str, *args: str) -> subprocess.Popen:
    env = dict(os.environ, EVE_DATA_DIR=data)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(role_cmd(role, *args), env=env, cwd=HERE, creationflags=flags,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def server_up(p: int, timeout: float = 0.5) -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{p}/api/live", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def wait_server(p: int, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if server_up(p):
            return True
        time.sleep(0.3)
    return False


# ---------------------------------------------------------------------------
# Роли
# ---------------------------------------------------------------------------

def run_tracker(argv: list) -> int:
    import eve_log_watcher
    args = list(argv)
    if "--data-dir" not in args:
        args += ["--data-dir", data_dir()]
    return eve_log_watcher.main(args)


def overlay_module(cfg: Optional[dict] = None):
    """Модуль оверлея, если он установлен (и включён, когда передан cfg)."""
    import modkit
    return modkit.find(modkit.modules_dir(HERE), "overlay", cfg)


def run_overlay(argv: list) -> int:
    import modkit
    os.environ.setdefault("EVE_DATA_DIR", data_dir())
    mod = overlay_module()
    if mod is None:
        return 1
    py = modkit.import_file(mod, mod.meta["process"])
    sys.argv = [sys.argv[0]] + list(argv)
    return py.main()


WAIT_PAGE = """<!doctype html><meta charset="utf-8"><title>EVE Log HUD</title>
<body style="margin:0;background:#0f1115;color:#c8d1da;font:15px 'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center;height:100vh">
<div style="text-align:center"><div style="font-size:20px;color:#e8edf2;margin-bottom:8px">EVE Log HUD</div>%s</div></body>"""


def unblock_own_files() -> int:
    """Снять с файлов программы пометку «скачано из интернета» (поток Zone.Identifier).

    Windows ставит её на всё, что распаковано из скачанного архива, а .NET отказывается загружать помеченные
    библиотеки — без этого окно приложения (pywebview → pythonnet → Python.Runtime.dll) падает при запуске.
    Трогаем только свои файлы: папку программы. Возвращает, сколько пометок снято.
    """
    if not FROZEN or sys.platform != "win32":
        return 0
    n = 0
    for root in {RES, HERE}:
        for dp, _, fns in os.walk(root):
            for fn in fns:
                if fn.lower().endswith((".dll", ".exe", ".pyd")):
                    try:
                        os.remove(os.path.join(dp, fn) + ":Zone.Identifier")
                        n += 1
                    except OSError:
                        pass
    return n


def run_window(argv: list) -> int:
    data = data_dir()
    try:
        return _run_window(data)
    except Exception as e:                                       # окно не открылось — показать страницу в браузере
        try:
            with open(os.path.join(data, "window_error.log"), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} окно не открылось: {e!r}\n")
        except OSError:
            pass
        p = port(data)
        wait_server(p, 25)
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{p}/")
        return 1


def _run_window(data: str) -> int:
    import webview
    p = port(data)
    url = f"http://127.0.0.1:{p}/"
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True           # кнопка «Скачать CSV»
    except Exception:
        pass
    win = webview.create_window(APP_NAME, html=WAIT_PAGE % "Запускаю трекер логов…", width=1280, height=860,
                                min_size=(900, 600), background_color="#0f1115")

    def load():
        if wait_server(p, 25):
            win.load_url(url)
        else:
            win.load_html(WAIT_PAGE % ("Трекер логов не отвечает.<br><span style='color:#9aa7b4;font-size:13px'>"
                                       "Закройте приложение через значок в трее и запустите снова. "
                                       "Журнал: watcher.log в папке данных.</span>"))

    storage = os.path.join(data, "webview")                  # тема и настройки страницы переживают перезапуск
    os.makedirs(storage, exist_ok=True)
    webview.start(load, private_mode=False, storage_path=storage)
    return 0


class Shell:
    """Значок в трее: держит трекер запущенным, открывает окно, включает оверлей."""

    def __init__(self):
        self.data = data_dir()
        os.makedirs(self.data, exist_ok=True)
        self.port = port(self.data)
        self.children = {"tracker": None, "window": None, "overlay": None}
        self.own_tracker = False
        self.prefs_path = os.path.join(self.data, "app.json")
        self.prefs = {"overlay": True}
        try:
            with open(self.prefs_path, encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    self.prefs.update({k: v for k, v in d.items() if k in self.prefs and isinstance(v, bool)})
        except (OSError, ValueError):
            pass

    def save_prefs(self):
        try:
            with open(self.prefs_path, "w", encoding="utf-8") as f:
                json.dump(self.prefs, f)
        except OSError:
            pass

    def alive(self, name: str) -> bool:
        c = self.children.get(name)
        return c is not None and c.poll() is None

    def ensure_tracker(self):
        if server_up(self.port) or self.alive("tracker"):
            return                                           # уже работает (в том числе запущенный отдельно)
        self.children["tracker"] = spawn("tracker", self.data)
        self.own_tracker = True

    def open_window(self, *_):
        self.ensure_tracker()
        if not self.alive("window"):
            self.children["window"] = spawn("window", self.data)

    def overlay_available(self) -> bool:
        """Модуль оверлея установлен и включён на вкладке «Модули»."""
        try:
            with open(os.path.join(self.data, "config.json"), encoding="utf-8-sig") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = {}
        return overlay_module(cfg if isinstance(cfg, dict) else {}) is not None

    def set_overlay(self, on: bool):
        if on and not self.overlay_available():
            on = False
        if on and not self.alive("overlay"):
            self.children["overlay"] = spawn("overlay", self.data)
        elif not on and self.alive("overlay"):
            self.children["overlay"].terminate()

    def toggle_overlay(self, *_):
        self.prefs["overlay"] = not self.alive("overlay")
        self.save_prefs()
        self.set_overlay(self.prefs["overlay"])

    def open_data(self, *_):
        os.startfile(self.data)

    def watchdog(self, stop: threading.Event):
        """Трекер должен работать всё время, пока приложение запущено."""
        while not stop.wait(15):
            self.ensure_tracker()

    def quit(self, icon=None, *_):
        for name in ("overlay", "window"):
            if self.alive(name):
                self.children[name].terminate()
        if self.own_tracker and self.alive("tracker"):
            try:                                             # вежливая остановка: трекер допишет историю и выйдет
                open(os.path.join(self.data, "stop.flag"), "w").close()
                self.children["tracker"].wait(timeout=12)
            except (OSError, subprocess.TimeoutExpired):
                self.children["tracker"].terminate()
        if icon is not None:
            icon.stop()

    def run(self) -> int:
        import pystray
        from PIL import Image
        self.ensure_tracker()
        self.open_window()
        if self.prefs["overlay"]:
            self.set_overlay(True)
        stop = threading.Event()
        threading.Thread(target=self.watchdog, args=(stop,), daemon=True).start()
        image = Image.open(os.path.join(RES, "app.ico"))
        menu = pystray.Menu(
            pystray.MenuItem("Открыть окно", self.open_window, default=True),
            pystray.MenuItem("Оверлей поверх игры", self.toggle_overlay, checked=lambda item: self.alive("overlay"),
                             visible=lambda item: self.overlay_available()),
            pystray.MenuItem("Папка с данными", self.open_data),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", self.quit))
        icon = pystray.Icon("EveLogHUD", image, APP_NAME, menu)
        try:
            icon.run()
        finally:
            stop.set()
        return 0


def already_running() -> bool:
    """Второй запуск не плодит значки: просто открывает окно у уже работающего приложения."""
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "EveLogHUDShell")
    return ctypes.windll.kernel32.GetLastError() == 183


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] == "--window":
        unblock_own_files()
    if argv and argv[0] == "--tracker":
        return run_tracker(argv[1:])
    if argv and argv[0] == "--overlay":
        return run_overlay(argv[1:])
    if argv and argv[0] == "--window":
        return run_window(argv[1:])
    if sys.platform != "win32":
        print("Приложение работает только в Windows.")
        return 1
    if already_running():
        spawn("window", data_dir())
        return 0
    return Shell().run()


if __name__ == "__main__":
    sys.exit(main())
