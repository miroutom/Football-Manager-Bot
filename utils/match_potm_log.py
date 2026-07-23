# -*- coding: utf-8 -*-
"""Журнал Player of the Match (POTM) по матчам — с месяцем календаря."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from utils.utils import PROJECT_ROOT

STORE_PATH = os.path.join(PROJECT_ROOT, "data", "match_potm_log.json")


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


def record_match_potm(
    *,
    player: str,
    team: str,
    position: str = "",
    home: str = "",
    away: str = "",
    tournament: str = "league",
    day: int | None = None,
    home_score: int | None = None,
    away_score: int | None = None,
    league_code: str | None = None,
    cl_phase: str | None = None,
    season: int | None = None,
) -> dict[str, Any]:
    """
    Записать / обновить POTM для слота матча.

    Если home+away уже есть в журнале (тот же сезон/день/турнир) — заменяем игрока
    (повторный выбор / правка). Иначе — append.
    """
    from utils import season_paths

    sn = int(season if season is not None else season_paths.get_active_season())
    tourn = (tournament or "league").strip().lower()
    row: dict[str, Any] = {
        "season": sn,
        "day": int(day) if day is not None else None,
        "home": _norm_team(home),
        "away": _norm_team(away),
        "tournament": tourn,
        "player": (player or "").strip(),
        "team": _norm_team(team),
        "position": (position or "").strip().upper(),
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


def load_match_potm_log() -> list[dict[str, Any]]:
    return _load()


def potm_by_month(
    *,
    season: int | None = None,
    day: int | None = None,
) -> list[dict[str, Any]]:
    """Фильтр журнала: сезон и/или месяц календаря (``day`` = мN)."""
    from utils import season_paths

    sn = int(season if season is not None else season_paths.get_active_season())
    out = [r for r in _load() if int(r.get("season") or 0) == sn]
    if day is not None:
        out = [r for r in out if r.get("day") is not None and int(r["day"]) == int(day)]
    out.sort(
        key=lambda r: (
            int(r.get("day") or 0),
            str(r.get("tournament") or ""),
            str(r.get("home") or ""),
        )
    )
    return out
