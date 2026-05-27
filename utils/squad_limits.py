# -*- coding: utf-8 -*-
"""Лимиты заявки клуба: 11 старт, 7 скамейка, до 30 игроков (остальные — резерв)."""
from __future__ import annotations

SQUAD_MAX = 30
SQUAD_START = 11
SQUAD_BENCH = 7
SQUAD_MIN_FOR_WIZARD = SQUAD_START + SQUAD_BENCH  # 18


def squad_reserve_count(total_players: int) -> int:
    """Число игроков в резерве при полной заявке ``total_players``."""
    return max(0, int(total_players) - SQUAD_START - SQUAD_BENCH)


def squad_limits_for_total(total_players: int) -> dict[str, int]:
    return {
        "start": SQUAD_START,
        "bench": SQUAD_BENCH,
        "reserve": squad_reserve_count(total_players),
    }
