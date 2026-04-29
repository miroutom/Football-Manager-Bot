# -*- coding: utf-8 -*-
"""
Синхронизация заявки команды: overall, nation, position, status; удаление лишних игроков;
вставка отсутствующих строк. Скрипт: ``scripts/sync_england_apl_rosters.py``.

Полный прогон АПЛ по умолчанию пишет в ``league_new.db`` и (только для клубов из пула ЛЧ —
``_team_in_cl_pool``, те же ключи что ``teams_champ_league`` / участники из ``get_cl_participants``)
в ``champions_league_new.db``, затем при необходимости пересобирает ``common.db``.

Статусы в БД: ``start`` | ``bench`` | ``reserve``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import func, or_

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.common_db import _team_in_cl_pool
from utils.utils import defenders, forwards, get_session, goalkeepers, midfielders

_ALL_PLAYER = (Forward, Midfielder, Defender, Goalkeeper)


def _filter_team(Cls, team: str):
    """
    Кириллица: SQLite lower() буквы не понижает, поэтому вместо одного
    func.lower(Cls.team) == python_lower(team) сравниваем ещё и по точной строке клуба.
    """
    t = (team or "").strip()
    tl = t.lower()
    return or_(Cls.team == t, func.lower(Cls.team) == tl)


def _cls_for_position(position: str) -> type:
    pos = (position or "").strip().upper()
    if pos in forwards:
        return Forward
    if pos in midfielders:
        return Midfielder
    if pos in defenders:
        return Defender
    return Goalkeeper


def find_player_row(session, name: str, team: str) -> tuple[Any, type | None]:
    nl = (name or "").strip().lower()
    for Cls in _ALL_PLAYER:
        for r in session.query(Cls).filter(_filter_team(Cls, team)).all():
            if (r.name or "").strip().lower() == nl:
                return r, Cls
    return None, None


def _all_rows_same_player(session, name: str, team: str) -> list[tuple[Any, type]]:
    nl = (name or "").strip().lower()
    out: list[tuple[Any, type]] = []
    for Cls in _ALL_PLAYER:
        for r in session.query(Cls).filter(_filter_team(Cls, team)).all():
            if (r.name or "").strip().lower() == nl:
                out.append((r, Cls))
    return out


def _merge_carry_dicts(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Суммирует статистику из двух carry-словарей (рейтинг — по матчам взвешенно)."""
    m1 = int(a.get("matches", 0) or 0)
    m2 = int(b.get("matches", 0) or 0)
    mt = m1 + m2
    r1 = float(a.get("rating", 0) or 0)
    r2 = float(b.get("rating", 0) or 0)
    rt = (r1 * m1 + r2 * m2) / mt if mt else 0.0
    out: dict[str, Any] = {
        "matches": mt,
        "rating": rt,
        "trophies": int(a.get("trophies", 0) or 0) + int(b.get("trophies", 0) or 0),
        "golden_balls": int(a.get("golden_balls", 0) or 0) + int(b.get("golden_balls", 0) or 0),
    }
    for k in (
        "goals",
        "assists",
        "ga",
        "golden_boots",
        "golden_boys",
        "golden_gloves",
        "clean_sheets",
        "missed_goals",
    ):
        if k in a or k in b:
            out[k] = int(a.get(k, 0) or 0) + int(b.get(k, 0) or 0)
    return out


def _dedupe_player_rows_for_team(
    session, name: str, team: str
) -> tuple[Any, type | None, dict[str, Any] | None]:
    """
    Одна строка на игрока+клуб. Если в БД несколько дублей — удаляем все и возвращаем
    объединённый carry, чтобы вставка не обнуляла статистику.
    """
    found = _all_rows_same_player(session, name, team)
    if not found:
        return None, None, None
    if len(found) == 1:
        r, c = found[0]
        return r, c, None
    merged: dict[str, Any] | None = None
    for r, _Cls in found:
        c = _carry_from_row(r)
        merged = c if merged is None else _merge_carry_dicts(merged, c)
        session.delete(r)
    session.flush()
    return None, None, merged


