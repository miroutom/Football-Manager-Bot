# -*- coding: utf-8 -*-
"""Один игрок + один клуб = одна строка; смена позиции — update/move, не insert."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from data.forward import Forward
from data.midfielder import Midfielder
from utils.person_registry import (
    lookup_canonical_person_id,
    lookup_canonical_person_id_by_team,
)
from utils.player_names import player_name_identity_token
from utils.squad_roster_sync import (
    _dedupe_player_rows_for_team,
    upsert_roster_player,
)


def test_player_name_identity_token_from_string():
    assert player_name_identity_token("Муриэль") == "Муриэль"
    assert player_name_identity_token("Габриэль Жезус") == "Жезус"


@pytest.mark.skipif(
    not os.path.isfile("db/common_synced.db"),
    reason="common_synced.db not present",
)
def test_lookup_by_team_finds_muriel_across_positions():
    pid_old = lookup_canonical_person_id("Муриэль", "ЛФА", team="Аталанта")
    pid_team = lookup_canonical_person_id_by_team("Муриэль", team="Аталанта")
    assert pid_team is not None
    assert pid_team == 60
    assert pid_old == 60


def test_dedupe_keeps_one_row_not_insert():
    """Два дубля в клубе → остаётся одна строка, не None."""
    row_stats = SimpleNamespace(
        id=10,
        name="Муриэль",
        team="Аталанта",
        position="ЛФА",
        person_id=60,
        matches=10,
        goals=8,
        assists=2,
        ga=10,
        trophies=0,
        golden_balls=0,
        golden_boots=0,
        golden_boys=0,
    )
    row_empty = SimpleNamespace(
        id=99,
        name="Муриэль",
        team="Аталанта",
        position="ПФА",
        person_id=3384,
        matches=0,
        goals=0,
        assists=0,
        ga=0,
        trophies=0,
        golden_balls=0,
        golden_boots=0,
        golden_boys=0,
    )
    session = MagicMock()

    with patch(
        "utils.squad_roster_sync._all_rows_same_player",
        return_value=[(row_stats, Forward), (row_empty, Forward)],
    ):
        keep, cls, carry, pid = _dedupe_player_rows_for_team(session, "Муриэль", "Аталанта")

    assert keep is row_stats
    assert cls is Forward
    assert carry is None
    assert pid == 60
    assert row_stats.goals == 8
    session.delete.assert_called_once_with(row_empty)
    session.flush.assert_called_once()


def test_upsert_position_change_keeps_person_id():
    old_row = SimpleNamespace(
        name="Симонс",
        team="Аталанта",
        position="ЦАП",
        overall=83,
        nation=None,
        person_id=347,
        matches=9,
        goals=3,
        assists=3,
        ga=6,
        trophies=0,
        golden_balls=0,
        golden_boots=0,
        golden_boys=0,
        yellow_cards=0,
        red_cards=0,
        status="start",
        left_team=False,
        lineup_slot=None,
    )
    session = MagicMock()
    session.add = MagicMock()
    session.delete = MagicMock()
    session.flush = MagicMock()

    with patch(
        "utils.squad_roster_sync._resolve_roster_row",
        return_value=(old_row, Midfielder, None, 347),
    ):
        result = upsert_roster_player(
            session,
            team="Аталанта",
            name="Симонс",
            position="ЛФА",
            overall=83,
            nation=None,
            status="start",
        )

    assert result == "moved"
    session.delete.assert_called_once_with(old_row)
    added = session.add.call_args[0][0]
    assert isinstance(added, Forward)
    assert added.person_id == 347


def test_upsert_existing_row_updates_position_no_insert():
    row = SimpleNamespace(
        name="Муриэль",
        team="Аталанта",
        position="ЛФА",
        overall=85,
        nation=None,
        person_id=60,
        matches=5,
        goals=2,
        assists=1,
        ga=3,
        status="bench",
        left_team=False,
        lineup_slot=None,
    )
    session = MagicMock()
    session.add = MagicMock()

    with (
        patch(
            "utils.squad_roster_sync._resolve_roster_row",
            return_value=(row, Forward, None, 60),
        ),
        patch(
            "utils.person_registry.lookup_canonical_person_id_by_team",
            return_value=60,
        ),
    ):
        result = upsert_roster_player(
            session,
            team="Аталанта",
            name="Муриэль",
            position="ПФА",
            overall=85,
            nation=None,
            status="bench",
        )

    assert result == "updated"
    assert row.position == "ПФА"
    session.add.assert_not_called()
