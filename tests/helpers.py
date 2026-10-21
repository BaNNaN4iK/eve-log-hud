# -*- coding: utf-8 -*-
"""Общие помощники для тестов: генерация логов EVE, временные папки, конфиг."""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import eve_log_watcher as elw  # noqa: E402
import modkit  # noqa: E402

MODULES = os.path.join(ROOT, "modules")


def module(mid: str):
    """Код модуля (modules/<id>/…) — тот же объект, что загружает трекер."""
    m = modkit.find(MODULES, mid)
    assert m is not None, f"нет модуля {mid}"
    py = modkit.import_file(m, m.meta.get("entry") or m.meta["process"])
    if hasattr(py, "bind"):
        py.bind(elw)
    return py


def ctx(app, mid: str):
    """Контекст, как у модуля в работающем трекере (адреса регистрируются в app.routes)."""
    import threading
    m = modkit.find(MODULES, mid)
    m.enabled = m.loaded = True
    if m not in app.modules:
        app.modules.append(m)
    return modkit.Context(m, elw, app, threading.Event())

DASHES = "-" * 60


def header(who=None, ts=None, english=False):
    ts = ts if ts is not None else time.time()
    started = time.strftime("%Y.%m.%d %H:%M:%S", time.gmtime(ts))
    lines = [DASHES, "  Gamelog" if english else "  Игровой журнал"]
    if who:
        lines.append(("  Listener: " if english else "  Слушатель: ") + who)
    lines.append(("  Session Started: " if english else "  Сеанс начат: ") + started)
    lines.append(DASHES)
    return "\r\n".join(lines) + "\r\n"


def line(ts, typ, text):
    return "[ %s ] (%s) %s\r\n" % (time.strftime("%Y.%m.%d %H:%M:%S", time.gmtime(ts)), typ, text)


def dmg_out(ts, amount, target="Hostile Frigate", weapon="Hobgoblin I", quality="Попал"):
    return line(ts, "combat", f"<color=0xff00ffff><b>{amount}</b> <color=0x77ffffff><font size=10>на</font> "
                              f"<b><color=0xffffffff>{target}</b><font size=10><color=0x77ffffff> - "
                              f"{weapon} - {quality}")


def dmg_in(ts, amount, source="Hostile Frigate", quality="Попал"):
    return line(ts, "combat", f"<color=0xffcc0000><b>{amount}</b> <color=0x77ffffff><font size=10>из</font> "
                              f"<b><color=0xffffffff>{source}</b><font size=10><color=0x77ffffff> - {quality}")


def mine(ts, units, ore="Veldspar"):
    return line(ts, "mining", f"<color=0x77ffffff>Вы добыли <font size=12><color=#ff8dc169>{units}"
                              f"<color=0x77ffffff><font size=10> ед. ресурса <color=0xffffffff><font size=12>"
                              f"<localized hint=\"{ore}\">{ore}*")


def bounty(ts, isk):
    s = f"{isk:,}".replace(",", " ")
    return line(ts, "bounty", f"<font size=12><b><color=0xff00aa00>{s} ISK</b><color=0x77ffffff> "
                              f"добавлено к следующей выплате вознаграждения")


def make_cfg(logs_dir, **kw):
    cfg = dict(elw.DEFAULT_CONFIG)
    cfg.update(logs_dir=logs_dir, online_enabled=False, web_enabled=False)
    cfg.update(kw)
    return cfg


class TempDirs:
    """Временные папки logs/ и data/."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="elw_test_")
        self.logs = os.path.join(self.root, "logs")
        self.data = os.path.join(self.root, "data")
        os.makedirs(self.logs)
        os.makedirs(self.data)

    def write(self, name, text, mode="a"):
        path = os.path.join(self.logs, name)
        with open(path, mode + "b") as f:
            f.write(text.encode("utf-8"))
        return path

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def read_jsonl(path):
    import json
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def read_csv(path):
    import csv
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))
