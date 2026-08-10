# -*- coding: utf-8 -*-
from utils.wc_auto_callups import build_auto_callup_roster
from utils.wc_squad_app import wc_roster_from_nation_team, nation_team_template
from utils.wc_squad_quota import evaluate_wc_squad, WC_TOTAL


def test_auto_callup_picks_by_position():
    players = [
        {"name": "Вратарь1", "club": "A", "position": "ВРТ", "overall": 80},
        {"name": "Вратарь2", "club": "B", "position": "ВРТ", "overall": 75},
        {"name": "Левый", "club": "C", "position": "ЛЗ", "overall": 78},
        {"name": "Правый", "club": "D", "position": "ПЗ", "overall": 77},
        {"name": "ЦЗ1", "club": "E", "position": "ЦЗ", "overall": 82},
        {"name": "ЦЗ2", "club": "F", "position": "ЦЗ", "overall": 81},
        {"name": "ЦП1", "club": "G", "position": "ЦП", "overall": 79},
        {"name": "ЦП2", "club": "H", "position": "ЦП", "overall": 78},
        {"name": "ЦАП", "club": "I", "position": "ЦАП", "overall": 83},
        {"name": "ЛФА", "club": "J", "position": "ЛФА", "overall": 84},
        {"name": "ПФА", "club": "K", "position": "ПФА", "overall": 85},
        {"name": "ФРВ", "club": "L", "position": "ФРВ", "overall": 86},
    ]
    roster = build_auto_callup_roster("Испания", players)
    starts = {r["lineup_slot"]: r["name"] for r in roster if r.get("status") == "start"}
    assert starts["GK"] == "Вратарь1"
    assert starts["LB"] == "Левый"
    assert starts["RB"] == "Правый"
    assert starts["ST"] == "ФРВ"
    team = nation_team_template("Испания", roster=roster)
    ev = evaluate_wc_squad(wc_roster_from_nation_team(team))
    assert ev["start_filled"] == 11
    assert ev["gk_start"] == 1


def test_auto_callup_allows_short_squad():
    players = [
        {"name": "Вратарь", "club": "A", "position": "ВРТ", "overall": 80},
        {"name": "Защитник", "club": "B", "position": "ЦЗ", "overall": 75},
    ]
    roster = build_auto_callup_roster("Мальта", players)
    assert len(roster) <= WC_TOTAL


def test_auto_callup_balanced_bench_and_reserve():
    players = [
        {"name": "GK1", "club": "A", "position": "ВРТ", "overall": 85},
        {"name": "GK2", "club": "B", "position": "ВРТ", "overall": 70},
        {"name": "LB1", "club": "C", "position": "ЛЗ", "overall": 82},
        {"name": "LB2", "club": "D", "position": "ЛЗ", "overall": 60},
        {"name": "CB1", "club": "E", "position": "ЦЗ", "overall": 84},
        {"name": "CB2", "club": "F", "position": "ЦЗ", "overall": 61},
        {"name": "RB1", "club": "G", "position": "ПЗ", "overall": 83},
        {"name": "CM1", "club": "H", "position": "ЦП", "overall": 81},
        {"name": "CM2", "club": "I", "position": "ЦП", "overall": 62},
        {"name": "CAM1", "club": "J", "position": "ЦАП", "overall": 80},
        {"name": "LW1", "club": "K", "position": "ЛФА", "overall": 79},
        {"name": "RW1", "club": "L", "position": "ПФА", "overall": 78},
        {"name": "ST1", "club": "M", "position": "ФРВ", "overall": 86},
        {"name": "ST2", "club": "N", "position": "ФРВ", "overall": 63},
        {"name": "STAR", "club": "O", "position": "ЦП", "overall": 90},
        {"name": "X1", "club": "P", "position": "ЛЦЗ", "overall": 59},
        {"name": "X2", "club": "Q", "position": "ПЦЗ", "overall": 58},
        {"name": "X3", "club": "R", "position": "ЦОП", "overall": 57},
        {"name": "X4", "club": "S", "position": "ЛП", "overall": 56},
        {"name": "X5", "club": "T", "position": "ПП", "overall": 55},
        {"name": "X6", "club": "U", "position": "ЛЦП", "overall": 54},
        {"name": "X7", "club": "V", "position": "ПЦП", "overall": 53},
        {"name": "X8", "club": "W", "position": "ЦФД", "overall": 52},
        {"name": "X9", "club": "X", "position": "ЛФД", "overall": 51},
        {"name": "X10", "club": "Y", "position": "ПФД", "overall": 50},
        {"name": "X11", "club": "Z", "position": "ЛФЗ", "overall": 49},
    ]
    roster = build_auto_callup_roster("Испания", players)
    bench = [r for r in roster if r.get("status") == "bench"]
    reserve = [r for r in roster if r.get("status") == "reserve"]
    assert len(bench) == 7
    assert len(reserve) == 8
    assert any(r["name"] == "GK2" and r["position"] == "ВРТ" for r in bench)
    picked = {r["name"] for r in bench + reserve}
    assert "LB2" in picked
    assert "STAR" in picked
