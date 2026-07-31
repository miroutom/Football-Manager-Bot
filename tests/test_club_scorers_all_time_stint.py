# -*- coding: utf-8 -*-
"""Club all-time = sum of season archives while player was at that club."""
import os

import pytest

from bot.player_board_infographic import collect_club_scorer_rows_all_time
from utils.cumulative_db import list_season_archives_with_db


@pytest.mark.skipif(
    not list_season_archives_with_db(),
    reason="no season archives",
)
def test_havertz_stint_split_arsenal_city():
    arsenal = collect_club_scorer_rows_all_time("Арсенал", tournament="common")
    city = collect_club_scorer_rows_all_time("Сити", tournament="common")

    h_ars = next((r for r in arsenal if "Хаверц" in str(r["name"])), None)
    h_city = next((r for r in city if "Хаверц" in str(r["name"])), None)

    assert h_ars is not None, "Хаверц должен быть в Арсенале за сезоны 1–2"
    assert h_city is not None, "Хаверц должен быть в Сити за сезон 3+"

    # S1+S2 common: 24+23 matches, 16+19 goals, 12+14 assists
    assert int(h_ars["matches"]) == 47
    assert int(h_ars["goals"]) == 35
    assert int(h_ars["assists"]) == 26

    # S3 common only (S4 zeros): 19 / 29 / 8 — не карьера 66/64/34
    assert int(h_city["matches"]) == 19
    assert int(h_city["goals"]) == 29
    assert int(h_city["assists"]) == 8
    assert int(h_city["ga"]) == 37


def test_club_png_header_smoke():
    from bot.player_board_infographic import render_club_scorers_png_pages

    rows = [
        {
            "name": "Хаверц",
            "team": "Арсенал",
            "position": "ФРВ",
            "matches": 47,
            "goals": 35,
            "assists": 26,
            "ga": 61,
            "nation": "Германия",
        }
    ]
    blobs = render_club_scorers_png_pages(
        team="Арсенал",
        title="лига+ЛЧ · за все время",
        rows=rows,
        league_code="eng",
    )
    assert blobs and blobs[0][:8] == b"\x89PNG\r\n\x1a\n"
