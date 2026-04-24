# -*- coding: utf-8 -*-
"""
Схемы расстановки для PNG «Состав клуба».

Каждый слот задаётся позициями из БД (как в поле ``players.position``).
Игрок попадает в слот только если его позиция входит в ``allowed_positions``.
Пустой слот остаётся «—», без подстановки «лучшего оставшегося» — так не окажется
нападающий на ЦОП.

Как добавить схему команды
---------------------------
1. В ``FORMATION_SLOTS`` завести новый ключ, например ``"433_сити"``, скопировав
   кортеж из ``"433"`` и поменяв множества позиций под вашу схему.
2. В ``TEAM_FORMATION_KEY`` сопоставить имя команды **как в SQLite** ключу схемы::

       TEAM_FORMATION_KEY["Сити"] = "433_сити"

Имена команд для ключа — те же, что в ``player_stats.LEAGUE_TEAMS`` и в боте
(в т.ч. «Цска», не «ЦСКА»). Если команды нет в словаре — используется ``"433"``.
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


def get_slots_for_team(team_db: str) -> tuple[SquadSlot, ...]:
    key = TEAM_FORMATION_KEY.get((team_db or "").strip(), DEFAULT_FORMATION_KEY)
    slots = FORMATION_SLOTS.get(key)
    if slots is None:
        return FORMATION_SLOTS[DEFAULT_FORMATION_KEY]
    return slots


def formation_label_for_team(team_db: str) -> str:
    """Короткая подпись для подзаголовка (какой ключ схемы задействован)."""
    key = TEAM_FORMATION_KEY.get((team_db or "").strip(), DEFAULT_FORMATION_KEY)
    return key
