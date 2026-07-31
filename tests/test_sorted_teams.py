# -*- coding: utf-8 -*-
from table.team import Team
from teams import get_sorted_teams


def test_empty_table_alphabetical():
    teams = {
        "Спартак": Team("Спартак"),
        "Цска": Team("Цска"),
        "Динамо": Team("Динамо"),
        "Зенит": Team("Зенит"),
    }
    names = [n for n, _ in get_sorted_teams(teams)]
    assert names == sorted(names, key=str.casefold)


def test_with_results_by_points():
    a = Team("Альфа")
    b = Team("Бета")
    c = Team("Гамма")
    a.update_stats(1, 0, "Бета")
    b.update_stats(0, 1, "Альфа")
    # Гамма ещё не играла
    teams = {"Гамма": c, "Бета": b, "Альфа": a}
    names = [n for n, _ in get_sorted_teams(teams)]
    assert names[0] == "Альфа"
    assert names[1] == "Гамма"
    assert names[2] == "Бета"
