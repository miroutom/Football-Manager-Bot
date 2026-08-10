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
_DEPTH_POSITION_ORDER: tuple[str, ...] = (
    "ВРТ",
    "ЛЗ",
    "ПЗ",
    "ЦЗ",
    "ЛЦЗ",
    "ПЦЗ",
    "ЛФЗ",
    "ПФЗ",
    "ЦП",
    "ЦАП",
    "ЦОП",
    "ЛП",
    "ПП",
    "ЛЦП",
    "ПЦП",
    "ЛФА",
    "ПФА",
    "ФРВ",
    "ЦФД",
    "ЛФД",
    "ПФД",
)


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


def _best_unused(candidates: list[dict[str, Any]], used: set[str]) -> dict[str, Any] | None:
    pool = [p for p in candidates if p["name"].casefold() not in used]
    if not pool:
        return None
    return max(
        pool,
        key=lambda x: (int(x.get("overall") or 0), str(x.get("name") or "").casefold()),
    )


def _pick_bench_and_reserve(
    pool: list[dict[str, Any]],
    used: set[str],
    *,
    bench_size: int,
    reserve_size: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Запас + резерв: 1 вратарь в запас, по одному на каждую позицию, остальное — по рейтингу.
    """
    bench: list[dict[str, Any]] = []
    reserve: list[dict[str, Any]] = []

    def _remaining() -> list[dict[str, Any]]:
        return [p for p in pool if p["name"].casefold() not in used]

    def _append(target: str, player: dict[str, Any]) -> None:
        if target == "bench":
            bench.append(player)
        else:
            reserve.append(player)
        used.add(player["name"].casefold())

    def _next_target() -> str | None:
        if len(bench) < bench_size:
            return "bench"
        if len(reserve) < reserve_size:
            return "reserve"
        return None

    gk = _best_unused([p for p in _remaining() if _is_gk(p)], used)
    if gk and _next_target() == "bench":
        _append("bench", gk)

    for pos in _DEPTH_POSITION_ORDER:
        if pos == "ВРТ":
            continue
        if _next_target() is None:
            break
        picked = _best_unused(
            [p for p in _remaining() if not _is_gk(p) and _norm_pos(p.get("position")) == pos],
            used,
        )
        if picked:
            _append(_next_target() or "reserve", picked)

    for p in _sort_pool([x for x in _remaining() if not _is_gk(x)]):
        slot = _next_target()
        if slot is None:
            break
        _append(slot, p)

    return bench, reserve


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

    bench, reserve = _pick_bench_and_reserve(
        pool,
        used,
        bench_size=WC_BENCH,
        reserve_size=WC_RESERVE,
    )

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
