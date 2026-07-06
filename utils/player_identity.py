# -*- coding: utf-8 -*-
"""Один игрок в клубе = одна строка БД; алиасы после переименования в боте."""
from __future__ import annotations

import json
import os
from typing import Any

from utils.player_transfer import _norm_cmp
from utils.utils import PROJECT_ROOT

_ALIASES_PATH = os.path.join(PROJECT_ROOT, "data", "player_name_aliases.json")


def _load() -> dict[str, dict[str, str]]:
    if not os.path.isfile(_ALIASES_PATH):
        return {}
    try:
        with open(_ALIASES_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for team, mp in raw.items():
        if not isinstance(mp, dict):
            continue
        canon_team = str(team).strip().title()
        out[canon_team] = {
            str(k).strip(): str(v).strip()
            for k, v in mp.items()
            if str(k).strip() and str(v).strip()
        }
    return out


def _save(data: dict[str, dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(_ALIASES_PATH), exist_ok=True)
    with open(_ALIASES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def resolve_canonical_name(team: str, name: str) -> str:
    """Старое имя из заявки/статы → текущее имя в БД после переименования."""
    team_t = (team or "").strip().title()
    want = _norm_cmp(name)
    for old, new in (_load().get(team_t) or {}).items():
        if _norm_cmp(old) == want:
            return new.strip().title()
    return (name or "").strip().title()


def register_name_change(team: str, old_name: str, new_name: str) -> None:
    old_n = (old_name or "").strip().title()
    new_n = (new_name or "").strip().title()
    if not old_n or not new_n or _norm_cmp(old_n) == _norm_cmp(new_n):
        return
    data = _load()
    team_t = (team or "").strip().title()
    mp = dict(data.get(team_t) or {})
    mp[old_n] = new_n
    for k, v in list(mp.items()):
        if _norm_cmp(v) == _norm_cmp(new_n):
            mp[k] = new_n
        if _norm_cmp(k) == _norm_cmp(new_n):
            del mp[k]
    data[team_t] = mp
    _save(data)


_STAT_COPY_FIELDS = (
    "matches",
    "goals",
    "assists",
    "ga",
    "clean_sheets",
    "missed_goals",
    "trophies",
    "golden_balls",
    "golden_boots",
    "golden_gloves",
    "golden_boys",
    "yellow_cards",
    "red_cards",
    "potm",
    "motm",
)


def row_stats_snapshot(row: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for fld in _STAT_COPY_FIELDS:
        if hasattr(row, fld):
            out[fld] = int(getattr(row, fld, 0) or 0)
    return out


def copy_stats_replace(dst: Any, src: Any) -> None:
    """Заменить полевую стату dst значениями src (не суммировать)."""
    for fld in _STAT_COPY_FIELDS:
        if hasattr(dst, fld) and hasattr(src, fld):
            setattr(dst, fld, int(getattr(src, fld, 0) or 0))
    if hasattr(dst, "ga"):
        dst.ga = int(getattr(dst, "goals", 0) or 0) + int(
            getattr(dst, "assists", 0) or 0
        )


def merge_row_stats_into(keeper: Any, donor: Any) -> None:
    """Суммировать статистику donor → keeper, затем donor удаляют снаружи."""
    for fld in (
        "matches",
        "goals",
        "assists",
        "ga",
        "clean_sheets",
        "missed_goals",
        "trophies",
        "golden_balls",
        "golden_boots",
        "golden_gloves",
        "golden_boys",
        "yellow_cards",
        "red_cards",
        "potm",
        "motm",
    ):
        if not hasattr(keeper, fld) or not hasattr(donor, fld):
            continue
        setattr(
            keeper,
            fld,
            int(getattr(keeper, fld, 0) or 0) + int(getattr(donor, fld, 0) or 0),
        )
    ko = int(getattr(keeper, "overall", 0) or 0)
    do = int(getattr(donor, "overall", 0) or 0)
    if do > ko:
        keeper.overall = do
    if not (getattr(keeper, "status", None) or "").strip():
        keeper.status = getattr(donor, "status", None)
    if hasattr(keeper, "ga"):
        keeper.ga = int(getattr(keeper, "goals", 0) or 0) + int(
            getattr(keeper, "assists", 0) or 0
        )


def merge_same_name_duplicates_in_session(
    sess,
    team: str,
    name: str,
    *,
    keeper_row: Any | None = None,
    merge_mode: str = "sum",
) -> int:
    """Оставить одну строку на имя в клубе (разные позиции). Возвращает число удалённых."""
    from utils.squad_roster_sync import _all_rows_same_player

    found = _all_rows_same_player(sess, name, team)
    if len(found) <= 1:
        return 0
    if keeper_row is not None:
        kid = int(getattr(keeper_row, "id", 0) or 0)
        ordered = [x for x in found if int(getattr(x[0], "id", 0) or 0) == kid]
        ordered += [
            x
            for x in found
            if int(getattr(x[0], "id", 0) or 0) != kid
        ]
        if ordered:
            found = ordered
    keeper, _keeper_cls = found[0]
    donors = found[1:]
    return _apply_merge_donors(sess, keeper, donors, merge_mode)


def _apply_merge_donors(
    sess,
    keeper: Any,
    donors: list[tuple[Any, type]],
    merge_mode: str,
) -> int:
    """Удалить donors; merge_mode: sum | keep_primary | keep:TABLE:ID."""
    if not donors:
        return 0
    mode = (merge_mode or "sum").strip().lower()
    if mode.startswith("keep:"):
        parts = mode.split(":", 2)
        if len(parts) == 3:
            want_tbl, want_id = parts[1].lower(), int(parts[2])
            winner: Any | None = None
            for row, Cls in [(keeper, type(keeper)), *donors]:
                if (
                    Cls.__tablename__.lower() == want_tbl
                    and int(getattr(row, "id", 0) or 0) == want_id
                ):
                    winner = row
                    break
            if winner is not None:
                if int(getattr(winner, "id", 0) or 0) != int(
                    getattr(keeper, "id", 0) or 0
                ):
                    copy_stats_replace(keeper, winner)
                for row, _Cls in donors:
                    sess.delete(row)
                if winner is not keeper:
                    sess.delete(winner)
                if hasattr(keeper, "ga"):
                    keeper.ga = int(getattr(keeper, "goals", 0) or 0) + int(
                        getattr(keeper, "assists", 0) or 0
                    )
                return len(donors)
    if mode == "keep_primary":
        for donor, _Cls in donors:
            sess.delete(donor)
        return len(donors)
    from utils.person_registry import row_person_id

    if row_person_id(keeper) is None:
        for donor, _Cls in donors:
            dpid = row_person_id(donor)
            if dpid is not None:
                keeper.person_id = dpid
                break
    removed = 0
    for donor, _Cls in donors:
        if mode == "sum":
            merge_row_stats_into(keeper, donor)
        sess.delete(donor)
        removed += 1
    if hasattr(keeper, "ga"):
        keeper.ga = int(getattr(keeper, "goals", 0) or 0) + int(
            getattr(keeper, "assists", 0) or 0
        )
    return removed
