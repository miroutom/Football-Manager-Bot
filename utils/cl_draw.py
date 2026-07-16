# -*- coding: utf-8 -*-
"""
Ручной жребий ЛЧ: места 1–24 из групповой таблицы, статусы «нужен жребий».
"""
from __future__ import annotations

from typing import Literal

from champions_league.bracket_html import (
    _load_cl_scores_and_penalties,
    _winner_two_leg,
)
from champions_league.cl_format import get_cl_participants
from champions_league.knockout_bracket import (
    bracket_needs_r1_draw,
    bracket_needs_r2_draw,
    get_default_round1_pairs,
    round1_pairs_are_placeholders,
)
from match_results import compute_cl_group_standings_from_journal

ClDrawAction = Literal["r1", "r2"]


def ordered_cl_group_standings() -> list[str]:
    """Названия команд ЛЧ по месту в группе (1 = лидер)."""
    teams = compute_cl_group_standings_from_journal(get_cl_participants())
    ordered = sorted(
        teams.values(),
        key=lambda t: (-t.points, -t.difference, -t.scored),
    )
    return [t.name for t in ordered]


def is_cl_group_stage_complete() -> bool:
    """Группа закрыта: у каждой из 30 команд по 8 матчей в групповой фазе."""
    teams = compute_cl_group_standings_from_journal(get_cl_participants())
    if len(teams) < 30:
        return False
    return all(int(t.matches) >= 8 for t in teams.values())


def cl_draw_menu_action() -> ClDrawAction | None:
    """
    Что показать в главном меню:
    - ``r1`` — жребий 1/16 (группа готова, пары пустые);
    - ``r2`` — жребий 1/8 (1/16 сыграна, посевы пустые);
    - ``None`` — плашка не нужна.
    """
    if bracket_needs_r1_draw():
        if is_cl_group_stage_complete():
            return "r1"
        return None
    if bracket_needs_r2_draw():
        from utils.cl_knockout_schedule import is_knockout_round_complete

        if is_knockout_round_complete("round_1"):
            return "r2"
        return None
    return None


def r1_draw_pool() -> list[str]:
    """Места 9–24 (16 команд) для пар 1/16."""
    return ordered_cl_group_standings()[8:24]


def r2_seed_pool() -> list[str]:
    """Места 1–8 (bye в 1/8), ещё не привязанные к веткам."""
    return ordered_cl_group_standings()[:8]


def r1_winners_in_bracket_order() -> list[str] | None:
    """
    8 победителей стыков 1/16 в порядке слотов сетки.
    ``None``, если пары не заполнены или какой-то стык ещё без победителя.
    """
    if round1_pairs_are_placeholders():
        return None
    pairs = get_default_round1_pairs()
    scores, pen = _load_cl_scores_and_penalties()
    out: list[str] = []
    for h, a in pairs[:8]:
        win = _winner_two_leg(scores, h, a, pen)
        if not win:
            return None
        out.append(win)
    return out
