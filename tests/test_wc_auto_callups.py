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
