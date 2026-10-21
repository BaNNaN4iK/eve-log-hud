#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EVE Log Watcher — фоновое приложение для Windows.

Следит за папкой игровых логов EVE Online, считает итоги каждой игровой сессии
(урон, DPS по оружию, получено, ремонт, нейты, варп-глушение, баунти, добыча руды)
и показывает их на локальной веб-странице http://localhost:47322.

Только стандартная библиотека Python 3.9+.
Сеть: только esi.evetech.net и images.evetech.net (названия предметов/систем,
цены Jita, иконки). Логи, ники и статистика наружу не уходят.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import html
import io
import json
import logging
import logging.handlers
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import modkit
import updater
from collections import namedtuple
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Iterable, List, Optional, Tuple

VERSION = "2.2.1"
UPDATE_REPO = "BaNNaN4iK/eve-log-hud"                     # официальный репозиторий для обновлений: «владелец/репозиторий»
APP_NAME = "EVE Log Watcher"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_VERSION = 2
RECORD_VERSION = 2

log = logging.getLogger("eve_log_watcher")

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "logs_dir": "",                    # пусто = найти автоматически (Документы, OneDrive)
    "session_gap_seconds": 300,
    "min_session_seconds": 20,
    "poll_seconds": 5,
    "import_days": 30,                 # сколько дней логов читать при первом запуске
    "characters": [],                  # пустой список = все персонажи
    "web_enabled": True,
    "web_port": 47322,
    "lock_port": 47321,
    "state_save_seconds": 30,
    "online_enabled": True,            # ESI: названия, объёмы, системы, цены, иконки
    "price_auto_refresh_minutes": 60,  # автообновление цен, пока открыта страница (0 = только кнопкой)
    "esi_contact": "",                 # контакт для User-Agent ESI (необязательно)
    "ore_prices_override": {},         # {"Veldspar": 15.5} — ручные цены, приоритетнее ESI
    "notifiers": {},                   # зарезервировано для будущих получателей (Discord и т.п.)
    "aa_url": "",                      # Alliance Auth с плагином Fleet Watch (пусто = не отправлять)
    "aa_key": "",                      # личный ключ со страницы «Мои логи» в AA
    "aa_live_upload": True,            # отправлять идущую сессию раз в минуту
    "esi_client_id": "",               # Client ID приложения EVE (developers.eveonline.com) — флот без Alliance Auth
    "update_check": True,              # сверять версии приложения и модулей с последним выпуском на GitHub
    "update_check_hours": 6,
    "update_repo": "",                 # «владелец/репозиторий» на GitHub; пусто = официальный (UPDATE_REPO)
}

_INT_LIMITS = {
    "session_gap_seconds": (10, 86400),
    "min_session_seconds": (0, 86400),
    "poll_seconds": (1, 3600),
    "import_days": (1, 3650),
    "web_port": (1024, 65535),
    "lock_port": (1024, 65535),
    "state_save_seconds": (1, 3600),
    "price_auto_refresh_minutes": (0, 10080),
    "update_check_hours": (1, 168),
}


def load_config(data_dir: str) -> dict:
    """Читает config.json; создаёт его с настройками по умолчанию, дописывает новые ключи."""
    path = os.path.join(data_dir, "config.json")
    cfg = dict(DEFAULT_CONFIG)
    changed = False
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                user = json.load(f)
            if not isinstance(user, dict):
                raise ValueError("корень config.json должен быть объектом")
            cfg.update(user)
            changed = any(k not in user for k in DEFAULT_CONFIG)
        except Exception as e:
            log.error("config.json не прочитан (%s) — использую настройки по умолчанию", e)
    else:
        changed = True
    for key, (lo, hi) in _INT_LIMITS.items():
        try:
            v = int(cfg[key])
        except (TypeError, ValueError):
            v = DEFAULT_CONFIG[key]
        cfg[key] = max(lo, min(hi, v))
    if not isinstance(cfg.get("characters"), list):
        cfg["characters"] = []
    if not isinstance(cfg.get("ore_prices_override"), dict):
        cfg["ore_prices_override"] = {}
    if changed:
        try:
            atomic_write_json(path, {k: cfg[k] for k in cfg}, indent=2)
        except OSError as e:
            log.error("Не удалось записать config.json: %s", e)
    return cfg


def documents_candidates() -> List[str]:
    """Возможные расположения папки «Документы» (в т.ч. перенаправленной в OneDrive)."""
    cands: List[str] = []
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            # CSIDL_PERSONAL = 5 — реальный путь «Документов», учитывает перенаправление
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                cands.append(buf.value)
        except Exception:
            pass
    home = os.path.expanduser("~")
    for env in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        v = os.environ.get(env)
        if v:
            cands += [os.path.join(v, "Documents"), os.path.join(v, "Документы")]
    cands += [os.path.join(home, "Documents"), os.path.join(home, "OneDrive", "Documents"),
              os.path.join(home, "OneDrive", "Документы")]
    out: List[str] = []
    for c in cands:
        if c and c not in out:
            out.append(c)
    return out


def detect_logs_dir() -> str:
    cands = [os.path.join(d, "EVE", "logs", "Gamelogs") for d in documents_candidates()]
    for p in cands:
        if os.path.isdir(p):
            return p
    return cands[0] if cands else os.path.join(os.path.expanduser("~"), "Documents", "EVE", "logs", "Gamelogs")


def resolve_logs_dir(cfg: dict) -> str:
    d = (cfg.get("logs_dir") or "").strip()
    return os.path.expandvars(os.path.expanduser(d)) if d else detect_logs_dir()


# ---------------------------------------------------------------------------
# Вспомогательные функции ввода-вывода
# ---------------------------------------------------------------------------

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


def atomic_write_json(path: str, data, indent=None) -> None:
    """Атомарная запись: временный файл + fsync + os.replace."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent, separators=None if indent else (",", ":"))
        f.flush()
        os.fsync(f.fileno())
    for attempt in range(5):
        try:
            replace_file(tmp, path)
            return
        except PermissionError:
            # на Windows файл может быть кратко занят антивирусом/индексатором
            if attempt == 4:
                raise
            time.sleep(0.1 * (attempt + 1))


def repair_tail(path: str) -> None:
    """Если последняя строка файла неполная (сбой во время записи) — отрезать её."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    if size == 0:
        return
    with open(path, "rb+") as f:
        f.seek(-1, os.SEEK_END)
        if f.read(1) == b"\n":
            return
        chunk = min(size, 1 << 20)
        f.seek(size - chunk)
        data = f.read(chunk)
        idx = data.rfind(b"\n")
        new_size = (size - chunk + idx + 1) if idx >= 0 else 0
        f.truncate(new_size)
    log.warning("%s: отрезана неполная последняя строка (последствие сбоя)", os.path.basename(path))


def digits(s: str) -> int:
    s = s.strip()
    neg = s.startswith("-")
    d = re.sub(r"\D", "", s)
    if not d:
        return 0
    v = int(d)
    return -v if neg else v


def num_isk(s: str) -> float:
    """'8 250' / '79 688,50' -> число."""
    s = re.sub(r"[\s  ]", "", s)
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return float(digits(s))


# ---------------------------------------------------------------------------
# Разбор строк лога
# ---------------------------------------------------------------------------

Event = namedtuple("Event", "ts kind data hints")

LINE_RE = re.compile(r"^\[ (\d{4})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2}):(\d{2}) \] \(([^)]*)\) ?(.*)$")
TAG_RE = re.compile(r"<[^>]*>")
HINT_RE = re.compile(r'<localized hint="([^"]*)">([^<*]*)')   # видимый текст заканчивается на '*' 
COLOR_RE = re.compile(r"<color=(?:0x|#)([0-9a-fA-F]{6,8})>")
TARGET_B_RE = re.compile(r"<b><color=(?:0x|#)[0-9a-fA-F]{6,8}>(.*?)</b>")
HEADER_LISTENER_RE = re.compile(r"^\s*(?:Слушатель|Listener):\s*(.+?)\s*$", re.M)
HEADER_DASHES_RE = re.compile(r"^-{20,}\s*$", re.M)

IGNORED_TYPES = {"hint", "info", "notify", "question", "warning"}

QUALITIES = {
    "Попал", "Царапнул", "Пробил", "Скользнул", "Сокрушил", "Раздробил",
    "Hits", "Grazes", "Penetrates", "Glances Off", "Smashes", "Wrecks", "Barely Scratches",
}
# Порядок для страницы (от слабого к сильному)
QUALITY_ORDER = ["Царапнул", "Скользнул", "Попал", "Пробил", "Раздробил", "Сокрушил"]   # от слабого к сильному

INCOMING_NEUT_COLOR = "ffe57f7f"   # цвет строки нейта/носа, когда энергию сливают у вас

NUM = r"-?\d[\d\s]*"
DMG_HEAD_RE = re.compile(r"^(\d[\d\s]*) (на|из|to|from) (.+)$")
REFL_RE = re.compile(r"\s*\((?:Отражено|Reflected) (\d[\d\s]*)\)$")
MISS_IN_RE = re.compile(r"^(.+?): промах мимо вашего корабля(?: - (.+))?$")
MISS_IN_PILOT_RE = re.compile(r"^Орудие (.+?) пилота (.+?) промахнулось мимо вашего корабля(?: - .+)?$")
MISS_OUT_RE = re.compile(r"^(?:Ваше орудие|Ваша группа) (.+?) промахнул(?:ось|ась) мимо (.+)$")
NEUT_RE = re.compile(r"^(" + NUM + r") ГДж энергии нейтрализовано (.+)$")
NOS_RE = re.compile(r"^(" + NUM + r") ГДж энергии извлечено и передано (.+)$")
REP_IN_RE = re.compile(r"^(\d[\d\s]*) единиц запаса прочности (щитов|брони|корпуса) получено "
                       r"(?:накачкой|дистанционным ремонтом) от (.+)$")
REP_OUT_RE = re.compile(r"^(\d[\d\s]*) единиц запаса прочности (щитов) накачано (.+)$")
WARP_RE = re.compile(r"^Попытка (варп-глушения|варп-подавления): источник (.+?), цель (.+)$")
JAM_IN_RE = re.compile(r"^Вы под действием помех сопровождению целей от (.+)$")
JAM_OUT_RE = re.compile(r"^Сопровождение целей (.+?) приостановлено(?: - (.+))?$")
MINE_RE = re.compile(r"^Вы добыли (\d[\d\s]*) ед\. (?:ресурса|руды) (.+?)"
                     r"(?: и утратили (\d[\d\s]*) ед\. отходов\.?)?$")
MINE_CRIT_RE = re.compile(r"^Успешный крит\. удар! Вы добыли ещё (\d[\d\s]*) ед\. ресурса (.+)$")
RESIDUE_RE = re.compile(r"^Ещё (\d[\d\s]*) ед\. превратилось в отходы\.?$")
BOUNTY_RE = re.compile(r"^(\d[\d\s.,]*) ISK добавлено к следующей (?:выплате вознаграждения|награде за голову)")
JUMP_RE = re.compile(r"^Осуществляется прыжок из (.+) в (.+?)\.?$")
UNDOCK_RE = re.compile(r"^Выход из дока (.+) в звездную систему (.+?)\.?$")

LAYERS = {"щитов": "щиты", "брони": "броня", "корпуса": "корпус"}
WARP_LABELS = {"варп-глушения": "Варп-глушение", "варп-подавления": "Варп-подавление"}


