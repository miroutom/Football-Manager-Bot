# -*- coding: utf-8 -*-
"""Кандидаты в игроки месяца: POTM + голы + передачи за календарный месяц."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# Веса: при равных POTM решают голы и передачи.
POTM_W = 5
GOAL_W = 3
ASSIST_W = 2


@dataclass
class MonthMotmCandidate:
    player: str
    team: str
    position: str
    goals: int
    assists: int
    potm: int
    score: float

    @property
    def ga(self) -> int:
        return self.goals + self.assists

    def label(self) -> str:
        return (
            f"{self.player} · {self.team} · {self.goals}+{self.assists} "
            f"· POTM×{self.potm} · {self.score:g}"
        )


def _norm(s: str) -> str:
    return (s or "").strip().casefold()


def _entry_league_code(row: dict[str, Any]) -> str:
    lc = str(row.get("league_code") or "").strip().lower()
    if lc:
        return lc
    if str(row.get("tournament") or "").strip().lower() == "cl":
        return "cl"
    # fallback по хозяевам
    try:
        from player_stats import national_league_code_for_team

        return (national_league_code_for_team(str(row.get("home") or "")) or "").lower()
    except Exception:
        return ""


def _matches_league(row: dict[str, Any], league_code: str) -> bool:
    want = (league_code or "").strip().lower()
    if not want:
        return True
    got = _entry_league_code(row)
    if want == "cl":
        return got == "cl" or str(row.get("tournament") or "").lower() == "cl"
    return got == want


def month_motm_candidates(
    month: int,
    league_code: str,
    *,
    season: int | None = None,
    limit: int = 8,
) -> list[MonthMotmCandidate]:
    """
    Топ кандидатов за месяц в лиге.

    score = goals×3 + assists×2 + potm×5
    """
    from utils import season_paths
    from utils.match_player_stats_log import load_match_player_stats_log
    from utils.match_potm_log import load_match_potm_log

    sn = int(season if season is not None else season_paths.get_active_season())
    month = int(month)
    lc = (league_code or "").strip().lower()

    bag: dict[tuple[str, str], dict[str, Any]] = {}

    def _slot(player: str, team: str) -> dict[str, Any]:
        key = (_norm(player), _norm(team))
        if key not in bag:
            bag[key] = {
                "player": (player or "").strip(),
                "team": (team or "").strip().title(),
                "position": "",
                "goals": 0,
                "assists": 0,
                "potm": 0,
            }
        return bag[key]

    for row in load_match_player_stats_log():
        if int(row.get("season") or 0) != sn:
            continue
        if row.get("day") is None or int(row["day"]) != month:
            continue
        if not _matches_league(row, lc):
            continue
        for p in row.get("players") or []:
            if not isinstance(p, dict):
                continue
            name = str(p.get("player") or "").strip()
            team = str(p.get("team") or "").strip()
            if not name or not team:
                continue
            slot = _slot(name, team)
            slot["goals"] += int(p.get("goals") or 0)
            slot["assists"] += int(p.get("assists") or 0)
            pos = str(p.get("position") or "").strip()
            if pos and not slot["position"]:
                slot["position"] = pos

    for row in load_match_potm_log():
        if int(row.get("season") or 0) != sn:
            continue
        if row.get("day") is None or int(row["day"]) != month:
            continue
        if not _matches_league(row, lc):
            continue
        name = str(row.get("player") or "").strip()
        team = str(row.get("team") or "").strip()
        if not name or not team:
            continue
        slot = _slot(name, team)
        slot["potm"] += 1
        pos = str(row.get("position") or "").strip()
        if pos and not slot["position"]:
            slot["position"] = pos

    cands: list[MonthMotmCandidate] = []
    for slot in bag.values():
        g = int(slot["goals"])
        a = int(slot["assists"])
        potm = int(slot["potm"])
        if g + a + potm <= 0:
            continue
        score = g * GOAL_W + a * ASSIST_W + potm * POTM_W
        cands.append(
            MonthMotmCandidate(
                player=slot["player"],
                team=slot["team"],
                position=slot["position"],
                goals=g,
                assists=a,
                potm=potm,
                score=float(score),
            )
        )
    cands.sort(
        key=lambda c: (-c.score, -c.ga, -c.goals, -c.potm, c.player.casefold())
    )
    return cands[: max(1, int(limit))] if cands else []
