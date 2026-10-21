# -*- coding: utf-8 -*-
"""
Собрать reprocess_data.json — что получается при переработке каждого предмета (справочник игры, SDE).

В ESI этих данных нет, поэтому справочник лежит рядом с модулем и обновляется этим скриптом после патчей игры.

Запуск — из папки myauth сервера Alliance Auth, где установлен django-eveonline-sde (eve_sde) и загружен SDE:
  set REPROCESS_DATA_OUT=<папка модуля reprocess>/reprocess_data.json
  python manage.py shell -c "exec(open(r'<папка модуля reprocess>/build_reprocess_data.py', encoding='utf-8').read())"

Формат:
  {"v": 1, "built": "<дата>",
   "types":     {"<type_id>": [name_en, name_ru, category_id, group_id, portion_size, volume, [[material_id, qty], ...]]},
   "materials": {"<type_id>": [name_en, name_ru, volume]}}
"""
import datetime
import json
import os
from collections import defaultdict

from eve_sde.models import ItemType, ItemTypeMaterials

OUT = os.environ.get("REPROCESS_DATA_OUT") or os.path.abspath("reprocess_data.json")

mats = defaultdict(list)
for tid, mid, q in ItemTypeMaterials.objects.values_list("item_type_id", "material_item_type_id", "quantity"):
    if q:
        mats[tid].append([mid, q])

types, materials = {}, {}
qs = (ItemType.objects.filter(id__in=list(mats), published=True)
      .values_list("id", "name_en", "name_ru", "group__category_id", "group_id", "portion_size", "packaged_volume", "volume"))
used = set()
for tid, en, ru, cat, grp, portion, pvol, vol in qs:
    rows = sorted(mats[tid])
    types[str(tid)] = [en or ru or str(tid), ru if ru and ru != en else "", cat, grp, portion or 1, pvol or vol or 0, rows]
    used.update(m for m, _ in rows)
for tid, en, ru, pvol, vol in ItemType.objects.filter(id__in=used).values_list("id", "name_en", "name_ru", "packaged_volume", "volume"):
    materials[str(tid)] = [en or ru or str(tid), ru if ru and ru != en else "", pvol or vol or 0]

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"v": 1, "built": datetime.date.today().isoformat(), "types": types, "materials": materials},
              f, ensure_ascii=False, separators=(",", ":"))
print(f"reprocess_data.json: предметов {len(types)}, материалов {len(materials)}, {os.path.getsize(OUT) // 1024} КБ")
