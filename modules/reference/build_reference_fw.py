# -*- coding: utf-8 -*-
"""
Собрать reference_fw.json — раздел «Фракционные войны» модуля «Справочник»: фракции, их милиции и что продают
LP-магазины милиций.

Из публичного ESI (при сборке): фракции с милициями (/universe/factions/), кто с кем воюет (/fw/wars/), предложения
LP-магазинов корпораций-милиций (/loyalty/stores/{корпорация}/offers/), названия корпораций и систем.
Из справочника игры (SDE): названия предметов (англ. и рус.), группа и категория (для фильтров).
Живая статистика войны (системы, убийства, очки победы) — не здесь: её подгружает модуль из ESI во время работы.

Запуск — из папки myauth сервера Alliance Auth (django-eveonline-sde с загруженным SDE), нужен интернет:
  set REFERENCE_FW_OUT=<папка модуля reference>/reference_fw.json
  python manage.py shell -c "exec(open(r'<папка модуля reference>/build_reference_fw.py', encoding='utf-8').read())"

Формат:
  {"v": 1, "built": "<дата>",
   "factions": [{"id", "name", "corp_id", "corp", "militia_id", "militia", "hq_id", "hq", "against": [фракции]}],
   "offers":   {"<милиция>": [[предмет, кол-во, lp, isk, ak, [[предмет, кол-во]]], ...]},
   "types":    {"<type_id>": [name_en, name_ru, group_id, category_id]},
   "groups":   {"<group_id>": название_ru},
   "cats":     {"<category_id>": название_ru}}
"""
import datetime
import json
import os
import time
import urllib.error
import urllib.request
from collections import defaultdict

from eve_sde.models import ItemCategory, ItemGroup, ItemType

OUT = os.environ.get("REFERENCE_FW_OUT") or os.path.abspath("reference_fw.json")
ESI = "https://esi.evetech.net/latest"


def esi(path, body=None):
    req = urllib.request.Request(ESI + path + ("&" if "?" in path else "?") + "datasource=tranquility",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"User-Agent": "EveLogHUD reference builder", "Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return []
            time.sleep(2)
        except Exception:
            time.sleep(2)
    return []


wars = defaultdict(list)
for w in esi("/fw/wars/") or []:
    wars[w["faction_id"]].append(w["against_id"])
factions, offers, used = [], {}, set()
for f in esi("/universe/factions/") or []:
    mil = f.get("militia_corporation_id")
    if not mil:
        continue
    rows = []
    for o in esi(f"/loyalty/stores/{mil}/offers/") or []:
        req = [[r["type_id"], r["quantity"]] for r in o.get("required_items") or []]
        rows.append([o["type_id"], o.get("quantity") or 1, o.get("lp_cost") or 0, o.get("isk_cost") or 0, o.get("ak_cost") or 0, req])
        used.update([o["type_id"]] + [t for t, _ in req])
    offers[str(mil)] = rows
    name = lambda path: (esi(path) or {}).get("name") or ""
    factions.append({"id": f["faction_id"], "name": f["name"], "corp_id": f.get("corporation_id"), "corp": name(f"/corporations/{f.get('corporation_id')}/"),
                     "militia_id": mil, "militia": name(f"/corporations/{mil}/"), "hq_id": f.get("solar_system_id"),
                     "hq": name(f"/universe/systems/{f.get('solar_system_id')}/") if f.get("solar_system_id") else "",
                     "against": sorted(wars.get(f["faction_id"], []))})

types, gids = {}, set()
for t, en, ru, g, c in ItemType.objects.filter(id__in=used).values_list("id", "name_en", "name_ru", "group_id", "group__category_id"):
    types[str(t)] = [en or str(t), ru if ru and ru != en else "", g, c]
    gids.add(g)
groups = {str(g): ru or en for g, ru, en in ItemGroup.objects.filter(id__in=gids).values_list("id", "name_ru", "name_en")}
cats = {str(c): ru or en for c, ru, en in ItemCategory.objects.filter(id__in={v[3] for v in types.values()}).values_list("id", "name_ru", "name_en")}

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump({"v": 1, "built": datetime.date.today().isoformat(), "factions": factions, "offers": offers,
               "types": types, "groups": groups, "cats": cats}, fh, ensure_ascii=False, separators=(",", ":"))
print(f"reference_fw.json: фракций {len(factions)}, предложений {sum(len(v) for v in offers.values())}, предметов {len(types)}, "
      f"{os.path.getsize(OUT) // 1024} КБ")
