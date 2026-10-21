# -*- coding: utf-8 -*-
"""
Модуль «Типы урона»: чем бьёт каждый атакующий — доли ЭМ / термо / кинетика / взрыв.

В игровом логе типа урона нет. Это оценка по справочнику игры (damage_profiles.json, собран из SDE):
NPC узнаются по названию, игроки — по ракетам и дронам. Модуль дописывает поле prof каждому атакующему
в живых сессиях; оверлей по нему показывает получаемый урон по типам.
"""
import json
import os
from typing import List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))


_PROFILES: Optional[dict] = None


def damage_profiles() -> dict:
    """{название в нижнем регистре: [ЭМ, термо, кинетика, взрыв]} — доли урона NPC, ракет и дронов (из SDE).

    Файл damage_profiles.json собирается build_damage_profiles.py; без него типы урона просто не показываются.
    """
    global _PROFILES
    if _PROFILES is None:
        try:
            with open(os.path.join(HERE, "damage_profiles.json"), encoding="utf-8") as f:
                _PROFILES = json.load(f).get("profiles") or {}
        except (OSError, ValueError):
            _PROFILES = {}
    return _PROFILES


def damage_profile(name: str, actor: dict) -> Optional[List[float]]:
    """Каким типом урона бьёт атакующий: доли [ЭМ, термо, кинетика, взрыв]; сумма < 1 — остальное неизвестно.

    В логе типа урона нет. NPC узнаём по названию; игрока — по ракетам и дронам (у пушек тип зависит от
    заряда, а заряд в лог не пишется).
    """
    prof = damage_profiles()
    if not prof:
        return None
    if not actor.get("ticker") and not actor.get("ship"):   # у NPC нет ни тикера, ни корабля в скобках
        p = prof.get(name.strip().lower())
        if p:
            return p
    weapons = actor.get("weapons") or {}
    total = sum(v for v in weapons.values() if isinstance(v, (int, float)))
    if total <= 0:
        return None
    acc, known = [0.0, 0.0, 0.0, 0.0], 0.0
    for w, dmg in weapons.items():
        p = prof.get(str(w).strip().lower())
        if p and isinstance(dmg, (int, float)):
            known += dmg
            acc = [a + x * dmg for a, x in zip(acc, p)]
    return [round(a / total, 3) for a in acc] if known > 0 else None


def enrich(session: dict) -> None:
    session["attackers"] = {n: dict(a, prof=damage_profile(n, a)) for n, a in (session.get("attackers") or {}).items()}


def setup(ctx) -> None:
    ctx.on_live(enrich)
