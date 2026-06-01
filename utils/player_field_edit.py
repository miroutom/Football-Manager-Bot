# -*- coding: utf-8 -*-
"""Правка одного поля строки игрока в нац. БД и ЛЧ + пересборка common."""
from __future__ import annotations

from typing import Any

from sqlalchemy import Integer, String
from sqlalchemy.orm import Session

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.player_identity import (
    merge_row_stats_into,
    merge_same_name_duplicates_in_session,
    register_name_change,
    resolve_canonical_name,
)
from utils.player_transfer import _filter_team, _norm_cmp

_ALL = (Forward, Midfielder, Defender, Goalkeeper)
_TABLE_TO_CLS: dict[str, type] = {
    "forwards": Forward,
    "midfielders": Midfielder,
    "defenders": Defender,
    "goalkeepers": Goalkeeper,
}

_SKIP_FIELDS = frozenset({"id", "ga"})


def find_player_row(
    sess: Session, team: str, name: str, position: str
) -> tuple[type | None, Any]:
    """Точное имя+позиция, иначе единственный игрок с таким именем в клубе."""
    want_n = _norm_cmp(name)
    want_p = _norm_cmp(position)
    by_name: list[tuple[type, Any]] = []
    for Cls in _ALL:
        for r in sess.query(Cls).filter(_filter_team(Cls, team)).all():
            if _norm_cmp(getattr(r, "name", "") or "") != want_n:
                continue
            if _norm_cmp(getattr(r, "position", "") or "") == want_p:
                return Cls, r
            by_name.append((Cls, r))
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        pick = max(
            by_name,
            key=lambda c: (
                int(getattr(c[1], "matches", 0) or 0),
                int(getattr(c[1], "overall", 0) or 0),
                int(getattr(c[1], "id", 0) or 0),
            ),
        )
        return pick
    canon = resolve_canonical_name(team, name)
    if _norm_cmp(canon) != want_n:
        return find_player_row(sess, team, canon, position)
    return None, None


def find_player_row_by_pk(
    sess: Session, table: str, row_id: int
) -> tuple[type | None, Any]:
    Cls = _TABLE_TO_CLS.get((table or "").strip().lower())
    if Cls is None or row_id is None:
        return None, None
    row = sess.get(Cls, int(row_id))
    if row is None:
        return None, None
    return Cls, row


def resolve_player_row(
    sess: Session,
    team: str,
    name: str,
    position: str,
    *,
    table: str | None = None,
    row_id: int | None = None,
) -> tuple[type | None, Any]:
    if table and row_id is not None:
        Cls, row = find_player_row_by_pk(sess, table, row_id)
        if row is not None:
            return Cls, row
    return find_player_row(sess, team, name, position)


def _editable_field_names(Cls: type) -> list[str]:
    out: list[str] = []
    for col in Cls.__table__.columns:
        if col.primary_key or col.name in _SKIP_FIELDS:
            continue
        out.append(col.name)
    out.sort()
    return out


def parse_field_value(Cls: type, field: str, raw: str) -> Any:
    col = Cls.__table__.columns.get(field)
    if col is None:
        raise ValueError(f"Нет поля «{field}» для этой позиции.")
    s = (raw or "").strip()
    if s in ("", "-", "—") and col.nullable:
        return None
    if s in ("", "-", "—") and not col.nullable:
        raise ValueError("Пустое значение для обязательного поля недопустимо.")
    py = getattr(col.type, "python_type", None)
    if py is int or isinstance(col.type, Integer):
        v = int(s)
        if field == "overall":
            return max(1, min(99, v))
        return v
    if py is str or isinstance(col.type, String):
        if field == "position":
            return s.upper()
        if field == "status":
            sl = s.lower()
            if sl not in ("start", "bench", "reserve", ""):
                raise ValueError("status: start | bench | reserve или - для сброса")
            return sl or None
        if field == "name":
            from utils.player_transfer import normalize_player_name_for_db

            return normalize_player_name_for_db(s) or None
        return s or None
    raise ValueError(f"Тип поля «{field}» не поддерживается через бота.")


