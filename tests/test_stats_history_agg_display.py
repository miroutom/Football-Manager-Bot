# -*- coding: utf-8 -*-
"""Подпись в топах сезона: не подменять игрока с большим id при слиянии по person_id."""
from __future__ import annotations

from utils.stats_history_agg import aggregate_outfield, collect_stats_history_rows


def test_season1_martinez_inter_not_alvarez_label():
    rows = aggregate_outfield("allcl", season_num=1, merge_by_player=True)
    mart = next(r for r in rows if r.get("person_id") == 62 and r["team"] == "Интер")
    assert mart["name"] == "Мартинез"
    assert mart["goals"] == 56
    assert mart["assists"] == 8
    assert mart["ga"] == 64

    _, top, err = collect_stats_history_rows("season", "allcl", "ga", 1, season_num=1)
    assert err is None
    assert top[0]["name"] == "Мартинез"
    assert top[0]["team"] == "Интер"


def test_alvarez_martinez_separate_person_id():
    rows = aggregate_outfield("allcl", season_num=1, merge_by_player=True)
    alv = next(
        (r for r in rows if r.get("name") == "Альварес Мартинез"),
        None,
    )
    assert alv is not None
    assert alv["person_id"] == 1095
    assert alv["goals"] == 0
    assert alv["assists"] == 0
