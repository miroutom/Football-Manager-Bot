# -*- coding: utf-8 -*-
"""Жеребьёвка ЧМ, календарь м.11, состояние турнира."""
from __future__ import annotations

import json
from pathlib import Path

from utils.world_cup import nations_by_confederation
from utils.world_cup_format import (
    GROUP_IDS,
    N_TEAMS,
    build_fifa_pots,
    draw_groups_fifa,
    nation_to_confederation,
)
from utils.wc_schedule import group_stage_lines_ordered, ensure_wc_group_stage_in_schedule
from utils.wc_tournament import default_tournament, save_tournament


def test_fifa_pots_four_by_twelve():
    by = nations_by_confederation()
    pots = build_fifa_pots(by)
    assert len(pots) == 4
    assert all(len(p) == 12 for p in pots)
    names = [t for pot in pots for t, _ in pot]
    assert len(names) == N_TEAMS
    assert len(set(n.casefold() for n in names)) == N_TEAMS


def test_draw_fifa_conf_limits():
    by = nations_by_confederation()
    conf_of = nation_to_confederation(by)
    groups = draw_groups_fifa(by, seed=2026)
    assert set(groups) == set(GROUP_IDS)
    assert all(len(v) == 4 for v in groups.values())
    for gid, teams in groups.items():
        confs = [conf_of[t] for t in teams]
        assert confs.count("Европа") <= 3
        for c in ("Африка", "Азия", "Сев. Америка", "Юж. Америка"):
            assert confs.count(c) <= 1, (gid, confs)


def test_group_stage_72_lines():
    by = nations_by_confederation()
    groups = draw_groups_fifa(by, seed=7)
    lines = group_stage_lines_ordered(groups)
    assert len(lines) == 72
    assert all(ln.endswith(";wc;group") for ln in lines)


def test_ensure_month11_writes(tmp_path: Path, monkeypatch):
    by = nations_by_confederation()
    groups = draw_groups_fifa(by, seed=11)
    # подменить tournament + mixed file
    tour = default_tournament(4)
    tour["drawn"] = True
    tour["groups"] = groups
    tour_path = tmp_path / "wc_tournament.json"
    mixed = tmp_path / "mixed_schedule.json"
    mixed.write_text(
        json.dumps({"version": 3, "kind": "months", "rounds": [{"day": 10, "matches": []}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    import utils.wc_tournament as wt
    import utils.wc_schedule as ws
    import utils.world_cup as wc

    monkeypatch.setattr(wt, "_PATH", str(tour_path))
    monkeypatch.setattr(ws, "MIXED_FILE", mixed)
    monkeypatch.setattr(wc, "is_world_cup_season", lambda season=None: True)
    save_tournament(tour)

    ok, msg = ensure_wc_group_stage_in_schedule(path=mixed, replace_existing=True)
    assert ok, msg
    doc = json.loads(mixed.read_text(encoding="utf-8"))
    days = {int(b["day"]): b for b in doc["rounds"]}
    assert 11 in days
    wc_lines = [ln for ln in days[11]["matches"] if ";wc;" in ln]
    assert len(wc_lines) == 72
