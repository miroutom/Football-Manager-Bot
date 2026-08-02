# -*- coding: utf-8 -*-
"""Правка существующего игрока (клуб / FA) из Transfer Window App."""
from __future__ import annotations

from typing import Any

from utils.free_agents_db import (
    fa_player_id,
    is_free_agent_team,
    update_free_agent_player_fields,
)
from utils.roster_manual import FREE_AGENT_TEAM
from utils.player_field_edit import apply_player_field_update, find_player_row
from utils.player_nicknames import get_nickname, set_nickname
from utils.person_registry import lookup_canonical_person_id_by_team
from utils.utils import session_league


def _resolve_person_id(
    *,
    team: str,
    name: str,
    position: str,
    person_id: int | None,
    is_fa: bool,
) -> int | None:
    if person_id and int(person_id) > 0:
        return int(person_id)
    if is_fa:
        return lookup_canonical_person_id_by_team(name, team=FREE_AGENT_TEAM)
    _, row = find_player_row(session_league, team, name, position)
    if row is not None and getattr(row, "person_id", None):
        try:
            pid = int(row.person_id)
            return pid if pid > 0 else None
        except (TypeError, ValueError):
            pass
    return lookup_canonical_person_id_by_team(name, team=team)


def update_existing_player(
    *,
    team: str,
    name: str,
    position: str,
    person_id: int | None = None,
    new_name: str | None = None,
    new_position: str | None = None,
    new_overall: int | None = None,
    new_nation: str | None = None,
    nation_set: bool = False,
    nickname: str | None = None,
    nickname_set: bool = False,
) -> dict[str, Any]:
    """
    Обновить поля существующей строки в БД (league + CL или FA).
    Новые записи не создаются.
    """
    team_raw = (team or "").strip()
    is_fa = is_free_agent_team(team_raw) or team_raw == "Free Agent"
    team_db = FREE_AGENT_TEAM if is_fa else team_raw.title()

    cur_name = (name or "").strip()
    cur_pos = (position or "").strip().upper()
    if not cur_name or not cur_pos:
        raise ValueError("Нужны имя и позиция.")

    pid = _resolve_person_id(
        team=team_db,
        name=cur_name,
        position=cur_pos,
        person_id=person_id,
        is_fa=is_fa,
    )

    nation_clear = nation_set and not (new_nation or "").strip()

    if is_fa:
        row = update_free_agent_player_fields(
            cur_name,
            cur_pos,
            new_name=new_name,
            new_position=new_position,
            new_overall=new_overall,
            new_nation=new_nation if nation_set and not nation_clear else None,
            nation_clear=nation_clear,
            person_id=pid,
        )
        cur_name = row["name"]
        cur_pos = row["position"]
    else:
        updates: list[tuple[str, str]] = []
        if new_name is not None and str(new_name).strip() and str(new_name).strip() != cur_name:
            updates.append(("name", str(new_name).strip()))
        if (
            new_position is not None
            and str(new_position).strip().upper()
            and str(new_position).strip().upper() != cur_pos
        ):
            updates.append(("position", str(new_position).strip().upper()))
        if new_overall is not None:
            updates.append(("overall", str(int(new_overall))))
        if nation_set:
            updates.append(("nation", (new_nation or "").strip() or "-"))

        for i, (field, raw) in enumerate(updates):
            apply_player_field_update(
                team_db,
                cur_name,
                cur_pos,
                field,
                raw,
                rebuild_common=(i == len(updates) - 1),
            )
            if field == "name":
                cur_name = str(raw).strip()
            elif field == "position":
                cur_pos = str(raw).strip().upper()

        if not updates:
            from utils.common_db import rebuild_common_database

            rebuild_common_database()

        _, row_obj = find_player_row(session_league, team_db, cur_name, cur_pos)
        if row_obj is not None and getattr(row_obj, "person_id", None):
            try:
                pid = int(row_obj.person_id) if int(row_obj.person_id) > 0 else pid
            except (TypeError, ValueError):
                pass
        row = {
            "id": f"{team_db}|{cur_name}|{cur_pos}",
            "person_id": pid,
            "name": cur_name,
            "position": cur_pos,
            "overall": int(getattr(row_obj, "overall", 0) or 0) if row_obj else int(new_overall or 0),
            "nation": (getattr(row_obj, "nation", None) or "") or "",
            "team": team_db,
            "is_fa": False,
        }

    if nickname_set and pid and int(pid) > 0:
        set_nickname(
            int(pid),
            nickname or "",
            name=cur_name,
            team=team_db,
        )

    nick = get_nickname(pid) if pid else None
    return {
        "ok": True,
        "player": {
            **row,
            "nickname": nick or "",
            "id": row.get("id") or fa_player_id(cur_name, cur_pos),
        },
        "person_id": pid,
        "old_id": f"{team_raw if is_fa else team_db}|{(name or '').strip()}|{(position or '').strip().upper()}",
        "new_id": row.get("id") or fa_player_id(cur_name, cur_pos),
    }
