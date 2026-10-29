# -*- coding: utf-8 -*-
"""
Собрать reference_bp.json — раздел «Чертежи» модуля «Справочник»: что производит каждый чертёж и как его получить.

Из справочника игры (SDE): производство и реакции (материалы, время), изобретение T2 (из какой копии T1, датакоры, шанс),
реверс-инжиниринг T3 (из каких реликвий), продаётся ли оригинал NPC на рынке (есть группа рынка), базовая цена, время
исследований. Из публичного ESI (один раз, при сборке): предложения LP-магазинов всех NPC-корпораций — какие копии чертежей
там продаются, за сколько LP, ISK и предметов.

Запуск — из папки myauth сервера Alliance Auth (django-eveonline-sde с загруженным SDE), нужен интернет:
  set REFERENCE_BP_OUT=<папка модуля reference>/reference_bp.json
  python manage.py shell -c "exec(open(r'<папка модуля reference>/build_reference_bp.py', encoding='utf-8').read())"

Формат:
  {"v": 1, "built": "<дата>",
   "bp":   {"<чертёж>": [продукт, "m"|"r", выход, время_с, макс_прогонов, базовая_цена, группа_рынка_чертежа, [[материал, кол-во]],
                         время_копии, время_ME, время_TE, tech_level_продукта]},
   "inv":  {"<чертёж T2/T3>": [[источник, шанс, прогонов_в_копии, [[датакор, кол-во]], время_с], ...]}  — источник: чертёж T1 или реликвия,
   "lp":   {"<чертёж>": [[корпорация, lp, isk, прогонов/штук, [[предмет, кол-во]]], ...]},
   "corps": {"<корпорация>": название},
   "mg":   {"<группа рынка>": [родитель, название_ru]},   — дерево рынка для каталога (группы продуктов и чертежей)
   "pmg":  {"<чертёж>": группа рынка продукта},
   "types": {"<type_id>": [name_en, name_ru, group_id, category_id]}}
"""
import datetime
import json
import os
import time
import urllib.error
import urllib.request
from collections import defaultdict

from eve_sde.models import BlueprintActivity, BlueprintActivityMaterial, BlueprintActivityProduct, ItemMarketGroup, ItemType

OUT = os.environ.get("REFERENCE_BP_OUT") or os.path.abspath("reference_bp.json")
ESI = "https://esi.evetech.net/latest"
KIND = {"manufacturing": "m", "reaction": "r"}


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


acts = defaultdict(dict)                   # чертёж → {activity: (id, time, limit)}
for aid, bp, act, t, lim in BlueprintActivity.objects.values_list("id", "blueprint_item_type_id", "activity", "time", "max_production_limit"):
    acts[bp][act] = (aid, t or 0, lim or 0)
mats = defaultdict(list)
for aid, tid, q in BlueprintActivityMaterial.objects.values_list("blueprint_activity_id", "item_type_id", "quantity"):
    if q:
        mats[aid].append([tid, q])
products = defaultdict(list)
for aid, tid, q, prob in BlueprintActivityProduct.objects.values_list("blueprint_activity_id", "item_type_id", "quantity", "probability"):
    products[aid].append((tid, q or 1, prob))

published = set(ItemType.objects.filter(published=True).values_list("id", flat=True))
info = {t: (mg, bprice, tl) for t, mg, bprice, tl in ItemType.objects.filter(id__in=published).values_list("id", "market_group_id", "base_price", "tech_level")}

bp, used = {}, set()
for b, a in acts.items():
    if b not in published:
        continue
    for act, kind in KIND.items():
        if act not in a:
            continue
        aid, t, lim = a[act]
        prods = [p for p in products.get(aid, []) if p[0] in published]
        if not prods:
            continue
        prod, q, _ = prods[0]
        m = sorted(mats.get(aid, []))
        mg, price, _ = info.get(b, (None, 0, None))
        bp[str(b)] = [prod, kind, q, t, lim, price or 0, mg, m, a.get("copying", (0, 0))[1], a.get("research_material", (0, 0))[1],
                      a.get("research_time", (0, 0))[1], (info.get(prod) or (None, 0, None))[2]]
        used.update([b, prod] + [x for x, _ in m])
        break

# изобретение (T2) и реверс-инжиниринг (T3): источник → копия чертежа с шансом
inv = defaultdict(list)
for src, a in acts.items():
    if "invention" not in a or src not in published:
        continue
    aid, t, _ = a["invention"]
    dc = sorted(mats.get(aid, []))
    for prod, runs, prob in products.get(aid, []):
        if str(prod) in bp:
            inv[str(prod)].append([src, prob or 0, runs, dc, t])
            used.update([src] + [x for x, _ in dc])

# LP-магазины NPC-корпораций (ESI, публично)
lp, corps = defaultdict(list), {}
bp_ids = {int(k) for k in bp}
npc = esi("/corporations/npccorps/") or []
for i, cid in enumerate(npc):
    for o in esi(f"/loyalty/stores/{cid}/offers/") or []:
        if o.get("type_id") in bp_ids:
            req = [[r["type_id"], r["quantity"]] for r in o.get("required_items") or []]
            lp[str(o["type_id"])].append([cid, o.get("lp_cost") or 0, o.get("isk_cost") or 0, o.get("quantity") or 1, req])
            corps[cid] = ""
            used.update(x for x, _ in req)
for cid in sorted(corps):                  # по одной: /universe/names/ отклоняет весь список из-за одного «служебного» номера
    corps[cid] = (esi(f"/corporations/{cid}/") or {}).get("name") or str(cid)

# дерево рынка: по группе рынка продукта (как в плане производства), для чертежей без группы — по группе чертежа
allmg = {g: (p, r, e) for g, p, r, e in ItemMarketGroup.objects.values_list("id", "parent_group_id", "name_ru", "name_en")}
pmg = {}
for b, row in bp.items():
    g = (info.get(row[0]) or (None,))[0] or row[6]
    if g:
        pmg[b] = g
mg = {}
for g in set(pmg.values()) | {row[6] for row in bp.values() if row[6]}:
    while g and str(g) not in mg and g in allmg:
        p, r, e = allmg[g]
        mg[str(g)] = [p, r or e]
        g = p

types = {str(t): [en or str(t), ru if ru and ru != en else "", g, c]
         for t, en, ru, g, c in ItemType.objects.filter(id__in=used).values_list("id", "name_en", "name_ru", "group_id", "group__category_id")}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"v": 1, "built": datetime.date.today().isoformat(), "bp": bp, "inv": inv, "lp": lp,
               "corps": {str(k): v for k, v in corps.items()}, "mg": mg, "pmg": pmg, "types": types},
              f, ensure_ascii=False, separators=(",", ":"))
print(f"reference_bp.json: чертежей {len(bp)}, изобретение/реверс {len(inv)}, в LP-магазинах {len(lp)} (корпораций {len(corps)}), "
      f"{os.path.getsize(OUT) // 1024} КБ")
