import os

import pytest

from utils import season_paths


def test_all_time_club_stats_uses_synced_db():
    from bot.services import (
        render_team_goalscorers_all_time_single,
        teams_ordered_for_goalscorers,
        _cumulative_db_path_for_goalscorers_scope,
    )

    path = _cumulative_db_path_for_goalscorers_scope("league")
    if not os.path.isfile(path):
        pytest.skip(f"no synced db: {path}")

    teams = teams_ordered_for_goalscorers("eng")
    idx = next(i for i, t in enumerate(teams) if "Ньюкасл" in t)
    text = render_team_goalscorers_all_time_single("eng", idx, "league")
    assert "за все время" in text
    assert "Тонали" in text
    assert season_paths.get_cumulative_league_db_path() in path or path.endswith(
        "league_synced.db"
    )