def clean_text(raw: str) -> str:
    """Снять теги, &-сущности, '*', неразрывные пробелы; схлопнуть пробелы."""
    s = TAG_RE.sub("", raw)
    s = html.unescape(s)
    s = s.replace(" ", " ").replace(" ", " ").replace("*", "")
    return re.sub(r"\s+", " ", s).strip()


def extract_hints(raw: str) -> Dict[str, str]:
    """Пары «видимое название → англ. название из hint» (для запросов к ESI)."""
    out = {}
    for hint, vis in HINT_RE.findall(raw):
        v = clean_text(vis)
        h = clean_text(hint)
        if v and h:
            out[v] = h
    return out


def split_actor(name: str) -> Tuple[str, str, str]:
    """'Qvatra[.RO.](Vedmak)' -> ('Qvatra', '.RO.', 'Vedmak')."""
    m = re.match(r"^(.*?)(?:\[([^\]]*)\])?(?:\(([^()]*)\))?$", name.strip())
    base, ticker, ship = (m.group(1) or "").strip(), m.group(2) or "", m.group(3) or ""
    if not base:  # имя целиком в скобках — оставить как есть
        return name.strip(), "", ""
    return base, ticker, ship


def actor_from_slashes(s: str) -> str:
    """'Pioneer // NeutPilot NEUTS /' -> 'NeutPilot NEUTS (Pioneer)'."""
    s = s.strip()
    if " // " in s:
        ship, rest = s.split(" // ", 1)
        rest = rest.strip().rstrip("/").strip()
        return f"{rest} ({ship.strip()})" if rest else ship.strip()
    return s.rstrip("/").strip()


def split_module(s: str) -> Tuple[str, Optional[str]]:
    """'Pioneer // X NEUTS / - Small Energy Neutralizer II' -> (источник, модуль)."""
    if " - " in s:
        a, b = s.rsplit(" - ", 1)
        return a.strip(), b.strip()
    return s.strip(), None


def _looks_like_weapon(part: str) -> bool:
    return not re.search(r"\[[^\]]*\]|\)\s*$", part)


def parse_damage(text: str, raw: str) -> Optional[dict]:
    m = DMG_HEAD_RE.match(text)
    if not m:
        return None
    total = digits(m.group(1))
    direction = "out" if m.group(2) in ("на", "to") else "in"
    rest = m.group(3)
    refl = 0
    mr = REFL_RE.search(rest)
    if mr:
        refl = digits(mr.group(1))
        rest = rest[:mr.start()]
    parts = rest.split(" - ")
    quality = None
    while len(parts) > 1 and parts[-1].strip() in QUALITIES:
        quality = parts.pop().strip()
    body = " - ".join(parts).strip()
    target, weapon = None, None
    # Основной способ: имя цели в сыром тексте выделено <b><color=...>...</b>
    mb = TARGET_B_RE.search(raw) if raw else None
    if mb:
        tname = clean_text(mb.group(1))
        if tname and body.startswith(tname):
            remainder = body[len(tname):]
            if remainder == "":
                target = tname
            elif remainder.startswith(" - "):
                target, weapon = tname, remainder[3:].strip() or None
    if target is None:
        # Запасной способ: разбор с конца строки
        if len(parts) >= 2 and _looks_like_weapon(parts[-1]):
            weapon = parts[-1].strip()
            target = " - ".join(parts[:-1]).strip()
        else:
            target = body
    base, ticker, ship = split_actor(target)
    return {"dir": direction, "amount": total, "refl": min(refl, total), "quality": quality,
            "target": base, "ticker": ticker, "ship": ship, "weapon": weapon}


def first_color(raw: str) -> str:
    m = COLOR_RE.search(raw or "")
    return m.group(1).lower().rjust(8, "f") if m else ""


def parse_combat(text: str, raw: str) -> Optional[Tuple[str, dict]]:
    d = parse_damage(text, raw)
    if d:
        return ("dmg", d)
    m = MISS_IN_PILOT_RE.match(text)
    if m:
        return ("miss_in", {"attacker": split_actor(m.group(2))[0], "weapon": m.group(1).strip()})
    m = MISS_IN_RE.match(text)
    if m:
        return ("miss_in", {"attacker": split_actor(m.group(1))[0],
                            "weapon": (m.group(2) or "").strip() or None})
    m = MISS_OUT_RE.match(text)
    if m:
        weapon, rest = m.group(1).strip(), m.group(2).strip()
        suffix = " - " + weapon
        target = rest[:-len(suffix)] if rest.endswith(suffix) else split_module(rest)[0]
        return ("miss_out", {"weapon": weapon, "target": split_actor(target)[0]})
    m = NEUT_RE.match(text) or NOS_RE.match(text)
    if m:
        # Известен только цвет входящих нейтов/носов; исходящие не придумываем
        if first_color(raw) == INCOMING_NEUT_COLOR:
            src, module = split_module(m.group(2))
            kind = "neut_in" if "нейтрализовано" in text else "nos_in"
            return (kind, {"amount": abs(digits(m.group(1))), "source": actor_from_slashes(src), "module": module})
        return None
    m = REP_IN_RE.match(text)
    if m:
        src, module = split_module(m.group(3))
        return ("rep_in", {"amount": digits(m.group(1)), "layer": LAYERS[m.group(2)],
                           "source": actor_from_slashes(src), "module": module})
    m = REP_OUT_RE.match(text)
    if m:
        tgt, module = split_module(m.group(3))
        return ("rep_out", {"amount": digits(m.group(1)), "layer": LAYERS[m.group(2)],
                            "target": actor_from_slashes(tgt), "module": module})
    m = WARP_RE.match(text)
    if m:
        src, tgt = m.group(2).strip(), m.group(3).strip()
        return ("warp", {"kind": WARP_LABELS[m.group(1)],
                         "source_me": src == "вы", "target_me": tgt.rstrip("!") == "вы",
                         "source": actor_from_slashes(src), "target": actor_from_slashes(tgt.rstrip("!"))})
    m = JAM_IN_RE.match(text)
    if m:
        src, module = split_module(m.group(1))
        return ("jam_in", {"source": actor_from_slashes(src), "module": module})
    m = JAM_OUT_RE.match(text)
    if m:
        return ("jam_out", {"target": actor_from_slashes(m.group(1)), "module": (m.group(2) or "").strip() or None})
    return None


def parse_mining(text: str) -> Optional[Tuple[str, dict]]:
    m = MINE_RE.match(text)
    if m:
        return ("mine", {"ore": m.group(2).strip(), "units": digits(m.group(1)),
                         "residue": digits(m.group(3)) if m.group(3) else 0})
    m = MINE_CRIT_RE.match(text)
    if m:
        return ("mine_crit", {"ore": m.group(2).strip(), "units": digits(m.group(1))})
    m = RESIDUE_RE.match(text)
    if m:
        return ("residue", {"units": digits(m.group(1))})
    return None


def parse_bounty(text: str) -> Optional[Tuple[str, dict]]:
    m = BOUNTY_RE.match(text)
    if m:
        return ("bounty", {"isk": num_isk(m.group(1))})
    return None


def parse_location(text: str) -> Optional[Tuple[str, dict]]:
    m = JUMP_RE.match(text)
    if m:
        return ("system", {"system": m.group(2).strip(), "from": m.group(1).strip()})
    m = UNDOCK_RE.match(text)
    if m:
        return ("system", {"system": m.group(2).strip(), "station": m.group(1).strip()})
    return None


def parse_line(line: str) -> Optional[Event]:
    """Строка лога -> Event или None (заголовок, служебные сообщения)."""
    m = LINE_RE.match(line.rstrip("\r\n"))
    if not m:
        return None
    g = m.groups()
    ts = calendar.timegm((int(g[0]), int(g[1]), int(g[2]), int(g[3]), int(g[4]), int(g[5])))
    typ, raw = g[6], g[7]
    if typ in IGNORED_TYPES:
        return None
    text = clean_text(raw)
    if typ == "combat":
        r = parse_combat(text, raw)
    elif typ == "mining":
        r = parse_mining(text)
    elif typ == "bounty":
        r = parse_bounty(text)
    elif typ == "None":
        r = parse_location(text)
        if r is None:
            return None   # прочие системные сообщения (док, связь) не считаются
    else:
        return None
    if r is None:
        return Event(ts, "unparsed", {"type": typ, "text": text, "raw": raw[:500]}, {})
    return Event(ts, r[0], r[1], extract_hints(raw))


def parse_header(text: str) -> Tuple[bool, Optional[str]]:
    """(заголовок полностью записан?, имя персонажа или None)."""
    m = HEADER_LISTENER_RE.search(text)
    complete = len(HEADER_DASHES_RE.findall(text)) >= 2 or bool(re.search(r"^\[ \d{4}\.", text, re.M))
    return complete, (m.group(1).strip() if m else None)


def unparsed_key(text: str) -> str:
    k = re.sub(r"\d[\d\s.,]*", "N", text)
    return k[:120]


# ---------------------------------------------------------------------------
# Сессия: накопление и итоговая запись
# ---------------------------------------------------------------------------

NO_WEAPON = "(без оружия)"
NO_SYSTEM = "(неизвестно)"


def _inc(d: dict, k, v=1):
    d[k] = d.get(k, 0) + v


def new_session(who: str, ts: int) -> dict:
    return {
        "who": who, "t0": ts, "t1": ts, "first_out": None, "last_out": None,
        "first_in": None, "last_in": None,
        "out": 0, "in": 0, "refl": 0, "miss_in": 0, "miss_out": 0, "hits_out": 0, "hits_in": 0,
        "bounty": 0.0, "bounty_n": 0, "residue": 0, "cycles": 0, "last_ore": None,
        "ore": {}, "ore_crit": {}, "ore_residue": {}, "ore_cycles": {},
        "weapons": {}, "targets": {}, "attackers": {}, "in_weapons": {},
        "reps_in": {}, "reps_out": {}, "reps_in_from": {}, "reps_out_to": {},
        "neut_in": {"gj": 0, "n": 0, "from": {}}, "nos_in": {"gj": 0, "n": 0, "from": {}},
        "ewar": {}, "systems": {},
        "sec_out": {}, "sec_in": {}, "min": {},
        "unparsed": 0, "events": 0,
    }


