# -*- coding: utf-8 -*-
"""
Собрать reference_crystals.json — кристаллы для добычи в разделе «Руда» модуля «Справочник».

Из справочника игры (SDE): кристаллы (группа 482, в продаже), названия (англ. и рус.), какие руды подходят — список типов
из атрибута «Valid target types» (typeLists: группы и отдельные типы). Из публичного ESI: атрибуты кристаллов — множитель
добычи, длительность цикла, шанс и объём отходов, износ, расход накопителя, навык.

Запуск — из папки myauth сервера Alliance Auth (django-eveonline-sde с загруженным SDE), нужен интернет:
  set REFERENCE_CRYSTALS_OUT=<папка модуля reference>/reference_crystals.json
  python manage.py shell -c "exec(open(r'<папка модуля reference>/build_reference_crystals.py', encoding='utf-8').read())"

Формат:
  {"v": 1, "built": "<дата>",
   "crystals": [{"id", "name", "ru", "family", "type": "A"|"B"|"C"|"", "tech": 1|2, "yield", "duration", "residue_chance",
                 "residue_volume", "volatility", "volatility_damage", "cap", "skill", "skill_level", "volume", "ores": [type_id]}],
   "ores": {"<type_id>": [name_en, name_ru, group_id]}}
"""
import datetime
import json
import os
import re
import time
import urllib.error
import urllib.request

from eve_sde.models import ItemType, TypeListGroup, TypeListType

OUT = os.environ.get("REFERENCE_CRYSTALS_OUT") or os.path.abspath("reference_crystals.json")
ESI = "https://esi.evetech.net/latest"
ATTR = {782: "yield", 3161: "duration", 3160: "residue_chance", 3159: "residue_volume", 783: "volatility",
        784: "volatility_damage", 317: "cap", 182: "skill", 277: "skill_level", 3148: "list"}
NAME_RE = re.compile(r"^(.+?) Mining Crystal(?: Type ([ABC]))? (I|II)$")


def esi(path):
    req = urllib.request.Request(ESI + path + ("&" if "?" in path else "?") + "datasource=tranquility",
                                 headers={"User-Agent": "EveLogHUD reference builder"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return {}
            time.sleep(2)
        except Exception:
            time.sleep(2)
    return {}


crystals, lists = [], set()
for t in ItemType.objects.filter(group_id=482, published=True).order_by("name_en"):
    m = NAME_RE.match(t.name_en or "")
    if not m:
        continue
    d = esi(f"/universe/types/{t.id}/")
    a = {ATTR[x["attribute_id"]]: x["value"] for x in d.get("dogma_attributes") or [] if x["attribute_id"] in ATTR}
    if "list" not in a:
        continue
    lists.add(int(a["list"]))
    crystals.append({"id": t.id, "name": t.name_en, "ru": t.name_ru if t.name_ru and t.name_ru != t.name_en else "",
                     "family": m.group(1), "type": m.group(2) or "", "tech": 2 if m.group(3) == "II" else 1,
                     "yield": a.get("yield", 1), "duration": a.get("duration", 1), "residue_chance": a.get("residue_chance", 0),
                     "residue_volume": a.get("residue_volume", 0), "volatility": a.get("volatility", 0),
                     "volatility_damage": a.get("volatility_damage", 0), "cap": a.get("cap", 0),
                     "skill": int(a.get("skill", 0)), "skill_level": int(a.get("skill_level", 0)), "volume": t.volume or 0,
                     "list": int(a["list"])})

# руды списка: отдельные типы и целые группы (кроме исключённых); только опубликованные, без сжатой
# (Prismaticite для кристаллов «Erratic Ore» в справочнике — материал, не астероид, поэтому категорию не проверяем)
members = {}
for lid in lists:
    inc = set(TypeListType.objects.filter(type_list_id=lid, excluded=False).values_list("item_type_id", flat=True))
    exc = set(TypeListType.objects.filter(type_list_id=lid, excluded=True).values_list("item_type_id", flat=True))
    groups = set(TypeListGroup.objects.filter(type_list_id=lid, excluded=False).values_list("item_group_id", flat=True))
    inc |= set(ItemType.objects.filter(group_id__in=groups, published=True).values_list("id", flat=True))
    members[lid] = inc - exc
ores = {}
for t in ItemType.objects.filter(id__in=set().union(*members.values()), published=True).select_related("group"):
    if "Compressed" in (t.name_en or ""):                     # сжатая руда кристаллом не добывается
        continue
    ores[t.id] = [t.name_en, t.name_ru if t.name_ru and t.name_ru != t.name_en else "", t.group_id]
for c in crystals:
    c["ores"] = sorted((x for x in members[c.pop("list")] if x in ores), key=lambda x: ores[x][0])
skills = {s.id: s.name_ru or s.name_en for s in ItemType.objects.filter(id__in={c["skill"] for c in crystals})}
for c in crystals:
    c["skill_name"] = skills.get(c["skill"], "")

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"v": 1, "built": datetime.date.today().isoformat(), "crystals": crystals, "ores": {str(k): v for k, v in ores.items()}},
              f, ensure_ascii=False, separators=(",", ":"))
print(f"reference_crystals.json: кристаллов {len(crystals)}, руд {len(ores)}, {os.path.getsize(OUT) // 1024} КБ")
