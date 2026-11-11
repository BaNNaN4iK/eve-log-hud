# -*- coding: utf-8 -*-
"""
Карта: регионы EVE схемой (как 2D-карта игры), где сейчас ваши персонажи, разведка из интел-каналов и активность по системам.

Только стандартная библиотека. Системы, врата и раскладка — map_data.json (из SDE, build_map_data.py), работают без интернета.
Где персонаж — из логов чата: локальный канал пишет «Канал изменен на Локальный: <система>» (каждый персонаж — свой файл,
Listener в шапке); запасной вариант — прыжки из боевых логов трекера. Разведка — сообщения выбранных интел-каналов: названия
систем (в логах они помечены «*»), «чисто»/clr — система чистая; до каждой — сколько прыжков от ваших персонажей.
Активность — публичный ESI: прыжки, убитые NPC, корабли и капсулы за час, суверенитет альянсов, инкурсии.
"""
import json
import os
import re
import threading
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
INTEL_KEEP = 2 * 3600                  # сколько держать сообщения разведки
ACTIVITY_TTL = 3600                    # ESI обновляет прыжки и убийства раз в час
SOV_TTL = 6 * 3600
SCAN_EVERY = 2                         # как часто читать логи чата, с
FILE_AGE = 24 * 3600                   # файлы чата старше суток не читаем
ALARM_FRESH = 180                      # тревога — только по свежим сообщениям (не при перечитывании старого лога)
ALARM_GAP = 3                          # не чаще раза в 3 с
SOUNDS = {"beep": "два сигнала", "exclamation": "Windows: восклицание", "hand": "Windows: критическая ошибка",
          "asterisk": "Windows: звёздочка", "wav": "свой файл .wav"}
LINE_RE = re.compile(r"^﻿?\[ (\d{4})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2}):(\d{2}) \] (.+?) > (.*)$")
LOCAL_RE = re.compile(r"(?:Канал изменен на Локальный|Channel changed to Local)\s*:\s*(.+?)\*?\s*$")
SYSTEM_SENDERS = {"Система EVE", "EVE System"}
CLEAR_WORDS = {"clr", "clear", "чисто", "чист", "клир"}
HEADER_RE = {"channel": re.compile(r"Channel Name:\s*(.+)"), "listener": re.compile(r"Listener:\s*(.+)"),
             "started": re.compile(r"Session started:\s*(.+)")}


