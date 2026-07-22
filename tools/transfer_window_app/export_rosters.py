#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Экспорт 40 составов в rosters.json для Transfer Window App."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bot.squad_pitch import (  # noqa: E402
    SUBSTITUTES_COUNT,
    _assign_slots,
    load_team_squad_players,
)
from coach_squad_state import get_coach_for_team, label_for_squad_caption  # noqa: E402
from coach_squad_state import resolve_formation_key_for_team  # noqa: E402
from player_stats import LEAGUE_NAMES, LEAGUE_TEAMS  # noqa: E402
from team_squad_schemas import get_slots_for_formation_key  # noqa: E402
from utils.season_paths import get_active_season  # noqa: E402
from utils.transfer_market_draft import _EXCLUDED_TEAMS  # noqa: E402

EXTRA_RESERVE_SLOTS = 5
_EMPTY = {"id": None, "name": None, "position": None, "overall": None}
# Зимнее окно: показываем травмы «на момент» этого месяца календаря.
INJURY_AS_OF_MONTH = 6


def _injury_fields(name: str, team: str, *, season: int, month: int = INJURY_AS_OF_MONTH) -> dict:
    """Поля травмы для карточки игрока (на ``month`` активного сезона)."""
    from utils.player_discipline import (
        _get_active_season_or_default,
        _injury_blocking_at_month,
        _injury_total_months,
        _load,
    )

    st = _load()
    season_now = int(season) if season else _get_active_season_or_default()
    inj = _injury_blocking_at_month(
        st, name, team, month, current_season=season_now
    )
    if not inj:
        return {"injured": False}
    ret = inj.get("return_month")
    ofm = inj.get("out_from_month")
    return {
        "injured": True,
        "injury_from": int(ofm) if ofm is not None else None,
        "injury_until": int(ret) if ret is not None else None,
        "injury_months": _injury_total_months(inj),
    }


def _pl_dict(
    p,
    team: str,
    slot_id: str | None = None,
    *,
    season: int,
) -> dict:
    row = {
        "id": f"{team}|{p.name}|{p.position}",
        "name": p.name,
        "position": p.position,
        "overall": int(p.score or 0),
        "slot": slot_id,
    }
    row.update(_injury_fields(p.name, team, season=season))
    return row


def export_team(team: str, *, season: int) -> dict:
    players = load_team_squad_players(team, "league")
    slot_map, bench_all = _assign_slots(players, team)
    slots_tpl = get_slots_for_formation_key(resolve_formation_key_for_team(team))
    start = []
    for slot in slots_tpl:
        p = slot_map.get(slot.slot_id)
        if p:
            start.append(
                {
                    **_pl_dict(p, team, slot.slot_id, season=season),
                    "x": slot.x,
                    "y": slot.y,
                }
            )
        else:
            start.append(
                {
                    **_EMPTY,
                    "injured": False,
                    "slot": slot.slot_id,
                    "x": slot.x,
                    "y": slot.y,
                }
            )
    bench = [_pl_dict(p, team, season=season) for p in bench_all[:SUBSTITUTES_COUNT]]
    reserve = [_pl_dict(p, team, season=season) for p in bench_all[SUBSTITUTES_COUNT:]]
    while len(bench) < SUBSTITUTES_COUNT:
        bench.append({**_EMPTY, "injured": False})
    reserve.extend({**_EMPTY, "injured": False} for _ in range(EXTRA_RESERVE_SLOTS))
    starters_ovr = [s["overall"] for s in start if s.get("overall")]
    avg = round(sum(starters_ovr) / len(starters_ovr), 1) if starters_ovr else 0.0
    coach = get_coach_for_team(team)
    caption = label_for_squad_caption(team)
    all_ids = [x["id"] for x in start + bench + reserve if x.get("id")]
    return {
        "name": team,
        "league": None,
        "caption": caption,
        "coach": coach.name if coach else "",
        "formation": caption,
        "avg_start": avg,
        "start": start,
        "bench": bench,
        "reserve": reserve,
        "baseline_ids": all_ids,
    }


def export_all() -> dict:
    season = get_active_season()
    teams: list[dict] = []
    baseline_home: dict[str, str] = {}
    for code in ("rpl", "eng", "esp", "ita", "ger"):
        for team in LEAGUE_TEAMS.get(code, []):
            if team in _EXCLUDED_TEAMS:
                continue
            block = export_team(team, season=season)
            block["league"] = LEAGUE_NAMES.get(code, code)
            teams.append(block)
            for pid in block["baseline_ids"]:
                baseline_home[pid] = team
    injured_n = sum(
        1
        for t in teams
        for z in ("start", "bench", "reserve")
        for p in t.get(z) or []
        if p.get("injured")
    )
    return {
        "season": season,
        "injury_as_of_month": INJURY_AS_OF_MONTH,
        "injured_count": injured_n,
        "teams": teams,
        "baseline_home": baseline_home,
    }


def main() -> int:
    out = Path(__file__).resolve().parent / "rosters.json"
    data = export_all()
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Экспортировано {len(data['teams'])} команд → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
