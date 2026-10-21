#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Собрать настольное приложение.

  dist/EveLogHUD/EveLogHUD.exe          программа (ядро)
  dist/EveLogHUD/modules/<id>/          модули — обычные папки: удалить папку = удалить модуль
  dist/EveLogHUD-<версия>.zip           всё вместе, для раздачи
  dist/modules/<id>-<версия>.zip        каждый модуль отдельно (установить — распаковать в modules/)

Нужно: pip install pyinstaller pywebview pystray pillow
Запуск: python build_app.py
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import eve_log_watcher
import updater  # noqa: E402
import modkit  # noqa: E402

NAME = "EveLogHUD"
# модули пишутся только на стандартной библиотеке Python, но в exe попадает лишь то, что импортирует ядро —
# поэтому всё, что нужно модулям, перечислено здесь (иначе установленный модуль не запустится)
STDLIB_FOR_MODULES = ["tkinter", "tkinter.ttk", "concurrent.futures", "secrets", "hashlib", "base64", "html", "webbrowser",
                      "shutil", "ctypes.wintypes", "importlib.util", "collections", "urllib.request", "urllib.parse",
                      "urllib.error", "http.client", "socket", "typing", "argparse", "uuid", "zipfile", "csv", "math"]


def copy_modules(dst: str) -> list:
    """Модули рядом с exe — без кэшей и тестов. Возвращает [(id, version)]."""
    src = os.path.join(HERE, "modules")
    out = []
    os.makedirs(dst, exist_ok=True)
    for m in modkit.discover(src):
        target = os.path.join(dst, m.id)
        shutil.copytree(m.path, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests", "*.tmp"))
        out.append((m.id, m.meta.get("version", "0")))
    shutil.copy2(os.path.join(src, "README.md"), os.path.join(dst, "README.md"))
    return out


def main() -> int:
    os.chdir(HERE)
    for d in ("build", os.path.join("dist", NAME), os.path.join("dist", "modules")):
        shutil.rmtree(d, ignore_errors=True)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir", "--name", NAME,
           "--icon", "app.ico", "--add-data", "dashboard.html;.", "--add-data", "app.ico;.",
           "--hidden-import", "eve_log_watcher", "--hidden-import", "modkit", "--hidden-import", "updater",
           "--collect-submodules", "webview", "--collect-data", "webview"]
    for name in STDLIB_FOR_MODULES:
        cmd += ["--hidden-import", name]
    r = subprocess.run(cmd + ["eve_log_app.py"])
    if r.returncode:
        return r.returncode
    app_dir = os.path.join("dist", NAME)
    mods = copy_modules(os.path.join(app_dir, "modules"))
    with open(os.path.join(app_dir, "ПРОЧТИ.txt"), "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write("EVE Log HUD %s\n\nЗапуск: EveLogHUD.exe. Значок появится в трее (возле часов).\n"
                "Данные и настройки: %%LOCALAPPDATA%%\\EveLogHUD (или папка data рядом с программой, если её создать).\n"
                "В игре включите запись логов: Esc -> Чат -> «Вести журнал в файле».\n"
                "Windows может предупредить о неизвестном издателе: «Подробнее» -> «Выполнить в любом случае».\n\n"
                "Модули (папка modules): %s.\n"
                "Удалить модуль — удалить его папку. Установить — распаковать архив модуля в папку modules.\n"
                "Включать и выключать — на вкладке «Модули» в окне программы.\n"
                % (eve_log_watcher.VERSION, ", ".join(m for m, _ in mods)))
    zip_base = os.path.join("dist", f"{NAME}-{eve_log_watcher.VERSION}")
    if os.path.exists(zip_base + ".zip"):
        os.remove(zip_base + ".zip")
    shutil.make_archive(zip_base, "zip", "dist", NAME)
    for mid, ver in mods:                                     # каждый модуль отдельным архивом: modules/<id>/…
        shutil.make_archive(os.path.join("dist", "modules", f"{mid}-{ver}"), "zip", os.path.join(app_dir, "modules"), mid)
    size = sum(os.path.getsize(os.path.join(dp, fn)) for dp, _, fns in os.walk(app_dir) for fn in fns)
    # список модулей выпуска с размером и SHA-256 — по нему приложение проверяет и ставит обновления (updater.py)
    entries = []
    for mid, ver in mods:
        with open(os.path.join(app_dir, "modules", mid, "module.json"), encoding="utf-8-sig") as f:
            meta = json.load(f)
        entries.append({"id": mid, "name": meta.get("name", mid), "description": meta.get("description", ""), "version": ver,
                        "file": f"{mid}-{ver}.zip", "path": os.path.join("dist", "modules", f"{mid}-{ver}.zip"),
                        "min_app": meta.get("min_app", "")})
    with open(os.path.join("dist", "modules", updater.INDEX_NAME), "w", encoding="utf-8") as f:
        json.dump(updater.build_index(eve_log_watcher.VERSION, entries), f, ensure_ascii=False, indent=2)
    print(f"Готово: {app_dir}/{NAME}.exe ({size // 2**20} МБ), архив {zip_base}.zip "
          f"({os.path.getsize(zip_base + '.zip') // 2**20} МБ), модулей: {len(mods)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