def load_map(path: Optional[str] = None) -> dict:
    try:
        with open(path or os.path.join(HERE, "map_data.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"regions": {}, "constellations": {}, "systems": {}, "gates": []}


class Universe:
    """Системы, врата и поиск: по названию, соседи, прыжки между системами."""

    def __init__(self, d: dict):
        self.d = d
        self.sys = {int(k): v for k, v in (d.get("systems") or {}).items()}
        self.const = {int(k): v for k, v in (d.get("constellations") or {}).items()}
        self.by_name = {v[0].casefold(): k for k, v in self.sys.items()}
        self.adj: Dict[int, List[int]] = {k: [] for k in self.sys}
        for a, b in d.get("gates") or []:
            if a in self.adj and b in self.adj:
                self.adj[a].append(b)
                self.adj[b].append(a)
        self.multi = {}                                          # названия из нескольких слов: «New Caldari», «Old Man Star»
        for name, sid in self.by_name.items():
            parts = name.split()
            if len(parts) > 1:
                self.multi.setdefault(len(parts), {})[name] = sid

    def region(self, sid: int) -> Optional[int]:
        s = self.sys.get(sid)
        return self.const.get(s[1], [None, None])[1] if s else None

    def find(self, name: str) -> Optional[int]:
        return self.by_name.get((name or "").strip().strip("*").casefold())

    def jumps(self, starts: List[int], limit: int = 30) -> Dict[int, int]:
        """Сколько прыжков до каждой системы от ближайшей из starts (не дальше limit)."""
        dist = {s: 0 for s in starts if s in self.adj}
        frontier = list(dist)
        for d in range(1, limit + 1):
            nxt = []
            for s in frontier:
                for n in self.adj[s]:
                    if n not in dist:
                        dist[n] = d
                        nxt.append(n)
            if not nxt:
                break
            frontier = nxt
        return dist

    def systems_in(self, text: str) -> Tuple[List[int], bool]:
        """Системы, названные в сообщении разведки, и есть ли «чисто»."""
        clean = re.sub(r"[*,;!?()\[\]<>\"']", " ", text)
        words = clean.split()
        low = [w.casefold().strip(".:") for w in words]
        found, used = [], set()
        for n in sorted(self.multi, reverse=True):                 # сначала названия из нескольких слов
            for i in range(len(low) - n + 1):
                key = " ".join(low[i:i + n])
                sid = self.multi[n].get(key)
                if sid and not used.intersection(range(i, i + n)):
                    found.append(sid)
                    used.update(range(i, i + n))
        for i, w in enumerate(low):
            if i in used or len(w) < 3:
                continue
            sid = self.by_name.get(w)
            if sid and sid not in found:
                found.append(sid)
        return found, any(w in CLEAR_WORDS for w in low)


def parse_header(text: str) -> dict:
    out = {}
    for k, rx in HEADER_RE.items():
        m = rx.search(text)
        if m:
            out[k] = m.group(1).strip()
    return out


def parse_chat_line(line: str) -> Optional[Tuple[int, str, str]]:
    """Строка лога чата → (время UTC, кто, текст) или None."""
    import calendar
    m = LINE_RE.match(line.strip("\r\n").lstrip("﻿"))
    if not m:
        return None
    g = m.groups()
    ts = calendar.timegm((int(g[0]), int(g[1]), int(g[2]), int(g[3]), int(g[4]), int(g[5])))
    return ts, g[6].strip(), g[7].strip()


class Chat:
    """Читает логи чата: где персонажи (локальный канал) и сообщения интел-каналов."""

    def __init__(self, uni: Universe, chat_dir: str, intel: List[str]):
        self.uni, self.dir = uni, chat_dir
        self.intel = set(intel)
        self.files: Dict[str, dict] = {}                         # путь → {off, channel, listener}
        self.where: Dict[str, Tuple[int, int]] = {}             # персонаж → (система, время)
        self.reports: deque = deque(maxlen=2000)
        self.channels: Dict[str, int] = {}                      # канал → время последнего файла
        self.lock = threading.Lock()
        self.version = 0
        self.on_report = None                                    # новое сообщение разведки → fn(report) (тревога)

    def set_intel(self, names: List[str]) -> None:
        with self.lock:
            new = set(names) - self.intel
            self.intel = set(names)
            for path, f in self.files.items():                   # новый канал — перечитать его файлы с начала
                if f.get("channel") in new:
                    f["off"] = f["start"]
            self.version += 1

    def scan(self, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        if not self.dir or not os.path.isdir(self.dir):
            return
        try:
            names = os.listdir(self.dir)
        except OSError:
            return
        for name in names:
            if not name.lower().endswith(".txt"):
                continue
            path = os.path.join(self.dir, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            if now - st.st_mtime > FILE_AGE:
                continue
            f = self.files.get(path)
            if f is None:
                f = self._open(path)
                if f is None:
                    continue
                self.files[path] = f
            ch = f.get("channel")
            if ch:
                self.channels[ch] = max(self.channels.get(ch, 0), int(st.st_mtime))
            if st.st_size > f["off"] and (ch == "Локальный" or ch == "Local" or ch in self.intel):
                self._read(path, f, st.st_size, now)

    def _open(self, path: str) -> Optional[dict]:
        try:
            with open(path, "rb") as fh:
                head = fh.read(4096)
        except OSError:
            return None
        text = head.decode("utf-16-le", errors="ignore")
        h = parse_header(text)
        if not h.get("channel"):
            return None
        # начало сообщений — после второй линии из дефисов шапки
        idx = [m.end() for m in re.finditer(r"-{20,}", text)]
        start = len(text[:idx[1]].encode("utf-16-le")) if len(idx) > 1 else 0      # BOM — первый символ text, уже учтён
        return {"channel": h["channel"], "listener": h.get("listener", ""), "start": start, "off": start}

    def _read(self, path: str, f: dict, size: int, now: float) -> None:
        try:
            with open(path, "rb") as fh:
                fh.seek(f["off"])
                raw = fh.read(min(size - f["off"], 4_000_000))
        except OSError:
            return
        cut = len(raw) - (len(raw) % 2)
        text = raw[:cut].decode("utf-16-le", errors="ignore")
        last_nl = text.rfind("\n")
        if last_nl < 0:
            return                                               # строка ещё не дописана
        done = text[:last_nl + 1]
        f["off"] += len(done.encode("utf-16-le"))
        local = f["channel"] in ("Локальный", "Local")
        for line in done.splitlines():
            p = parse_chat_line(line)
            if not p:
                continue
            ts, who, msg = p
            if who in SYSTEM_SENDERS:
                m = LOCAL_RE.search(msg) if local else None
                if m:
                    sid = self.uni.find(m.group(1))
                    if sid and f["listener"]:
                        prev = self.where.get(f["listener"])
                        if not prev or ts >= prev[1]:
                            self.where[f["listener"]] = (sid, ts)
                            self.version += 1
                continue
            if local or now - ts > INTEL_KEEP:
                continue
            systems, clear = self.uni.systems_in(msg)
            rep = {"ts": ts, "channel": f["channel"], "who": who, "text": msg[:400], "systems": systems, "clear": clear}
            with self.lock:
                self.reports.append(rep)
                self.version += 1
            if self.on_report and f["channel"] in self.intel:
                self.on_report(rep, now)

    def recent(self, now: Optional[float] = None) -> List[dict]:
        now = time.time() if now is None else now
        with self.lock:
            return sorted((r for r in self.reports if now - r["ts"] <= INTEL_KEEP and r["channel"] in self.intel), key=lambda r: r["ts"])


class Activity:
    """Публичный ESI: прыжки, убийства, суверенитет, инкурсии — в фоне, с кэшем."""

    def __init__(self, esi):
        self.esi = esi
        self.at = self.sov_at = 0
        self.data: Dict[int, list] = {}                          # система → [прыжки, NPC, корабли, капсулы]
        self.sov: Dict[int, int] = {}                            # система → альянс (или фракция)
        self.names: Dict[int, str] = {}
        self.incursions: List[int] = []
        self.busy, self.error = False, ""

    def get(self, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        if self.esi is not None and not self.busy and (now - self.at >= ACTIVITY_TTL or now - self.sov_at >= SOV_TTL):
            self.busy = True
            threading.Thread(target=self.refresh, name="map-activity", daemon=True).start()

    def refresh(self) -> None:
        try:
            now = time.time()
            if now - self.at >= ACTIVITY_TTL:
                data: Dict[int, list] = {}
                jumps, _ = self.esi("/universe/system_jumps/")
                for r in jumps or []:
                    data.setdefault(r["system_id"], [0, 0, 0, 0])[0] = r.get("ship_jumps", 0)
                kills, _ = self.esi("/universe/system_kills/")
                for r in kills or []:
                    row = data.setdefault(r["system_id"], [0, 0, 0, 0])
                    row[1], row[2], row[3] = r.get("npc_kills", 0), r.get("ship_kills", 0), r.get("pod_kills", 0)
                inc, _ = self.esi("/incursions/")
                self.incursions = sorted({s for i in inc or [] for s in i.get("infested_solar_systems") or []})
                self.data, self.at, self.error = data, int(now), ""
            if now - self.sov_at >= SOV_TTL:
                sov, _ = self.esi("/sovereignty/map/")
                m = {}
                for r in sov or []:
                    owner = r.get("alliance_id") or r.get("faction_id")
                    if owner:
                        m[r["system_id"]] = owner
                want = sorted(set(m.values()) - set(self.names))
                for i in range(0, len(want), 500):
                    try:
                        rows, _ = self.esi("/universe/names/", "POST", want[i:i + 500])
                        for r in rows or []:
                            self.names[r["id"]] = r["name"]
                    except Exception:
                        pass
                self.sov, self.sov_at = m, int(now)
        except Exception as e:
            self.error = str(e)
            self.at = self.at or int(time.time()) - ACTIVITY_TTL + 300  # не вышло — повторим через 5 минут
        finally:
            self.busy = False


class Sound:
    """Звук тревоги из самого трекера (Windows, winsound): звучит, даже если окно программы закрыто."""

    def __init__(self):
        try:
            import winsound
            self.ws = winsound
        except ImportError:                                      # не Windows — звука нет, страница скажет
            self.ws = None
        self.last = 0.0

    def play(self, kind: str = "beep", path: str = "", urgent: bool = False, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        if self.ws is None or now - self.last < ALARM_GAP:
            return False
        self.last = now
        threading.Thread(target=self._play, args=(kind, path, urgent), name="map-sound", daemon=True).start()
        return True

    def _play(self, kind: str, path: str, urgent: bool) -> None:
        ws = self.ws
        try:
            alias = {"exclamation": "SystemExclamation", "hand": "SystemHand", "asterisk": "SystemAsterisk"}.get(kind)
            if kind == "wav" and path and os.path.isfile(path):
                ws.PlaySound(path, ws.SND_FILENAME)
                if urgent:
                    ws.PlaySound(path, ws.SND_FILENAME)
            elif alias:
                ws.PlaySound(alias, ws.SND_ALIAS)
                if urgent:
                    time.sleep(0.15)
                    ws.PlaySound(alias, ws.SND_ALIAS)
            else:                                                # два сигнала; враг совсем рядом — четыре, выше
                for _ in range(4 if urgent else 2):
                    ws.Beep(1200 if urgent else 880, 140)
                    time.sleep(0.06)
        except (RuntimeError, OSError):
            pass


def alarm_hit(rep: dict, dist: Dict[int, int], rng: int, now: float) -> Optional[int]:
    """Тревога по сообщению разведки: свежее, не «чисто», система в пределах rng прыжков → сколько прыжков, иначе None."""
    if rep["clear"] or now - rep["ts"] > ALARM_FRESH:
        return None
    near = [dist[s] for s in rep["systems"] if s in dist]
    return min(near) if near and min(near) <= rng else None


def chat_dir_for(logs_dir: str) -> str:
    """Логи чата лежат рядом с боевыми: …/logs/Gamelogs → …/logs/Chatlogs."""
    return os.path.join(os.path.dirname(os.path.normpath(logs_dir or "")), "Chatlogs") if logs_dir else ""


def setup(ctx) -> None:
    uni = Universe(load_map())
    path = os.path.join(ctx.data_dir, "map_settings.json")
    try:
        with open(path, encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, ValueError):
        settings = {}
    settings = {"intel": list(settings.get("intel") or []), "range": int(settings.get("range") or 5), "sound": settings.get("sound", True) is not False,
                "sound_kind": settings.get("sound_kind") if settings.get("sound_kind") in SOUNDS else "beep",
                "sound_file": str(settings.get("sound_file") or "")}
    sound = Sound()
    chat = Chat(uni, chat_dir_for(getattr(ctx.watcher, "logs_dir", "")), settings["intel"])
    act = Activity(ctx.online.esi if ctx.online is not None else None)

    def on_report(rep, now):                                     # тревога — из трекера, окно может быть закрыто
        if not settings["sound"]:
            return
        cs = chars()
        if not cs:
            return
        j = alarm_hit(rep, uni.jumps([c["system"] for c in cs], settings["range"]), settings["range"], now)
        if j is not None:
            sound.play(settings["sound_kind"], settings["sound_file"], urgent=j <= 1, now=now)
    chat.on_report = on_report

    def loop():
        while not ctx.stop.wait(SCAN_EVERY):
            try:
                chat.scan()
            except Exception as e:
                ctx.log.warning("Карта: логи чата не прочитаны: %s", e)
    ctx.thread(loop, "map-chat")

    def chars() -> List[dict]:
        out, seen = [], set()
        for who, (sid, ts) in chat.where.items():
            out.append({"name": who, "system": sid, "at": ts, "src": "чат"})
            seen.add(who)
        for who, name in (getattr(ctx.watcher, "cur_sys", {}) or {}).items():   # запасной: прыжки из боевых логов
            sid = uni.find(name)
            if sid and who not in seen:
                out.append({"name": who, "system": sid, "at": 0, "src": "бой"})
        return sorted(out, key=lambda c: -c["at"])

    def static(qs):
        return {"ok": True, **uni.d}

    def state(qs):
        act.get()
        cs = chars()
        dist = uni.jumps([c["system"] for c in cs], 40) if cs else {}
        reps = []
        for r in chat.recent():
            near = [dist[s] for s in r["systems"] if s in dist]
            reps.append(dict(r, jumps=min(near) if near else None))
        chans = sorted(({"name": k, "at": v, "intel": k in chat.intel} for k, v in chat.channels.items()
                        if k not in ("Локальный", "Local")), key=lambda c: (not c["intel"], -c["at"]))
        return {"ok": True, "chars": cs, "intel": reps[-300:], "version": chat.version, "channels": chans, "settings": settings,
                "sounds": SOUNDS, "sound_ok": sound.ws is not None,
                "activity": {str(k): v for k, v in act.data.items()}, "activity_at": act.at or None, "activity_error": act.error,
                "sov": {str(k): v for k, v in act.sov.items()}, "sov_names": {str(k): v for k, v in act.names.items()},
                "incursions": act.incursions, "online": ctx.online is not None, "chat_dir": chat.dir,
                "chat_ok": bool(chat.dir and os.path.isdir(chat.dir))}

    def save(body, qs=None):
        b = body if isinstance(body, dict) else {}
        if isinstance(b.get("intel"), list):
            settings["intel"] = [str(x)[:100] for x in b["intel"]][:30]
            chat.set_intel(settings["intel"])
        if b.get("range") is not None:
            try:
                settings["range"] = max(0, min(30, int(b["range"])))
            except (TypeError, ValueError):
                pass
        if "sound" in b:
            settings["sound"] = bool(b["sound"])
        if b.get("sound_kind") in SOUNDS:
            settings["sound_kind"] = b["sound_kind"]
        if isinstance(b.get("sound_file"), str):
            settings["sound_file"] = b["sound_file"].strip().strip('"')[:400]
        ctx.core.atomic_write_json(path, settings)
        return {"ok": True, "settings": settings}

    ctx.get("/api/map/data", static)
    ctx.get("/api/map/state", state)
    def test_sound(body=None, qs=None):
        if sound.ws is None:
            return {"ok": False, "message": "Звук тревоги работает только в Windows."}
        if settings["sound_kind"] == "wav" and not os.path.isfile(settings["sound_file"]):
            return {"ok": False, "message": "Файл не найден: " + (settings["sound_file"] or "не указан") + " — играю два сигнала."} if sound.play("beep", now=time.time() + ALARM_GAP) else {"ok": False}
        sound.last = 0
        sound.play(settings["sound_kind"], settings["sound_file"], urgent=bool((body or {}).get("urgent")))
        return {"ok": True}

    ctx.post("/api/map/settings", save)
    ctx.post("/api/map/sound/test", test_sound)
