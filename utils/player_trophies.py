# -*- coding: utf-8 -*-
"""
Трофеи игроков: пересчёт ``trophies`` в сезонных БД по ``season_history.json``.

В архиве сезона в ``trophies`` хранится прирост за этот сезон (0 или 1+),
в ``*_synced.db`` — сумма по сезонам.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any

from bot.season_history_store import load_history
from utils import season_paths

PLAYER_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")


def _norm(s: str) -> str:
    return (s or "").strip().casefold()


def season_tournament_db_path(season_num: int, *, cl: bool) -> str | None:
    active = int(season_paths.get_active_season())
    if season_num == active:
        path = (
            season_paths.get_cl_db_path()
            if cl
            else season_paths.get_league_db_path()
        )
        return path if os.path.isfile(path) else None
    fname = season_paths.SEASON_CL_NAME if cl else season_paths.SEASON_LEAGUE_NAME
    path = os.path.join(season_paths.season_archive_directory(season_num), fname)
    return path if os.path.isfile(path) else None


def _distinct_teams_in_db(db_path: str) -> list[str]:
    names: set[str] = set()
    conn = sqlite3.connect(db_path)
    try:
        for tbl in PLAYER_TABLES:
            try:
                cur = conn.execute(
                    f"SELECT DISTINCT team FROM {tbl} "
                    f"WHERE team IS NOT NULL AND trim(team) != ''"
                )
            except sqlite3.OperationalError:
                continue
            for (tm,) in cur:
                s = str(tm or "").strip()
                if s:
                    names.add(s)
    finally:
        conn.close()
    return sorted(names, key=lambda x: x.casefold())


def teams_matching_winner(db_path: str, winner: str) -> list[str]:
    """Клуб(ы) в БД, которым засчитывается титул (точное имя или «Атлетик»⊂«Атлетико»)."""
    if not db_path or not os.path.isfile(db_path):
        return []
    w = _norm(winner)
    if not w:
        return []
    out: list[str] = []
    for team in _distinct_teams_in_db(db_path):
        t = _norm(team)
        if t == w or w in t or t in w:
            out.append(team)
    if not out and winner.strip():
        out.append(winner.strip())
    return out


def iter_squad_rows_in_db(
    db_path: str, team: str
) -> list[tuple[str, str, Any, str, int]]:
    want = _norm(team)
    out: list[tuple[str, str, Any, str, int]] = []
    conn = sqlite3.connect(db_path)
    try:
        for tbl in PLAYER_TABLES:
            try:
                cur = conn.execute(
                    f"SELECT name, team, position, overall, person_id FROM {tbl} "
                    f"WHERE team IS NOT NULL AND trim(team) != ''"
                )
            except sqlite3.OperationalError:
                continue
            for name, tm, pos, ovr, pid in cur:
                if _norm(str(tm or "")) != want:
                    continue
                nm = str(name or "").strip()
                if not nm:
                    continue
                out.append(
                    (
                        nm,
                        str(pos or "").strip().upper(),
                        pid,
                        str(tm or "").strip().title(),
                        int(ovr or 0),
                    )
                )
    finally:
        conn.close()
    return out


def reset_trophies_in_db(db_path: str) -> int:
    if not db_path or not os.path.isfile(db_path):
        return 0
    n = 0
    conn = sqlite3.connect(db_path)
    try:
        for tbl in PLAYER_TABLES:
            try:
                cur = conn.execute(f"UPDATE {tbl} SET trophies = 0")
                n += int(cur.rowcount or 0)
            except sqlite3.OperationalError:
                continue
        conn.commit()
    finally:
        conn.close()
    return n


def _inc_trophies_for_team_in_db(db_path: str, team: str, delta: int = 1) -> int:
    want = _norm(team)
    n = 0
    conn = sqlite3.connect(db_path)
    try:
        for tbl in PLAYER_TABLES:
            try:
                cur = conn.execute(f"SELECT id, team FROM {tbl}")
            except sqlite3.OperationalError:
                continue
            for row_id, tm in cur:
                if _norm(str(tm or "")) != want:
                    continue
                conn.execute(
                    f"UPDATE {tbl} SET trophies = COALESCE(trophies, 0) + ? WHERE id = ?",
                    (int(delta), row_id),
                )
                n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def history_winners_by_season(rows: list[Any] | None) -> dict[int, str]:
    out: dict[int, str] = {}
    for row in rows or []:
        if not row or len(row) < 2:
            continue
        try:
            sn = int(row[0])
        except (TypeError, ValueError):
            continue
        team = str(row[1] or "").strip()
        if team:
            out[sn] = team
    return out


def apply_history_trophies_to_season(
    season_num: int,
    hist: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """+1 ``trophies`` в league/cl БД сезона по победителям из истории."""
    hist = hist or load_history()
    sn = int(season_num)
    log: dict[str, Any] = {"season": sn, "league": [], "cl": None}

    league_path = season_tournament_db_path(sn, cl=False)
    if league_path:
        for code, rows in (hist.get("league_winners") or {}).items():
            winners = history_winners_by_season(rows)
            winner = winners.get(sn)
            if not winner:
                continue
            for team in teams_matching_winner(league_path, winner):
                n = _inc_trophies_for_team_in_db(league_path, team, 1)
                log["league"].append({"code": code, "winner": winner, "team": team, "rows": n})

    cl_path = season_tournament_db_path(sn, cl=True)
    cl_winners = history_winners_by_season(hist.get("champions_league"))
    winner_cl = cl_winners.get(sn)
    if cl_path and winner_cl:
        cl_log: list[dict[str, Any]] = []
        for team in teams_matching_winner(cl_path, winner_cl):
            n = _inc_trophies_for_team_in_db(cl_path, team, 1)
            cl_log.append({"winner": winner_cl, "team": team, "rows": n})
        log["cl"] = cl_log
    return log


def rebuild_archives_trophies_from_history(
    *,
    include_active: bool = True,
) -> dict[str, Any]:
    """Обнулить и заново начислить ``trophies`` во всех архивах (+ активный сезон)."""
    from utils.cumulative_db import list_season_archives_with_db

    hist = load_history()
    seasons = sorted(set(list_season_archives_with_db()))
    if include_active:
        seasons.append(int(season_paths.get_active_season()))
    seasons = sorted(set(seasons))

    log: dict[str, Any] = {"seasons": [], "reset": 0, "apply": []}
    for sn in seasons:
        for cl in (False, True):
            path = season_tournament_db_path(sn, cl=cl)
            if path:
                log["reset"] += reset_trophies_in_db(path)
        part = apply_history_trophies_to_season(sn, hist)
        log["apply"].append(part)
        log["seasons"].append(sn)
    return log


def rebuild_synced_trophies_from_archives() -> dict[str, Any]:
    """Пересобрать ``*_synced.db`` после правки архивов."""
    from utils.cumulative_db import rebuild_all_time_databases_from_season_archives

    return rebuild_all_time_databases_from_season_archives()
