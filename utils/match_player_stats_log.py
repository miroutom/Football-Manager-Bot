# -*- coding: utf-8 -*-
"""Журнал голов/передач игроков по матчам (для игрока месяца)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from utils.utils import PROJECT_ROOT

STORE_PATH = os.path.join(PROJECT_ROOT, "data", "match_player_stats_log.json")


def _norm_team(name: str) -> str:
    return (name or "").strip().title()


def _load() -> list[dict[str, Any]]:
    if not os.path.isfile(STORE_PATH):
        return []
    try:
        with open(STORE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return []
    return raw if isinstance(raw, list) else []


def _save(rows: list[dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def _slot_key(row: dict[str, Any]) -> tuple:
    return (
        int(row.get("season") or 0),
        _norm_team(str(row.get("home") or "")),
        _norm_team(str(row.get("away") or "")),
        str(row.get("tournament") or "league").strip().lower(),
        str(row.get("cl_phase") or "").strip().lower(),
        int(row["day"]) if row.get("day") is not None else -1,
    )


def record_match_player_stats(
    *,
    players: list[dict[str, Any]],
    home: str,
    away: str,
    tournament: str = "league",
    day: int | None = None,
    home_score: int | None = None,
    away_score: int | None = None,
    league_code: str | None = None,
    cl_phase: str | None = None,
    season: int | None = None,
) -> dict[str, Any]:
    """
    Записать вклад игроков за один матч (заменяет предыдущую запись слота).

    ``players``: [{player, team, position?, goals, assists}, ...]
    """
    from utils import season_paths

    sn = int(season if season is not None else season_paths.get_active_season())
    tourn = (tournament or "league").strip().lower()
    clean_players: list[dict[str, Any]] = []
    for p in players or []:
        g = int(p.get("goals") or 0)
        a = int(p.get("assists") or 0)
        if g == 0 and a == 0:
            continue
        clean_players.append(
            {
                "player": str(p.get("player") or p.get("name") or "").strip(),
                "team": _norm_team(str(p.get("team") or "")),
                "position": str(p.get("position") or "").strip().upper(),
                "goals": g,
                "assists": a,
            }
        )
    row: dict[str, Any] = {
        "season": sn,
        "day": int(day) if day is not None else None,
        "home": _norm_team(home),
        "away": _norm_team(away),
        "tournament": tourn,
        "players": clean_players,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if home_score is not None:
        row["home_score"] = int(home_score)
    if away_score is not None:
        row["away_score"] = int(away_score)
    if league_code:
        row["league_code"] = str(league_code).strip().lower()
    if tourn == "cl" and cl_phase:
        row["cl_phase"] = str(cl_phase).strip().lower()

    rows = _load()
    if row["home"] and row["away"]:
        key = _slot_key(row)
        for i, old in enumerate(rows):
            if _slot_key(old) == key:
                rows[i] = row
                _save(rows)
                return row
    rows.append(row)
    _save(rows)
    return row


def load_match_player_stats_log() -> list[dict[str, Any]]:
    return _load()


def flush_session_acc_to_log(
    session_acc: dict[str, dict] | None,
    *,
    home: str,
    away: str,
    tournament: str = "league",
    day: int | None = None,
    home_score: int | None = None,
    away_score: int | None = None,
    league_code: str | None = None,
    cl_phase: str | None = None,
    season: int | None = None,
) -> dict[str, Any] | None:
    """Снять ``stats_session_acc`` бота в журнал матча."""
    if not session_acc:
        return None
    players: list[dict[str, Any]] = []
    for _key, acc in session_acc.items():
        if not isinstance(acc, dict):
            continue
        g = int(acc.get("goals") or 0)
        a = int(acc.get("assists") or 0)
        if g == 0 and a == 0:
            continue
        players.append(
            {
                "player": str(acc.get("display_name") or "").strip(),
                "team": str(acc.get("team") or "").strip(),
                "position": str(acc.get("position") or "").strip(),
                "goals": g,
                "assists": a,
            }
        )
    if not players:
        return None
    return record_match_player_stats(
        players=players,
        home=home,
        away=away,
        tournament=tournament,
        day=day,
        home_score=home_score,
        away_score=away_score,
        league_code=league_code,
        cl_phase=cl_phase,
        season=season,
    )
