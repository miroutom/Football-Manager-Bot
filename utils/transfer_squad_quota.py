# -*- coding: utf-8 -*-
"""
Квота заявки для трансферного приложения: 11 в основе + 21 замена по слотам схемы.

На каждый слот поля (кроме GK) — 2 игрока в запасе с подходящей позицией; на GK — 1.
Игроки из ``bench`` и ``reserve`` считаются вместе.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SQUAD_TOTAL = 32
SQUAD_START = 11
SQUAD_RESERVE = SQUAD_TOTAL - SQUAD_START  # 21

# Подпись группы замен в UI (русские коды позиций).
_SLOT_RESERVE_LABEL: dict[str, str] = {
    "GK": "ВРТ",
    "LB": "ЛЗ",
    "RB": "ПЗ",
    "LCB": "ЦЗ",
    "RCB": "ЦЗ",
    "CB": "ЦЗ",
    "LW": "ЛФА",
    "ST": "ФРВ",
    "RW": "ПФА",
    "LCM": "ЦП",
    "RCM": "ЦП",
    "CAM": "ЦАП",
    "CDM": "ЦОП",
    "LM": "ЛП",
    "RM": "ПП",
    "STL": "ФРВ",
    "STR": "ПФА",
    "CCM": "ЦП",
}


@dataclass(frozen=True)
class ReserveGroup:
    slot_id: str
    label: str
    allowed: frozenset[str]
    need: int


def _primary_reserve_label(slot_id: str, allowed: frozenset[str]) -> str:
    pref = _SLOT_RESERVE_LABEL.get(slot_id)
    if pref and pref in allowed:
        return pref
    if allowed:
        return sorted(allowed)[0]
    return slot_id or "?"


def reserve_groups_for_formation(slots: list[dict[str, Any]]) -> list[ReserveGroup]:
    groups: list[ReserveGroup] = []
    for slot in slots or []:
        sid = str(slot.get("slot_id") or "").strip()
        allowed = frozenset(str(p).strip().upper() for p in (slot.get("allowed_positions") or []) if p)
        need = 1 if sid == "GK" else 2
        groups.append(
            ReserveGroup(
                slot_id=sid,
                label=_primary_reserve_label(sid, allowed),
                allowed=allowed,
                need=need,
            )
        )
    return groups


def _norm_pos(raw: Any) -> str:
    return str(raw or "").strip().upper()


def assign_substitutes_to_groups(
    players: list[dict[str, Any]],
    groups: list[ReserveGroup],
) -> tuple[list[int], list[dict[str, Any]]]:
    """Распределить запасных по группам слотов. Возвращает (filled[], missing[])."""
    pool = [p for p in players if p and p.get("name") and _norm_pos(p.get("position"))]
    assigned = [0] * len(groups)
    used = [False] * len(pool)

    order = sorted(
        range(len(groups)),
        key=lambda i: (len(groups[i].allowed), -groups[i].need, groups[i].slot_id),
    )

    for gi in order:
        g = groups[gi]
        for _ in range(g.need):
            picked = -1
            for pi, p in enumerate(pool):
                if used[pi]:
                    continue
                if _norm_pos(p.get("position")) in g.allowed:
                    picked = pi
                    break
            if picked < 0:
                break
            used[picked] = True
            assigned[gi] += 1

    missing: list[dict[str, Any]] = []
    for i, g in enumerate(groups):
        short = g.need - assigned[i]
        if short > 0:
            missing.append(
                {
                    "slot_id": g.slot_id,
                    "label": g.label,
                    "need": short,
                }
            )
    return assigned, missing


def _aggregate_missing(missing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agg: dict[str, int] = {}
    for m in missing:
        lab = str(m.get("label") or "?")
        agg[lab] = agg.get(lab, 0) + int(m.get("need") or 0)
    return [{"label": k, "need": v} for k, v in sorted(agg.items())]


def evaluate_team_squad(team: dict[str, Any], formation: dict[str, Any] | None) -> dict[str, Any]:
    """Проверка заявки одной команды."""
    slots = (formation or {}).get("slots") or []
    groups = reserve_groups_for_formation(slots)

    starters = [p for p in (team.get("start") or []) if p and p.get("id")]
    subs: list[dict[str, Any]] = []
    for zone in ("bench", "reserve"):
        subs.extend([p for p in (team.get(zone) or []) if p and p.get("id")])

    start_slots = team.get("start") or []
    start_missing = sum(1 for s in start_slots if not (s and s.get("id")))

    assigned, reserve_missing = assign_substitutes_to_groups(subs, groups)
    missing_agg = _aggregate_missing(reserve_missing)

    total = len(starters) + len(subs)
    complete = (
        start_missing == 0
        and not reserve_missing
        and total == SQUAD_TOTAL
        and len(start_slots) == SQUAD_START
    )

    group_status = [
        {
            "slot_id": g.slot_id,
            "label": g.label,
            "need": g.need,
            "have": assigned[i],
            "allowed": sorted(g.allowed),
        }
        for i, g in enumerate(groups)
    ]

    return {
        "team": team.get("name") or "",
        "total": total,
        "target": SQUAD_TOTAL,
        "start_filled": SQUAD_START - start_missing,
        "start_target": SQUAD_START,
        "reserve_filled": SQUAD_RESERVE - sum(m["need"] for m in reserve_missing),
        "reserve_target": SQUAD_RESERVE,
        "complete": complete,
        "missing_start": start_missing,
        "missing_reserve": missing_agg,
        "group_status": group_status,
        "groups": [
            {
                "slot_id": g.slot_id,
                "label": g.label,
                "need": g.need,
                "allowed": sorted(g.allowed),
            }
            for g in groups
        ],
    }


def evaluate_all_teams(
    teams: list[dict[str, Any]],
    formations: list[dict[str, Any]],
) -> dict[str, Any]:
    by_id = {int(f.get("id") or 0): f for f in formations or []}
    rows: list[dict[str, Any]] = []
    incomplete: list[str] = []
    for team in teams or []:
        fid = int(team.get("formation_id") or 1)
        form = by_id.get(fid) or (formations[0] if formations else None)
        ev = evaluate_team_squad(team, form)
        rows.append(ev)
        if not ev["complete"]:
            incomplete.append(str(ev["team"]))
    return {
        "squad_total": SQUAD_TOTAL,
        "squad_start": SQUAD_START,
        "squad_reserve": SQUAD_RESERVE,
        "teams": rows,
        "all_complete": not incomplete,
        "incomplete_teams": incomplete,
    }


def format_missing_hint(ev: dict[str, Any]) -> str:
    parts: list[str] = []
    if int(ev.get("missing_start") or 0) > 0:
        parts.append(f"основа ×{ev['missing_start']}")
    for m in ev.get("missing_reserve") or []:
        parts.append(f"{m['label']} ×{m['need']}")
    if int(ev.get("total") or 0) < SQUAD_TOTAL:
        parts.append(f"всего {ev['total']}/{SQUAD_TOTAL}")
    elif int(ev.get("total") or 0) > SQUAD_TOTAL:
        parts.append(f"лишних {int(ev['total']) - SQUAD_TOTAL}")
    return " · ".join(parts) if parts else "OK"
