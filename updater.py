# -*- coding: utf-8 -*-
"""
Обновления с GitHub: сверка версий приложения и модулей с последним выпуском (Release) репозитория и установка модулей.

Только стандартная библиотека. Источник — https://api.github.com/repos/<repo>/releases/latest. В выпуске лежат:
  modules-index.json     {"app_version": "2.2.0", "modules": [{"id", "name", "version", "file", "sha256", "size", "min_app"}]}
  <id>-<версия>.zip      модуль: папка <id>/ с module.json внутри
  EveLogHUD-<версия>.zip всё приложение (его ставят вручную: exe нельзя заменить, пока он работает)

Установка модуля: скачать архив → сверить SHA-256 и размер с modules-index.json → проверить, что внутри только папка
<id>/ без «..» и абсолютных путей и module.json с тем же id и версией → распаковать во временную папку → старую версию
отложить в modules/.old/ → новую поставить на место. Если что-то пошло не так, старая версия возвращается.
Вступает в силу после перезапуска трекера.
"""
import hashlib
import io
import json
import logging
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from typing import Callable, Dict, List, Optional

log = logging.getLogger("updater")

HOSTS = {"api.github.com", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
REPO_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,39}/[A-Za-z0-9_.\-]{1,100}$")
ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
INDEX_NAME = "modules-index.json"
MAX_ZIP = 30 * 1024 * 1024           # архив модуля
MAX_UNPACKED = 80 * 1024 * 1024      # распакованный модуль
MAX_FILES = 500


class UpdateError(Exception):
    """Ошибка с понятным пользователю текстом."""


def vtuple(v: str) -> tuple:
    """«2.10.1» → (2, 10, 1); мусор → (0,). Для сравнения версий."""
    parts = re.findall(r"\d+", str(v or ""))
    return tuple(int(p) for p in parts[:4]) or (0,)


