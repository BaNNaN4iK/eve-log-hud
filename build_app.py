#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Собрать настольное приложение.

  dist/EveLogHUD/EveLogHUD.exe          программа (ядро)
  dist/EveLogHUD/modules/<id>/          модули — обычные папки: удалить папку = удалить модуль
  dist/EveLogHUD-<версия>.zip           всё вместе, для раздачи (в Linux — EveLogHUD-<версия>-linux.tar.gz)
  dist/modules/<id>-<версия>.zip        каждый модуль отдельно (установить — распаковать в modules/)

Нужно: pip install pyinstaller pywebview pystray pillow
Запуск: python build_app.py            (собирает для той системы, где запущен: Windows или Linux)
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
LINUX = sys.platform.startswith("linux")
SEP = os.pathsep                                   # разделитель --add-data у PyInstaller: «;» в Windows, «:» в Linux
# модули пишутся только на стандартной библиотеке Python, но в exe попадает лишь то, что импортирует ядро —
# поэтому всё, что нужно модулям, перечислено здесь (иначе установленный модуль не запустится)
STDLIB_FOR_MODULES = ["tkinter", "tkinter.ttk", "concurrent.futures", "secrets", "hashlib", "base64", "html", "webbrowser",
                      "shutil", "ctypes.wintypes", "importlib.util", "collections", "urllib.request", "urllib.parse",
                      "urllib.error", "http.client", "socket", "typing", "argparse", "uuid", "zipfile", "csv", "math", "gzip", "calendar"]


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
           "--icon", "app.ico", "--add-data", f"dashboard.html{SEP}.", "--add-data", f"app.ico{SEP}.",
           "--hidden-import", "eve_log_watcher", "--hidden-import", "modkit", "--hidden-import", "updater",
           "--collect-submodules", "webview", "--collect-data", "webview"]
    for name in STDLIB_FOR_MODULES:
        cmd += ["--hidden-import", name]
    r = subprocess.run(cmd + ["eve_log_app.py"])
    if r.returncode:
        return r.returncode
    app_dir = os.path.join("dist", NAME)
    mods = copy_modules(os.path.join(app_dir, "modules"))
    if LINUX:
        start = ("Запуск: ./EveLogHUD (или двойной щелчок). Значок появится в трее, если окружение его поддерживает;\n"
                 "окно — встроенное (нужен WebKitGTK) или страница в браузере.\n"
                 "Данные и настройки: ~/.local/share/EveLogHUD (или папка data рядом с программой, если её создать).\n"
                 "Логи EVE ищутся в Steam Proton, Wine, Lutris и Bottles; если не нашлись — укажите папку на вкладке «Настройки».\n")
    else:
        start = ("Запуск: EveLogHUD.exe. Значок появится в трее (возле часов).\n"
                 "Данные и настройки: %LOCALAPPDATA%\\EveLogHUD (или папка data рядом с программой, если её создать).\n"
                 "Windows может предупредить о неизвестном издателе: «Подробнее» -> «Выполнить в любом случае».\n")
    with open(os.path.join(app_dir, "ПРОЧТИ.txt"), "w", encoding="utf-8" if LINUX else "utf-8-sig",
              newline="\n" if LINUX else "\r\n") as f:
        f.write(f"EVE Log HUD {eve_log_watcher.VERSION}\n\n{start}"
                "В игре включите запись логов: Esc -> Чат -> «Вести журнал в файле».\n\n"
                f"Модули (папка modules): {', '.join(m for m, _ in mods)}.\n"
                "Удалить модуль — удалить его папку. Новые версии ставятся кнопкой «Обновить» на вкладке «Настройки».\n")
    zip_base = os.path.join("dist", f"{NAME}-{eve_log_watcher.VERSION}" + ("-linux" if LINUX else ""))
    for ext in (".zip", ".tar.gz"):
        if os.path.exists(zip_base + ext):
            os.remove(zip_base + ext)
    shutil.make_archive(zip_base, "gztar" if LINUX else "zip", "dist", NAME)       # tar.gz сохраняет права на запуск
    archive = zip_base + (".tar.gz" if LINUX else ".zip")
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
    print(f"Готово: {app_dir}/{NAME}{'' if LINUX else '.exe'} ({size // 2**20} МБ), архив {archive} "
          f"({os.path.getsize(archive) // 2**20} МБ), модулей: {len(mods)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
