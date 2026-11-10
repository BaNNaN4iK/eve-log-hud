# -*- coding: utf-8 -*-
"""
Собрать map_data.json — модуль «Карта»: системы k-space, регионы, созвездия и звёздные врата.

Из справочника игры (SDE, django-eveonline-sde): название, регион, созвездие, безопасность, 2D-раскладка карты игры
(position2D — как у карты в клиенте) и 3D-координаты (для дальности прыжка), связи врат. Червоточины (J-space) и Бездна не входят.

Запуск — из папки myauth сервера Alliance Auth:
  set MAP_DATA_OUT=<папка модуля map>/map_data.json
  python manage.py shell -c "exec(open(r'<папка модуля map>/build_map_data.py', encoding='utf-8').read())"

Формат:
  {"v": 1, "built": "<дата>",
   "regions": {"<регион>": название},
   "constellations": {"<созвездие>": [название, регион]},
   "systems": {"<система>": [название, созвездие, безопасность, x2d, y2d, x_ly, y_ly, z_ly]},
   "gates": [[система, система], ...]}       — каждая пара один раз
"""
import datetime
import json
import os

from eve_sde.models import Constellation, Region, SolarSystem, Stargate

OUT = os.environ.get("MAP_DATA_OUT") or os.path.abspath("map_data.json")
LY = 9.4607e15                                  # метров в световом году
KSPACE = 11000000                               # регионы с этого номера — червоточины, Бездна и служебные

regions = {r.id: r.name for r in Region.objects.filter(id__lt=KSPACE)}
consts = {c.id: [c.name, c.region_id] for c in Constellation.objects.filter(region_id__in=regions)}
systems = {}
for s in SolarSystem.objects.filter(constellation_id__in=consts).values("id", "name", "constellation_id", "security_status", "x_2d", "y_2d", "x", "y", "z"):
    if s["x_2d"] is None:
        continue
    systems[s["id"]] = [s["name"], s["constellation_id"], round(s["security_status"] or 0, 3), round(s["x_2d"] / 1e14, 4), round(s["y_2d"] / 1e14, 4),
                        round((s["x"] or 0) / LY, 3), round((s["y"] or 0) / LY, 3), round((s["z"] or 0) / LY, 3)]
pairs = set()
for a, b in Stargate.objects.values_list("solar_system_id", "destination_id"):
    if a in systems and b in systems and a != b:
        pairs.add((min(a, b), max(a, b)))

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"v": 1, "built": datetime.date.today().isoformat(), "regions": {str(k): v for k, v in regions.items()},
               "constellations": {str(k): v for k, v in consts.items()}, "systems": {str(k): v for k, v in systems.items()},
               "gates": sorted(pairs)}, f, ensure_ascii=False, separators=(",", ":"))
print(f"map_data.json: регионов {len(regions)}, систем {len(systems)}, врат {len(pairs)}, {os.path.getsize(OUT) // 1024} КБ")
