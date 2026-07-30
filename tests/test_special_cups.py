# -*- coding: utf-8 -*-
"""Золотые / платиновые кубки чемпионских кампаний."""


def test_cl_winners_gold_undefeated():
    from bot.team_history import campaign_special_cup

    # Интер с1 и Ливерпуль с2 выиграли ЛЧ без поражений (с ничьими)
    assert campaign_special_cup("Интер", 1, competition="cl") == "gold"
    assert campaign_special_cup("Ливерпуль", 2, competition="cl") == "gold"


def test_league_champion_not_automatically_gold():
    from bot.team_history import campaign_special_cup

    # Бавария с1 — чемпион, но были поражения
    assert (
        campaign_special_cup("Бавария", 1, competition="league", league_code="ger")
        is None
    )


def test_special_cup_assets_exist():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert (root / "assets/history/trophies/cup_gold.png").is_file()
    assert (root / "assets/history/trophies/cup_platinum.png").is_file()


def test_cl_history_png_renders():
    from bot.history_render import render_cl_history_png

    png = render_cl_history_png()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 10_000
