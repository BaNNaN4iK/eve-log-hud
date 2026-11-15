# -*- coding: utf-8 -*-
"""
Удаление программы: закрыть её и стереть папку программы, а по желанию — и данные пользователя.

Работающая программа не может удалить сама себя (её файлы заняты), поэтому пишется маленький скрипт во временную
папку: он ждёт, пока все процессы EVE Log HUD завершатся, удаляет папки и удаляет себя. Приложение получает
сигнал закрыться через файл quit.flag в папке данных.

Только для собранной программы (PyInstaller): из исходников — отказ, чтобы случайно не стереть папку с кодом.
"""
import os
import subprocess
import sys
import tempfile
from typing import Optional, Tuple

EXE = "EveLogHUD.exe" if sys.platform == "win32" else "EveLogHUD"
QUIT_FLAG = "quit.flag"


def program_dir() -> Optional[str]:
    """Папка собранной программы — или None, если это не она (запуск из исходников, чужая папка)."""
    if not getattr(sys, "frozen", False):
        return None
    d = os.path.dirname(os.path.abspath(sys.executable))
    if os.path.basename(sys.executable).lower() != EXE.lower() or not os.path.isdir(os.path.join(d, "_internal")):
        return None
    if len(os.path.normpath(d).replace("\\", "/").strip("/").split("/")) < 2:   # не корень диска и не «C:\папка»
        return None
    return d


def safe_data_dir(data: str, prog: str) -> bool:
    """Папку данных стираем, только если это наша папка: …/EveLogHUD (обычная) или <программа>/data (переносная)."""
    data = os.path.normcase(os.path.abspath(data))
    return os.path.basename(data) == os.path.normcase("EveLogHUD") or data == os.path.normcase(os.path.join(prog, "data"))


def _script_win(prog: str, data: Optional[str]) -> str:
    """Удалять папку, пока не получится: файлы заняты, пока программа закрывается (до минуты). Чужие процессы
    и другие копии программы не трогаем — ждём освобождения именно этих папок."""
    q = lambda p: p.replace("%", "%%")
    lines = ["@echo off", "setlocal EnableDelayedExpansion", "chcp 65001 >nul", "ping -n 4 127.0.0.1 >nul"]
    for i, d in enumerate([prog] + ([data] if data else [])):
        lines += ["set N=0", f":try{i}", f'rmdir /s /q "{q(d)}" 2>nul',
                  f'if not exist "{q(d)}" goto done{i}', "set /a N=N+1",
                  "ping -n 2 127.0.0.1 >nul", f"if !N! lss 60 goto try{i}", f":done{i}"]
    lines.append('(goto) 2>nul & del "%~f0"')
    return "\r\n".join(lines) + "\r\n"


def _script_sh(prog: str, data: Optional[str]) -> str:
    sq = lambda p: "'" + p.replace("'", "'\\''") + "'"
    lines = ["#!/bin/sh", "sleep 5", f"rm -rf {sq(prog)}"]
    if data:
        lines.append(f"rm -rf {sq(data)}")
    lines.append('rm -f "$0"')
    return "\n".join(lines) + "\n"


def start(data_dir: str, remove_data: bool) -> Tuple[bool, str]:
    """Запустить удаление. Возвращает (получилось, сообщение). После успеха приложение закроется само."""
    prog = program_dir()
    if prog is None:
        return False, "Удалить можно только собранную программу (EveLogHUD.exe). Запуск из исходников не удаляется."
    data = data_dir if remove_data else None
    if data and not safe_data_dir(data, prog):
        return False, f"Папка данных выглядит необычно ({data}) — удалите её вручную."
    try:
        if sys.platform == "win32":
            fd, path = tempfile.mkstemp(prefix="EveLogHUD-uninstall-", suffix=".cmd")
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(_script_win(prog, data))
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0) | \
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen(["cmd.exe", "/c", path], cwd=tempfile.gettempdir(), creationflags=flags, close_fds=True)
        else:
            fd, path = tempfile.mkstemp(prefix="EveLogHUD-uninstall-", suffix=".sh")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(_script_sh(prog, data))
            os.chmod(path, 0o700)
            subprocess.Popen(["/bin/sh", path], cwd=tempfile.gettempdir(), start_new_session=True, close_fds=True)
        with open(os.path.join(data_dir, QUIT_FLAG), "w") as f:            # приложению — закрыться
            f.write("uninstall")
    except OSError as e:
        return False, f"Не удалось запустить удаление: {e}"
    return True, ("Программа закрывается и удаляется" + (" вместе с данными." if data else ". Ваши данные остались в " + data_dir + "."))
