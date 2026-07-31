# -*- coding: utf-8 -*-
from bot.services import teams_ordered_for_goalscorers, tournament_db_for_league


def test_wc_teams_and_tournament():
    assert tournament_db_for_league("wc") == "wc"
    nations = teams_ordered_for_goalscorers("wc")
    assert len(nations) >= 40
    assert all(isinstance(n, str) and n.strip() for n in nations)


def test_wc_squad_pitch_png_smoke():
    from bot.squad_pitch import render_squad_pitch_png_bytes

    nations = teams_ordered_for_goalscorers("wc")
    png = render_squad_pitch_png_bytes(nations[0], "wc")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
