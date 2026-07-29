# -*- coding: utf-8 -*-
"""Поднять всех игроков РПЛ с overall < 75 до 75."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from player_stats import LEAGUE_TEAMS
from utils.ovr_debug_advice import _scan_club_players
from utils.player_overall_bumps import apply_overall_bumps_for_team


@dataclass
class RaiseRplFloorResult:
    raised: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def raise_rpl_overall_floor(
    *,
    floor: int = 75,
    dry_run: bool = False,
) -> RaiseRplFloorResult:
    """Все игроки клубов РПЛ с overall &lt; floor → floor (через delta bumps)."""
    res = RaiseRplFloorResult()
    by_team: dict[str, list[str]] = defaultdict(list)
    for team in LEAGUE_TEAMS.get("rpl") or []:
        for p in _scan_club_players(team):
            name = str(p.get("name") or "").strip()
            cur = int(p.get("overall") or 0)
            if not name or cur >= int(floor):
                continue
            delta = int(floor) - cur
            by_team[team].append(f"{name} {delta:+d}")
            res.raised.append(f"{name} ({team}): {cur} → {floor}")

    if dry_run or not by_team:
        return res

    teams = list(by_team.keys())
    for i, team in enumerate(teams):
        bump = apply_overall_bumps_for_team(
            team,
            "\n".join(by_team[team]),
            rebuild_common=(i == len(teams) - 1),
        )
        for e in bump.errors:
            res.errors.append(f"{team}: {e}")
    return res
