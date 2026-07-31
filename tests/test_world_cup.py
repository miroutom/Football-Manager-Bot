# -*- coding: utf-8 -*-
from utils.world_cup import is_world_cup_season, next_world_cup_season


def test_wc_season_every_4():
    assert not is_world_cup_season(1)
    assert not is_world_cup_season(3)
    assert is_world_cup_season(4)
    assert not is_world_cup_season(5)
    assert is_world_cup_season(8)
    assert is_world_cup_season(12)
    assert next_world_cup_season(3) == 4
    assert next_world_cup_season(4) == 4
    assert next_world_cup_season(5) == 8


def test_ensure_wc_db_season4():
    from utils.world_cup import ensure_world_cup_db
    import os

    path = ensure_world_cup_db(4)
    assert path and os.path.isfile(path)
    assert path.endswith("world_cup.db")


def test_wc_history_png():
    from bot.history_render import render_wc_history_png

    png = render_wc_history_png(preview_demo=True)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 5_000


def test_timeline_wc_slot():
    from bot.season_history_store import timeline_wc

    rows = timeline_wc(4)
    assert any(s == 4 for s, _ in rows)
