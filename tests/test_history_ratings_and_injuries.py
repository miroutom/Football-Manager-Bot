# -*- coding: utf-8 -*-
from __future__ import annotations

from bot.team_history import (
    club_career_conceded,
    rank_clubs_by_attack,
    rank_clubs_by_defense,
)
from utils.player_discipline import format_never_injured_report_text


def test_club_career_conceded_sorted_ascending():
    rows = club_career_conceded(pool_only=True)
    assert len(rows) == 40
    assert all(r.total_ga == r.league_ga + r.cl_ga for r in rows)
    totals = [r.total_ga for r in rows]
    assert totals == sorted(totals)


def test_attack_defense_ratings_cover_pool():
    atk = rank_clubs_by_attack(pool_only=True)
    dfn = rank_clubs_by_defense(pool_only=True)
    assert len(atk) == 40
    assert len(dfn) == 40
    assert atk[0].score >= atk[-1].score
    assert dfn[0].score >= dfn[-1].score


def test_never_injured_report_has_header():
    text = format_never_injured_report_text(limit=10, min_matches=1)
    assert "НИ РАЗУ НЕ ТРАВМИРОВАЛИСЬ" in text
    assert "Игрок" in text