def session_add(s: dict, ev: Event, system: Optional[str]) -> None:
    ts = ev.ts
    if ts < s["t0"]:
        s["t0"] = ts
    if ts > s["t1"]:
        s["t1"] = ts
    s["events"] += 1
    k, d = ev.kind, ev.data
    mkey = str(ts - ts % 60)
    sys_name = system or NO_SYSTEM
    sysd = s["systems"].setdefault(sys_name, {"out": 0, "in": 0, "bounty": 0.0, "ore": 0, "n": 0,
                                              "t0": ts, "t1": ts})
    sysd["n"] += 1
    sysd["t0"] = min(sysd["t0"], ts)
    sysd["t1"] = max(sysd["t1"], ts)

    def pm(i, v):
        row = s["min"].setdefault(mkey, [0, 0, 0, 0])
        row[i] += v

    if k == "dmg":
        amount, refl = d["amount"], d["refl"]
        if d["dir"] == "out":
            net = max(0, amount - refl)
            w = d["weapon"] or NO_WEAPON
            s["out"] += net
            s["refl"] += refl
            s["hits_out"] += 1
            s["first_out"] = ts if s["first_out"] is None else min(s["first_out"], ts)
            s["last_out"] = ts if s["last_out"] is None else max(s["last_out"], ts)
            ws = s["weapons"].setdefault(w, {"dmg": 0, "hits": 0, "miss": 0, "max": 0, "refl": 0,
                                             "q": {}, "t0": ts, "t1": ts, "targets": {}})
            ws["dmg"] += net
            ws["hits"] += 1
            ws["refl"] += refl
            ws["max"] = max(ws["max"], net)
            ws["t0"] = min(ws["t0"], ts)
            ws["t1"] = max(ws["t1"], ts)
            if d["quality"]:
                _inc(ws["q"], d["quality"])
            _inc(ws["targets"], d["target"], net)
            t = s["targets"].setdefault(d["target"], {"dmg": 0, "hits": 0, "miss": 0, "refl": 0, "max": 0,
                                                      "ship": d["ship"], "ticker": d["ticker"],
                                                      "t0": ts, "t1": ts, "weapons": {}})
            t["dmg"] += net
            t["hits"] += 1
            t["refl"] += refl
            t["max"] = max(t["max"], net)
            t["t1"] = max(t["t1"], ts)
            if d["ship"]:
                t["ship"] = d["ship"]
            _inc(t["weapons"], w, net)
            _inc(s["sec_out"].setdefault(w, {}), str(ts), net)
            _inc(t.setdefault("s10", {}), str(ts - ts % 10), net)   # по цели — для сопоставления с киллмейлами
            pm(0, net)
            sysd["out"] += net
        else:
            s["in"] += amount
            s["hits_in"] += 1
            s["first_in"] = ts if s["first_in"] is None else min(s["first_in"], ts)
            s["last_in"] = ts if s["last_in"] is None else max(s["last_in"], ts)
            a = s["attackers"].setdefault(d["target"], {"dmg": 0, "hits": 0, "miss": 0, "max": 0,
                                                        "ship": d["ship"], "ticker": d["ticker"],
                                                        "q": {}, "weapons": {}})
            a["dmg"] += amount
            a["hits"] += 1
            a["max"] = max(a["max"], amount)
            if d["ship"]:
                a["ship"] = d["ship"]
            if d["quality"]:
                _inc(a["q"], d["quality"])
            w = d["weapon"] or "(не указано)"
            _inc(a["weapons"], w, amount)
            iw = s["in_weapons"].setdefault(w, {"dmg": 0, "hits": 0, "miss": 0, "max": 0})
            iw["dmg"] += amount
            iw["hits"] += 1
            iw["max"] = max(iw["max"], amount)
            _inc(s["sec_in"], str(ts), amount)
            _inc(a.setdefault("s10", {}), str(ts - ts % 10), amount)   # от атакующего — для киллмейлов
            pm(1, amount)
            sysd["in"] += amount
    elif k == "miss_in":
        s["miss_in"] += 1
        a = s["attackers"].setdefault(d["attacker"], {"dmg": 0, "hits": 0, "miss": 0, "max": 0,
                                                      "ship": "", "ticker": "", "q": {}, "weapons": {}})
        a["miss"] += 1
        if d.get("weapon"):
            iw = s["in_weapons"].setdefault(d["weapon"], {"dmg": 0, "hits": 0, "miss": 0, "max": 0})
            iw["miss"] += 1
    elif k == "miss_out":
        s["miss_out"] += 1
        ws = s["weapons"].setdefault(d["weapon"], {"dmg": 0, "hits": 0, "miss": 0, "max": 0, "refl": 0,
                                                   "q": {}, "t0": ts, "t1": ts, "targets": {}})
        ws["miss"] += 1
        ws["t0"] = min(ws["t0"], ts)
        ws["t1"] = max(ws["t1"], ts)
        t = s["targets"].setdefault(d["target"], {"dmg": 0, "hits": 0, "miss": 0, "refl": 0, "max": 0,
                                                  "ship": "", "ticker": "", "t0": ts, "t1": ts, "weapons": {}})
        t["miss"] += 1
    elif k in ("neut_in", "nos_in"):
        n = s[k]
        n["gj"] += d["amount"]
        n["n"] += 1
        _inc(n["from"], d["source"], d["amount"])
    elif k == "rep_in":
        r = s["reps_in"].setdefault(d["layer"], {"hp": 0, "n": 0})
        r["hp"] += d["amount"]
        r["n"] += 1
        _inc(s["reps_in_from"], d["source"], d["amount"])
    elif k == "rep_out":
        r = s["reps_out"].setdefault(d["layer"], {"hp": 0, "n": 0})
        r["hp"] += d["amount"]
        r["n"] += 1
        _inc(s["reps_out_to"], d["target"], d["amount"])
    elif k == "warp":
        if d["source_me"]:
            label, other = d["kind"] + " — вы наложили", d["target"]
        elif d["target_me"]:
            label, other = d["kind"] + " — по вам", d["source"]
        else:
            label, other = d["kind"] + " — между другими", d["source"] + " → " + d["target"]
        e = s["ewar"].setdefault(label, {"n": 0, "who": {}})
        e["n"] += 1
        _inc(e["who"], other)
    elif k == "jam_in":
        e = s["ewar"].setdefault("Помехи сопровождению — по вам", {"n": 0, "who": {}})
        e["n"] += 1
        _inc(e["who"], d["source"])
    elif k == "jam_out":
        e = s["ewar"].setdefault("Сопровождение целей подавлено — вами", {"n": 0, "who": {}})
        e["n"] += 1
        _inc(e["who"], d["target"])
    elif k == "mine":
        ore = d["ore"]
        _inc(s["ore"], ore, d["units"])
        _inc(s["ore_cycles"], ore)
        s["cycles"] += 1
        s["last_ore"] = ore
        if d["residue"]:
            _inc(s["ore_residue"], ore, d["residue"])
            s["residue"] += d["residue"]
        pm(2, d["units"])
        sysd["ore"] += d["units"]
    elif k == "mine_crit":
        ore = d["ore"]
        _inc(s["ore"], ore, d["units"])
        _inc(s["ore_crit"], ore, d["units"])
        pm(2, d["units"])
        sysd["ore"] += d["units"]
    elif k == "residue":
        s["residue"] += d["units"]
        _inc(s["ore_residue"], s.get("last_ore") or "(неизвестно)", d["units"])
    elif k == "bounty":
        s["bounty"] += d["isk"]
        s["bounty_n"] += 1
        pm(3, d["isk"])
        sysd["bounty"] += d["isk"]
    elif k == "unparsed":
        s["unparsed"] += 1


def peak_window(sec: Dict[int, float], window: int = 30) -> float:
    """Пиковый DPS: максимум суммы урона в любом окне длиной window секунд, делённый на window."""
    items = sorted(sec.items())
    best = cur = 0.0
    j = 0
    for t, v in items:
        cur += v
        while items[j][0] <= t - window:
            cur -= items[j][1]
            j += 1
        best = max(best, cur)
    return best / window


