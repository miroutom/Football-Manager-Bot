# -*- coding: utf-8 -*-
from bot.squad_pitch import _Pl, _dedupe_squad_pl_by_name, load_team_squad_players


def test_dedupe_keeps_two_silvas_at_city():
    rows = [
        _Pl(name="Сильва", position="ЦЗ", overall=88, tags=frozenset(), score=88, nation=None, status="start", person_id=773),
        _Pl(name="Сильва", position="ЦП", overall=85, tags=frozenset(), score=85, nation=None, status="bench", person_id=278),
    ]
    out = _dedupe_squad_pl_by_name(rows)
    assert len(out) == 2
    positions = sorted(p.position for p in out)
    assert positions == ["ЦЗ", "ЦП"]


def test_dedupe_merges_same_person_id():
    rows = [
        _Pl(name="Сильва", position="ЦЗ", overall=88, tags=frozenset(), score=88, nation=None, status="start", person_id=773),
        _Pl(name="Сильва", position="ЦЗ", overall=88, tags=frozenset(), score=88, nation=None, status="bench", person_id=773),
    ]
    out = _dedupe_squad_pl_by_name(rows)
    assert len(out) == 1
    assert out[0].status == "start"


def test_city_export_includes_both_silvas():
    players = load_team_squad_players("Сити", "league")
    silvas = [p for p in players if p.name == "Сильва"]
    assert len(silvas) == 2
