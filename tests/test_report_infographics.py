# -*- coding: utf-8 -*-
from bot.report_gfx import theme_for_league
from bot.standings_infographic import (
    collect_standings_rows,
    collect_wc_group_standings,
    render_standings_infographic_png_bytes,
    render_wc_group_standings_png_pages,
)


def test_themes_cover_main_leagues():
    for code in ("rpl", "eng", "esp", "ita", "ger", "cl", "wc"):
        t = theme_for_league(code)
        assert t.code == code
        assert t.title


def test_standings_png_smoke():
    title, rows, _note = collect_standings_rows("rpl")
    assert title
    blobs = render_standings_infographic_png_bytes("rpl")
    assert blobs and blobs[0][:8] == b"\x89PNG\r\n\x1a\n"


def test_wc_standings_png_smoke(monkeypatch):
    from utils.world_cup_format import GROUP_IDS

    fake = {
        "version": 1,
        "drawn": True,
        "groups": {
            gid: [f"Нация{gid}1", f"Нация{gid}2", f"Нация{gid}3", f"Нация{gid}4"]
            for gid in GROUP_IDS
        },
    }
    monkeypatch.setattr("utils.wc_tournament.load_tournament", lambda: fake)
    monkeypatch.setattr("utils.wc_tournament.groups_drawn", lambda: True)
    monkeypatch.setattr(
        "match_results.load_records_and_keys",
        lambda: (
            [
                {
                    "home": "Нацияa1",
                    "away": "Нацияa2",
                    "league": "wc",
                    "home_score": 2,
                    "away_score": 1,
                }
            ],
            set(),
        ),
    )
    data = collect_wc_group_standings()
    assert data["groups"]
    assert len(data["groups"]) == 12
    blobs = render_wc_group_standings_png_pages()
    assert len(blobs) == 4  # 12 / 3
    assert blobs[0][:8] == b"\x89PNG\r\n\x1a\n"
    blobs2 = render_standings_infographic_png_bytes("wc")
    assert blobs2 and blobs2[0][:8] == b"\x89PNG\r\n\x1a\n"
