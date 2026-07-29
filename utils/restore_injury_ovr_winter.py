# -*- coding: utf-8 -*-
"""
Вернуть overall игрокам с травмами с месяца 6+ к значениям из
``data/transfer_window/squads_export_winter.txt`` (выгрузка после зимнего ТО).

Штраф за травмы в сезоне отключён — см. ``injury_overall_penalty``.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils import season_paths
from utils.player_discipline import _load, _norm
from utils.player_overall_bumps import apply_overall_bumps_for_team
from utils.squad_roster_sync import find_player_row_first_match
from utils.utils import session_cl, session_league

_WINTER_EXPORT = (
    Path(season_paths.PROJECT_ROOT)
    / "data"
    / "transfer_window"
    / "squads_export_winter.txt"
)

# Латинские/русские коды позиций в хвосте строки экспорта.
_POS_TAIL = re.compile(
    r"^(?:GK|LB|RB|CB|LCB|RCB|CCB|LWB|RWB|CM|LCM|RCM|CAM|CDM|LCDM|RCDM|"
    r"LW|RW|ST|STL|STR|LM|RM|CF|"
    r"ВРТ|ВР|ЛЗ|ПЗ|ЦЗ|ЛЦЗ|ПЦЗ|ЦП|ЦАП|ЦОП|ЛФА|ПФА|ФРВ|ПП|ЛФЗ|ПФЗ)$",
    re.IGNORECASE,
)


@dataclass
class RestoreInjuryOvrResult:
    restored: list[str] = field(default_factory=list)
    skipped_same: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    missing_target: list[str] = field(default_factory=list)


def parse_winter_squad_overalls(
    path: Path | str | None = None,
) -> dict[tuple[str, str], int]:
    """``(team_norm, name_norm) → overall`` из текстовой выгрузки составов."""
    p = Path(path) if path else _WINTER_EXPORT
    text = p.read_text(encoding="utf-8")
    out: dict[tuple[str, str], int] = {}
    team: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("@"):
            team = line[1:].strip()
            continue
        if line.startswith("=") or line.startswith("#"):
            continue
        m = re.search(r"^(.+?)\s+(\d{2})\s*$", line)
        if not m or not team:
            continue
        left = m.group(1).strip()
        ovr = int(m.group(2))
        parts = left.split()
        while len(parts) > 1 and _POS_TAIL.match(parts[-1]):
            parts.pop()
        # хвост вида LCDM / всё CAPS латиница ≤5
        while len(parts) > 1:
            tok = parts[-1]
            if tok.isascii() and tok.isupper() and 1 < len(tok) <= 5:
                parts.pop()
                continue
            break
        name = " ".join(parts).strip()
        if name:
            out[(_norm(team), _norm(name))] = ovr
    return out


def _current_overall(name: str, team: str) -> int | None:
    for sess in (session_league, session_cl):
        row, _Cls, _m = find_player_row_first_match(sess, name, team)
        if row is not None:
            return int(getattr(row, "overall", 0) or 0)
    return None


def _target_ovr_for_injury(
    inj: dict[str, Any],
    winter: dict[tuple[str, str], int],
) -> int | None:
    name = str(inj.get("name") or "").strip()
    team = str(inj.get("team") or "").strip()
    if not name or not team:
        return None
    w = winter.get((_norm(team), _norm(name)))
    if w is not None:
        return int(w)
    before = inj.get("overall_before_penalty")
    if before is not None:
        try:
            return int(before)
        except (TypeError, ValueError):
            return None
    return None


def collect_injury_ovr_restores(
    *,
    season: int | None = None,
    from_month: int = 6,
    winter_path: Path | str | None = None,
) -> list[tuple[str, str, int, int]]:
    """
    Список ``(team, name, current, target)`` для игроков с травмой
    ``out_from_month >= from_month`` в сезоне (по умолчанию активный).
    """
    sn = int(season if season is not None else season_paths.get_active_season())
    winter = parse_winter_squad_overalls(winter_path)
    seen: set[tuple[str, str]] = set()
    rows: list[tuple[str, str, int, int]] = []
    for inj in _load().get("injuries") or []:
        try:
            if int(inj.get("season")) != sn:
                continue
            if int(inj.get("out_from_month") or 0) < int(from_month):
                continue
        except (TypeError, ValueError):
            continue
        name = str(inj.get("name") or "").strip()
        team = str(inj.get("team") or "").strip()
        key = (_norm(name), _norm(team))
        if not name or not team or key in seen:
            continue
        seen.add(key)
        target = _target_ovr_for_injury(inj, winter)
        if target is None:
            continue
        cur = _current_overall(name, team)
        if cur is None:
            continue
        rows.append((team, name, cur, target))
    return rows


def restore_injury_ovr_from_winter(
    *,
    season: int | None = None,
    from_month: int = 6,
    dry_run: bool = False,
    winter_path: Path | str | None = None,
) -> RestoreInjuryOvrResult:
    """
    Применить overall из зимней выгрузки (или ``overall_before_penalty``)
    игрокам с травмами с ``from_month`` и позже.
    """
    res = RestoreInjuryOvrResult()
    planned = collect_injury_ovr_restores(
        season=season, from_month=from_month, winter_path=winter_path
    )
    winter = parse_winter_squad_overalls(winter_path)
    sn = int(season if season is not None else season_paths.get_active_season())

    # пометить missing (нет ни winter, ни before)
    seen_ok = {(_norm(n), _norm(t)) for t, n, _c, _tg in planned}
    for inj in _load().get("injuries") or []:
        try:
            if int(inj.get("season")) != sn:
                continue
            if int(inj.get("out_from_month") or 0) < int(from_month):
                continue
        except (TypeError, ValueError):
            continue
        name = str(inj.get("name") or "").strip()
        team = str(inj.get("team") or "").strip()
        if not name or not team:
            continue
        if (_norm(name), _norm(team)) in seen_ok:
            continue
        if _target_ovr_for_injury(inj, winter) is None:
            res.missing_target.append(f"{name} ({team})")

    by_team: dict[str, list[str]] = defaultdict(list)
    for team, name, cur, target in planned:
        if cur == target:
            res.skipped_same.append(f"{name} ({team}): {cur}")
            continue
        delta = int(target) - int(cur)
        by_team[team].append(f"{name} {delta:+d}")
        res.restored.append(f"{name} ({team}): {cur} → {target}")

    if dry_run or not by_team:
        return res

    teams = list(by_team.keys())
    for i, team in enumerate(teams):
        last = i == len(teams) - 1
        bump = apply_overall_bumps_for_team(
            team,
            "\n".join(by_team[team]),
            rebuild_common=last,
        )
        for e in bump.errors:
            res.errors.append(f"{team}: {e}")
    return res
