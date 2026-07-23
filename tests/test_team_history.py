# -*- coding: utf-8 -*-
from __future__ import annotations

from bot.team_history import compute_team_prestige, rank_teams_by_prestige


def test_prestige_ranks_big5_above_easy_rpl_titles():
    rows = rank_teams_by_prestige(limit=None)
    assert len(rows) == 40
    names = [r.team for r in rows]
    assert "Интер" in names[:5]
    # Зенит с 2 титулами РПЛ не должен быть в топ-10 силы
    if "Зенит" in names:
        assert names.index("Зенит") >= 10


def test_prestige_breakdown_non_negative():
    p = compute_team_prestige("Ливерпуль")
    assert p.score >= 0
    assert all(v >= 0 for v in p.breakdown.values())
