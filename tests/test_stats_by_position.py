import os

import pytest

from utils.stats_by_position import collect_group_stats, format_group_stats


def test_collect_forwards_current_season_has_matches_column():
    rows = collect_group_stats("cur", "fwd")
    if not rows:
        pytest.skip("no forward data in current season")
    r = rows[0]
    assert "matches" in r
    assert "goals" in r
    assert "assists" in r
    assert "ga" in r
    assert int(r["matches"]) > 0


def test_collect_goalkeepers_life_clean_sheets():
    from utils import season_paths

    if not os.path.isfile(season_paths.get_cumulative_common_db_path()):
        pytest.skip("no common_synced.db")
    rows = collect_group_stats("life", "gk")
    if not rows:
        pytest.skip("no goalkeeper data")
    r = rows[0]
    assert "clean_sheets" in r
    assert "matches" in r


def test_format_group_stats_titles():
    import os

    from utils import season_paths

    if not os.path.isfile(season_paths.get_cumulative_common_db_path()):
        pytest.skip("no common_synced.db")
    text = format_group_stats("life", "mid")
    assert "Полузащитники" in text
    assert "Г+А" in text
    assert "POTM" in text
    assert "MOTM" in text
    gk_text = format_group_stats("life", "gk")
    assert "Вратари" in gk_text
    assert "Сух." in gk_text
    assert "POTM" in gk_text
    assert "MOTM" in gk_text
