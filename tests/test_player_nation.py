# -*- coding: utf-8 -*-
from utils.player_nation import (
    nation_to_flagcdn_code,
    normalize_nation_label,
    normalize_player_nation_for_db,
    resolve_player_nation,
)


def test_usa_aliases_map_to_same_flag():
    for raw in ("США", "сша", "Сша"):
        assert normalize_nation_label(raw) == "США"
        assert nation_to_flagcdn_code(raw) == "us"
        assert normalize_player_nation_for_db(raw) == "США"


def test_ivory_coast_variants_map_to_same_country():
    variants = (
        "Кот-Д'Ивуар",
        "Кот-д'Ивуар",
        "Кот-Д\u2019Ивуар",
        "кот-д'ивуар",
    )
    canon = normalize_player_nation_for_db("Кот-д'Ивуар")
    assert canon
    for raw in variants:
        assert nation_to_flagcdn_code(raw) == "ci"
        assert normalize_player_nation_for_db(raw) == canon


def test_kafu_resolves_brazil():
    assert resolve_player_nation("Кафу", "Рома", None) == "Бразилия"
    assert nation_to_flagcdn_code(resolve_player_nation("Кафу", "Рома", None)) == "br"
    assert resolve_player_nation("Пеле", "Сити", None) == "Бразилия"
    assert resolve_player_nation("Роналдиньо", "Интер", None) == "Бразилия"


def test_seedorf_resolves_netherlands():
    assert resolve_player_nation("Зидорф", "Фиорентина", None) == "Нидерланды"
    assert nation_to_flagcdn_code(resolve_player_nation("Зидорф", "Фиорентина", None)) == "nl"
