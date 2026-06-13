# -*- coding: utf-8 -*-
from utils.lineup_slot import is_valid_lineup_slot, normalize_lineup_slot
from utils.roster_manual import parse_squad_declaration_text


def test_parse_start_with_slot():
    text = """==== start ===
Рамсдейл GK ВРТ 84
Габриэль Жезус RW ПФА 85
=== bench ===
Райа ВРТ 80
"""
    entries, errs = parse_squad_declaration_text(text)
    assert not errs
    assert len(entries) == 3
    assert entries[0][5] == "GK"
    assert entries[1][5] == "RW"
    assert entries[2][5] is None


def test_normalize_lineup_slot():
    assert normalize_lineup_slot("rcb") == "RCB"
    assert is_valid_lineup_slot("CAM")
