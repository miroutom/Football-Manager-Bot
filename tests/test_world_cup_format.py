# -*- coding: utf-8 -*-
"""Формат ЧМ 48 команд / лучшие третьи."""
from utils.world_cup_format import (
    BEST_THIRDS,
    N_TEAMS,
    all_group_fixtures,
    compute_group_tables,
    draw_groups,
    group_fixtures,
    qualify_from_groups,
    validate_nation_count,
)
from utils.world_cup import load_wc_config, nations_by_confederation


def test_nation_list_is_48():
    by = nations_by_confederation()
    ok, msg = validate_nation_count(by)
    assert ok, msg
    cfg = load_wc_config()
    assert len(cfg.get("nations") or []) == N_TEAMS


def test_group_rr_six_matches():
    teams = ["A", "B", "C", "D"]
    fx = group_fixtures(teams)
    assert len(fx) == 6
    pairs = {(min(h, a), max(h, a)) for h, a, _ in fx}
    assert len(pairs) == 6


def test_draw_and_qualify_best_thirds():
    by = nations_by_confederation()
    groups = draw_groups(by, seed=42)
    assert len(groups) == 12
    assert all(len(v) == 4 for v in groups.values())
    fx = all_group_fixtures(groups)
    assert len(fx) == 12 * 6  # 72 матча группы

    # синтетические результаты: побеждает первый в алфавите
    results = []
    for m in fx:
        h, a = m["home"], m["away"]
        if h.casefold() < a.casefold():
            results.append({**m, "home_score": 2, "away_score": 0})
        else:
            results.append({**m, "home_score": 0, "away_score": 2})
    tables = compute_group_tables(groups, results)
    q = qualify_from_groups(tables)
    assert len(q["winners"]) == 12
    assert len(q["runners_up"]) == 12
    assert len(q["thirds_qualified"]) == BEST_THIRDS
    assert len(q["thirds_eliminated"]) == 12 - BEST_THIRDS
    assert len(q["knockout_teams"]) == 32
