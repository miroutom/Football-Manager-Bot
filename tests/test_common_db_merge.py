# -*- coding: utf-8 -*-
"""Слияние league + ЛЧ в common по person_id."""
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


def test_common_merge_same_person_id_league_and_cl():
    league = _FakeSession(
        [_fwd("Хаверц", "Арсенал", "ФРВ", pid=105, goals=22, assists=17, matches=29)]
    )
    cl = _FakeSession(
        [_fwd("Хаверц", "Арсенал", "ФРВ", pid=105, goals=13, assists=9, matches=18)]
    )
    buckets = _merge_bucket_outfield(
        object, league, cl, include_all_cl_teams=True
    )
    assert len(buckets) == 1
    b = next(iter(buckets.values()))
    assert b["goals"] == 35
    assert b["assists"] == 26
    assert b["matches"] == 47
    assert b["person_id"] == 105


def test_common_key_uses_person_id():
    p1 = _fwd("Кейн", "Бавария", "ФРВ", pid=10, goals=1, assists=0, matches=1)
    p2 = _fwd("Кейн", "Бавария", "ФРВ", pid=11, goals=2, assists=1, matches=2)
    assert _key(p1) != _key(p2)
