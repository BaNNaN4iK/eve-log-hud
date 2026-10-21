# -*- coding: utf-8 -*-
"""
Собрать damage_profiles.json — «каким типом урона бьёт» для NPC, ракет, зарядов и дронов.

В игровом логе типа урона нет, поэтому трекер оценивает его по справочнику игры (SDE):
у NPC — по характеристикам его орудий и ракет, у игроков — по названию ракеты или дрона.

Запуск — из папки myauth сервера Alliance Auth, где установлен django-eveonline-sde (eve_sde) и загружен SDE:
  set DAMAGE_PROFILES_OUT=<папка модуля damage_types>/damage_profiles.json
  python manage.py shell -c "exec(open(r'<папка модуля damage_types>/build_damage_profiles.py', encoding='utf-8').read())"
"""
import json
import os
from collections import defaultdict

from eve_sde.models import ItemType, TypeDogma

OUT = os.environ.get("DAMAGE_PROFILES_OUT") or os.path.abspath("damage_profiles.json")   # куда писать файл
EM, EXP, KIN, THERM = 114, 116, 117, 118            # порядок в файле: [ЭМ, термо, кинетика, взрыв]
MULT, SPEED, MISSILE, M_MULT, M_SPEED = 64, 51, 507, 212, 506
CATEGORIES = {11: "npc", 8: "charge", 18: "drone", 87: "fighter"}

attrs = defaultdict(dict)
for tid, aid, val in TypeDogma.objects.filter(
        dogma_attribute_id__in=[EM, EXP, KIN, THERM, MULT, SPEED, MISSILE, M_MULT, M_SPEED]
).values_list("item_type_id", "dogma_attribute_id", "value"):
    attrs[tid][aid] = val


def raw(tid):
    a = attrs.get(tid, {})
    return [a.get(EM, 0) or 0, a.get(THERM, 0) or 0, a.get(KIN, 0) or 0, a.get(EXP, 0) or 0]


def profile(tid, cat):
    a = attrs.get(tid, {})
    dmg = raw(tid)
    if cat == "npc":
        speed = a.get(SPEED) or 0
        k = (a.get(MULT) or 1) / speed if speed else 1.0           # урон орудий в секунду
        dmg = [x * k for x in dmg]
        mid = int(a.get(MISSILE) or 0)
        if mid:
            ms = a.get(M_SPEED) or 0
            mk = (a.get(M_MULT) or 1) / ms if ms else (1.0 if not speed else 0.0)
            dmg = [x + y * mk for x, y in zip(dmg, raw(mid))]
    total = sum(dmg)
    if total <= 0:
        return None
    return [round(x / total, 2) for x in dmg]


out, counts = {}, defaultdict(int)
for t in ItemType.objects.filter(group__category_id__in=list(CATEGORIES)).values(
        "id", "name_en", "name_ru", "group__category_id"):
    cat = CATEGORIES[t["group__category_id"]]
    p = profile(t["id"], cat)
    if not p:
        continue
    counts[cat] += 1
    for name in {t["name_en"], t["name_ru"]}:
        if name:
            out.setdefault(name.strip().lower(), p)                 # одинаковые имена: первый найденный

with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    json.dump({"order": ["em", "therm", "kin", "exp"], "source": "EVE SDE (eve_sde в стенде AA)",
               "profiles": out}, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
print("типов:", dict(counts), "· названий:", len(out), "· файл:", os.path.getsize(OUT) // 1024, "КБ")
for n in ("alvus queen", "strain render alvi", "guristas despoiler", "scourge fury heavy missile", "hobgoblin ii"):
    print(" ", n, out.get(n))
