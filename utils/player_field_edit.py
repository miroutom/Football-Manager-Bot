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
from utils.player_transfer import _filter_team, _norm_cmp

_ALL = (Forward, Midfielder, Defender, Goalkeeper)

_SKIP_FIELDS = frozenset({"id", "ga"})


def find_player_row(
    sess: Session, team: str, name: str, position: str
) -> tuple[type | None, Any]:
    want_n = _norm_cmp(name)
    want_p = _norm_cmp(position)
    for Cls in _ALL:
        for r in sess.query(Cls).filter(_filter_team(Cls, team)).all():
            if _norm_cmp(getattr(r, "name", "") or "") != want_n:
                continue
            if _norm_cmp(getattr(r, "position", "") or "") != want_p:
                continue
            return Cls, r
    return None, None


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


def apply_player_field_update(
    team: str,
    name: str,
    position: str,
    field: str,
    raw: str,
    *,
    rebuild_common: bool = True,
) -> dict[str, Any]:
    """Обновляет поле в session_league и session_cl (если строка есть), коммитит, пересобирает common."""
    from utils.common_db import rebuild_common_database, _team_in_cl_pool
    from utils.utils import session_cl, session_league

    field = (field or "").strip()
    if field in _SKIP_FIELDS:
        raise ValueError("Это поле нельзя менять.")

    Cls_l, row_l = find_player_row(session_league, team, name, position)
    if row_l is None:
        raise ValueError(
            f"Не найден игрок «{name}» ({position}) в клубе «{team}» в нац. лиге."
        )
    val = parse_field_value(Cls_l, field, raw)
    old = getattr(row_l, field, None)
    setattr(row_l, field, val)
    _sync_ga_if_needed(row_l, field)
    session_league.commit()

    cl_updated = 0
    if _team_in_cl_pool(team):
        Cls_c, row_c = find_player_row(session_cl, team, name, position)
        if row_c is not None:
            setattr(row_c, field, val)
            _sync_ga_if_needed(row_c, field)
            session_cl.commit()
            cl_updated = 1

    if rebuild_common:
        rebuild_common_database()

    return {
        "field": field,
        "before": old,
        "after": getattr(row_l, field, None),
        "league_table": Cls_l.__tablename__,
        "cl_updated": cl_updated,
    }


def list_editable_fields_for_player(team: str, name: str, position: str) -> list[str]:
    from utils.utils import session_league

    Cls, row = find_player_row(session_league, team, name, position)
    if row is None:
        return []
    return _editable_field_names(Cls)
