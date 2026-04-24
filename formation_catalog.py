# -*- coding: utf-8 -*-
"""
Каталог тактических схем по **фиксированным** числовым id (1–10).
Названия и соответствие id → ключ слотов в ``team_squad_schemas`` не меняются.

Слоты на поле для каждого id пока совпадают с базовой 4-3-3 (``fid_N`` → копия 433);
координаты/допуски по позициям можно позже развести по ключам ``fid_*``.
"""
from __future__ import annotations

from typing import Final

# id → человекочитаемое имя (как в таблице)
FORMATION_ID_LABELS: dict[int, str] = {
    1: "4-3-3 ат",
    2: "4-3-3 уд",
    3: "4-3-3 линия",
    4: "4-4-2 линия",
    5: "4-3-1-2",
    6: "4-3-3 9",
    7: "4-2-1-3",
    8: "4-2-4",
    9: "5-2-1-2",
    10: "5-2-3",
}

# id → ключ в FORMATION_SLOTS (геометрия поля)
FORMATION_ID_TO_SLOT_KEY: Final[dict[int, str]] = {
    i: f"fid_{i}" for i in range(1, 11)
}


def slot_key_for_formation_id(fid: int) -> str:
    if fid not in FORMATION_ID_LABELS:
        return "433"
    return FORMATION_ID_TO_SLOT_KEY[fid]


def label_for_formation_id(fid: int) -> str:
    return FORMATION_ID_LABELS.get(fid, "?")


def validate_formation_id(fid: int) -> None:
    if fid not in FORMATION_ID_LABELS:
        raise ValueError(f"Недопустимый id схемы: {fid} (допустимы 1–10).")
