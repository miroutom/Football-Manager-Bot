# -*- coding: utf-8 -*-
"""
Схемы расстановки для PNG «Состав клуба».

Каждый слот задаётся позициями из БД (как в поле ``players.position``).
Какой **ключ** схемы применяется к команде, читайте в ``coach_squad_state``:
тренер · три **числовых id** (1–10, см. ``formation_catalog``), один active,
привязка тренер→команда. Ключ слотов на поле: ``fid_<id>`` (геометрия в ``formation_geometry``).

Статический запасной вариант: ``TEAM_FORMATION_KEY`` / ``DEFAULT`` (``433``),
если тренер для команды ещё не настроен.

1. В ``FORMATION_SLOTS`` при необходимости завести геометрию под ``fid_<id>``.
2. В ``data/coach_squad_state.json`` — ``formation_ids`` и ``active_formation_id``;
   команде тренер через ``coach_squad_state.assign_coach_to_team``.

Пока тренер не задан — сработает ``TEAM_FORMATION_KEY[команда]`` или ``433``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class SquadSlot:
    """Слот на поле: координаты + допустимые позиции из БД (русские сокращения)."""

    slot_id: str
    x: float
    y: float
    allowed_positions: frozenset[str]


DEFAULT_FORMATION_KEY: Final[str] = "433"

# Имя команды (как в БД) → ключ из FORMATION_SLOTS
TEAM_FORMATION_KEY: dict[str, str] = {
    # Примеры (раскомментируйте и заведите свой ключ в FORMATION_SLOTS):
    # "Сити": "433",
}


FORMATION_SLOTS: dict[str, tuple[SquadSlot, ...]] = {
    "433": (
        SquadSlot("GK", 0.50, 0.86, frozenset({"ВРТ"})),
        SquadSlot("LB", 0.10, 0.68, frozenset({"ЛЗ", "ЛФЗ"})),
        SquadSlot("RB", 0.90, 0.68, frozenset({"ПЗ", "ПФЗ"})),
        SquadSlot("LCB", 0.36, 0.68, frozenset({"ЦЗ", "ЛЦЗ"})),
        SquadSlot("RCB", 0.64, 0.68, frozenset({"ЦЗ", "ПЦЗ"})),
        SquadSlot("CDM", 0.50, 0.52, frozenset({"ЦОП"})),
        SquadSlot(
            "LCM",
            0.32,
            0.40,
            frozenset({"ЛП", "ЛЦП", "ЦАП", "ЦП"}),
        ),
        SquadSlot(
            "RCM",
            0.68,
            0.40,
            frozenset({"ПП", "ПЦП", "ЦАП", "ЦП"}),
        ),
        SquadSlot("LW", 0.18, 0.22, frozenset({"ЛФА", "ЛФД"})),
        SquadSlot("ST", 0.50, 0.14, frozenset({"ФРВ", "ЦФД"})),
        SquadSlot("RW", 0.82, 0.22, frozenset({"ПФА", "ПФД"})),
    ),
}

from formation_geometry import register_fid_slots

register_fid_slots(FORMATION_SLOTS)


def get_slots_for_formation_key(formation_key: str) -> tuple[SquadSlot, ...]:
    """Слоты по ключу из ``FORMATION_SLOTS``; неизвестный ключ — дефолт 433."""
    key = (formation_key or "").strip() or DEFAULT_FORMATION_KEY
    slots = FORMATION_SLOTS.get(key)
    if slots is None:
        return FORMATION_SLOTS[DEFAULT_FORMATION_KEY]
    return slots
