# -*- coding: utf-8 -*-
from utils.wc_branding import (
    is_wc_start_announced,
    mark_wc_start_announced,
)


def test_should_announce_wc_start_cl_final(monkeypatch):
    from bot.wc_announcement import should_announce_wc_start

    monkeypatch.setattr("utils.season_paths.get_active_season", lambda: 4)
    monkeypatch.setattr("utils.world_cup.is_world_cup_season", lambda s: s == 4)
    monkeypatch.setattr(
        "utils.cl_knockout_schedule._cl_knockout_is_final_match",
        lambda h, a: True,
    )
    monkeypatch.setattr("utils.wc_branding.is_wc_start_announced", lambda s=None: False)

    assert should_announce_wc_start(
        ok=True,
        league_code="cl",
        cl_phase="knockout",
        home="Real Madrid",
        away="Bayern",
    )
    assert not should_announce_wc_start(
        ok=True,
        league_code="pl",
        cl_phase="knockout",
        home="Real Madrid",
        away="Bayern",
    )
    assert not should_announce_wc_start(
        ok=True,
        league_code="cl",
        cl_phase="group",
        home="Real Madrid",
        away="Bayern",
    )


def test_wc_start_announced_flag(tmp_path, monkeypatch):
    path = tmp_path / "wc_branding.json"
    monkeypatch.setattr("utils.wc_branding._PATH", str(path))
    monkeypatch.setattr("utils.wc_branding.migrate_branding_styles", lambda: None)
    monkeypatch.setattr(
        "utils.wc_branding._host_pool",
        lambda: ["Япония", "Бразилия"],
    )
    assert not is_wc_start_announced(4)
    mark_wc_start_announced(4)
    assert is_wc_start_announced(4)


def test_build_wc_start_caption():
    from bot.wc_announcement import build_wc_start_caption

    cap = build_wc_start_caption(4, "Япония")
    assert "сезон 4" in cap
    assert "Япония" in cap
    assert "🏆" in cap
