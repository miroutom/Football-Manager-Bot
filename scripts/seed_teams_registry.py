#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Заполнить ``db/teams_registry.db`` из LEAGUE_TEAMS и config/leagues_config."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.leagues_config import (  # noqa: E402
    ALL_LEAGUES,
    CL_PARTICIPANTS,
    manager_side_for_team,
)
from player_stats import LEAGUE_TEAMS  # noqa: E402
from utils.team_registry import (  # noqa: E402
    TIER_AMBITION,
    init_teams_registry_db,
    refresh_team_strength_cache,
    upsert_league,
    upsert_team,
    count_teams,
)
from utils.team_strength import get_teams_sorted_by_strength  # noqa: E402

# trophy_tier 1..5 — индивидуальная критичность трофеев (не только сила состава)
TROPHY_TIER_BY_NORM: dict[str, int] = {
    # РПЛ — в целом низкая критичность
    "зенит": 2,
    "краснодар": 2,
    "цска": 2,
    "спартак": 2,
    "локомотив": 2,
    "динамо": 1,
    "крылья советов": 1,
    "урал": 1,
    "ростов": 1,
    "рубин": 1,
    # АПЛ
    "сити": 5,
    "ливерпуль": 5,
    "арсенал": 5,
    "мю": 4,
    "челси": 4,
    "астон вилла": 3,
    "ньюкасл": 3,
    "тоттенхэм": 3,
    "фулхэм": 1,
    "брайтон": 2,
    # Ла Лига
    "реал": 5,
    "барселона": 5,
    "атлетико": 5,
    "атлетик": 4,
    "реал сосьедад": 2,
    "севилья": 2,
    "бетис": 2,
    "жирона": 1,
    "вильярреал": 3,
    "райо вальекано": 1,
    # Бундеслига
    "бавария": 5,
    "дортмунд": 4,
    "байер": 4,
    "лейпциг": 4,
    "франкфурт": 3,
    "фрайбург": 2,
    "боруссия м": 2,
    "вольфсбург": 2,
    "штутгарт": 2,
    "хоффенхайм": 2,
    # Серия А
    "интер": 5,
    "милан": 5,
    "ювентус": 5,
    "наполи": 4,
    "аталанта": 3,
    "лацио": 3,
    "рома": 3,
    "фиорентина": 2,
    "торино": 1,
    "сассуоло": 1,
}

LEAGUE_META: dict[str, tuple[str, float, float, float]] = {
    # display_name, trophy_scale, cl_scale, competitiveness
    "rpl": ("РПЛ", 0.30, 0.10, 0.55),
    "eng": ("АПЛ", 1.00, 1.00, 1.00),
    "esp": ("Ла Лига", 1.00, 0.85, 1.00),
    "ger": ("Бундеслига", 0.92, 0.92, 0.95),
    "ita": ("Серия А", 0.90, 0.88, 0.92),
}

# Ранг силы → тир, если клуб не в TROPHY_TIER_BY_NORM
_RANK_TIER: tuple[tuple[int, int], ...] = (
    (2, 4),
    (4, 3),
    (7, 2),
    (10, 1),
)


def _norm(s: str) -> str:
    t = (s or "").strip()
    if t.casefold() == "цска":
        return "цска"
    return " ".join(t.casefold().split())


def _active_norms() -> set[str]:
    out: set[str] = set()
    for info in ALL_LEAGUES.values():
        for t in info.get("teams") or []:
            out.add(_norm(t))
    return out


def _cl_norms() -> set[str]:
    out: set[str] = set()
    for clubs in CL_PARTICIPANTS.values():
        for t in clubs:
            out.add(_norm(t))
    return out


def _tier_from_rank(rank: int) -> int:
    r = max(1, int(rank))
    for max_rank, tier in _RANK_TIER:
        if r <= max_rank:
            return tier
    return 1


def seed(*, refresh_strength: bool = True) -> int:
    init_teams_registry_db()
    active = _active_norms()
    cl_set = _cl_norms()

    for code, (display, trophy_scale, cl_scale, comp) in LEAGUE_META.items():
        upsert_league(
            league_code=code,
            display_name=display,
            trophy_scale=trophy_scale,
            cl_scale=cl_scale,
            competitiveness=comp,
        )

    n = 0
    for league_code, names in LEAGUE_TEAMS.items():
        ranked = get_teams_sorted_by_strength(list(names), "league")
        rank_by_norm = {_norm(t): i for i, (t, _s) in enumerate(ranked, start=1)}

        for display_name in names:
            nn = _norm(display_name)
            rank = rank_by_norm.get(nn, 10)
            tier = TROPHY_TIER_BY_NORM.get(nn)
            if tier is None:
                tier = _tier_from_rank(rank)
            mgr = manager_side_for_team(display_name)
            upsert_team(
                name=display_name,
                league_code=league_code,
                manager=mgr,
                in_cl_pool=nn in cl_set,
                trophy_tier=tier,
                active=nn in active,
            )
            n += 1
            if refresh_strength:
                try:
                    refresh_team_strength_cache(display_name)
                except Exception:
                    pass

    return n


def main() -> None:
    p = argparse.ArgumentParser(description="Seed teams_registry.db")
    p.add_argument(
        "--no-strength",
        action="store_true",
        help="Не обновлять strength_cached из league.db",
    )
    args = p.parse_args()
    n = seed(refresh_strength=not args.no_strength)
    total = count_teams()
    print(f"Seeded {n} teams (total in registry: {total})")


if __name__ == "__main__":
    main()