def newer(a: str, b: str) -> bool:
    """a новее b."""
    return vtuple(a) > vtuple(b)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Переходить по перенаправлениям только на хосты GitHub (файлы выпусков отдаются с другого домена)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname not in HOSTS:
            raise UpdateError(f"GitHub перенаправил на чужой адрес: {urllib.parse.urlsplit(newurl).hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_get(url: str, ua: str, accept: str = "application/json", limit: int = MAX_ZIP) -> bytes:
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.hostname not in HOSTS:
        raise UpdateError(f"Адрес не GitHub: {u.hostname}")
    opener = urllib.request.build_opener(_SafeRedirect())
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": accept})
    try:
        with opener.open(req, timeout=30) as resp:
            data = resp.read(limit + 1)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("На GitHub нет выпусков (или репозиторий закрытый).") from e
        if e.code == 403:
            raise UpdateError("GitHub временно ограничил запросы — попробуйте через час.") from e
        raise UpdateError(f"GitHub ответил ошибкой {e.code}.") from e
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError(f"Нет связи с GitHub: {getattr(e, 'reason', e)}") from e
    if len(data) > limit:
        raise UpdateError("Файл слишком большой.")
    return data


class Updater:
    """Состояние проверки и установка. modules() → список modkit.Module; fetch(url, accept) → bytes (для тестов)."""

    def __init__(self, repo: str, app_version: str, root: str, modules: Callable[[], list],
                 fetch: Optional[Callable[[str, str], bytes]] = None, state_path: Optional[str] = None):
        self.repo = repo if REPO_RE.match(repo or "") else ""
        self.app_version = app_version
        self.root = root
        self.modules = modules
        self.fetch = fetch or (lambda url, accept: http_get(url, f"EveLogHUD/{app_version} (updater)", accept))
        self.state_path = state_path
        self.lock = threading.Lock()
        self.release: Optional[dict] = None         # {"tag", "url", "published", "assets": {name: url}}
        self.index: Optional[dict] = None
        self.checked = 0
        self.error = ""
        self.pending: Dict[str, str] = {}             # установлено, ждёт перезапуска: id → версия
        self._load_state()

    # ----- сохранение последней проверки (чтобы после перезапуска сразу показать) -----
    def _load_state(self) -> None:
        if not self.state_path:
            return
        try:
            with open(self.state_path, encoding="utf-8") as f:
                s = json.load(f)
            if s.get("repo") == self.repo:
                self.release, self.index, self.checked = s.get("release"), s.get("index"), int(s.get("checked") or 0)
        except (OSError, ValueError, TypeError):
            pass

    def _save_state(self, write_json: Optional[Callable] = None) -> None:
        if not self.state_path:
            return
        data = {"repo": self.repo, "release": self.release, "index": self.index, "checked": self.checked}
        try:
            if write_json:
                write_json(self.state_path, data)
            else:
                with open(self.state_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
        except OSError as e:
            log.info("Состояние обновлений не сохранено: %s", e)

    # ----- проверка -----
    def check(self, write_json: Optional[Callable] = None) -> dict:
        if not self.repo:
            self.error = "Не указан репозиторий GitHub (update_repo в config.json)."
            return self.status()
        try:
            raw = self.fetch(f"https://api.github.com/repos/{self.repo}/releases/latest", "application/vnd.github+json")
            rel = json.loads(raw.decode("utf-8"))
            assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets") or []
                      if isinstance(a, dict) and a.get("name") and a.get("browser_download_url")}
            release = {"tag": rel.get("tag_name") or "", "url": rel.get("html_url") or "",
                       "published": rel.get("published_at") or "", "assets": assets}
            index = None
            if INDEX_NAME in assets:
                index = json.loads(self.fetch(assets[INDEX_NAME], "application/octet-stream").decode("utf-8"))
                if not isinstance(index, dict) or not isinstance(index.get("modules"), list):
                    raise UpdateError("В выпуске испорчен список модулей.")
            with self.lock:
                self.release, self.index, self.checked, self.error = release, index, int(time.time()), ""
            self._save_state(write_json)
        except (UpdateError, ValueError, KeyError, TypeError) as e:
            with self.lock:
                self.error, self.checked = str(e) or "Не удалось проверить обновления.", int(time.time())
            log.info("Проверка обновлений: %s", self.error)
        return self.status()

    def _remote(self) -> Dict[str, dict]:
        out = {}
        for m in (self.index or {}).get("modules") or []:
            if isinstance(m, dict) and ID_RE.match(str(m.get("id") or "")) and m.get("version") and m.get("file"):
                out[m["id"]] = m
        return out

    def status(self) -> dict:
        with self.lock:
            rel, remote = self.release, self._remote()
        local = {m.id: m for m in self.modules()}
        rows = []
        for mid in sorted(set(local) | set(remote)):
            lm, rm = local.get(mid), remote.get(mid)
            installed = lm.meta.get("version", "") if lm else ""
            latest = rm.get("version", "") if rm else ""
            needs_app = bool(rm and rm.get("min_app") and newer(rm["min_app"], self.app_version))
            pending = self.pending.get(mid, "")
            rows.append({
                "id": mid, "pending": pending, "name": (lm.meta.get("name") if lm else None) or (rm or {}).get("name") or mid,
                "description": (rm or {}).get("description", "") if not lm else "",
                "installed": installed, "latest": latest,
                "update": bool(lm and rm and newer(latest, installed) and not needs_app and not pending),
                "new": bool(rm and not lm and not needs_app and not pending),
                "needs_app": rm.get("min_app") if needs_app else "",
                "kind": lm.info()["kind"] if lm else "",
            })
        app_latest = ((self.index or {}).get("app_version") or (rel or {}).get("tag", "")).lstrip("vV") if rel else ""
        app_zip = next((n for n in (rel or {}).get("assets", {}) if re.fullmatch(r"EveLogHUD-[\d.]+\.zip", n)), "")
        return {
            "ok": True, "enabled": bool(self.repo), "repo": self.repo, "checked": self.checked, "error": self.error,
            "release": {"tag": rel.get("tag"), "url": rel.get("url"), "published": rel.get("published")} if rel else None,
            "app": {"current": self.app_version, "latest": app_latest, "newer": bool(app_latest and newer(app_latest, self.app_version)),
                    "download": (rel or {}).get("assets", {}).get(app_zip, "") if app_zip else "",
                    "url": (rel or {}).get("url", "")},
            "modules": rows, "updates": sum(1 for r in rows if r["update"]), "pending": bool(self.pending),
        }

    # ----- установка -----
    def install(self, mid: str) -> dict:
        if not ID_RE.match(mid or ""):
            raise UpdateError("Неверное имя модуля.")
        with self.lock:
            rm = self._remote().get(mid)
            assets = dict((self.release or {}).get("assets") or {})
        if not rm:
            raise UpdateError("Этого модуля нет в последнем выпуске — нажмите «Проверить».")
        if rm.get("min_app") and newer(rm["min_app"], self.app_version):
            raise UpdateError(f"Нужна версия приложения {rm['min_app']} или новее — сначала обновите приложение.")
        url = assets.get(rm["file"])
        if not url:
            raise UpdateError(f"В выпуске нет файла {rm['file']}.")
        data = self.fetch(url, "application/octet-stream")
        if rm.get("size") and len(data) != int(rm["size"]):
            raise UpdateError("Размер скачанного архива не совпал — попробуйте ещё раз.")
        if not rm.get("sha256") or hashlib.sha256(data).hexdigest() != str(rm["sha256"]).lower():
            raise UpdateError("Контрольная сумма архива не совпала — архив повреждён или подменён, не устанавливаю.")
        return self.install_zip(mid, data, rm["version"])

    def install_zip(self, mid: str, data: bytes, version: str) -> dict:
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise UpdateError("Архив модуля повреждён.") from e
        infos = zf.infolist()
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNPACKED:
            raise UpdateError("Архив модуля слишком большой.")
        for i in infos:
            name = i.filename.replace("\\", "/")
            parts = name.split("/")
            if name.startswith("/") or ":" in name or ".." in parts or parts[0] != mid:
                raise UpdateError(f"В архиве лишний или опасный путь: {i.filename}")
        try:
            meta = json.loads(zf.read(f"{mid}/module.json").decode("utf-8-sig"))
        except (KeyError, ValueError) as e:
            raise UpdateError("В архиве нет module.json.") from e
        if meta.get("id") != mid or str(meta.get("version")) != str(version):
            raise UpdateError("module.json в архиве не совпадает с выпуском.")

        os.makedirs(self.root, exist_ok=True)
        stage = os.path.join(self.root, f".staging-{mid}")
        shutil.rmtree(stage, ignore_errors=True)
        os.makedirs(stage)
        try:
            for i in infos:
                if i.is_dir():
                    continue
                target = os.path.join(stage, *i.filename.replace("\\", "/").split("/"))
                if not os.path.abspath(target).startswith(os.path.abspath(stage) + os.sep):
                    raise UpdateError(f"Опасный путь: {i.filename}")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(i) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            new_dir, cur_dir = os.path.join(stage, mid), os.path.join(self.root, mid)
            backup = ""
            old_version = ""
            if os.path.isdir(cur_dir):
                try:
                    with open(os.path.join(cur_dir, "module.json"), encoding="utf-8-sig") as f:
                        old_version = str(json.load(f).get("version") or "")
                except (OSError, ValueError):
                    pass
                os.makedirs(os.path.join(self.root, ".old"), exist_ok=True)
                backup = os.path.join(self.root, ".old", f"{mid}-{old_version or 'x'}-{int(time.time())}")
                os.replace(cur_dir, backup)
            try:
                os.replace(new_dir, cur_dir)
            except OSError:
                if backup:
                    os.replace(backup, cur_dir)               # вернуть старую версию
                raise
        except OSError as e:
            raise UpdateError(f"Не удалось записать файлы модуля: {e}") from e
        finally:
            shutil.rmtree(stage, ignore_errors=True)
        self.pending[mid] = str(version)
        log.info("Модуль %s обновлён: %s → %s", mid, old_version or "—", version)
        return {"id": mid, "from": old_version, "to": str(version), "backup": os.path.basename(backup) if backup else ""}


def build_index(app_version: str, modules: List[dict]) -> dict:
    """modules-index.json для выпуска: modules — [{id, name, description, version, file, path}] (path — локальный zip)."""
    out = []
    for m in modules:
        with open(m["path"], "rb") as f:
            data = f.read()
        out.append({"id": m["id"], "name": m.get("name") or m["id"], "description": m.get("description", ""),
                    "version": m["version"], "file": m["file"], "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(), "min_app": m.get("min_app", "")})
    return {"app_version": app_version, "modules": out}