def _new_player_kwargs(
    tgt_cls: type,
    *,
    name: str,
    team: str,
    position: str,
    overall: int,
    nation: str | None,
    status: str,
    carry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pos = position.strip().upper()
    st = status.strip().lower()
    c = carry or {}
    kw: dict[str, Any] = dict(
        name=name,
        team=team,
        position=pos,
        overall=int(overall),
        nation=(nation.strip() if nation else None) or None,
        status=st,
        matches=int(c.get("matches", 0) or 0),
        rating=float(c.get("rating", 0) or 0),
        trophies=int(c.get("trophies", 0) or 0),
        golden_balls=int(c.get("golden_balls", 0) or 0),
    )
    kw["golden_boys"] = int(c.get("golden_boys", 0) or 0)
    if tgt_cls is Forward:
        kw.update(
            goals=int(c.get("goals", 0) or 0),
            assists=int(c.get("assists", 0) or 0),
            ga=int(c.get("ga", 0) or 0),
            golden_boots=int(c.get("golden_boots", 0) or 0),
        )
    elif tgt_cls is Midfielder:
        kw.update(
            goals=int(c.get("goals", 0) or 0),
            assists=int(c.get("assists", 0) or 0),
            ga=int(c.get("ga", 0) or 0),
            golden_boots=int(c.get("golden_boots", 0) or 0),
        )
    elif tgt_cls is Defender:
        kw.update(
            goals=int(c.get("goals", 0) or 0),
            assists=int(c.get("assists", 0) or 0),
            ga=int(c.get("ga", 0) or 0),
            clean_sheets=int(c.get("clean_sheets", 0) or 0),
            golden_boots=int(c.get("golden_boots", 0) or 0),
        )
    else:
        kw.update(
            clean_sheets=int(c.get("clean_sheets", 0) or 0),
            missed_goals=int(c.get("missed_goals", 0) or 0),
            golden_boots=int(c.get("golden_boots", 0) or 0),
            golden_gloves=int(c.get("golden_gloves", 0) or 0),
        )
    return kw


def _carry_from_row(row: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "matches": getattr(row, "matches", 0),
        "rating": getattr(row, "rating", 0.0),
        "trophies": getattr(row, "trophies", 0),
        "golden_balls": getattr(row, "golden_balls", 0),
    }
    if hasattr(row, "goals"):
        out["goals"] = getattr(row, "goals", 0)
        out["assists"] = getattr(row, "assists", 0)
        out["ga"] = getattr(row, "ga", 0)
    if hasattr(row, "golden_boots"):
        out["golden_boots"] = getattr(row, "golden_boots", 0)
    if hasattr(row, "golden_boys"):
        out["golden_boys"] = getattr(row, "golden_boys", 0)
    if hasattr(row, "clean_sheets") and not hasattr(row, "goals"):
        out["clean_sheets"] = getattr(row, "clean_sheets", 0)
    elif hasattr(row, "clean_sheets"):
        out["clean_sheets"] = getattr(row, "clean_sheets", 0)
    if hasattr(row, "missed_goals"):
        out["missed_goals"] = getattr(row, "missed_goals", 0)
    if hasattr(row, "golden_gloves"):
        out["golden_gloves"] = getattr(row, "golden_gloves", 0)
    return out


def upsert_roster_player(
    session,
    *,
    team: str,
    name: str,
    position: str,
    overall: int,
    nation: str | None,
    status: str,
) -> str:
    st = status.strip().lower()
    if st not in ("start", "bench", "reserve"):
        raise ValueError(f"status must be start|bench|reserve, got {status!r}")

    tgt_cls = _cls_for_position(position)
    row, cur_cls, dedupe_carry = _dedupe_player_rows_for_team(session, name, team)
    pos_u = position.strip().upper()

    if row is None:
        session.add(
            tgt_cls(
                **_new_player_kwargs(
                    tgt_cls,
                    name=name,
                    team=team,
                    position=pos_u,
                    overall=overall,
                    nation=nation,
                    status=st,
                    carry=dedupe_carry,
                )
            )
        )
        return "inserted"

    if cur_cls is not tgt_cls:
        carry = _carry_from_row(row)
        session.delete(row)
        session.flush()
        session.add(
            tgt_cls(
                **_new_player_kwargs(
                    tgt_cls,
                    name=(row.name or name).strip(),
                    team=team,
                    position=pos_u,
                    overall=overall,
                    nation=nation,
                    status=st,
                    carry=carry,
                )
            )
        )
        return "moved"

    row.position = pos_u
    row.overall = int(overall)
    row.nation = (nation.strip() if nation else None) or None
    row.status = st
    return "updated"


def delete_team_players_not_in_names(session, team: str, roster_names: set[str]) -> int:
    nset = {n.strip().lower() for n in roster_names}
    deleted = 0
    for Cls in _ALL_PLAYER:
        for r in session.query(Cls).filter(_filter_team(Cls, team)).all():
            if (r.name or "").strip().lower() not in nset:
                session.delete(r)
                deleted += 1
    return deleted


def sync_team_roster(
    session,
    team: str,
    rows: list[tuple[str, str, int, str | None, str]],
    *,
    prune: bool = True,
) -> dict[str, int]:
    stats: dict[str, int] = {"inserted": 0, "updated": 0, "moved": 0, "deleted": 0}
    names = {r[0] for r in rows}
    if prune:
        stats["deleted"] = delete_team_players_not_in_names(session, team, names)
    for name, position, overall, nation, status in rows:
        k = upsert_roster_player(
            session,
            team=team,
            name=name,
            position=position,
            overall=overall,
            nation=nation,
            status=status,
        )
        stats[k] += 1
    return stats


RosterRow = tuple[str, str, int, Optional[str], str]


def run_squads_sync(
    squads: dict[str, list[RosterRow]],
    *,
    label: str = "squads",
    tournaments: tuple[str, ...] | None = None,
    rebuild_common: bool = True,
) -> dict[str, dict[str, dict[str, int]]]:
    """
    Миграция ``status`` во все SQLite (лига + ЛЧ + common), затем синк переданного словаря заявок.

    Для ``cl`` — только команды из ``_team_in_cl_pool`` (участники ЛЧ).
    """
    from utils.migrate_player_status import migrate_all_player_status_columns

    migrate_all_player_status_columns()
    if not squads:
        raise RuntimeError(f"Словарь заявок пуст ({label}).")

    keys = tournaments if tournaments is not None else ("league", "cl")
    out: dict[str, dict[str, dict[str, int]]] = {}
    for tkey in keys:
        session = get_session(tkey)
        per_team: dict[str, dict[str, int]] = {}
        for team, rows in squads.items():
            if tkey in ("cl", "champ_league") and not _team_in_cl_pool(team):
                continue
            per_team[team] = sync_team_roster(session, team, rows, prune=True)
        session.commit()
        out[tkey] = per_team
    if rebuild_common:
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
    return out


def run_full_england_sync(
    *,
    tournaments: tuple[str, ...] | None = None,
    rebuild_common: bool = True,
) -> dict[str, dict[str, dict[str, int]]]:
    from data.england_apl_squads import ENGLAND_APL_SQUADS

    return run_squads_sync(
        ENGLAND_APL_SQUADS,
        label="ENGLAND_APL_SQUADS",
        tournaments=tournaments,
        rebuild_common=rebuild_common,
    )


def run_bundesliga_sync(
    *,
    tournaments: tuple[str, ...] | None = None,
    rebuild_common: bool = True,
) -> dict[str, dict[str, dict[str, int]]]:
    from data.germany_bundesliga_squads import GERMANY_BUNDESLIGA_SQUADS

    return run_squads_sync(
        GERMANY_BUNDESLIGA_SQUADS,
        label="GERMANY_BUNDESLIGA_SQUADS",
        tournaments=tournaments,
        rebuild_common=rebuild_common,
    )


def run_italy_seria_sync(
    *,
    tournaments: tuple[str, ...] | None = None,
    rebuild_common: bool = True,
) -> dict[str, dict[str, dict[str, int]]]:
    from data.italy_seria_a_squads import ITALY_SERIE_A_SQUADS

    return run_squads_sync(
        ITALY_SERIE_A_SQUADS,
        label="ITALY_SERIE_A_SQUADS",
        tournaments=tournaments,
        rebuild_common=rebuild_common,
    )


def run_spain_la_liga_sync(
    *,
    tournaments: tuple[str, ...] | None = None,
    rebuild_common: bool = True,
) -> dict[str, dict[str, dict[str, int]]]:
    from data.spain_la_liga_squads import SPAIN_LA_LIGA_SQUADS

    return run_squads_sync(
        SPAIN_LA_LIGA_SQUADS,
        label="SPAIN_LA_LIGA_SQUADS",
        tournaments=tournaments,
        rebuild_common=rebuild_common,
    )


def run_russia_rpl_sync(
    *,
    tournaments: tuple[str, ...] | None = None,
    rebuild_common: bool = True,
) -> dict[str, dict[str, dict[str, int]]]:
    from data.russia_rpl_squads import RUSSIA_RPL_SQUADS

    return run_squads_sync(
        RUSSIA_RPL_SQUADS,
        label="RUSSIA_RPL_SQUADS",
        tournaments=tournaments,
        rebuild_common=rebuild_common,
    )
