# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from bot.team_history import (
    compare_clubs,
    compute_nation_prestige,
    compute_result_streaks,
    compute_team_prestige,
    is_nation_name,
    rank_nations_by_prestige,
    rank_teams_by_prestige,
)


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


def test_compute_result_streaks():
    # как у Интера на скрине: 8 побед подряд, луз-стрик 1
    seq = list("WLWWWWWLWWLWWWWWWWWLWWDLD")
    s = compute_result_streaks(seq)
    assert s["wins"] == 8
    assert s["unbeaten"] == 8
    assert s["losses"] == 1

    assert compute_result_streaks(["W", "D", "W", "L", "L", "L", "W"]) == {
        "unbeaten": 3,
        "wins": 1,
        "losses": 3,
    }
    assert compute_result_streaks([]) == {"unbeaten": 0, "wins": 0, "losses": 0}


def test_nation_prestige_and_compare_rules():
    nations = rank_nations_by_prestige()
    assert len(nations) >= 2
    p = compute_nation_prestige(nations[0].team)
    assert p.league_code == "wc"
    assert p.score >= 0
    assert "ЧМ титул" in p.breakdown
    assert is_nation_name(nations[0].team)
    assert not is_nation_name("Ливерпуль")

    data = compare_clubs(nations[0].team, nations[1].team)
    assert data["kind"] == "nation"

    with pytest.raises(ValueError, match="клуб с клубом"):
        compare_clubs("Ливерпуль", nations[0].team)