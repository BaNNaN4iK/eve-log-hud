# -*- coding: utf-8 -*-
"""
Собрать industry_data.json — чертежи: что нужно на один прогон, сколько выходит и сколько длится (справочник игры, SDE).

В ESI этих данных нет, поэтому справочник лежит рядом с модулем и обновляется этим скриптом после патчей игры.

Запуск — из папки myauth сервера Alliance Auth, где установлен django-eveonline-sde (eve_sde) и загружен SDE:
  set INDUSTRY_DATA_OUT=<папка модуля industry>/industry_data.json
  python manage.py shell -c "exec(open(r'<папка модуля industry>/build_industry_data.py', encoding='utf-8').read())"

Формат:
  {"v": 1, "built": "<дата>",
   "bp":    {"<продукт>": [чертёж, "m"|"r", время_с, выход_за_прогон, [[материал, кол-во], ...], макс_прогонов, откуда]},
            откуда: "bpo" — оригинал продаётся на рынке, "inv" — копия из изобретения (T2/T3), "bpc" — только редкие копии
   "inv":   {"<чертёж T2>": [чертёж T1, продукт T1, шанс, прогонов_в_копии, [[датакор, кол-во], ...], время_с]},
   "types": {"<type_id>": [name_en, group_id, category_id, объём]},
   "groups": {"<group_id>": название}}
"""
import datetime
import json
import os
from collections import defaultdict

from eve_sde.models import BlueprintActivity, BlueprintActivityMaterial, BlueprintActivityProduct, ItemGroup, ItemType

OUT = os.environ.get("INDUSTRY_DATA_OUT") or os.path.abspath("industry_data.json")
KIND = {"manufacturing": "m", "reaction": "r"}

mats = defaultdict(list)
for act_id, tid, q in BlueprintActivityMaterial.objects.filter(
        blueprint_activity__activity__in=list(KIND)).values_list("blueprint_activity_id", "item_type_id", "quantity"):
    if q:
        mats[act_id].append([tid, q])

# откуда берут чертёж: оригинал с рынка (есть группа рынка) или изобретение; иначе — только редкие копии
invented = set(BlueprintActivityProduct.objects.filter(blueprint_activity__activity="invention").values_list("item_type_id", flat=True))
on_market = set(ItemType.objects.filter(market_group__isnull=False, group__category_id=9).values_list("id", flat=True))

bp = {}
used = set()
rows = (BlueprintActivityProduct.objects.filter(blueprint_activity__activity__in=list(KIND), item_type__published=True,
                                                blueprint_activity__blueprint_item_type__published=True)
        .values_list("item_type_id", "quantity", "blueprint_activity_id", "blueprint_activity__activity",
                     "blueprint_activity__time", "blueprint_activity__max_production_limit",
                     "blueprint_activity__blueprint_item_type_id"))
for product, qty, act_id, activity, t, max_runs, bp_id in rows:
    m = sorted(mats.get(act_id, []))
    if not m or str(product) in bp:
        continue
    src = "inv" if bp_id in invented else "bpo" if bp_id in on_market else "bpc"
    bp[str(product)] = [bp_id, KIND[activity], t or 0, qty or 1, m, max_runs or 0, src]
    used.add(product)
    used.update(x for x, _ in m)

# изобретение: из копии T1 с датакорами получается копия T2 (с шансом)
t1_product = dict(BlueprintActivityProduct.objects.filter(blueprint_activity__activity="manufacturing")
                  .values_list("blueprint_activity__blueprint_item_type_id", "item_type_id"))
inv = {}
for act_id, t1_bp, t2_bp, runs, prob, t in BlueprintActivityProduct.objects.filter(blueprint_activity__activity="invention").values_list(
        "blueprint_activity_id", "blueprint_activity__blueprint_item_type_id", "item_type_id", "quantity", "probability",
        "blueprint_activity__time"):
    if str(t2_bp) in inv:
        continue
    dc = sorted(mats.get(act_id) or [])
    if not dc:
        dc = sorted([[m, q] for m, q in BlueprintActivityMaterial.objects.filter(blueprint_activity_id=act_id).values_list("item_type_id", "quantity") if q])
    inv[str(t2_bp)] = [t1_bp, t1_product.get(t1_bp), prob or 0, runs or 1, dc, t or 0]
    used.update(m for m, _ in dc)
    if t1_product.get(t1_bp):
        used.add(t1_product[t1_bp])

types, groups = {}, set()
for tid, en, gid, cat, pvol, vol in ItemType.objects.filter(id__in=used).values_list(
        "id", "name_en", "group_id", "group__category_id", "packaged_volume", "volume"):
    types[str(tid)] = [en or str(tid), gid, cat, pvol or vol or 0]
    groups.add(gid)
gnames = {str(g): n for g, n in ItemGroup.objects.filter(id__in=groups).values_list("id", "name_en")}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"v": 1, "built": datetime.date.today().isoformat(), "bp": bp, "inv": inv, "types": types, "groups": gnames},
              f, ensure_ascii=False, separators=(",", ":"))
print(f"industry_data.json: чертежей {len(bp)}, изобретений {len(inv)}, предметов {len(types)}, {os.path.getsize(OUT) // 1024} КБ")
