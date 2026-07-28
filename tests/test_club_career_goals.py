# -*- coding: utf-8 -*-
from __future__ import annotations

from bot.team_history import ClubCareerGoals, club_career_goals


def test_club_career_goals_has_pool_and_totals():
    rows = club_career_goals(pool_only=True)
    assert len(rows) == 40
    assert all(isinstance(r, ClubCareerGoals) for r in rows)
    assert rows[0].total_gf >= rows[-1].total_gf
    assert all(r.total_gf == r.league_gf + r.cl_gf for r in rows)
    # хотя бы у кого-то есть голы в лиге и у кого-то в ЛЧ
    assert any(r.league_gf > 0 for r in rows)
    assert any(r.cl_gf > 0 for r in rows)
