# -*- coding: utf-8 -*-
"""
Собрать pi_data.json — калькулятор планетарки модуля «Производство»: что из чего собирается на планетах.

Из официального справочника игры CCP (SDE в формате JSONL, https://developers.eveonline.com/static-data):
схемы планетарных фабрик (planetSchematics: входы, выход, время цикла), уровни P0–P4 по группам, названия (англ. и рус.), объём.
На каких типах планет добывается сырьё P0, в SDE нет — таблица PLANETS ниже, по EVE University Wiki (не меняется с 2011 г.).

Запуск (стандартная библиотека, AA не нужен):
  python build_pi_data.py <путь к eve-online-static-data-…-jsonl.zip> [pi_data.json]

Формат:
  {"v": 1, "built": "<дата>", "sde": "<архив SDE>",
   "schematics": {"<выход>": [время_цикла_с, выход_за_цикл, [[вход, кол-во], ...]]},
   "types":      {"<type_id>": [name_en, name_ru, уровень 0–4, объём_м³]},
   "planets":    {"<сырьё P0>": [типы планет]}}
"""
import datetime
import json
import os
import sys
import zipfile

LEVEL = {1032: 0, 1033: 0, 1035: 0, 1042: 1, 1034: 2, 1040: 3, 1041: 4}   # группы игры → уровень планетарки
PLANETS = {                                                               # сырьё P0 → типы планет (EVE University Wiki)
    "Aqueous Liquids": ["barren", "gas", "ice", "oceanic", "storm", "temperate"],
    "Autotrophs": ["temperate"],
    "Base Metals": ["barren", "gas", "lava", "plasma", "storm"],
    "Carbon Compounds": ["barren", "oceanic", "temperate"],
    "Complex Organisms": ["oceanic", "temperate"],
    "Felsic Magma": ["lava"],
    "Heavy Metals": ["ice", "lava", "plasma"],
    "Ionic Solutions": ["gas", "storm"],
    "Microorganisms": ["barren", "ice", "oceanic", "temperate"],
    "Noble Gas": ["gas", "ice", "storm"],
    "Noble Metals": ["barren", "plasma"],
    "Non-CS Crystals": ["lava", "plasma"],
    "Planktic Colonies": ["ice", "oceanic"],
    "Reactive Gas": ["gas"],
    "Suspended Plasma": ["lava", "plasma", "storm"],
}


def rows(z, name):
    for line in z.read(name).decode("utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


def main(src, out):
    z = zipfile.ZipFile(src)
    schematics, used = {}, set()
    for s in rows(z, "planetSchematics.jsonl"):
        outs = [t for t in s["types"] if not t["isInput"]]
        if len(outs) != 1:
            continue
        o = outs[0]
        schematics[str(o["_key"])] = [s["cycleTime"], o["quantity"], [[t["_key"], t["quantity"]] for t in s["types"] if t["isInput"]]]
        used.update(t["_key"] for t in s["types"])
    types = {}
    for t in rows(z, "types.jsonl"):
        lv = LEVEL.get(t.get("groupID"))
        if lv is None or (t["_key"] not in used and lv > 0) or not t.get("published", True):
            continue
        name = t.get("name") or {}
        en, ru = name.get("en") or str(t["_key"]), name.get("ru") or ""
        types[str(t["_key"])] = [en, ru if ru != en else "", lv, t.get("volume") or 0]
    planets = {k: PLANETS[v[0]] for k, v in types.items() if v[2] == 0 and v[0] in PLANETS}
    missing = sorted(v[0] for v in types.values() if v[2] == 0 and v[0] not in PLANETS)
    if missing:
        print("Нет в таблице планет:", ", ".join(missing))
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "built": datetime.date.today().isoformat(), "sde": os.path.basename(src), "schematics": schematics,
                   "types": types, "planets": planets}, f, ensure_ascii=False, separators=(",", ":"))
    by = {}
    for v in types.values():
        by[v[2]] = by.get(v[2], 0) + 1
    print(f"pi_data.json: схем {len(schematics)}, предметов по уровням {dict(sorted(by.items()))}, {os.path.getsize(out) // 1024} КБ")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "pi_data.json"))
