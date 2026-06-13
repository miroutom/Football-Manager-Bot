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
        "CM",
        "CAM",
        "LM",
        "RM",
        "LW",
        "RW",
        "ST",
        "CF",
        "STL",
        "STR",
        "RS",
        "LS",
        "RDM",
        "LDM",
        "LCDM",
        "RCDM",
        "LCAM",
        "RCAM",
        "LAM",
        "RAM",
        "LWB",
        "RWB",
    }
)

# Алиасы с фото редактора (только при отсутствии точного слота в схеме)
_SLOT_FALLBACKS: dict[str, tuple[str, ...]] = {
    "RS": ("STL", "STR", "ST"),
    "LS": ("STR", "STL", "ST"),
    "RDM": ("RCDM", "RCM", "RM"),
    "LDM": ("LCDM", "LCM", "LM"),
    "CM": ("CCM", "CDM"),
    "RAM": ("RCAM", "RM", "RW"),
    "LAM": ("LCAM", "LM", "LW"),
}


def resolve_lineup_slot_for_formation(
    slot_id: str | None, valid_slot_ids: frozenset[str] | set[str]
) -> str | None:
    """Слот с фото → id слота активной схемы (RS→STL, RDM→RCM и т.д.)."""
    s = (slot_id or "").strip().upper()
    if not s:
        return None
    if s in valid_slot_ids:
        return s
    for alt in _SLOT_FALLBACKS.get(s, ()):
        if alt in valid_slot_ids:
            return alt
    return None


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
