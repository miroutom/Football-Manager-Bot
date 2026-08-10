# -*- coding: utf-8 -*-
"""Автовызов лучших игроков в сборные ЧМ по позициям (4-3-3 ат, ``fid_1``)."""
from __future__ import annotations

from typing import Any

from team_squad_schemas import SquadSlot, get_slots_for_formation_key
from utils.wc_callups import club_players_for_nation, resolve_nation_name
from utils.wc_squad_app import nation_team_template, wc_nations_flat
from utils.wc_squad_quota import WC_BENCH, WC_FORMATION_KEY, WC_RESERVE, WC_START

_CB_MARKERS = frozenset({"ЦЗ", "ЛЦЗ", "ПЦЗ"})
_INTER_FB = frozenset({"ЛЗ", "ПЗ", "ЛФЗ", "ПФЗ"})
_INTER_CM = frozenset({"ЦП", "ЦОП"})
_INTER_ATTACK = frozenset({"ЛФА", "ПФА", "ФРВ", "ЛФД", "ПФД", "ЦФД"})
_FORWARD_SLOT_IDS = frozenset({"LW", "RW", "ST", "STL", "STR", "CF"})


def _norm_pos(raw: Any) -> str:
    return str(raw or "").strip().upper()


def _is_gk(p: dict[str, Any]) -> bool:
    return _norm_pos(p.get("position")) == "ВРТ"


def _natural_fits_slot(p: dict[str, Any], slot: SquadSlot) -> bool:
    return _norm_pos(p.get("position")) in slot.allowed_positions


def _player_fits_slot(p: dict[str, Any], slot: SquadSlot) -> bool:
    pos = _norm_pos(p.get("position"))
    allowed = slot.allowed_positions
    if pos in allowed:
        return True
    if allowed == frozenset({"ВРТ"}):
        return False
    if pos == "ЦОП" and allowed & _CB_MARKERS:
        return True
    if pos in _INTER_FB and allowed & _INTER_FB:
        return True
    if pos in _INTER_CM and allowed & _INTER_CM:
        return True
    if slot.slot_id in _FORWARD_SLOT_IDS and pos in _INTER_ATTACK:
        if allowed & _INTER_ATTACK or allowed & frozenset({"ЦФД"}):
            return True
    return False


def _pick_for_slot(slot: SquadSlot, pool: list[dict[str, Any]], used: set[str]) -> dict[str, Any] | None:
    cands = [p for p in pool if p["name"].casefold() not in used and _natural_fits_slot(p, slot)]
    if not cands:
        cands = [p for p in pool if p["name"].casefold() not in used and _player_fits_slot(p, slot)]
    if slot.slot_id == "LCM" and len(cands) > 1:
        pref = [p for p in cands if _norm_pos(p.get("position")) in ("ЛП", "ЛЦП")]
        cands = pref or cands
    if slot.slot_id == "RCM" and len(cands) > 1:
        pref = [p for p in cands if _norm_pos(p.get("position")) in ("ПП", "ПЦП")]
        cands = pref or cands
    if slot.slot_id == "CAM" and len(cands) > 1:
        pref = [p for p in cands if _norm_pos(p.get("position")) == "ЦАП"]
        cands = pref or cands
    if not cands:
        return None
    best = max(
        cands,
        key=lambda x: (int(x.get("overall") or 0), str(x.get("name") or "").casefold()),
    )
    used.add(str(best["name"]).casefold())
    return best


def _sort_pool(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        pool,
        key=lambda x: (-int(x.get("overall") or 0), str(x.get("name") or "").casefold()),
    )


def build_auto_callup_roster(
    nation: str,
    players: list[dict[str, Any]] | None = None,
    *,
    formation_id: int = 1,
) -> list[dict[str, Any]]:
    """
    Лучшие игроки нации → заявка 26: 11 старт (по слотам 4-3-3 ат) + 7 запас + 8 резерв.
    Пустые слоты, если игроков не хватает.
    """
    canon = resolve_nation_name(nation) or (nation or "").strip()
    pool = list(players if players is not None else club_players_for_nation(canon))
    pool = _sort_pool(pool)
    slots = get_slots_for_formation_key(WC_FORMATION_KEY)
    used: set[str] = set()
    roster: list[dict[str, Any]] = []

    for slot in slots:
        picked = _pick_for_slot(slot, pool, used)
        if not picked:
            continue
        roster.append(
            {
                "name": picked["name"],
                "club": picked.get("club") or "Free Agent",
                "position": _norm_pos(picked.get("position")),
                "overall": int(picked.get("overall") or 0),
                "status": "start",
                "lineup_slot": slot.slot_id,
                "source": "callup",
                "person_id": picked.get("person_id"),
            }
        )

    remaining = [p for p in pool if p["name"].casefold() not in used]
    gk_remaining = [p for p in remaining if _is_gk(p)]
    out_remaining = [p for p in remaining if not _is_gk(p)]

    bench: list[dict[str, Any]] = []
    if gk_remaining and sum(1 for r in roster if _is_gk(r)) == 1:
        gk_bench = gk_remaining.pop(0)
        bench.append(gk_bench)
        used.add(gk_bench["name"].casefold())

    for p in _sort_pool(out_remaining + gk_remaining):
        if len(bench) >= WC_BENCH:
            break
        key = p["name"].casefold()
        if key in used:
            continue
        bench.append(p)
        used.add(key)

    reserve: list[dict[str, Any]] = []
    for p in _sort_pool([x for x in pool if x["name"].casefold() not in used]):
        if len(reserve) >= WC_RESERVE:
            break
        reserve.append(p)
        used.add(p["name"].casefold())

    for p in bench:
        roster.append(
            {
                "name": p["name"],
                "club": p.get("club") or "Free Agent",
                "position": _norm_pos(p.get("position")),
                "overall": int(p.get("overall") or 0),
                "status": "bench",
                "source": "callup",
                "person_id": p.get("person_id"),
            }
        )
    for p in reserve:
        roster.append(
            {
                "name": p["name"],
                "club": p.get("club") or "Free Agent",
                "position": _norm_pos(p.get("position")),
                "overall": int(p.get("overall") or 0),
                "status": "reserve",
                "source": "callup",
                "person_id": p.get("person_id"),
            }
        )
    _ = formation_id
    return roster


def build_all_auto_callup_teams(*, formation_id: int = 1) -> list[dict[str, Any]]:
    """Все сборные ЧМ из конфига → объекты transfer app."""
    from utils import season_paths

    season = season_paths.get_active_season()
    teams: list[dict[str, Any]] = []
    for nation in wc_nations_flat():
        canon = resolve_nation_name(nation) or nation
        roster = build_auto_callup_roster(canon, formation_id=formation_id)
        teams.append(
            nation_team_template(
                canon,
                formation_id=formation_id,
                coach="",
                roster=roster,
                season=season,
            )
        )
    return teams


def auto_callup_summary(teams: list[dict[str, Any]]) -> dict[str, Any]:
    """Сводка: где не хватает игроков."""
    from utils.wc_squad_app import wc_roster_from_nation_team
    from utils.wc_squad_quota import evaluate_wc_squad

    incomplete: list[dict[str, Any]] = []
    for team in teams:
        nation = str(team.get("name") or "")
        ev = evaluate_wc_squad(wc_roster_from_nation_team(team))
        if not ev.get("complete"):
            incomplete.append(
                {
                    "nation": nation,
                    "total": ev.get("total"),
                    "missing": ev.get("missing"),
                }
            )
    return {
        "nations": len(teams),
        "complete": len(teams) - len(incomplete),
        "incomplete": incomplete,
    }
