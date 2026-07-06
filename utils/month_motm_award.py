# -*- coding: utf-8 -*-
"""Man Of The Month: завершённые месяцы календаря, запись награды по лигам."""
from __future__ import annotations

import json
import os
from typing import Any

from utils.utils import PROJECT_ROOT

_STORE_PATH = os.path.join(PROJECT_ROOT, "data", "month_motm_awards.json")


def _load() -> dict[str, Any]:
    if not os.path.isfile(_STORE_PATH):
        return {}
    try:
        with open(_STORE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_STORE_PATH), exist_ok=True)
    with open(_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _season_key(season: int | None = None) -> str:
    from utils import season_paths

    s = int(season or season_paths.get_active_season())
    return f"season_{s}"


def calendar_months_in_schedule(schedule: list[dict]) -> list[int]:
    out: set[int] = set()
    for day_data in schedule or []:
        try:
            d = int(day_data.get("day"))
        except (TypeError, ValueError):
            continue
        if 1 <= d <= 12:
            out.add(d)
    return sorted(out)


def is_calendar_month_complete(month: int, schedule: list[dict] | None = None) -> bool:
    """Все матчи месяца сыграны или в пропусках."""
    from main import (
        cl_phase_from_mixed_schedule_line,
        get_teams_by_league,
        is_match_played,
        load_or_generate_mixed_schedule,
        load_skipped_matches,
    )
    from main import _skipped_matches_slot

    sched = schedule if schedule is not None else load_or_generate_mixed_schedule()
    skipped = load_skipped_matches()
    month = int(month)
    has_matches = False
    for day_data in sched:
        if int(day_data.get("day") or 0) != month:
            continue
        for match_str in day_data.get("matches") or []:
            has_matches = True
            parts = [x.strip() for x in str(match_str).split(";")]
            if len(parts) < 3:
                continue
            home, away, league_code = parts[0], parts[1], parts[2]
            cl_ph = (
                cl_phase_from_mixed_schedule_line(match_str)
                if league_code == "cl"
                else None
            )
            teams = get_teams_by_league(league_code)
            if not teams:
                continue
            if is_match_played(home, away, league_code, teams, cl_phase=cl_ph):
                continue
            if any(
                _skipped_matches_slot(s, home, away, league_code, cl_ph)
                for s in skipped
            ):
                continue
            return False
    return has_matches


def completed_calendar_months(schedule: list[dict] | None = None) -> list[int]:
    sched = schedule
    if sched is None:
        from main import load_or_generate_mixed_schedule

        sched = load_or_generate_mixed_schedule()
    return [m for m in calendar_months_in_schedule(sched) if is_calendar_month_complete(m, sched)]


def get_month_award(
    month: int,
    league_code: str,
    *,
    season: int | None = None,
) -> dict[str, str] | None:
    data = _load()
    row = (data.get(_season_key(season)) or {}).get(str(int(month))) or {}
    item = row.get(str(league_code).strip().lower())
    if not isinstance(item, dict):
        return None
    name = str(item.get("player") or "").strip()
    team = str(item.get("team") or "").strip()
    if not name or not team:
        return None
    return {
        "player": name,
        "team": team,
        "position": str(item.get("position") or "").strip(),
    }


def month_league_already_awarded(
    month: int,
    league_code: str,
    *,
    season: int | None = None,
) -> bool:
    return get_month_award(month, league_code, season=season) is not None


def record_month_award(
    month: int,
    league_code: str,
    *,
    player: str,
    team: str,
    position: str = "",
    season: int | None = None,
) -> None:
    data = _load()
    sk = _season_key(season)
    season_block = dict(data.get(sk) or {})
    month_block = dict(season_block.get(str(int(month))) or {})
    month_block[str(league_code).strip().lower()] = {
        "player": str(player).strip(),
        "team": str(team).strip(),
        "position": str(position or "").strip(),
    }
    season_block[str(int(month))] = month_block
    data[sk] = season_block
    _save(data)


def apply_month_motm_award(
    month: int,
    league_code: str,
    player_name: str,
    team: str,
    *,
    position: str = "",
    season: int | None = None,
) -> tuple[bool, str]:
    """
    Проверки + запись MOTM месяца в БД лиги/ЛЧ и журнал наград.
    """
    from bot.services import tournament_db_for_league
    from player_stats import apply_month_motm

    month = int(month)
    lg = str(league_code).strip().lower()
    if not is_calendar_month_complete(month):
        return False, f"Месяц {month} ещё не завершён — не все матчи сыграны."
    if month_league_already_awarded(month, lg, season=season):
        prev = get_month_award(month, lg, season=season) or {}
        return (
            False,
            f"За месяц {month} в этой лиге уже выбран "
            f"{prev.get('player')} ({prev.get('team')}).",
        )
    tourn = tournament_db_for_league(lg)
    ok = apply_month_motm(
        player_name,
        position,
        team,
        tournament=tourn,
        sync_derived=True,
    )
    if not ok:
        return False, "Игрок не найден в базе выбранной лиги."
    record_month_award(
        month,
        lg,
        player=player_name,
        team=team,
        position=position,
        season=season,
    )
    return True, f"MOTM месяца {month}: {player_name} ({team})"
