# -*- coding: utf-8 -*-
"""
Пакетная правка заявки сборной ЧМ: строки «имя start [LW]» / «имя bench» / «имя reserve».
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from utils.lineup_slot import normalize_lineup_slot, resolve_lineup_slot_for_formation
from utils.wc_callups import resolve_nation_name
from utils.wc_squad_quota import formation_slot_ids
from utils.world_cup import load_wc_squads, save_wc_squads

_LINE_RE = re.compile(
    r"^\s*(.+?)\s+(start|bench|reserve)(?:\s+([A-Za-z]{2,4}))?\s*$",
    re.IGNORECASE | re.UNICODE,
)


@dataclass
class WcSquadApplyResult:
    ok: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _find_player_index(roster: list[dict[str, Any]], name: str) -> int | None:
    want = (name or "").strip().casefold()
    if not want:
        return None
    for i, row in enumerate(roster):
        if str(row.get("name") or "").strip().casefold() == want:
            return i
    return None


def apply_wc_squad_status_lines(nation: str, text: str) -> WcSquadApplyResult:
    """Обновить status / lineup_slot игроков в ``world_cup_squads.json``."""
    canon = resolve_nation_name(nation) or (nation or "").strip()
    if not canon:
        raise ValueError("Неизвестная сборная")

    data = load_wc_squads()
    teams = data.setdefault("teams", {})
    roster: list[dict[str, Any]] = teams.setdefault(canon, [])
    if not isinstance(roster, list):
        raise ValueError(f"Некорректная заявка {canon!r}")

    valid_slots = formation_slot_ids()
    res = WcSquadApplyResult()
    changed = False

    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            res.errors.append(f"не разобрать (имя + start|bench|reserve [слот]): {line!r}")
            continue
        name = m.group(1).strip()
        status = m.group(2).strip().lower()
        slot_raw = (m.group(3) or "").strip().upper()

        idx = _find_player_index(roster, name)
        if idx is None:
            res.errors.append(f"не в заявке: {name}")
            continue

        row = roster[idx]
        row["status"] = status
        if status == "start" and slot_raw:
            try:
                slot_norm = normalize_lineup_slot(slot_raw)
            except ValueError as e:
                res.errors.append(f"{name}: {e}")
                continue
            resolved = resolve_lineup_slot_for_formation(slot_norm, valid_slots)
            if not resolved:
                res.errors.append(f"{name}: слот {slot_raw} не в схеме 4-3-3 ат")
                continue
            row["lineup_slot"] = resolved
        else:
            row.pop("lineup_slot", None)

        changed = True
        slot_note = f" → {row.get('lineup_slot')}" if status == "start" and row.get("lineup_slot") else ""
        res.ok.append(f"{name} → {status}{slot_note}")

    if changed and res.ok:
        from utils import season_paths

        data["season"] = season_paths.get_active_season()
        save_wc_squads(data)

    return res
