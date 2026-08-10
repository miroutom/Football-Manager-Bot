# -*- coding: utf-8 -*-
from __future__ import annotations

from bot.team_history import TitledPlayer, _titled_players_from_bucket


def test_titled_players_sort_and_filter():
    bucket = {
        ("a",): {
            "name": "Alpha",
            "team": "Club A",
            "position": "ФРВ",
            "overall": 85,
            "league_titles": 2,
            "cl_titles": 1,
            "individual_awards": 0,
            "league_titles_by_club": {"club a": 2},
            "cl_titles_by_club": {"club a": 1},
        },
        ("b",): {
            "name": "Beta",
            "team": "Club B",
            "position": "ЦП",
            "overall": 82,
            "league_titles": 1,
            "cl_titles": 0,
            "individual_awards": 1,
            "league_titles_by_club": {"club b": 1},
            "cl_titles_by_club": {},
        },
        ("c",): {
            "name": "Gamma",
            "team": "Club A",
            "position": "ВР",
            "overall": 80,
            "league_titles": 3,
            "cl_titles": 1,
            "individual_awards": 0,
            "league_titles_by_club": {"club b": 3},
            "cl_titles_by_club": {"club b": 1},
        },
    }
    global_rows = _titled_players_from_bucket(bucket, min_total=3)
    assert [r.name for r in global_rows] == ["Gamma", "Alpha"]
    assert global_rows[0].total_titles == 4

    club_rows = _titled_players_from_bucket(
        bucket, min_total=1, team="Club A", at_club=True
    )
    assert [r.name for r in club_rows] == ["Alpha"]
    assert club_rows[0].league_titles == 2 and club_rows[0].cl_titles == 1

    # Карьерные титулы за Club B, сейчас в Club A — не попадает в Club A
    assert "Gamma" not in [r.name for r in club_rows]


def test_titled_player_total():
    p = TitledPlayer(
        name="X",
        team="Y",
        position="ФРВ",
        overall=90,
        league_titles=2,
        cl_titles=1,
        individual_awards=2,
    )
    assert p.total_titles == 5
