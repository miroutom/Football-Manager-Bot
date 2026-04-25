# -*- coding: utf-8 -*-
"""
Геометрия слотов (x, y — доли поля, y меньше = ближе к атаке) для тактик id 1–10.
Позиции в ``allowed_positions`` — как в БД (русские сокращения).

Порядок id совпадает с ``formation_catalog.FORMATION_ID_LABELS``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from team_squad_schemas import SquadSlot

_slots_cache: dict[int, tuple["SquadSlot", ...]] | None = None

# Частые множества позиций из БД
_VRT = frozenset({"ВРТ"})
_LB = frozenset({"ЛЗ", "ЛФЗ"})
_RB = frozenset({"ПЗ", "ПФЗ"})
_CB_L = frozenset({"ЦЗ", "ЛЦЗ"})
_CB_R = frozenset({"ЦЗ", "ПЦЗ"})
_CB_C = frozenset({"ЦЗ"})
_CDM = frozenset({"ЦОП"})
_CM_L = frozenset({"ЛП", "ЛЦП", "ЦП", "ЦАП"})
_CM_R = frozenset({"ПП", "ПЦП", "ЦП", "ЦАП"})
_CM_C = frozenset({"ЦП", "ЦАП", "ЛП", "ПП", "ЛЦП", "ПЦП"})
_CAM = frozenset({"ЦАП", "ЦП"})
_LW = frozenset({"ЛФА", "ЛФД"})
_RW = frozenset({"ПФА", "ПФД"})
_ST = frozenset({"ФРВ", "ЦФД"})
_CF = frozenset({"ФРВ", "ЦФД"})


def _S(slot_id: str, x: float, y: float, pos: frozenset[str]) -> "SquadSlot":
    from team_squad_schemas import SquadSlot

    return SquadSlot(slot_id, x, y, pos)


def _build_all() -> dict[int, tuple["SquadSlot", ...]]:
    # --- 1: 4-3-3 ат (два центральных ниже, CAM выше треугольником вверх) ---
    fid1 = (
        _S("GK", 0.50, 0.88, _VRT),
        _S("LB", 0.10, 0.70, _LB),
        _S("LCB", 0.36, 0.74, _CB_L),
        _S("RCB", 0.64, 0.74, _CB_R),
        _S("RB", 0.90, 0.70, _RB),
        _S("LCM", 0.30, 0.50, _CM_L),
        _S("RCM", 0.70, 0.50, _CM_R),
        _S("CAM", 0.50, 0.34, _CAM),
        _S("LW", 0.16, 0.18, _LW),
        _S("ST", 0.50, 0.12, _ST),
        _S("RW", 0.84, 0.18, _RW),
    )

    # --- 2: 4-3-3 уд (CDM + два CM выше «уголком») — как базовый 433 в проекте ---
    fid2 = (
        _S("GK", 0.50, 0.86, _VRT),
        _S("LB", 0.10, 0.68, _LB),
        _S("RB", 0.90, 0.68, _RB),
        _S("LCB", 0.36, 0.68, _CB_L),
        _S("RCB", 0.64, 0.68, _CB_R),
        _S("CDM", 0.50, 0.52, _CDM),
        _S("LCM", 0.32, 0.40, _CM_L),
        _S("RCM", 0.68, 0.40, _CM_R),
        _S("LW", 0.18, 0.22, _LW),
        _S("ST", 0.50, 0.14, _ST),
        _S("RW", 0.82, 0.22, _RW),
    )

    # --- 3: 4-3-3 линия (три ЦП почти в линию) ---
    fid3 = (
        _S("GK", 0.50, 0.86, _VRT),
        _S("LB", 0.10, 0.68, _LB),
        _S("RB", 0.90, 0.68, _RB),
        _S("LCB", 0.36, 0.68, _CB_L),
        _S("RCB", 0.64, 0.68, _CB_R),
        _S("LCM", 0.28, 0.42, _CM_L),
        _S("CCM", 0.50, 0.44, _CM_C),
        _S("RCM", 0.72, 0.42, _CM_R),
        _S("LW", 0.18, 0.22, _LW),
        _S("ST", 0.50, 0.14, _ST),
        _S("RW", 0.82, 0.22, _RW),
    )

    # --- 4: 4-4-2 линия ---
    fid4 = (
        _S("GK", 0.50, 0.88, _VRT),
        _S("LB", 0.10, 0.70, _LB),
        _S("LCB", 0.36, 0.74, _CB_L),
        _S("RCB", 0.64, 0.74, _CB_R),
        _S("RB", 0.90, 0.70, _RB),
        _S("LM", 0.08, 0.48, frozenset({"ЛП", "ЛЦП", "ЛФА", "ЛФД"})),
        _S("LCM", 0.38, 0.50, _CM_C),
        _S("RCM", 0.62, 0.50, _CM_C),
        _S("RM", 0.92, 0.48, frozenset({"ПП", "ПЦП", "ПФА", "ПФД"})),
        _S("STL", 0.38, 0.16, _ST),
        _S("STR", 0.62, 0.16, _ST),
    )

    # --- 5: 4-3-1-2 ---
    fid5 = (
        _S("GK", 0.50, 0.88, _VRT),
        _S("LB", 0.10, 0.70, _LB),
        _S("LCB", 0.36, 0.74, _CB_L),
        _S("RCB", 0.64, 0.74, _CB_R),
        _S("RB", 0.90, 0.70, _RB),
        _S("LCM", 0.30, 0.52, _CM_L),
        _S("CCM", 0.50, 0.56, frozenset({"ЦОП", "ЦП", "ЦАП"})),
        _S("RCM", 0.70, 0.52, _CM_R),
        _S("CAM", 0.50, 0.34, _CAM),
        _S("STL", 0.38, 0.14, _ST),
        _S("STR", 0.62, 0.14, _ST),
    )

    # --- 6: 4-3-3 «9» (опорник + два CM; центр: ФРВ и ЦФД — одна точка, взаимозаменяемо как в заявке) ---
    fid6 = (
        _S("GK", 0.50, 0.86, _VRT),
        _S("LB", 0.10, 0.68, _LB),
        _S("RB", 0.90, 0.68, _RB),
        _S("LCB", 0.36, 0.68, _CB_L),
        _S("RCB", 0.64, 0.68, _CB_R),
        _S("CDM", 0.50, 0.52, _CDM),
        _S("LCM", 0.32, 0.40, _CM_L),
        _S("RCM", 0.68, 0.40, _CM_R),
        _S("LW", 0.18, 0.20, _LW),
        _S("ST", 0.50, 0.16, _ST),
        _S("RW", 0.82, 0.20, _RW),
    )

    # --- 7: 4-2-1-3 (два опорника, CAM, тройка впереди, ST) ---
    fid7 = (
        _S("GK", 0.50, 0.88, _VRT),
        _S("LB", 0.10, 0.70, _LB),
        _S("LCB", 0.36, 0.74, _CB_L),
        _S("RCB", 0.64, 0.74, _CB_R),
        _S("RB", 0.90, 0.70, _RB),
        _S("LCDM", 0.36, 0.54, _CDM),
        _S("RCDM", 0.64, 0.54, _CDM),
        _S("LW", 0.14, 0.26, _LW),
        _S("CAM", 0.50, 0.32, _CAM),
        _S("RW", 0.86, 0.26, _RW),
        _S("ST", 0.50, 0.12, _ST),
    )

    # --- 8: 4-2-4 ---
    fid8 = (
        _S("GK", 0.50, 0.88, _VRT),
        _S("LB", 0.10, 0.70, _LB),
        _S("LCB", 0.36, 0.74, _CB_L),
        _S("RCB", 0.64, 0.74, _CB_R),
        _S("RB", 0.90, 0.70, _RB),
        _S("LCM", 0.38, 0.52, _CM_C),
        _S("RCM", 0.62, 0.52, _CM_C),
        _S("LW", 0.10, 0.18, _LW),
        _S("STL", 0.38, 0.14, _ST),
        _S("STR", 0.62, 0.14, _ST),
        _S("RW", 0.90, 0.18, _RW),
    )

    # --- 9: 5-2-1-2 (пять защитников, два CM, CAM, два ST) ---
    fid9 = (
        _S("GK", 0.50, 0.90, _VRT),
        _S("LWB", 0.06, 0.66, frozenset({"ЛЗ", "ЛФЗ", "ЛФД"})),
        _S("LCB", 0.30, 0.74, _CB_L),
        _S("CCB", 0.50, 0.68, _CB_C),
        _S("RCB", 0.70, 0.74, _CB_R),
        _S("RWB", 0.94, 0.66, frozenset({"ПЗ", "ПФЗ", "ПФД"})),
        _S("LCM", 0.38, 0.46, _CM_L),
        _S("RCM", 0.62, 0.46, _CM_R),
        _S("CAM", 0.50, 0.30, _CAM),
        _S("STL", 0.38, 0.14, _ST),
        _S("STR", 0.62, 0.14, _ST),
    )

    # --- 10: 5-2-3 ---
    fid10 = (
        _S("GK", 0.50, 0.90, _VRT),
        _S("LWB", 0.06, 0.62, frozenset({"ЛЗ", "ЛФЗ", "ЛФД"})),
        _S("LCB", 0.30, 0.72, _CB_L),
        _S("CCB", 0.50, 0.66, _CB_C),
        _S("RCB", 0.70, 0.72, _CB_R),
        _S("RWB", 0.94, 0.62, frozenset({"ПЗ", "ПФЗ", "ПФД"})),
        _S("LCM", 0.38, 0.44, _CM_L),
        _S("RCM", 0.62, 0.44, _CM_R),
        _S("LW", 0.16, 0.18, _LW),
        _S("ST", 0.50, 0.12, _ST),
        _S("RW", 0.84, 0.18, _RW),
    )

    return {
        1: fid1,
        2: fid2,
        3: fid3,
        4: fid4,
        5: fid5,
        6: fid6,
        7: fid7,
        8: fid8,
        9: fid9,
        10: fid10,
    }


def _slots_by_id() -> dict[int, tuple["SquadSlot", ...]]:
    global _slots_cache
    if _slots_cache is None:
        _slots_cache = _build_all()
    return _slots_cache


def register_fid_slots(slots_dict: dict[str, tuple["SquadSlot", ...]]) -> None:
    """Записать ``fid_1``…``fid_10`` в общий словарь ``FORMATION_SLOTS``."""
    by = _slots_by_id()
    for i in range(1, 11):
        slots_dict[f"fid_{i}"] = by[i]
