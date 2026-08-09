# -*- coding: utf-8 -*-
"""Заявка клуба: update существующих, не плодить person_id."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from utils.person_registry import lookup_canonical_person_id


def test_lookup_canonical_person_id_from_synced():
    pid = lookup_canonical_person_id("Хаверц", "ФРВ", team="Арсенал")
    assert pid == 105


def test_add_player_skips_cumulative_lookup_when_existing():
    from utils.roster_manual import add_player_to_team_roster

    existing = SimpleNamespace(
        name="Хаверц",
        team="Арсенал",
        position="ФРВ",
        overall=88,
        nation=None,
        person_id=105,
        status="bench",
        left_team=False,
    )

    mock_league = MagicMock()
    mock_cl = MagicMock()

    with (
        patch(
            "utils.player_field_edit.find_player_row",
            return_value=(object, existing),
        ),
        patch("utils.roster_manual._find_rows_cumulative_common") as cum_lookup,
        patch("utils.roster_manual._apply_upsert_and_cascade"),
        patch("utils.common_db.rebuild_common_database"),
        patch("utils.cumulative_mirror.mirror_roster_manual"),
        patch(
            "utils.common_db.resolve_team_name_for_cl_pool",
            return_value=None,
        ),
    ):
        add_player_to_team_roster(
            "Арсенал",
            "Хаверц",
            "ФРВ",
            overall=88,
            status="bench",
            session_league=mock_league,
            session_cl=mock_cl,
            rebuild_common=False,
            mirror_synced=False,
            commit=False,
            skip_status_cascade=True,
            skip_person_lookup=True,
        )

    cum_lookup.assert_not_called()


def test_add_player_updates_existing_without_new_person_id():
    from utils.roster_manual import add_player_to_team_roster

    existing = SimpleNamespace(
        name="Хаверц",
        team="Арсенал",
        position="ФРВ",
        overall=88,
        nation=None,
        person_id=105,
        matches=10,
        goals=5,
        assists=2,
        ga=7,
        status="bench",
        left_team=False,
    )

    mock_league = MagicMock()
    mock_cl = MagicMock()

    with (
        patch(
            "utils.player_field_edit.find_player_row",
            return_value=(object, existing),
        ),
        patch("utils.roster_manual._apply_upsert_and_cascade") as upsert,
        patch("utils.common_db.rebuild_common_database"),
        patch("utils.cumulative_mirror.mirror_roster_manual"),
        patch(
            "utils.common_db.resolve_team_name_for_cl_pool",
            return_value=None,
        ),
    ):
        add_player_to_team_roster(
            "Арсенал",
            "Хаверц",
            "ФРВ",
            overall=88,
            status="start",
            lineup_slot="ST",
            session_league=mock_league,
            session_cl=mock_cl,
            rebuild_common=False,
            mirror_synced=False,
            commit=False,
            skip_status_cascade=True,
        )

    assert upsert.call_count == 1
    args, kwargs = upsert.call_args
    assert args[7] is None  # carry
    assert kwargs["preferred_person_id"] == 105
