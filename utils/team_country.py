# -*- coding: utf-8 -*-
"""Определение «страны» лиги по названию клуба (для ЛЧ: запрет дерби одной страны)."""
from __future__ import annotations

from config.leagues_config import england, germany, italy, rpl, spain

_POOLS: list[tuple[str, tuple[str, ...]]] = [
    ("rpl", tuple(rpl)),
    ("eng", tuple(england)),
    ("esp", tuple(spain)),
    ("ita", tuple(italy)),
    ("ger", tuple(germany)),
]


def country_code_for_team(team_name: str) -> str | None:
    """Код страны/лиги: rpl, eng, esp, ita, ger или None."""
    t = (team_name or "").strip().lower()
    for code, names in _POOLS:
        for n in names:
            if n.lower() == t:
                return code
    return None


def same_country(team_a: str, team_b: str) -> bool:
    ca = country_code_for_team(team_a)
    cb = country_code_for_team(team_b)
    if ca is None or cb is None:
        return False
    return ca == cb