def _sparse_series(sec: Dict[int, float], t0: int, step: int) -> List[List[float]]:
    b: Dict[int, float] = {}
    for t, v in sec.items():
        _inc(b, (t - t0) // step, v)
    return [[i, b[i]] for i in sorted(b)]


def _top(d: dict, n: int, key="dmg") -> dict:
    if len(d) <= n:
        return d
    items = sorted(d.items(), key=lambda kv: (kv[1][key] if isinstance(kv[1], dict) else kv[1]), reverse=True)
    return dict(items[:n])


def _with_s10(actor: dict) -> dict:
    """Ряд урона по 10-секундным интервалам: {"ts": урон} -> [[ts, урон], ...] по времени (UTC)."""
    s10 = actor.get("s10")
    if not isinstance(s10, dict):
        return actor
    out = dict(actor)
    out["s10"] = [[int(k), v] for k, v in sorted(s10.items(), key=lambda kv: int(kv[0]))]
    return out


def round2(x: float) -> float:
    return round(x + 0.0, 2)


def session_finalize(s: dict, min_session_seconds: int) -> dict:
    """Итоговая запись сессии (JSON)."""
    t0, t1 = s["t0"], s["t1"]
    sec_total: Dict[int, float] = {}
    weapons = {}
    for w, ws in s["weapons"].items():
        secw = {int(k): v for k, v in s["sec_out"].get(w, {}).items()}
        for t, v in secw.items():
            _inc(sec_total, t, v)
        active = max(1, ws["t1"] - ws["t0"])
        shots = ws["hits"] + ws["miss"]
        weapons[w] = {
            "dmg": ws["dmg"], "hits": ws["hits"], "miss": ws["miss"], "max": ws["max"], "refl": ws["refl"],
            "avg_hit": round2(ws["dmg"] / ws["hits"]) if ws["hits"] else 0,
            "hit_rate": round2(ws["hits"] / shots) if shots else None,
            "dps": round2(ws["dmg"] / active) if ws["dmg"] else 0,
            "peak": round2(peak_window(secw)) if secw else 0,
            "active": active, "t0": ws["t0"], "t1": ws["t1"], "q": ws["q"],
            "targets": dict(sorted(ws["targets"].items(), key=lambda kv: kv[1], reverse=True)[:10]),
        }
    sec_in = {int(k): v for k, v in s["sec_in"].items()}
    out_span = max(1, (s["last_out"] - s["first_out"])) if s["first_out"] is not None else 1
    in_span = max(1, (s["last_in"] - s["first_in"])) if s["first_in"] is not None else 1
    targets = _top(s["targets"], 50)
    if len(s["targets"]) > len(targets):
        rest = [v for k, v in s["targets"].items() if k not in targets]
        targets = dict(targets)
        targets["(прочие)"] = {"dmg": sum(v["dmg"] for v in rest), "hits": sum(v["hits"] for v in rest),
                               "miss": sum(v["miss"] for v in rest), "refl": sum(v["refl"] for v in rest),
                               "max": max(v["max"] for v in rest), "ship": "", "ticker": "", "weapons": {},
                               "count": len(rest)}
    targets = {k: _with_s10({kk: vv for kk, vv in v.items() if kk not in ("t0", "t1")}) for k, v in targets.items()}
    per_min = [[int(k)] + [round2(x) for x in v] for k, v in sorted(s["min"].items(), key=lambda kv: int(kv[0]))]
    step = 10
    series = {"step": step, "t0": t0,
              "out": _sparse_series(sec_total, t0, step),
              "in": _sparse_series(sec_in, t0, step),
              "w": {w: _sparse_series({int(k): v for k, v in s["sec_out"].get(w, {}).items()}, t0, step)
                    for w in s["weapons"] if s["sec_out"].get(w)}}
    dur = t1 - t0
    rec = {
        "id": f"{s['who']}|{t0}", "v": RECORD_VERSION, "who": s["who"], "t0": t0, "t1": t1, "dur": dur,
        "significant": dur >= min_session_seconds,
        "out": s["out"], "in": s["in"], "refl": s["refl"],
        "miss_in": s["miss_in"], "miss_out": s["miss_out"], "hits_out": s["hits_out"], "hits_in": s["hits_in"],
        "bounty": round2(s["bounty"]), "bounty_n": s["bounty_n"],
        "ore": s["ore"], "ore_crit": s["ore_crit"], "ore_residue": s["ore_residue"], "ore_cycles": s["ore_cycles"],
        "ore_total": sum(s["ore"].values()), "residue": s["residue"], "cycles": s["cycles"],
        "weapons": weapons, "targets": targets,
        "attackers": {k: _with_s10(v) for k, v in _top(s["attackers"], 50).items()}, "in_weapons": s["in_weapons"],
        "reps_in": s["reps_in"], "reps_out": s["reps_out"],
        "reps_in_from": s["reps_in_from"], "reps_out_to": s["reps_out_to"],
        "neut_in": s["neut_in"], "nos_in": s["nos_in"], "ewar": s["ewar"],
        "systems": {k: dict(v, bounty=round2(v["bounty"])) for k, v in s["systems"].items()},
        "avg_dps": round2(s["out"] / out_span) if s["out"] else 0,
        "peak_dps": round2(peak_window(sec_total)) if sec_total else 0,
        "avg_dps_in": round2(s["in"] / in_span) if s["in"] else 0,
        "peak_dps_in": round2(peak_window(sec_in)) if sec_in else 0,
        "per_min": per_min, "series": series,
        "unparsed": s["unparsed"], "events": s["events"],
    }
    return rec


LIGHT_DROP = ("series", "per_min")


def light_record(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if k not in LIGHT_DROP}


# ---------------------------------------------------------------------------
# Хранилище истории: sessions.jsonl + history.csv (с защитой от дублей)
# ---------------------------------------------------------------------------

CSV_HEADER = ["id", "персонаж", "начало (местное)", "конец (местное)", "начало UTC", "длительность, с",
              "значимая", "нанесено", "получено", "отражено", "ваши промахи", "промахи по вам",
              "средний DPS", "пиковый DPS", "баунти, ISK", "руда, ед.", "отходы, ед.", "циклов добычи",
              "системы", "руда по типам", "оружие (урон)", "нераспознано строк"]


def _fmt_local(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _fmt_utc(ts: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts))


def _dec(x: float) -> str:
    return (f"{x:.2f}".rstrip("0").rstrip(".") or "0").replace(".", ",")


def csv_row(rec: dict) -> List[str]:
    return [
        rec["id"], rec["who"], _fmt_local(rec["t0"]), _fmt_local(rec["t1"]), _fmt_utc(rec["t0"]), str(rec["dur"]),
        "да" if rec["significant"] else "нет",
        str(rec["out"]), str(rec["in"]), str(rec["refl"]), str(rec["miss_out"]), str(rec["miss_in"]),
        _dec(rec["avg_dps"]), _dec(rec["peak_dps"]), _dec(rec["bounty"]),
        str(rec["ore_total"]), str(rec["residue"]), str(rec["cycles"]),
        ", ".join(k for k in rec["systems"] if k != NO_SYSTEM),
        " | ".join(f"{k}: {v}" for k, v in sorted(rec["ore"].items(), key=lambda kv: -kv[1])),
        " | ".join(f"{k}: {v['dmg']}" for k, v in sorted(rec["weapons"].items(), key=lambda kv: -kv[1]["dmg"])),
        str(rec["unparsed"]),
    ]


class History:
    """Запись завершённых сессий. Идемпотентна: запись с уже известным id не дублируется."""

    def __init__(self, data_dir: str):
        self.jsonl = os.path.join(data_dir, "sessions.jsonl")
        self.csv = os.path.join(data_dir, "history.csv")
        self.lock = threading.Lock()
        self.ids_jsonl: set = set()
        self.ids_csv: set = set()
        self._cache_key = None
        self._cache: List[dict] = []
        self.load_ids()

    def load_ids(self) -> None:
        for p in (self.jsonl, self.csv):
            if os.path.exists(p):
                repair_tail(p)
        self.ids_jsonl.clear()
        self.ids_csv.clear()
        if os.path.exists(self.jsonl):
            with open(self.jsonl, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        self.ids_jsonl.add(json.loads(line)["id"])
                    except Exception:
                        continue
        if os.path.exists(self.csv):
            with open(self.csv, "r", encoding="utf-8-sig", newline="") as f:
                r = csv.reader(f, delimiter=";")
                next(r, None)
                for row in r:
                    if row:
                        self.ids_csv.add(row[0])

    def write(self, rec: dict) -> bool:
        """Возвращает True, если запись новая (её ещё не было в sessions.jsonl)."""
        with self.lock:
            if rec["id"] not in self.ids_csv:
                new_file = not os.path.exists(self.csv) or os.path.getsize(self.csv) == 0
                with open(self.csv, "a", encoding="utf-8", newline="") as f:
                    if new_file:
                        f.write("﻿")
                    w = csv.writer(f, delimiter=";", lineterminator="\r\n")
                    if new_file:
                        w.writerow(CSV_HEADER)
                    w.writerow(csv_row(rec))
                    f.flush()
                    os.fsync(f.fileno())
                self.ids_csv.add(rec["id"])
            if rec["id"] in self.ids_jsonl:
                return False
            with open(self.jsonl, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self.ids_jsonl.add(rec["id"])
            return True

    def records(self, light=True) -> List[dict]:
        """Все записи из sessions.jsonl. light=True — без рядов для графиков (с кэшем по размеру/mtime)."""
        if not light:
            if not os.path.exists(self.jsonl):
                return []
            out = []
            with self.lock, open(self.jsonl, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
            return out
        try:
            st = os.stat(self.jsonl)
        except OSError:
            return []
        key = (st.st_size, st.st_mtime_ns)
        with self.lock:
            if key != self._cache_key:
                out = []
                with open(self.jsonl, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            out.append(light_record(json.loads(line)))
                        except Exception:
                            continue
                self._cache, self._cache_key = out, key
            return list(self._cache)

    def get(self, rec_id: str) -> Optional[dict]:
        if not os.path.exists(self.jsonl):
            return None
        needle = json.dumps(rec_id, ensure_ascii=False)
        with open(self.jsonl, "r", encoding="utf-8") as f:
            for line in f:
                if needle in line:
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    if r.get("id") == rec_id:
                        return r
        return None


# ---------------------------------------------------------------------------
# Получатели итогов (точка расширения: Discord, Telegram, сайт альянса)
# ---------------------------------------------------------------------------

class Notifier:
    """
    Интерфейс получателя итогов сессии. Чтобы подключить, например, Discord:
      1) написать класс DiscordNotifier(Notifier) с методом send(record);
      2) добавить его в NOTIFIER_FACTORIES под именем "discord";
      3) в config.json: "notifiers": {"discord": {"webhook": "..."}}.
    send() вызывается ровно один раз на каждую новую значимую сессию (не при --backfill
    и не при первичном импорте). Очередь повторов при ошибках — забота самого получателя.
    """
    name = "base"

    def __init__(self, options: dict):
        self.options = options

    def send(self, record: dict) -> None:
        raise NotImplementedError


NOTIFIER_FACTORIES: Dict[str, type] = {}


def build_notifiers(cfg: dict) -> List[Notifier]:
    out = []
    for name, opts in (cfg.get("notifiers") or {}).items():
        cls = NOTIFIER_FACTORIES.get(name)
        if cls is None:
            log.warning("Получатель «%s» указан в config.json, но не реализован — пропускаю", name)
            continue
        out.append(cls(opts if isinstance(opts, dict) else {}))
    return out


# ---------------------------------------------------------------------------
# Наблюдатель за логами
# ---------------------------------------------------------------------------

READ_CHUNK = 8 << 20
UNPARSED_KEEP = 200


class Watcher:
    def __init__(self, cfg: dict, data_dir: str, *, backfill: bool = False, days: Optional[int] = None,
                 notifiers: Optional[List[Notifier]] = None):
        self.cfg = cfg
        self.data_dir = data_dir
        self.logs_dir = resolve_logs_dir(cfg)
        self.state_path = os.path.join(data_dir, "state.json")
        self.backfill = backfill
        self.lock = threading.RLock()
        self.files: Dict[str, dict] = {}
        self.open: Dict[str, dict] = {}
        self.cur_sys: Dict[str, str] = {}
        self.names_en: Dict[str, str] = {}
        self.unparsed: Dict[str, list] = {}   # ключ-шаблон -> [кол-во, пример, тип, последнее время]
        self.unparsed_total = 0
        self.characters = set(c.strip().lower() for c in cfg.get("characters") or [] if str(c).strip())
        self.notifiers = notifiers if notifiers is not None else build_notifiers(cfg)
        self.history = History(data_dir)
        self.dirty = False
        self.last_save = 0.0
        self.initial_done = False
        self.progress = {"phase": "старт", "files_total": 0, "files_done": 0}
        self.closed_count = 0
        self.last_unparsed_logged = 0
        loaded = False
        if not backfill:
            loaded = self.load_state()
        self.import_days = days if days is not None else cfg["import_days"]
        self.cutoff = int(time.time()) - self.import_days * 86400
        self.fresh = not loaded
        self.changed_event = threading.Event()   # будит фоновые задачи (ESI) после новых сессий
        self.session_hooks: List = []     # модули: новая завершённая сессия (не при пересборке истории)
        self.live_hooks: List = []        # модули: дописать поля в живые сессии для страницы и оверлея
        self.status_hooks: Dict = {}      # модули: свои поля в /api/live

    # ----- состояние -----
    def load_state(self) -> bool:
        if not os.path.exists(self.state_path):
            return False
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                st = json.load(f)
            if st.get("v") != STATE_VERSION:
                log.warning("state.json другой версии (%s) — начинаю импорт заново", st.get("v"))
                return False
            self.files = st.get("files", {})
            self.open = st.get("open", {})
            self.cur_sys = st.get("cur_sys", {})
            self.names_en = st.get("names_en", {})
            self.unparsed = st.get("unparsed", {})
            self.unparsed_total = st.get("unparsed_total", 0)
            if st.get("logs_dir") and os.path.normcase(st["logs_dir"]) != os.path.normcase(self.logs_dir):
                log.warning("Папка логов изменилась: %s -> %s", st["logs_dir"], self.logs_dir)
            log.info("state.json загружен: файлов %d, незавершённых сессий %d", len(self.files), len(self.open))
            return True
        except Exception as e:
            log.error("state.json повреждён (%s) — начинаю импорт заново", e)
            return False

    def save_state(self, force: bool = False) -> None:
        now = time.time()
        with self.lock:
            if not force and (not self.dirty or now - self.last_save < self.cfg["state_save_seconds"]):
                return
            st = {"v": STATE_VERSION, "saved_at": int(now), "logs_dir": self.logs_dir,
                  "files": self.files, "open": self.open, "cur_sys": self.cur_sys,
                  "names_en": self.names_en, "unparsed": self.unparsed, "unparsed_total": self.unparsed_total}
            try:
                atomic_write_json(self.state_path, st)
                self.dirty = False
                self.last_save = now
            except OSError as e:
                log.error("Не удалось сохранить state.json: %s", e)

    # ----- файлы -----
    def list_files(self) -> List[str]:
        try:
            names = [n for n in os.listdir(self.logs_dir) if n.lower().endswith(".txt")]
        except FileNotFoundError:
            return []
        except OSError as e:
            log.error("Папка логов недоступна: %s", e)
            return []
        return sorted(names)

    def scan(self) -> int:
        """Один проход по папке логов. Возвращает число обработанных событий."""
        names = self.list_files()
        total = 0
        todo = []
        for name in names:
            path = os.path.join(self.logs_dir, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            info = self.files.get(name)
            if info is None:
                if st.st_mtime < self.cutoff:
                    continue   # старше периода импорта и ранее не встречался
            elif info.get("skip") or (info["off"] == st.st_size and info.get("mtime") == st.st_mtime):
                continue
            todo.append((name, path, st))
        if not self.initial_done:
            self.progress = {"phase": "импорт", "files_total": len(todo), "files_done": 0}
        for i, (name, path, st) in enumerate(todo):
            try:
                total += self.process_file(name, path, st)
            except Exception:
                log.exception("Ошибка при обработке %s", name)
            if not self.initial_done:
                self.progress["files_done"] = i + 1
        # забыть давно не обновлявшиеся файлы, которых уже нет
        existing = set(names)
        with self.lock:
            for name in list(self.files):
                if name not in existing:
                    del self.files[name]
                    self.dirty = True
        return total

    def process_file(self, name: str, path: str, st: os.stat_result) -> int:
        info = self.files.get(name)
        if info is None:
            info = {"off": 0, "size": 0, "mtime": 0, "who": None, "skip": False}
        if st.st_size < info["off"]:
            log.warning("%s: файл стал короче (усечён или пересоздан) — читаю с начала", name)
            info["off"] = 0
            info["who"] = None
        if info["who"] is None:
            with open(path, "rb") as f:
                head = f.read(4096).decode("utf-8", "replace")
            complete, who = parse_header(head)
            if not who:
                if complete:
                    # экран входа — без «Слушатель:», пропускаем
                    info.update(skip=True, off=st.st_size, size=st.st_size, mtime=st.st_mtime)
                    with self.lock:
                        self.files[name] = info
                        self.dirty = True
                return 0
            info["who"] = who
            if self.characters and who.lower() not in self.characters:
                info.update(skip=True, off=st.st_size, size=st.st_size, mtime=st.st_mtime)
                with self.lock:
                    self.files[name] = info
                    self.dirty = True
                return 0
        who = info["who"]
        count = 0
        with self.lock:
            self.files[name] = info
        with open(path, "rb") as f:
            f.seek(info["off"])
            while True:
                chunk = f.read(READ_CHUNK)
                if not chunk:
                    break
                idx = chunk.rfind(b"\n")
                if idx < 0:
                    break   # неполная строка — дочитаем в следующий раз
                data = chunk[:idx + 1]
                with self.lock:
                    # Смещение двигается после каждой строки: если посреди блока сессия
                    # завершится и state.json сохранится, смещение и сессии будут согласованы.
                    for bline in data.split(b"\n")[:-1]:
                        ev = parse_line(bline.decode("utf-8", "replace"))
                        if ev is not None:
                            self.handle_event(who, ev)
                            count += 1
                        info["off"] += len(bline) + 1
                    info["size"] = st.st_size
                    info["mtime"] = st.st_mtime
                    self.dirty = True
                if len(data) < len(chunk):
                    break
                f.seek(info["off"])
        return count

    # ----- события и сессии -----
    def handle_event(self, who: str, ev: Event) -> None:
        if ev.ts < self.cutoff:
            return
        if ev.kind == "system":
            self.cur_sys[who] = ev.data["system"]
            self._learn(ev.hints, [ev.data["system"]])
            return
        if ev.kind == "unparsed":
            self._remember_unparsed(ev)
        else:
            names = []
            for key in ("weapon", "ore"):
                if ev.data.get(key):
                    names.append(ev.data[key])
            self._learn(ev.hints, names)
        s = self.open.get(who)
        gap = self.cfg["session_gap_seconds"]
        if s is not None and ev.ts - s["t1"] > gap:
            self.close_session(who)
            s = None
        if s is None:
            s = new_session(who, ev.ts)
            self.open[who] = s
        session_add(s, ev, self.cur_sys.get(who))

    def _learn(self, hints: dict, names: Iterable[str]) -> None:
        for n in names:
            h = hints.get(n)
            if h and self.names_en.get(n) != h:
                self.names_en[n] = h

    def _remember_unparsed(self, ev: Event) -> None:
        self.unparsed_total += 1
        key = ev.data["type"] + "|" + unparsed_key(ev.data["text"])
        e = self.unparsed.get(key)
        if e:
            e[0] += 1
            e[3] = ev.ts
        else:
            if len(self.unparsed) >= UNPARSED_KEEP:
                victim = min(self.unparsed.items(), key=lambda kv: (kv[1][0], kv[1][3]))[0]
                del self.unparsed[victim]
            self.unparsed[key] = [1, ev.data["text"][:300], ev.data["type"], ev.ts]

    def close_session(self, who: str) -> Optional[dict]:
        s = self.open.get(who)
        if s is None:
            return None
        rec = session_finalize(s, self.cfg["min_session_seconds"])
        is_new = self.history.write(rec)
        del self.open[who]
        self.dirty = True
        self.closed_count += 1
        self.save_state(force=True)   # немедленно после завершения сессии
        log.info("Сессия завершена: %s %s–%s, %d с, урон %d, получено %d, баунти %.0f, руда %d%s",
                 who, _fmt_local(rec["t0"]), _fmt_local(rec["t1"]), rec["dur"], rec["out"], rec["in"],
                 rec["bounty"], rec["ore_total"], "" if is_new else " (уже была записана — дубль пропущен)")
        if is_new and not self.backfill:
            for hook in list(self.session_hooks):
                try:
                    hook(rec)
                except Exception:
                    log.exception("Модуль не обработал завершённую сессию")
        if is_new and rec["significant"] and self.initial_done and not self.backfill:
            for n in self.notifiers:
                try:
                    n.send(rec)
                except Exception:
                    log.exception("Получатель %s: ошибка отправки", getattr(n, "name", n))
        self.changed_event.set()
        return rec

    def close_idle(self, now: Optional[float] = None) -> int:
        now = time.time() if now is None else now
        gap = self.cfg["session_gap_seconds"]
        n = 0
        with self.lock:
            for who in list(self.open):
                if now - self.open[who]["t1"] > gap:
                    self.close_session(who)
                    n += 1
        return n

    def poll(self) -> None:
        self.scan()
        self.close_idle()
        if not self.initial_done:
            self.initial_done = True
            self.progress = {"phase": "наблюдение", "files_total": 0, "files_done": 0}
            self.save_state(force=True)   # сразу после первого сканирования
            log.info("Первичное сканирование завершено (%s). Незавершённых сессий: %d",
                     "импорт за %d дн." % self.import_days if self.fresh else "продолжение", len(self.open))
        else:
            self.save_state()
        self._log_unparsed()

    def _log_unparsed(self, force=False) -> None:
        if self.unparsed_total and (force or self.unparsed_total != self.last_unparsed_logged) \
                and (force or time.time() - getattr(self, "_unp_log_t", 0) > 600):
            self._unp_log_t = time.time()
            self.last_unparsed_logged = self.unparsed_total
            top = sorted(self.unparsed.values(), key=lambda v: -v[0])[:5]
            log.info("Нераспознанных строк: %d. Примеры: %s", self.unparsed_total,
                     " || ".join(f"({v[2]}) {v[1][:150]} ×{v[0]}" for v in top))

    # ----- для веб-страницы -----
    def live(self) -> dict:
        with self.lock:
            sessions = [session_finalize(s, self.cfg["min_session_seconds"]) for s in self.open.values()]
            for s in sessions:
                for hook in self.live_hooks:
                    try:
                        hook(s)
                    except Exception:
                        log.exception("Модуль не обработал живую сессию")
            chars = sorted(set(i["who"] for i in self.files.values() if i.get("who") and not i.get("skip")))
            return {
                "sessions": sessions, "now": int(time.time()), "logs_dir": self.logs_dir,
                "logs_dir_exists": os.path.isdir(self.logs_dir),
                "progress": dict(self.progress), "initial_done": self.initial_done,
                "cur_sys": dict(self.cur_sys), "characters": chars,
                "unparsed_total": self.unparsed_total,
                "history_count": len(self.history.ids_jsonl),
                "gap": self.cfg["session_gap_seconds"], "version": VERSION,
                "notifiers": [getattr(n, "name", "?") for n in self.notifiers],
                "aa": None,
                **self._module_status(),
            }

    def _module_status(self) -> dict:
        out = {}
        for key, fn in list(self.status_hooks.items()):
            try:
                out[key] = fn()
            except Exception:
                log.exception("Модуль не отдал состояние %s", key)
        return out

    def unparsed_list(self) -> dict:
        with self.lock:
            items = sorted(self.unparsed.values(), key=lambda v: -v[0])
            return {"total": self.unparsed_total,
                    "items": [{"count": v[0], "text": v[1], "type": v[2], "last": v[3]} for v in items]}

    def collect_names(self) -> Tuple[set, set, set]:
        """(руда, оружие/модули, системы) — видимые названия из истории и текущих сессий."""
        ores, items, systems = set(), set(), set()
        recs = self.history.records()
        with self.lock:
            live = [s for s in self.open.values()]
            systems.update(self.cur_sys.values())
        for r in recs + live:
            ores.update(r.get("ore", {}))
            items.update(r.get("weapons", {}))
            items.update(r.get("in_weapons", {}))
            systems.update(r.get("systems", {}))
        for bad in (NO_WEAPON, NO_SYSTEM, "(не указано)", "(неизвестно)"):
            ores.discard(bad)
            items.discard(bad)
            systems.discard(bad)
        return ores, items, systems


# ---------------------------------------------------------------------------
# Онлайн-данные: ESI (названия, объёмы, системы, цены Jita) и иконки
# ---------------------------------------------------------------------------

ALLOWED_HOSTS = {"esi.evetech.net", "images.evetech.net"}
ESI_BASE = "https://esi.evetech.net/latest"
IMG_BASE = "https://images.evetech.net"
THE_FORGE = 10000002
JITA_44 = 60003760
PRICE_MIN_INTERVAL = 300


class OnlineError(Exception):
    pass


class Online:
    def __init__(self, data_dir: str, cfg: dict, esi_base: str = None, img_base: str = None):
        self.cfg = cfg
        self.esi_base = (esi_base or ESI_BASE).rstrip("/")
        self.img_base = (img_base or IMG_BASE).rstrip("/")
        self.cache_path = os.path.join(data_dir, "esi_cache.json")
        self.prices_path = os.path.join(data_dir, "prices.json")
        self.icons_dir = os.path.join(data_dir, "cache", "icons")
        self.lock = threading.RLock()
        self.cache = {"types": {}, "groups": {}, "categories": {}, "systems": {}, "constellations": {}, "regions": {}}
        self.prices = {"updated_at": 0, "source": "", "types": {}}
        self.price_status = {"state": "idle", "done": 0, "total": 0, "message": "", "started_at": 0}
        self.last_price_start = 0.0
        self.last_page_seen = 0.0
        self.status = {"ok": None, "message": "", "at": 0}
        for path, attr in ((self.cache_path, "cache"), (self.prices_path, "prices")):
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    getattr(self, attr).update(data)
                except Exception as e:
                    log.warning("%s повреждён (%s) — будет пересоздан", os.path.basename(path), e)

    # ----- HTTP -----
    def _ua(self) -> str:
        c = (self.cfg.get("esi_contact") or "").strip()
        return f"EVELogWatcher/{VERSION} (local desktop app{'; ' + c if c else ''})"

    def request(self, url: str, method: str = "GET", body=None, binary=False):
        u = urllib.parse.urlsplit(url)
        if u.hostname not in ALLOWED_HOSTS:
            raise OnlineError(f"Хост {u.hostname} не входит в список разрешённых")
        data = None
        headers = {"User-Agent": self._ua(), "Accept": "*/*" if binary else "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
                hdrs = resp.headers
                self._respect_error_limit(hdrs)
                return (raw if binary else json.loads(raw.decode("utf-8"))), hdrs
        except urllib.error.HTTPError as e:
            self._respect_error_limit(e.headers)
            raise OnlineError(f"HTTP {e.code} для {u.path}") from e
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            raise OnlineError(f"нет связи с {u.hostname}: {getattr(e, 'reason', e)}") from e

    @staticmethod
    def _respect_error_limit(hdrs) -> None:
        if not hdrs:
            return
        try:
            remain = int(hdrs.get("X-ESI-Error-Limit-Remain", "100"))
            reset = int(hdrs.get("X-ESI-Error-Limit-Reset", "0"))
        except ValueError:
            return
        if remain < 10:
            log.warning("ESI: мало запаса ошибок (%d) — пауза %d с", remain, reset)
            time.sleep(min(60, max(1, reset)))

    def esi(self, path: str, method="GET", body=None, **params):
        q = {"datasource": "tranquility"}
        q.update({k: v for k, v in params.items() if v is not None})
        return self.request(f"{self.esi_base}{path}?{urllib.parse.urlencode(q)}", method, body)

    def _save_cache(self):
        with self.lock:
            atomic_write_json(self.cache_path, self.cache)

    # ----- справочники -----
    def resolve(self, visible_names: Iterable[str], system_names: Iterable[str], aliases: Dict[str, str]) -> int:
        """Найти type_id/system_id для новых названий. Возвращает число новых записей."""
        now = int(time.time())
        types, systems = self.cache["types"], self.cache["systems"]

        def need(cache, name):
            e = cache.get(name)
            return e is None or (e.get("missing") and now - e.get("ts", 0) > 86400)

        tnames = sorted({aliases.get(n, n) for n in visible_names if need(types, aliases.get(n, n))})
        snames = sorted({aliases.get(n, n) for n in system_names if need(systems, aliases.get(n, n))})
        if not tnames and not snames:
            return 0
        found_t, found_s = {}, {}
        allnames = tnames + snames
        for i in range(0, len(allnames), 250):
            batch = allnames[i:i + 250]
            try:
                data, _ = self.esi("/universe/ids/", "POST", batch, language="en")
            except OnlineError as e:
                if "HTTP 404" not in str(e):   # 404 = ни одно название не найдено
                    raise
                data = {}
            for e in data.get("inventory_types", []) or []:
                found_t[e["name"]] = e["id"]
            for e in data.get("systems", []) or []:
                found_s[e["name"]] = e["id"]
        lower_t = {k.lower(): v for k, v in found_t.items()}
        lower_s = {k.lower(): v for k, v in found_s.items()}
        added = 0
        for n in tnames:
            tid = found_t.get(n) or lower_t.get(n.lower())
            if not tid:
                types[n] = {"missing": True, "ts": now}
                continue
            info, _ = self.esi(f"/universe/types/{tid}/", language="ru")
            gid = info.get("group_id")
            grp = self._group(gid) if gid else {}
            types[n] = {"id": tid, "name_ru": info.get("name", n), "name_en": n,
                        "volume": info.get("volume"), "packaged_volume": info.get("packaged_volume"),
                        "group_id": gid, "group": grp.get("name", ""), "category_id": grp.get("category_id"),
                        "category": grp.get("category", ""), "ts": now}
            added += 1
            self.fetch_icon(tid)
            if added % 20 == 0:
                self._save_cache()   # промежуточное сохранение: первая загрузка может идти минуты
        for n in snames:
            sid = found_s.get(n) or lower_s.get(n.lower())
            if not sid:
                systems[n] = {"missing": True, "ts": now}
                continue
            info, _ = self.esi(f"/universe/systems/{sid}/", language="ru")
            cid = info.get("constellation_id")
            con = self._simple("constellations", f"/universe/constellations/{cid}/", cid) if cid else {}
            rid = con.get("region_id")
            reg = self._simple("regions", f"/universe/regions/{rid}/", rid) if rid else {}
            systems[n] = {"id": sid, "name": info.get("name", n), "sec": info.get("security_status"),
                          "constellation": con.get("name", ""), "region": reg.get("name", ""), "ts": now}
            added += 1
        self._save_cache()
        return added

    def _group(self, gid) -> dict:
        key = str(gid)
        g = self.cache["groups"].get(key)
        if g is None:
            info, _ = self.esi(f"/universe/groups/{gid}/", language="ru")
            cat = self._simple("categories", f"/universe/categories/{info.get('category_id')}/",
                               info.get("category_id"))
            g = {"name": info.get("name", ""), "category_id": info.get("category_id"),
                 "category": cat.get("name", "")}
            self.cache["groups"][key] = g
        return g

    def _simple(self, bucket: str, path: str, ident) -> dict:
        key = str(ident)
        e = self.cache[bucket].get(key)
        if e is None:
            info, _ = self.esi(path, language="ru")
            e = {k: info.get(k) for k in ("name", "region_id", "category_id") if k in info}
            self.cache[bucket][key] = e
        return e

    def icon_path(self, tid: int) -> str:
        return os.path.join(self.icons_dir, f"{int(tid)}.png")

    def fetch_icon(self, tid: int) -> bool:
        p = self.icon_path(tid)
        if os.path.exists(p):
            return True
        try:
            data, _ = self.request(f"{self.img_base}/types/{int(tid)}/icon?size=64", binary=True)
        except OnlineError as e:
            log.info("Иконка %s не получена: %s", tid, e)
            return False
        if not data.startswith(b"\x89PNG"):
            return False
        os.makedirs(self.icons_dir, exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        replace_file(tmp, p)
        return True

    # ----- цены -----
    def can_refresh_prices(self) -> Tuple[bool, int]:
        wait = int(PRICE_MIN_INTERVAL - (time.time() - self.last_price_start))
        if self.price_status["state"] == "running":
            return False, max(wait, 1)
        return wait <= 0, max(wait, 0)

    def start_price_refresh(self, type_ids: List[int]) -> Tuple[bool, str]:
        ok, wait = self.can_refresh_prices()
        if not ok:
            if self.price_status["state"] == "running":
                return False, "Цены уже обновляются"
            return False, f"Цены можно обновлять не чаще раза в 5 минут. Подождите {wait} с."
        if not type_ids:
            return False, "Нет руды с известным type_id — подождите, пока подтянутся справочники ESI"
        self.last_price_start = time.time()
        self.price_status = {"state": "running", "done": 0, "total": len(type_ids), "message": "",
                             "started_at": int(time.time())}
        threading.Thread(target=self._refresh_prices, args=(list(type_ids),), daemon=True,
                         name="prices").start()
        return True, "Обновление цен запущено"

    def _refresh_prices(self, type_ids: List[int]) -> None:
        try:
            result = {}
            avg = {}
            try:
                data, _ = self.esi("/markets/prices/")
                want = set(type_ids)
                avg = {e["type_id"]: e.get("average_price") for e in data if e.get("type_id") in want}
            except OnlineError as e:
                log.warning("Средние цены ESI не получены: %s", e)
            for i, tid in enumerate(type_ids):
                orders, page, pages = [], 1, 1
                while page <= pages and page <= 20:
                    data, hdrs = self.esi(f"/markets/{THE_FORGE}/orders/", order_type="all", type_id=tid, page=page)
                    orders += data
                    try:
                        pages = int(hdrs.get("X-Pages", "1"))
                    except ValueError:
                        pages = 1
                    page += 1
                buys = sorted((o for o in orders if o.get("is_buy_order") and o.get("location_id") == JITA_44),
                              key=lambda o: -o["price"])
                sells = [o["price"] for o in orders if not o.get("is_buy_order") and o.get("location_id") == JITA_44]
                result[str(tid)] = {
                    "buy": buys[0]["price"] if buys else None,
                    "sell": min(sells) if sells else None,
                    "avg": avg.get(tid),
                    "buy_book": [[o["price"], o["volume_remain"], o.get("min_volume", 1)] for o in buys[:200]],
                    "buy_orders": len(buys), "sell_orders": len(sells),
                }
                self.price_status["done"] = i + 1
            with self.lock:
                self.prices = {"updated_at": int(time.time()), "source": "ESI, Jita IV - Moon 4 (60003760)",
                               "types": result}
                atomic_write_json(self.prices_path, self.prices)
            self.price_status.update(state="ok", message=f"Цены обновлены: {len(result)} типов")
            log.info("Цены Jita обновлены: %d типов", len(result))
        except Exception as e:
            self.price_status.update(state="error", message=f"Ошибка обновления цен: {e}")
            log.warning("Ошибка обновления цен: %s", e)

    def ore_type_ids(self, ore_names: Iterable[str], aliases: Dict[str, str]) -> List[int]:
        out = []
        for n in ore_names:
            e = self.cache["types"].get(aliases.get(n, n))
            if e and e.get("id"):
                out.append(e["id"])
        return sorted(set(out))

    def meta(self) -> dict:
        with self.lock:
            return {"types": {k: v for k, v in self.cache["types"].items() if not v.get("missing")},
                    "systems": {k: v for k, v in self.cache["systems"].items() if not v.get("missing")},
                    "prices": self.prices, "price_status": dict(self.price_status),
                    "price_wait": self.can_refresh_prices()[1], "status": dict(self.status)}


# ---------------------------------------------------------------------------
# Веб-сервер
# ---------------------------------------------------------------------------

class App:
    """Связывает наблюдателя, онлайн-данные и веб-сервер."""

    def __init__(self, cfg: dict, data_dir: str, watcher: Watcher, online: Optional[Online]):
        self.cfg = cfg
        self.data_dir = data_dir
        self.watcher = watcher
        self.online = online
        self.port = cfg["web_port"]
        self.routes: Dict = {}             # модули: (метод, путь) → (id модуля, обработчик)
        self.modules: List = []            # modkit.Module: найденные модули и их состояние
        self.stop_hooks: List = []         # модули: что сделать при остановке
        self.updater = None                # updater.Updater: версии с GitHub и установка модулей

    def set_module(self, body) -> dict:
        """Вкладка «Модули»: включить или выключить (вступает в силу после перезапуска)."""
        if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
            return {"ok": False, "message": "Неверный запрос"}
        mid = str(body.get("id") or "")
        if not any(m.id == mid for m in self.modules):
            return {"ok": False, "message": "Такого модуля нет"}
        modkit.set_enabled(os.path.join(self.data_dir, "config.json"), mid, body["enabled"], atomic_write_json)
        return {"ok": True, "message": "Сохранено. Изменение вступит в силу после перезапуска.", "restart": True}

    def restart(self) -> dict:
        """Перезапуск трекера: в приложении его сразу поднимает значок в трее; без него — запустите снова сами."""
        try:
            open(os.path.join(self.data_dir, "stop.flag"), "w").close()
        except OSError as e:
            return {"ok": False, "message": f"Не удалось перезапустить: {e}"}
        return {"ok": True, "message": "Перезапускаю…"}

    def updates(self, action: str, body=None) -> Tuple[int, dict]:
        """Вкладка «Модули»: состояние обновлений, проверить сейчас, установить модуль (или все обновления)."""
        u = self.updater
        if u is None:
            return 200, {"ok": True, "enabled": False, "modules": [], "updates": 0, "app": {"current": VERSION},
                         "error": "Проверка обновлений выключена (update_check в config.json)."}
        if action == "status":
            return 200, u.status()
        if action == "check":
            return 200, u.check(atomic_write_json)
        if not isinstance(body, dict):
            return 400, {"ok": False, "message": "Неверный запрос"}
        ids = [r["id"] for r in u.status()["modules"] if r["update"]] if body.get("all") else [str(body.get("id") or "")]
        if not ids:
            return 200, {"ok": True, "message": "Обновлять нечего.", "done": []}
        done, errors = [], []
        for mid in ids:
            try:
                done.append(u.install(mid))
            except updater.UpdateError as e:
                errors.append(f"{mid}: {e}")
            except Exception as e:                                      # не уронить трекер из-за установки
                log.exception("Установка модуля %s", mid)
                errors.append(f"{mid}: {e}")
        msg = (f"Установлено: {', '.join(d['id'] + ' ' + d['to'] for d in done)}. Перезапустите трекер, чтобы включить."
               if done else "") + (" Ошибки: " + "; ".join(errors) if errors else "")
        return 200, {"ok": not errors, "message": msg.strip(), "done": done, "errors": errors, "restart": bool(done)}

    def meta(self) -> dict:
        m = self.online.meta() if self.online else {"types": {}, "systems": {}, "prices": {"types": {}},
                                                     "price_status": {}, "price_wait": 0, "status": {}}
        with self.watcher.lock:
            m["aliases"] = dict(self.watcher.names_en)
        m["online_enabled"] = bool(self.online)
        m["overrides"] = self.cfg.get("ore_prices_override") or {}
        m["auto_refresh_minutes"] = self.cfg["price_auto_refresh_minutes"]
        return m

    def refresh_prices(self) -> Tuple[int, dict]:
        if not self.online:
            return 409, {"ok": False, "message": "Онлайн-функции выключены в config.json (online_enabled)"}
        ores, _, _ = self.watcher.collect_names()
        with self.watcher.lock:
            aliases = dict(self.watcher.names_en)
        ok, msg = self.online.start_price_refresh(self.online.ore_type_ids(ores, aliases))
        if ok:
            return 202, {"ok": True, "message": msg}
        code = 429 if "не чаще" in msg or "уже" in msg else 409
        return code, {"ok": False, "message": msg, "wait": self.online.can_refresh_prices()[1]}


class Handler(BaseHTTPRequestHandler):
    server_version = "EVELogWatcher"
    sys_version = ""
    app: App = None  # задаётся в make_server

    def log_message(self, fmt, *args):
        log.debug("HTTP %s - %s", self.address_string(), fmt % args)

    # ----- проверки -----
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        return host in (f"localhost:{self.app.port}", f"127.0.0.1:{self.app.port}")

    def _origin_ok(self) -> bool:
        origin = (self.headers.get("Origin") or "").strip().lower()
        ours = origin in (f"http://localhost:{self.app.port}", f"http://127.0.0.1:{self.app.port}")
        return (ours or bool(self._overlay_headers())) and bool(self.headers.get("X-Requested-With"))

    def _overlay_headers(self) -> dict:
        """Приложение Overwolf (HUD и окно со страницей трекера) ходит со своего origin overwolf-extension://…

        Ему открыто то же, что странице в браузере; обычным сайтам — по-прежнему ничего.
        """
        origin = (self.headers.get("Origin") or "").strip()
        if re.match(r"^overwolf-extension://[a-z]{16,64}$", origin):
            return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
        return {}

    # ----- ответы -----
    def _send(self, code: int, body: bytes, ctype: str, extra: Optional[dict] = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in {**self._overlay_headers(), **(extra or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj, extra: Optional[dict] = None):
        self._send(code, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                   "application/json; charset=utf-8", extra)

    def _text(self, code: int, msg: str):
        self._send(code, msg.encode("utf-8"), "text/plain; charset=utf-8")

    # ----- методы -----
    def do_GET(self):
        if not self._host_ok():
            return self._text(403, "Запрещено: неверный заголовок Host")
        u = urllib.parse.urlsplit(self.path)
        path, qs = u.path, urllib.parse.parse_qs(u.query)
        app = self.app
        try:
            if path in ("/", "/index.html"):
                with open(os.path.join(SCRIPT_DIR, "dashboard.html"), "rb") as f:
                    body = f.read()
                csp = ("default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
                       "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'")
                return self._send(200, body, "text/html; charset=utf-8", {"Content-Security-Policy": csp})
            if path.startswith("/api/") and app.online:
                app.online.last_page_seen = time.time()
            if path == "/api/live":
                return self._json(200, app.watcher.live())
            if path == "/api/history":
                recs = app.watcher.history.records()
                if "since" in qs:
                    try:
                        since = int(qs["since"][0])
                        recs = [r for r in recs if r["t1"] >= since]
                    except ValueError:
                        pass
                return self._json(200, {"sessions": recs, "count": len(recs)})
            if path == "/api/session":
                rid = (qs.get("id") or [""])[0]
                rec = app.watcher.history.get(rid)
                if rec is None:
                    for s in app.watcher.live()["sessions"]:
                        if s["id"] == rid:
                            rec = s
                if rec is None:
                    return self._json(404, {"error": "сессия не найдена"})
                return self._json(200, rec)
            if path == "/api/meta":
                return self._json(200, app.meta())
            if path == "/api/updates":
                return self._json(*app.updates("status"))
            if path == "/api/modules":
                return self._json(200, {"ok": True, "modules": [m.info() for m in app.modules],
                                        "dir": modkit.modules_dir(SCRIPT_DIR)})
            m = re.match(r"^/modules/([a-z][a-z0-9_]{1,31})/([A-Za-z0-9_\-]+\.(js|css|png|svg))$", path)
            if m:
                return self._module_file(m.group(1), m.group(2))
            route = app.routes.get(("GET", path))
            if route:
                return self._module_reply(route, qs, None)
            if path == "/api/unparsed":
                return self._json(200, app.watcher.unparsed_list())
            if path == "/history.csv":
                p = app.watcher.history.csv
                body = b""
                if os.path.exists(p):
                    with open(p, "rb") as f:
                        body = f.read()
                if not body.startswith(b"\xef\xbb\xbf"):
                    body = b"\xef\xbb\xbf" + body
                fname = "eve_history_" + time.strftime("%Y%m%d") + ".csv"
                return self._send(200, body, "text/csv; charset=utf-8",
                                  {"Content-Disposition": f'attachment; filename="{fname}"'})
            m = re.match(r"^/icons/(\d{1,12})\.png$", path)
            if m and app.online:
                p = app.online.icon_path(int(m.group(1)))
                if os.path.exists(p):
                    with open(p, "rb") as f:
                        body = f.read()
                    return self._send(200, body, "image/png", {"Cache-Control": "max-age=86400"})
            return self._text(404, "Не найдено")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            log.exception("Ошибка обработки %s", self.path)
            try:
                self._text(500, "Внутренняя ошибка")
            except Exception:
                pass

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        if not self._host_ok():
            return self._text(403, "Запрещено: неверный заголовок Host")
        if not self._origin_ok():
            return self._text(403, "Запрещено: запрос не со страницы приложения")
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(length, 262144)) if length else b""
        if urllib.parse.urlsplit(self.path).path == "/api/prices/refresh":
            code, obj = self.app.refresh_prices()
            return self._json(code, obj)
        u = urllib.parse.urlsplit(self.path)
        body = None
        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                body = None
        if u.path == "/api/modules/set":
            return self._json(200, self.app.set_module(body))
        if u.path == "/api/restart":
            return self._json(200, self.app.restart())
        if u.path == "/api/updates/check":
            return self._json(*self.app.updates("check"))
        if u.path == "/api/updates/install":
            return self._json(*self.app.updates("install", body))
        route = self.app.routes.get(("POST", u.path))
        if route:
            return self._module_reply(route, urllib.parse.parse_qs(u.query), body)
        return self._text(404, "Не найдено")

    def _module_reply(self, route, qs, body):
        """Ответ обработчика модуля: dict → 200, (код, dict), modkit.Html. Ошибка модуля не роняет трекер."""
        mid, fn = route
        try:
            res = fn(qs) if self.command in ("GET", "HEAD") else fn(body, qs)
        except Exception as e:
            log.exception("Модуль %s: ошибка обработки %s", mid, self.path)
            return self._json(500, {"ok": False, "message": f"Ошибка модуля «{mid}»: {e}"})
        if isinstance(res, modkit.Html):
            return self._send(res.code, res.text.encode("utf-8"), "text/html; charset=utf-8",
                              {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})
        if isinstance(res, tuple):
            return self._json(res[0], res[1])
        return self._json(200, res)

    def _module_file(self, mid: str, name: str):
        """Файлы страницы из папки модуля — только перечисленные в его module.json и только у включённых."""
        mod = next((m for m in self.app.modules if m.id == mid and m.enabled), None)
        if mod is None or name not in mod.meta.get("web", []):
            return self._text(404, "Не найдено")
        try:
            with open(os.path.join(mod.path, name), "rb") as f:
                body = f.read()
        except OSError:
            return self._text(404, "Не найдено")
        ctype = {"js": "text/javascript", "css": "text/css", "png": "image/png", "svg": "image/svg+xml"}[name.rsplit(".", 1)[1]]
        return self._send(200, body, ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))

    def _not_allowed(self):
        if not self._host_ok():
            return self._text(403, "Запрещено: неверный заголовок Host")
        self._send(405, "Метод не поддерживается".encode("utf-8"), "text/plain; charset=utf-8",
                   {"Allow": "GET, HEAD, POST"})

    def do_OPTIONS(self):
        cors = self._overlay_headers()
        if not (self._host_ok() and cors and urllib.parse.urlsplit(self.path).path.startswith("/api/")):
            return self._not_allowed()
        cors.update({"Access-Control-Allow-Methods": "GET, POST", "Access-Control-Allow-Headers": "X-Requested-With, Content-Type",
                     "Access-Control-Allow-Private-Network": "true", "Access-Control-Max-Age": "600"})
        self._send(204, b"", "text/plain; charset=utf-8", cors)

    do_PUT = do_DELETE = do_PATCH = _not_allowed


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    # На Windows SO_REUSEADDR позволяет другому процессу занять тот же порт — выключаем
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # без HTTPServer.server_bind: там getfqdn(), который на Windows может тормозить секундами
        import socketserver
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "localhost", self.server_address[1]


def make_server(app: App) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app})
    return LocalServer(("127.0.0.1", app.port), handler)


# ---------------------------------------------------------------------------
# Один экземпляр, PID, остановка
# ---------------------------------------------------------------------------

def acquire_lock(port: int) -> Optional[socket.socket]:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        # Windows: без этого флага второй процесс может занять тот же порт
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        s.bind(("127.0.0.1", port))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


def is_running(port: int) -> bool:
    s = acquire_lock(port)
    if s is None:
        return True
    s.close()
    return False


def _pid_is_python(pid: int) -> bool:
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, timeout=10).stdout.lower()
            return "python" in out or "pyw" in out
        except Exception:
            return False
    return os.path.exists(f"/proc/{pid}")


def stop_running(cfg: dict, data_dir: str, timeout: float = 20.0) -> int:
    """Мягкая остановка через stop.flag; если не помогло — завершить процесс по watcher.pid."""
    port = cfg["lock_port"]
    if not is_running(port):
        print("Фоновая версия не запущена.")
        return 0
    flag = os.path.join(data_dir, "stop.flag")
    with open(flag, "w") as f:
        f.write(str(int(time.time())))
    print("Отправлен сигнал остановки, жду завершения…")
    t_end = time.time() + timeout
    while time.time() < t_end:
        if not is_running(port):
            print("Остановлено.")
            return 0
        time.sleep(0.5)
    pid_path = os.path.join(data_dir, "watcher.pid")
    try:
        pid = int(open(pid_path).read().strip())
    except Exception:
        print("Процесс не ответил, а watcher.pid не найден. Завершите pythonw.exe в диспетчере задач.")
        return 1
    if not _pid_is_python(pid):
        print(f"PID {pid} не похож на процесс Python — не трогаю.")
        return 1
    print(f"Процесс не ответил вовремя, завершаю PID {pid}…")
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception as e:
        print("Не удалось завершить процесс:", e)
        return 1
    try:
        os.remove(flag)
    except OSError:
        pass
    return 0


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

def setup_logging(data_dir: str, console: bool) -> None:
    log.setLevel(logging.INFO)
    for h in list(log.handlers):
        h.close()
        log.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.handlers.RotatingFileHandler(os.path.join(data_dir, "watcher.log"), maxBytes=2 << 20,
                                              backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if console and sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        log.addHandler(sh)


def fix_stdio() -> None:
    """В pythonw.exe sys.stdout/stderr = None: любой print уронил бы процесс."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def online_loop(app: App, stop: threading.Event) -> None:
    online, watcher = app.online, app.watcher
    backoff = 60
    while not stop.is_set():
        try:
            ores, items, systems = watcher.collect_names()
            with watcher.lock:
                aliases = dict(watcher.names_en)
            added = online.resolve(ores | items, systems, aliases)
            if added:
                log.info("ESI: получены данные для %d новых названий", added)
            online.status = {"ok": True, "message": "", "at": int(time.time())}
            backoff = 60
            auto = app.cfg["price_auto_refresh_minutes"]
            page_open = time.time() - online.last_page_seen < 300
            if auto and page_open and time.time() - online.prices.get("updated_at", 0) > auto * 60 \
                    and online.can_refresh_prices()[0]:
                online.start_price_refresh(online.ore_type_ids(ores, aliases))
        except OnlineError as e:
            online.status = {"ok": False, "message": str(e), "at": int(time.time())}
            log.info("ESI недоступен: %s (повтор через %d с)", e, backoff)
            backoff = min(backoff * 2, 1800)
        except Exception:
            log.exception("Ошибка фоновой загрузки данных ESI")
        watcher.changed_event.wait(backoff)
        watcher.changed_event.clear()


def run_backfill(cfg: dict, data_dir: str, days: Optional[int]) -> int:
    for name in ("history.csv", "sessions.jsonl", "state.json"):
        p = os.path.join(data_dir, name)
        if os.path.exists(p):
            os.remove(p)
    w = Watcher(cfg, data_dir, backfill=True, days=days, notifiers=[])
    if not os.path.isdir(w.logs_dir):
        log.error("Папка логов не найдена: %s", w.logs_dir)
        return 1
    log.info("Пересборка истории из %s за %d дн.…", w.logs_dir, w.import_days)
    t = time.time()
    w.poll()
    log.info("Готово за %.1f с: записано сессий %d, незавершённых (продолжатся в фоне) %d, нераспознанных строк %d",
             time.time() - t, w.closed_count, len(w.open), w.unparsed_total)
    w._log_unparsed(force=True)
    return 0


def update_loop(app: "App", stop: threading.Event) -> None:
    """Сверка версий с GitHub: через минуту после запуска, потом раз в update_check_hours."""
    u = app.updater
    if u is None or not u.repo:
        return
    every = app.cfg["update_check_hours"] * 3600
    if stop.wait(60 if time.time() - u.checked >= every else every - (time.time() - u.checked)):
        return
    while not stop.is_set():
        try:
            st = u.check(atomic_write_json)
            if st.get("updates") or st.get("app", {}).get("newer"):
                log.info("Есть обновления: модулей %d%s", st.get("updates", 0),
                         f", приложение {st['app']['latest']}" if st.get("app", {}).get("newer") else "")
        except Exception:
            log.exception("Проверка обновлений")
        if stop.wait(every):
            return


def main(argv=None) -> int:
    fix_stdio()
    ap = argparse.ArgumentParser(description="EVE Log Watcher — итоги игровых сессий EVE Online")
    ap.add_argument("--console", action="store_true", help="дублировать журнал в консоль")
    ap.add_argument("--backfill", action="store_true", help="пересобрать историю из существующих логов")
    ap.add_argument("--days", type=int, default=None, help="за сколько дней читать логи при --backfill")
    ap.add_argument("--stop", action="store_true", help="остановить фоновую версию")
    ap.add_argument("--dump-unparsed", action="store_true", help="вывести нераспознанные строки")
    ap.add_argument("--data-dir", default=None, help="папка с config.json и данными (по умолчанию — рядом со скриптом)")
    ap.add_argument("--aa-connect", nargs=2, metavar=("URL", "KEY"), help="подключить Alliance Auth (Fleet Watch)")
    ap.add_argument("--aa-disconnect", action="store_true", help="отключить отправку в AA")
    ap.add_argument("--aa-upload-history", action="store_true", help="отправить накопленную историю в AA")
    args = ap.parse_args(argv)

    data_dir = os.path.abspath(args.data_dir or SCRIPT_DIR)
    os.makedirs(data_dir, exist_ok=True)
    aa_cmd = args.aa_connect or args.aa_disconnect or args.aa_upload_history
    interactive = args.console or args.backfill or args.stop or args.dump_unparsed or aa_cmd
    setup_logging(data_dir, interactive)
    cfg = load_config(data_dir)

    if args.stop:
        return stop_running(cfg, data_dir)

    if args.aa_connect or args.aa_upload_history:
        mod = modkit.find(modkit.modules_dir(SCRIPT_DIR), "alliance_auth")
        if mod is None:
            print("Модуль «Alliance Auth» не установлен (папка modules/alliance_auth).")
            return 2
        aa = modkit.import_file(mod, mod.meta["entry"])
        aa.bind(sys.modules[__name__])
        if args.aa_connect:
            return aa.aa_connect(cfg, data_dir, *args.aa_connect)
        return aa.aa_upload_history(cfg, data_dir, args.days)
    if args.aa_disconnect:
        path = os.path.join(data_dir, "config.json")
        with open(path, "r", encoding="utf-8-sig") as f:
            user_cfg = json.load(f)
        user_cfg.update(aa_url="", aa_key="")
        atomic_write_json(path, user_cfg, indent=2)
        print("Отправка в AA отключена.")
        return 0

    if args.dump_unparsed:
        # читаем state.json напрямую, не мешая работающей фоновой версии
        try:
            with open(os.path.join(data_dir, "state.json"), "r", encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            st = {}
        items = sorted((st.get("unparsed") or {}).values(), key=lambda v: -v[0])
        out = [f"Нераспознанных строк всего: {st.get('unparsed_total', 0)}", ""]
        for v in items:
            out.append(f"×{v[0]}\t({v[2]}) {v[1]}")
        text = "\n".join(out)
        path = os.path.join(data_dir, "unparsed.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(text)
        print(f"\nСохранено в {path}")
        return 0

    lock = acquire_lock(cfg["lock_port"])
    if lock is None:
        if args.backfill:
            msg = ("Фоновая версия EVE Log Watcher уже работает — пересборка невозможна.\n"
                   "Остановите её: запустите uninstall_autostart.bat или выполните\n"
                   "  python eve_log_watcher.py --stop\n"
                   "а после пересборки снова запустите install_autostart.bat.")
            log.error(msg)
            return 2
        log.error("EVE Log Watcher уже запущен (порт %d занят). Страница: http://localhost:%d",
                  cfg["lock_port"], cfg["web_port"])
        return 1

    try:
        if args.backfill:
            return run_backfill(cfg, data_dir, args.days)
        return run_app(cfg, data_dir)
    finally:
        lock.close()


def run_app(cfg: dict, data_dir: str) -> int:
    pid_path = os.path.join(data_dir, "watcher.pid")
    flag = os.path.join(data_dir, "stop.flag")
    if os.path.exists(flag):
        os.remove(flag)
    with open(pid_path, "w") as f:
        f.write(str(os.getpid()))
    stop = threading.Event()

    def on_signal(signum, frame):
        log.info("Получен сигнал %s — завершаю работу", signum)
        stop.set()

    for sig in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, sig):
            try:
                signal.signal(getattr(signal, sig), on_signal)
            except (ValueError, OSError):
                pass

    watcher = Watcher(cfg, data_dir)
    log.info("%s %s запущен. Папка логов: %s%s", APP_NAME, VERSION, watcher.logs_dir,
             "" if os.path.isdir(watcher.logs_dir) else " (НЕ НАЙДЕНА — укажите logs_dir в config.json)")
    online = Online(data_dir, cfg) if cfg["online_enabled"] else None
    app = App(cfg, data_dir, watcher, online)
    mods = modkit.activate(sys.modules[__name__], app, modkit.modules_dir(SCRIPT_DIR), stop)
    log.info("Модули: %s", ", ".join(f"{m.id}{'' if m.enabled else ' (выключен)'}{' ОШИБКА' if m.error else ''}" for m in mods) or "нет")
    if cfg.get("update_check", True):
        app.updater = updater.Updater((cfg.get("update_repo") or UPDATE_REPO).strip(), VERSION, modkit.modules_dir(SCRIPT_DIR),
                                      lambda: app.modules, state_path=os.path.join(data_dir, "updates.json"))
        threading.Thread(target=update_loop, args=(app, stop), name="updates", daemon=True).start()
    srv = None
    if cfg["web_enabled"]:
        try:
            srv = make_server(app)
            threading.Thread(target=srv.serve_forever, name="web", daemon=True).start()
            log.info("Страница: http://localhost:%d", cfg["web_port"])
        except OSError as e:
            log.error("Веб-сервер не запущен: порт %d занят или недоступен (%s). Работаю без страницы.",
                      cfg["web_port"], e)
    if online:
        threading.Thread(target=online_loop, args=(app, stop), name="online", daemon=True).start()
    try:
        while not stop.is_set():
            try:
                watcher.poll()
            except Exception:
                log.exception("Ошибка цикла опроса")
            if os.path.exists(flag):
                log.info("Найден stop.flag — завершаю работу")
                break
            stop.wait(cfg["poll_seconds"])
    finally:
        stop.set()
        watcher.changed_event.set()
        for hook in app.stop_hooks:
            try:
                hook()
            except Exception:
                log.exception("Модуль не остановился")
        watcher.save_state(force=True)   # незавершённые сессии сохраняются и продолжатся после перезапуска
        if srv:
            srv.shutdown()
            srv.server_close()
        for p in (pid_path, flag):
            try:
                os.remove(p)
            except OSError:
                pass
        log.info("Остановлено.")
    return 0


if __name__ == "__main__":
    sys.modules.setdefault("eve_log_watcher", sys.modules[__name__])
    sys.exit(main())
