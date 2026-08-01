# -*- coding: utf-8 -*-
"""
Квота заявки сборной ЧМ: 26 игроков = 11 старт + 7 запас + 8 резерв.

Схема всегда 4-3-3 ат (``fid_1``). Старт — 11 слотов поля (гибкая расстановка:
любой игрок на любой слот). Два вратаря: один в старте, второй в запасе/резерве.
"""
from __future__ import annotations

from typing import Any

from team_squad_schemas import get_slots_for_formation_key
from utils.lineup_slot import resolve_lineup_slot_for_formation

WC_TOTAL = 26
WC_START = 11
WC_BENCH = 7
WC_RESERVE = 8
WC_FORMATION_KEY = "fid_1"
WC_GK_TOTAL = 2
WC_GK_IN_START = 1
WC_GK_IN_BENCH_RESERVE = 1

# Подписи слотов 4-3-3 ат для подсказок.
SLOT_LABELS_RU: dict[str, str] = {
    "LW": "ЛФА",
    "ST": "ФРВ",
    "RW": "ПФА",
    "LCM": "ЦП",
    "CAM": "ЦАП",
    "RCM": "ЦП",
    "LB": "ЛЗ",
    "LCB": "ЦЗ",
    "RCB": "ЦЗ",
    "RB": "ПЗ",
    "GK": "ВРТ",
}


def _norm_pos(raw: Any) -> str:
    return str(raw or "").strip().upper()


def _norm_status(raw: Any) -> str:
    return str(raw or "").strip().lower()


def _is_gk(p: dict[str, Any]) -> bool:
    return _norm_pos(p.get("position")) == "ВРТ"


def formation_slot_ids() -> frozenset[str]:
    slots = get_slots_for_formation_key(WC_FORMATION_KEY)
    return frozenset(s.slot_id for s in slots)


def evaluate_wc_squad(roster: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Проверка заявки одной сборной."""
    players = [dict(p) for p in (roster or []) if isinstance(p, dict) and (p.get("name") or "").strip()]
    by_st: dict[str, list[dict[str, Any]]] = {
        "start": [],
        "bench": [],
        "reserve": [],
        "": [],
    }
    for p in players:
        st = _norm_status(p.get("status"))
        if st not in ("start", "bench", "reserve"):
            st = ""
        by_st[st].append(p)

    start = by_st["start"]
    bench = by_st["bench"]
    reserve = by_st["reserve"]
    unset = by_st[""]

    valid_ids = formation_slot_ids()
    assigned_slots: set[str] = set()
    for p in start:
        sid = resolve_lineup_slot_for_formation(
            str(p.get("lineup_slot") or "").strip().upper() or None,
            valid_ids,
        )
        if sid:
            assigned_slots.add(sid)

    gk_start = sum(1 for p in start if _is_gk(p))
    gk_br = sum(1 for p in bench + reserve if _is_gk(p))
    gk_total = gk_start + gk_br

    missing: list[str] = []
    surplus: list[str] = []

    total = len(players)
    if total < WC_TOTAL:
        missing.append(f"всего {total}/{WC_TOTAL}")
    elif total > WC_TOTAL:
        surplus.append(f"всего +{total - WC_TOTAL}")

    def _count_hint(label: str, have: int, need: int) -> None:
        if have < need:
            missing.append(f"{label} ×{need - have}")
        elif have > need:
            surplus.append(f"{label} +{have - need}")

    _count_hint("старт", len(start), WC_START)
    _count_hint("запас", len(bench), WC_BENCH)
    _count_hint("резерв", len(reserve), WC_RESERVE)
    if unset:
        missing.append(f"без статуса ×{len(unset)}")

    if gk_total < WC_GK_TOTAL:
        missing.append(f"ВРТ ×{WC_GK_TOTAL - gk_total}")
    elif gk_total > WC_GK_TOTAL:
        surplus.append(f"ВРТ +{gk_total - WC_GK_TOTAL}")

    if gk_start < WC_GK_IN_START:
        missing.append("ВРТ в старте ×1")
    elif gk_start > WC_GK_IN_START:
        surplus.append(f"ВРТ в старте +{gk_start - WC_GK_IN_START}")

    if gk_br < WC_GK_IN_BENCH_RESERVE:
        missing.append("ВРТ в запасе ×1")
    elif gk_br > WC_GK_IN_BENCH_RESERVE:
        surplus.append(f"ВРТ в запасе +{gk_br - WC_GK_IN_BENCH_RESERVE}")

    complete = (
        total == WC_TOTAL
        and not missing
        and not surplus
        and len(start) == WC_START
        and len(bench) == WC_BENCH
        and len(reserve) == WC_RESERVE
        and not unset
    )

    return {
        "total": total,
        "target": WC_TOTAL,
        "start_filled": len(start),
        "start_target": WC_START,
        "bench_filled": len(bench),
        "bench_target": WC_BENCH,
        "reserve_filled": len(reserve),
        "reserve_target": WC_RESERVE,
        "unset_count": len(unset),
        "gk_total": gk_total,
        "gk_start": gk_start,
        "gk_bench_reserve": gk_br,
        "start_slots_assigned": len(assigned_slots),
        "start_slots_target": WC_START,
        "complete": complete,
        "missing": missing,
        "surplus": surplus,
        "formation_key": WC_FORMATION_KEY,
        "formation_label": "4-3-3 ат",
    }


def format_wc_quota_hint(ev: dict[str, Any]) -> str:
    if ev.get("complete"):
        return "OK"
    parts = list(ev.get("missing") or []) + list(ev.get("surplus") or [])
    return " · ".join(parts) if parts else "OK"


def format_wc_quota_summary_html(ev: dict[str, Any]) -> str:
    """Краткая HTML-строка для экрана сборной."""
    ok = "✅" if ev.get("complete") else "⚠️"
    hint = format_wc_quota_hint(ev)
    return (
        f"{ok} Заявка: <b>{ev.get('total', 0)}/{WC_TOTAL}</b> "
        f"(старт {ev.get('start_filled')}/{WC_START} · "
        f"запас {ev.get('bench_filled')}/{WC_BENCH} · "
        f"резерв {ev.get('reserve_filled')}/{WC_RESERVE}) · "
        f"ВРТ {ev.get('gk_total', 0)}/{WC_GK_TOTAL}"
        + (f"\n<i>{hint}</i>" if hint != "OK" else "")
    )
