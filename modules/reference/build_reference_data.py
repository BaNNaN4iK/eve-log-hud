# -*- coding: utf-8 -*-
"""
Собрать reference_data.json для модуля «Справочник» из справочника игры (SDE).

Запуск — из папки myauth сервера Alliance Auth, где установлен django-eveonline-sde (eve_sde) и загружен SDE:
  set REFERENCE_DATA_OUT=<папка модуля reference>/reference_data.json
  python manage.py shell -c "exec(open(r'<папка модуля reference>/build_reference_data.py', encoding='utf-8').read())"

Формат:
  {"v": 1, "built": "<дата>",
   "ores":      [[type_id, name_en, name_ru, group_id, порция_переработки, объём_м3, [[минерал, кол-во], ...]], ...],
   "groups":    {"<group_id>": [name_en, name_ru]},
   "materials": {"<type_id>": [name_en, name_ru, group_id]}}
Руды — все опубликованные предметы категории «Астероиды» (25), кроме льда (группа 465: отдельный раздел).
"""
import datetime
import json
import os
from collections import defaultdict

from eve_sde.models import ItemGroup, ItemType, ItemTypeMaterials

OUT = os.environ.get("REFERENCE_DATA_OUT") or os.path.abspath("reference_data.json")
ICE = 465

ores_qs = (ItemType.objects.filter(group__category_id=25, published=True).exclude(group_id=ICE)
           .values_list("id", "name_en", "name_ru", "group_id", "portion_size", "volume", "packaged_volume"))
ores = list(ores_qs)
mats = defaultdict(list)
for tid, mid, q in ItemTypeMaterials.objects.filter(item_type_id__in=[o[0] for o in ores]).values_list("item_type_id", "material_item_type_id", "quantity"):
    if q:
        mats[tid].append([mid, q])

out, groups, used = [], set(), set()
for tid, en, ru, gid, portion, vol, pvol in ores:
    rows = sorted(mats.get(tid, []))
    out.append([tid, en or str(tid), ru if ru and ru != en else "", gid, portion or 1, vol or pvol or 0, rows])
    groups.add(gid)
    used.update(m for m, _ in rows)
gnames = {str(g): [en, ru if ru and ru != en else ""] for g, en, ru in ItemGroup.objects.filter(id__in=groups).values_list("id", "name_en", "name_ru")}
materials = {str(t): [en or str(t), ru if ru and ru != en else "", g]
             for t, en, ru, g in ItemType.objects.filter(id__in=used).values_list("id", "name_en", "name_ru", "group_id")}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"v": 1, "built": datetime.date.today().isoformat(), "ores": sorted(out, key=lambda r: r[0]), "groups": gnames,
               "materials": materials}, f, ensure_ascii=False, separators=(",", ":"))
print(f"reference_data.json: руд {len(out)}, групп {len(gnames)}, материалов {len(materials)}, {os.path.getsize(OUT) // 1024} КБ")
