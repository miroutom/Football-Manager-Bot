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


def merge_same_name_duplicates_in_session(sess, team: str, name: str) -> int:
    """Оставить одну строку на имя в клубе (разные позиции). Возвращает число удалённых."""
    from utils.squad_roster_sync import _all_rows_same_player

    found = _all_rows_same_player(sess, name, team)
    if len(found) <= 1:
        return 0
    found.sort(
        key=lambda rc: (
            int(getattr(rc[0], "matches", 0) or 0),
            int(getattr(rc[0], "overall", 0) or 0),
            int(getattr(rc[0], "id", 0) or 0),
        ),
        reverse=True,
    )
    keeper, _ = found[0]
    removed = 0
    for donor, _Cls in found[1:]:
        merge_row_stats_into(keeper, donor)
        sess.delete(donor)
        removed += 1
    if hasattr(keeper, "ga"):
        keeper.ga = int(getattr(keeper, "goals", 0) or 0) + int(
            getattr(keeper, "assists", 0) or 0
        )
    return removed
