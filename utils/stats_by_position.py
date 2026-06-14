# -*- coding: utf-8 -*-
"""Стата по группам позиций: нападающие, полузащитники, защитники, вратари."""
from __future__ import annotations

import os
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.player_names import player_surname
from utils.utils import defenders, forwards, goalkeepers, midfielders

_OUTFIELD = (Forward, Midfielder, Defender)

GROUP_META: dict[str, dict[str, Any]] = {
    "fwd": {
        "title": "Нападающие",
        "positions": frozenset(forwards),
        "classes": (Forward,),
    },
    "mid": {
        "title": "Полузащитники",
        "positions": frozenset(midfielders),
        "classes": (Midfielder,),
    },
    "def": {
        "title": "Защитники",
        "positions": frozenset(defenders),
        "classes": (Defender,),
    },
    "gk": {
        "title": "Вратари",
        "positions": frozenset(goalkeepers),
        "classes": (Goalkeeper,),
    },
}


def _norm_pos(p: str) -> str:
    return (p or "").strip().upper()


def _norm_team(team: str) -> str:
    return (team or "").strip().casefold()


def _row_identity_key(row: Any) -> tuple:
    from utils.person_registry import row_person_id

    pid = row_person_id(row)
    if pid is not None:
        return ("pid", int(pid))
    sur = (player_surname(row) or getattr(row, "name", "") or "").strip().casefold()
    return ("name", sur)


def _fold_outfield(buckets: dict[tuple, dict], row: Any) -> None:
    pos = _norm_pos(getattr(row, "position", "") or "")
    team = (getattr(row, "team", None) or "").strip()
    if not pos or not team:
        return
    key = (*_row_identity_key(row), pos, _norm_team(team))
    g = int(getattr(row, "goals", 0) or 0)
    a = int(getattr(row, "assists", 0) or 0)
    m = int(getattr(row, "matches", 0) or 0)
    if key not in buckets:
        buckets[key] = {
            "name": (player_surname(row) or getattr(row, "name", "") or "").strip(),
            "team": team,
            "position": pos,
            "matches": 0,
            "goals": 0,
            "assists": 0,
            "ga": 0,
        }
    b = buckets[key]
    b["matches"] += m
    b["goals"] += g
    b["assists"] += a
    b["ga"] += int(getattr(row, "ga", 0) or 0) or (g + a)


def _fold_goalkeeper(buckets: dict[tuple, dict], row: Any) -> None:
    pos = _norm_pos(getattr(row, "position", "") or "")
    team = (getattr(row, "team", None) or "").strip()
    if not pos or not team:
        return
    key = (*_row_identity_key(row), pos, _norm_team(team))
    cs = int(getattr(row, "clean_sheets", 0) or 0)
    m = int(getattr(row, "matches", 0) or 0)
    if key not in buckets:
        buckets[key] = {
            "name": (player_surname(row) or getattr(row, "name", "") or "").strip(),
            "team": team,
            "position": pos,
            "matches": 0,
            "clean_sheets": 0,
        }
    b = buckets[key]
    b["matches"] += m
    b["clean_sheets"] += cs


def _open_scope_session(scope: str) -> tuple[list[Session], list[Any]]:
    """Возвращает (сессии, движки для dispose)."""
    from utils import season_paths

    if scope == "life":
        path = season_paths.get_cumulative_common_db_path()
        if not os.path.isfile(path):
            return [], []
        eng = create_engine(f"sqlite:///{path}")
        return [sessionmaker(bind=eng)()], [eng]
    from utils.utils import session_cl, session_league

    return [session_league, session_cl], []


def collect_group_stats(scope: str, group: str) -> list[dict]:
    """``scope``: ``cur`` (текущий сезон) или ``life`` (за все время)."""
    meta = GROUP_META.get(group)
    if not meta:
        return []
    sessions, engines = _open_scope_session(scope)
    if not sessions:
        return []
    allowed = meta["positions"]
    buckets: dict[tuple, dict] = {}
    try:
        for session in sessions:
            if group == "gk":
                for Cls in meta["classes"]:
                    for row in session.query(Cls).all():
                        if _norm_pos(getattr(row, "position", "") or "") not in allowed:
                            continue
                        _fold_goalkeeper(buckets, row)
            else:
                for Cls in meta["classes"]:
                    for row in session.query(Cls).all():
                        if _norm_pos(getattr(row, "position", "") or "") not in allowed:
                            continue
                        _fold_outfield(buckets, row)
    finally:
        for session in sessions:
            if engines:
                session.close()
        for eng in engines:
            eng.dispose()
    rows = [r for r in buckets.values() if int(r.get("matches", 0) or 0) > 0]
    if group == "gk":
        rows.sort(
            key=lambda r: (
                -int(r.get("clean_sheets", 0) or 0),
                -int(r.get("matches", 0) or 0),
                str(r.get("name") or "").lower(),
            )
        )
    else:
        rows.sort(
            key=lambda r: (
                -int(r.get("ga", 0) or 0),
                -int(r.get("goals", 0) or 0),
                str(r.get("name") or "").lower(),
            )
        )
    return rows


def _scope_label(scope: str) -> str:
    if scope == "life":
        return "за все время"
    from utils.season_paths import get_active_season

    return f"сезон {get_active_season()}"


def _format_outfield_table(rows: list[dict], *, title: str) -> str:
    width = 72
    sep = "=" * width
    lines = ["", sep, f"  {title}", sep]
    if not rows:
        lines.append("  Нет игроков с матчами в этой группе.")
        lines.append(sep)
        lines.append("")
        return "\n".join(lines)
    lines.append(
        f"{'#':<4} {'Игрок':<16} {'Команда':<14} {'Поз':<5} "
        f"{'И':>4} {'Г':>4} {'А':>4} {'Г+А':>5}"
    )
    lines.append("-" * width)
    for i, r in enumerate(rows, 1):
        lines.append(
            f"{i:<4} {r['name']:<16} {r['team']:<14} {r['position']:<5} "
            f"{int(r['matches']):>4} {int(r['goals']):>4} {int(r['assists']):>4} "
            f"{int(r['ga']):>5}"
        )
    lines.append(sep)
    lines.append("")
    return "\n".join(lines)


def _format_goalkeeper_table(rows: list[dict], *, title: str) -> str:
    width = 60
    sep = "=" * width
    lines = ["", sep, f"  {title}", sep]
    if not rows:
        lines.append("  Нет вратарей с матчами.")
        lines.append(sep)
        lines.append("")
        return "\n".join(lines)
    lines.append(
        f"{'#':<4} {'Игрок':<18} {'Команда':<16} {'И':>4} {'Сух.':>5}"
    )
    lines.append("-" * width)
    for i, r in enumerate(rows, 1):
        lines.append(
            f"{i:<4} {r['name']:<18} {r['team']:<16} "
            f"{int(r['matches']):>4} {int(r['clean_sheets']):>5}"
        )
    lines.append(sep)
    lines.append("")
    return "\n".join(lines)


def format_group_stats(scope: str, group: str) -> str:
    meta = GROUP_META.get(group)
    if not meta:
        return "Неизвестная группа позиций."
    rows = collect_group_stats(scope, group)
    title = f"{meta['title']} · {_scope_label(scope)} · лига + ЛЧ"
    if group == "gk":
        return _format_goalkeeper_table(rows, title=title)
    return _format_outfield_table(rows, title=title)
