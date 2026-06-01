"""
Учёт матчей со счётом в журнале, по которым статистика игроков ещё не внесена / уже внесена.
"""
from __future__ import annotations

import json
import os

from utils.utils import PROJECT_ROOT

COMPLETED_FILE = os.path.join(PROJECT_ROOT, "data", "matches_stats_completed.json")
PENDING_FILE = os.path.join(PROJECT_ROOT, "data", "matches_stats_pending.json")


def _load(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def _norm_team(name: str) -> str:
    return (name or "").strip().title()


def _slot_row(
    home: str,
    away: str,
    tournament: str,
    *,
    cl_phase: str | None = None,
    day: int | None = None,
) -> dict:
    row = {
        "home": _norm_team(home),
        "away": _norm_team(away),
        "tournament": (tournament or "league").strip().lower(),
    }
    if row["tournament"] == "cl":
        row["cl_phase"] = (cl_phase or "knockout").strip().lower()
    if day is not None:
        row["day"] = int(day)
    return row


def _same_slot(a: dict, b: dict) -> bool:
    if _norm_team(a.get("home", "")) != _norm_team(b.get("home", "")):
        return False
    if _norm_team(a.get("away", "")) != _norm_team(b.get("away", "")):
        return False
    ta = (a.get("tournament") or "league").strip().lower()
    tb = (b.get("tournament") or "league").strip().lower()
    if ta != tb:
        return False
    if ta == "cl":
        ap = (a.get("cl_phase") or "knockout").strip().lower()
        bp = (b.get("cl_phase") or "knockout").strip().lower()
        if ap != bp:
            return False
    da, db = a.get("day"), b.get("day")
    if da is not None and db is not None and int(da) != int(db):
        return False
    return True


def load_stats_completed() -> list[dict]:
    return _load(COMPLETED_FILE)


def load_stats_pending() -> list[dict]:
    return _load(PENDING_FILE)


def is_stats_completed(
    home: str,
    away: str,
    tournament: str,
    *,
    cl_phase: str | None = None,
) -> bool:
    key = _slot_row(home, away, tournament, cl_phase=cl_phase)
    return any(_same_slot(m, key) for m in load_stats_completed())


def is_stats_pending(
    home: str,
    away: str,
    tournament: str,
    *,
    cl_phase: str | None = None,
) -> bool:
    """Матч в очереди «Стата без матча» (после «Нет» сразу после счёта)."""
    key = _slot_row(home, away, tournament, cl_phase=cl_phase)
    return any(_same_slot(m, key) for m in load_stats_pending())


def _tournament_from_slot(slot: dict) -> tuple[str, str | None]:
    lc = str(slot.get("league_code") or "league").strip().lower()
    tourn = "cl" if lc == "cl" else "league"
    cl_ph = slot.get("cl_ph") if tourn == "cl" else None
    return tourn, cl_ph


def mark_stats_completed(
    home: str,
    away: str,
    tournament: str,
    *,
    cl_phase: str | None = None,
    day: int | None = None,
) -> None:
    key = _slot_row(home, away, tournament, cl_phase=cl_phase, day=day)
    rows = load_stats_completed()
    if not any(_same_slot(m, key) for m in rows):
        rows.append(key)
        _save(COMPLETED_FILE, rows)
    remove_stats_pending(home, away, tournament, cl_phase=cl_phase)


def mark_stats_pending(
    home: str,
    away: str,
    tournament: str,
    *,
    cl_phase: str | None = None,
    day: int | None = None,
) -> None:
    """Матч сыгран, пользователь отказался от статы сразу после матча."""
    if is_stats_completed(home, away, tournament, cl_phase=cl_phase):
        return
    key = _slot_row(home, away, tournament, cl_phase=cl_phase, day=day)
    rows = load_stats_pending()
    if not any(_same_slot(m, key) for m in rows):
        rows.append(key)
        _save(PENDING_FILE, rows)


def remove_stats_pending(
    home: str,
    away: str,
    tournament: str,
    *,
    cl_phase: str | None = None,
) -> bool:
    key = _slot_row(home, away, tournament, cl_phase=cl_phase)
    rows = load_stats_pending()
    new_rows = [m for m in rows if not _same_slot(m, key)]
    if len(new_rows) < len(rows):
        _save(PENDING_FILE, new_rows)
        return True
    return False


def filter_played_without_stats(slots: list[dict]) -> list[dict]:
    """
    Очередь «Стата без матча»: только матчи из ``matches_stats_pending.json``
    (после «Нет» на экране статы), ещё не в ``matches_stats_completed.json``.
    """
    out = []
    for slot in slots:
        tourn, cl_ph = _tournament_from_slot(slot)
        home = slot["home"]
        away = slot["away"]
        if is_stats_completed(home, away, tourn, cl_phase=cl_ph):
            continue
        if not is_stats_pending(home, away, tourn, cl_phase=cl_ph):
            continue
        out.append(slot)
    return out
