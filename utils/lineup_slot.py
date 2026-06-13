# -*- coding: utf-8 -*-
"""Слоты расстановки на поле (``lineup_slot`` / pos_on_pitch)."""
from __future__ import annotations

LINEUP_SLOT_IDS: frozenset[str] = frozenset(
    {
        "GK",
        "LB",
        "RB",
        "LCB",
        "RCB",
        "CB",
        "CDM",
        "LCM",
        "RCM",
        "CCM",
        "CAM",
        "LM",
        "RM",
        "LW",
        "RW",
        "ST",
        "CF",
        "STL",
        "STR",
    }
)


def normalize_lineup_slot(raw: str | None) -> str | None:
    s = (raw or "").strip().upper()
    if not s or s in ("-", "—", "NONE"):
        return None
    if s not in LINEUP_SLOT_IDS:
        raise ValueError(
            f"Неизвестный слот на поле {raw!r}; допустимо: {', '.join(sorted(LINEUP_SLOT_IDS))}"
        )
    return s


def is_valid_lineup_slot(raw: str) -> bool:
    return (raw or "").strip().upper() in LINEUP_SLOT_IDS
