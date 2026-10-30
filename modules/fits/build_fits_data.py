# -*- coding: utf-8 -*-
"""
Выгрузить фиты и доктрины из Alliance Auth (плагин «Фиты и навыки», fitskills) в fits_data.json модуля «Фиты».

Запуск — из папки myauth сервера Alliance Auth (нужны fitskills и eve_sde с загруженным справочником):
  set FITS_DATA_OUT=%LOCALAPPDATA%/EveLogHUD/fits_data.json   (папка данных приложения; или загрузите файл кнопкой на вкладке)
  python manage.py shell -c "exec(open(r'<папка модуля fits>/build_fits_data.py', encoding='utf-8').read())"

Формат:
  {"v": 1, "built": "<дата>", "source": "<сайт AA>",
   "doctrines": [{"id", "name", "description", "active"}],
   "fits": [{"id", "name", "ship_type_id", "ship_name", "ship_group", "race_id", "description", "eft", "doctrines": [id],
             "items": [{"type_id", "name", "slot", "qty"}], "required": {навык: уровень}, "plan": {навык: уровень}}],
   "skills": {"<навык>": [название, ранг]}}
required — минимум, чтобы сесть в корпус и поставить модули (с предварительными навыками); plan — «чтобы летать хорошо».
"""
import datetime
import json
import os

from django.conf import settings

from eve_sde.models import ItemType
from fitskills import sde
from fitskills.models import Doctrine, Fitting

OUT = os.environ.get("FITS_DATA_OUT") or os.path.abspath("fits_data.json")

fits = list(Fitting.objects.prefetch_related("doctrines").order_by("ship_name", "name"))
ships = {t.id: t for t in ItemType.objects.filter(id__in=[f.ship_type_id for f in fits]).select_related("group")}
skill_ids = set()
for f in fits:
    skill_ids |= {int(k) for k in (f.required or {})} | {int(k) for k in (f.plan or {})}
names = sde.names(skill_ids)
ranks = sde.ranks(skill_ids)

out = []
for f in fits:
    t = ships.get(f.ship_type_id)
    out.append({"id": f.pk, "name": f.name, "ship_type_id": f.ship_type_id, "ship_name": f.ship_name,
                "ship_group": t.group.name_en if t and t.group else "", "race_id": t.race_id if t else None,
                "description": f.description, "eft": f.eft, "doctrines": [d.pk for d in f.doctrines.all()],
                "items": [{"type_id": i.get("type_id"), "name": i.get("name"), "slot": i.get("slot"), "qty": i.get("qty") or 1}
                          for i in (f.items or [])],
                "required": {str(k): int(v) for k, v in (f.required or {}).items()},
                "plan": {str(k): int(v) for k, v in (f.plan or {}).items()}})

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump({"v": 1, "built": datetime.date.today().isoformat(), "source": getattr(settings, "SITE_URL", ""),
               "doctrines": [{"id": d.pk, "name": d.name, "description": d.description, "active": d.is_active}
                             for d in Doctrine.objects.order_by("name")],
               "fits": out, "skills": {str(s): [names.get(s, str(s)), float(ranks.get(s, 1))] for s in sorted(skill_ids)}},
              fh, ensure_ascii=False, separators=(",", ":"))
print(f"fits_data.json: фитов {len(out)}, доктрин {Doctrine.objects.count()}, навыков {len(skill_ids)}, {os.path.getsize(OUT) // 1024} КБ")
