# -*- coding: utf-8 -*-
from config.leagues_config import manager_side_for_team, manager_session_label
from utils.wc_tournament import load_tournament, managers_html


def test_managers_loaded():
    data = load_tournament()
    roman = data["managers"]["Roman"]
    lika = data["managers"]["Lika"]
    assert len(roman) == 24
    assert len(lika) == 24
    assert not (set(roman) & set(lika))
    assert manager_side_for_team("Аргентина") == "roman"
    assert manager_side_for_team("Бразилия") == "lika"
    assert manager_session_label("Аргентина", "Испания") == "Симуляция"
    assert manager_session_label("Аргентина", "Бразилия") == "Игра"
    html = managers_html()
    assert "Roman" in html and "Lika" in html
    assert "Аргентина" in html
