# -*- coding: utf-8 -*-
"""Слияние league + ЛЧ в common: один игрок — одна строка."""
from __future__ import annotations

from types import SimpleNamespace

from utils.common_db import _key, _merge_bucket_outfield


def _fwd(name, team, pos, *, pid, goals, assists, matches):
    return SimpleNamespace(
        name=name,
        team=team,
        position=pos,
        person_id=pid,
        matches=matches,
        goals=goals,
        assists=assists,
        yellow_cards=0,
        red_cards=0,
        trophies=0,
        golden_balls=0,
        golden_boots=0,
        golden_boys=0,
        overall=80,
        nation=None,
        status=None,
        left_team=False,
    )


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def query(self, _cls):
        return _FakeQuery(self._rows)


def test_common_merge_same_player_different_person_id():
    """Разные person_id в league и ЛЧ не должны давать две строки и двойную сумму."""
    league = _FakeSession(
        [_fwd("Хаверц", "Арсенал", "ФРВ", pid=1795, goals=22, assists=17, matches=29)]
    )
    cl = _FakeSession(
        [_fwd("Хаверц", "Арсенал", "ФРВ", pid=1796, goals=13, assists=9, matches=18)]
    )
    buckets = _merge_bucket_outfield(
        object, league, cl, include_all_cl_teams=True
    )
    assert len(buckets) == 1
    b = next(iter(buckets.values()))
    assert b["goals"] == 35
    assert b["assists"] == 26
    assert b["matches"] == 47


def test_common_merge_skips_duplicate_full_career_copy():
    """Если в cl_synced лежит копия полной карьеры — не удваивать."""
    league = _FakeSession(
        [_fwd("Хаверц", "Арсенал", "ФРВ", pid=1, goals=70, assists=52, matches=94)]
    )
    cl = _FakeSession(
        [_fwd("Хаверц", "Арсенал", "ФРВ", pid=2, goals=70, assists=52, matches=94)]
    )
    buckets = _merge_bucket_outfield(
        object, league, cl, include_all_cl_teams=True
    )
    b = next(iter(buckets.values()))
    assert b["goals"] == 70
    assert b["assists"] == 52
    assert b["matches"] == 94


def test_common_key_ignores_person_id():
    p1 = _fwd("Кейн", "Бавария", "ФРВ", pid=10, goals=1, assists=0, matches=1)
    p2 = _fwd("Кейн", "Бавария", "ФРВ", pid=11, goals=2, assists=1, matches=2)
    assert _key(p1) == _key(p2)