def _sync_ga_if_needed(row: Any, field: str) -> None:
    if field in ("goals", "assists") and hasattr(row, "ga"):
        row.ga = int(getattr(row, "goals", 0) or 0) + int(getattr(row, "assists", 0) or 0)


def _sync_field_to_cl(
    team: str,
    *,
    field: str,
    val: Any,
    lookup_name: str,
    lookup_pos: str,
    row_id: int | None,
    table: str | None,
) -> int:
    from utils.common_db import _team_in_cl_pool
    from utils.utils import session_cl

    if not _team_in_cl_pool(team):
        return 0
    Cls_c, row_c = resolve_player_row(
        session_cl,
        team,
        lookup_name,
        lookup_pos,
        table=table,
        row_id=row_id,
    )
    if row_c is None:
        return 0
    setattr(row_c, field, val)
    _sync_ga_if_needed(row_c, field)
    session_cl.commit()
    return 1


def apply_player_field_update(
    team: str,
    name: str,
    position: str,
    field: str,
    raw: str,
    *,
    rebuild_common: bool = True,
    row_id: int | None = None,
    table: str | None = None,
) -> dict[str, Any]:
    """
    Обновляет поле в той же строке (по id, если передан).
    Смена имени: алиас + слияние дубля с новым именем; дубли одного имени в клубе схлопываются.
    """
    from utils.common_db import rebuild_common_database
    from utils.squad_roster_sync import find_player_row as find_by_name_only
    from utils.utils import session_league

    field = (field or "").strip()
    if field in _SKIP_FIELDS:
        raise ValueError("Это поле нельзя менять.")

    team_t = (team or "").strip().title()
    Cls_l, row_l = resolve_player_row(
        session_league,
        team_t,
        name,
        position,
        table=table,
        row_id=row_id,
    )
    if row_l is None:
        raise ValueError(
            f"Не найден игрок «{name}» ({position}) в клубе «{team_t}» в нац. лиге."
        )

    old_name = (row_l.name or "").strip().title()
    old_pos = (row_l.position or "").strip().upper()
    val = parse_field_value(Cls_l, field, raw)
    old = getattr(row_l, field, None)
    setattr(row_l, field, val)
    _sync_ga_if_needed(row_l, field)

    merged = 0
    if field == "name":
        new_name = (getattr(row_l, "name", None) or "").strip().title()
        if new_name and _norm_cmp(new_name) != _norm_cmp(old_name):
            register_name_change(team_t, old_name, new_name)
            other, ocls = find_by_name_only(session_league, new_name, team_t)
            if other is not None and int(other.id) != int(row_l.id):
                merge_row_stats_into(row_l, other)
                session_league.delete(other)
                merged += 1
                _sync_ga_if_needed(row_l, field)
    merge_same_name_duplicates_in_session(session_league, team_t, row_l.name or name)

    session_league.commit()

    cl_updated = _sync_field_to_cl(
        team_t,
        field=field,
        val=getattr(row_l, field, None),
        lookup_name=old_name,
        lookup_pos=old_pos,
        row_id=row_id,
        table=table,
    )

    if rebuild_common:
        rebuild_common_database()

    return {
        "field": field,
        "before": old,
        "after": getattr(row_l, field, None),
        "league_table": Cls_l.__tablename__,
        "cl_updated": cl_updated,
        "merged_rows": merged,
        "display_name": (row_l.name or "").strip().title(),
        "display_pos": (row_l.position or "").strip().upper(),
    }


def list_editable_fields_for_player(
    team: str,
    name: str,
    position: str,
    *,
    row_id: int | None = None,
    table: str | None = None,
) -> list[str]:
    from utils.utils import session_league

    Cls, row = resolve_player_row(
        session_league, team, name, position, table=table, row_id=row_id
    )
    if row is None:
        return []
    return _editable_field_names(Cls)
