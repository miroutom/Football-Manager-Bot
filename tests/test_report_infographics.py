# -*- coding: utf-8 -*-
from bot.report_gfx import theme_for_league
from bot.standings_infographic import collect_standings_rows, render_standings_infographic_png_bytes


def test_themes_cover_main_leagues():
    for code in ("rpl", "eng", "esp", "ita", "ger", "cl"):
        t = theme_for_league(code)
        assert t.code == code
        assert t.title


def test_standings_png_smoke():
    title, rows, _note = collect_standings_rows("rpl")
    assert title
    blobs = render_standings_infographic_png_bytes("rpl")
    assert blobs and blobs[0][:8] == b"\x89PNG\r\n\x1a\n"
