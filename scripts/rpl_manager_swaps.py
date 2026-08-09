#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Свапы РПЛ ↔ топ-лиги внутри одного менеджера (Roman / Lika).

Игрок 75–79 из клуба топ-лиги ↔ игрок 80+ той же позиции из РПЛ-клуба того же менеджера.
Пары клубов — по силе (Сити↔Зенит, Барселона↔Локомотив, …).

  python3 scripts/rpl_manager_swaps.py \\
    --state ~/Downloads/transfer_window_state_summer_draft.json \\
    --out-dir ~/Downloads
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

LIKA_FOREIGN = [
    "Сити",
    "Барселона",
    "Дортмунд",
    "Интер",
    "Арсенал",
    "Атлетик",
    "Лейпциг",
    "Ювентус",
    "Тоттенхэм",
    "Реал Сосьедад",
    "Севилья",
    "Аталанта",
    "Лацио",
    "Боруссия М",
    "Хоффенхайм",
    "Ньюкасл",
]
LIKA_RPL = ["Зенит", "Локомотив", "Динамо", "Крылья Советов"]

ROMAN_FOREIGN = [
    "Наполи",
    "Ливерпуль",
    "Реал",
    "Бавария",
    "Мю",
    "Атлетико",
    "Милан",
    "Челси",
    "Астон Вилла",
    "Бетис",
    "Фиорентина",
    "Байер",
    "Жирона",
    "Рома",
    "Франкфурт",
    "Вольфсбург",
]
ROMAN_RPL = ["Цска", "Краснодар", "Спартак", "Урал"]

_ZONES = ("start", "bench", "reserve")
_ZONE_RANK = {"reserve": 0, "bench": 1, "start": 2}
_IDENTITY_KEYS = (
    "name",
    "position",
    "overall",
    "person_id",
    "nation",
    "nickname",
    "injured",
    "fired",
    "status",
)


@dataclass
class PlRef:
    team: str
    zone: str
    idx: int
    player: dict[str, Any]

    @property
    def key(self) -> tuple[str, str]:
        return (
            str(self.player.get("name") or "").strip().casefold(),
            str(self.player.get("position") or "").strip().upper(),
        )


def _team_index(teams: list[dict]) -> dict[str, dict]:
    return {str(t.get("name") or ""): t for t in teams}


def _iter_players(team: dict) -> list[PlRef]:
    name = str(team.get("name") or "")
    out: list[PlRef] = []
    for zone in _ZONES:
        for idx, p in enumerate(team.get(zone) or []):
            if p and p.get("name"):
                out.append(PlRef(name, zone, idx, p))
    return out


def _extract_identity(p: dict) -> dict[str, Any]:
    return {k: copy.deepcopy(p.get(k)) for k in _IDENTITY_KEYS if k in p}


def _apply_identity(p: dict, ident: dict[str, Any], *, team: str) -> None:
    for k, v in ident.items():
        p[k] = copy.deepcopy(v)
    pos = str(p.get("position") or "").strip().upper()
    nm = str(p.get("name") or "").strip()
    if nm and pos:
        p["id"] = f"{team}|{nm}|{pos}"


def _swap_identity(a: PlRef, b: PlRef) -> None:
    ia = _extract_identity(a.player)
    ib = _extract_identity(b.player)
    _apply_identity(a.player, ib, team=a.team)
    _apply_identity(b.player, ia, team=b.team)


def _pair_teams(foreign: list[str], rpl: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for i, f in enumerate(foreign):
        pairs.append((f, rpl[i % len(rpl)]))
    return pairs


def _find_swaps_for_pair(
    foreign_team: dict,
    rpl_team: dict,
    *,
    used_keys: set[tuple[str, str]],
) -> list[tuple[PlRef, PlRef]]:
    weak = [
        r
        for r in _iter_players(foreign_team)
        if 75 <= int(r.player.get("overall") or 0) <= 79 and r.key not in used_keys
    ]
    strong = [
        r
        for r in _iter_players(rpl_team)
        if int(r.player.get("overall") or 0) >= 80 and r.key not in used_keys
    ]
    weak.sort(
        key=lambda r: (
            _ZONE_RANK.get(r.zone, 9),
            int(r.player.get("overall") or 0),
            r.player.get("name") or "",
        )
    )
    strong_by_pos: dict[str, list[PlRef]] = {}
    for r in strong:
        strong_by_pos.setdefault(r.player.get("position") or "", []).append(r)
    for pos in strong_by_pos:
        strong_by_pos[pos].sort(
            key=lambda r: (-int(r.player.get("overall") or 0), r.player.get("name") or "")
        )

    swaps: list[tuple[PlRef, PlRef]] = []
    for w in weak:
        pos = str(w.player.get("position") or "")
        cands = [
            r
            for r in strong_by_pos.get(pos, [])
            if r.key not in used_keys
        ]
        if not cands:
            continue
        pick = cands[0]
        swaps.append((w, pick))
        used_keys.add(w.key)
        used_keys.add(pick.key)
    return swaps


def apply_manager_swaps(
    state: dict,
    *,
    manager: str,
    foreign_order: list[str],
    rpl_order: list[str],
) -> list[dict[str, Any]]:
    teams = state.get("teams") or []
    by_name = _team_index(teams)
    used: set[tuple[str, str]] = set()
    log: list[dict[str, Any]] = []

    for foreign_name, rpl_name in _pair_teams(foreign_order, rpl_order):
        ft = by_name.get(foreign_name)
        rt = by_name.get(rpl_name)
        if not ft or not rt:
            continue
        for w, s in _find_swaps_for_pair(ft, rt, used_keys=used):
            weak_name = w.player.get("name")
            weak_pos = w.player.get("position")
            weak_ovr = w.player.get("overall")
            strong_name = s.player.get("name")
            strong_pos = s.player.get("position")
            strong_ovr = s.player.get("overall")
            _swap_identity(w, s)
            log.append(
                {
                    "manager": manager,
                    "foreign_club": foreign_name,
                    "rpl_club": rpl_name,
                    "foreign_out": {
                        "name": weak_name,
                        "position": weak_pos,
                        "overall": weak_ovr,
                        "zone": w.zone,
                    },
                    "rpl_in": {
                        "name": strong_name,
                        "position": strong_pos,
                        "overall": strong_ovr,
                        "zone": s.zone,
                    },
                }
            )
    return log


def _export_bundle(state: dict, out_dir: Path, suffix: str) -> dict[str, Path]:
    from tools.transfer_window_app.main import (
        _write_squads_txt,
        _write_transfers_simple_txt,
        build_state_payload,
    )

    payload = build_state_payload(state)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "state": out_dir / f"transfer_window_state{suffix}.json",
        "transfers": out_dir / f"transfers_simple{suffix}.txt",
        "squads": out_dir / f"squads_export{suffix}.txt",
    }
    paths["state"].write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_transfers_simple_txt(paths["transfers"], payload.get("transfers") or [])
    _write_squads_txt(paths["squads"], payload, draft=True)
    return paths


def main() -> int:
    p = argparse.ArgumentParser(description="RPL ↔ top-league swaps per manager.")
    p.add_argument("--state", required=True, help="transfer_window_state_*.json")
    p.add_argument("--out-dir", default=str(Path.home() / "Downloads"))
    p.add_argument("--suffix", default="_rpl_swaps")
    args = p.parse_args()

    src = Path(args.state).expanduser()
    if not src.is_file():
        print("Not found:", src, file=sys.stderr)
        return 1

    state = json.loads(src.read_text(encoding="utf-8"))
    state = copy.deepcopy(state)

    lika_log = apply_manager_swaps(
        state, manager="Lika", foreign_order=LIKA_FOREIGN, rpl_order=LIKA_RPL
    )
    roman_log = apply_manager_swaps(
        state, manager="Roman", foreign_order=ROMAN_FOREIGN, rpl_order=ROMAN_RPL
    )
    all_log = lika_log + roman_log

    paths = _export_bundle(state, Path(args.out_dir).expanduser(), args.suffix)

    print(f"Swaps: {len(all_log)} (Lika {len(lika_log)}, Roman {len(roman_log)})")
    for row in all_log:
        fo = row["foreign_out"]
        ri = row["rpl_in"]
        print(
            f"  [{row['manager']}] {row['foreign_club']}↔{row['rpl_club']}: "
            f"{fo['name']} {fo['position']} {fo['overall']} ({fo['zone']}) → {row['rpl_club']}  |  "
            f"{ri['name']} {ri['position']} {ri['overall']} ({ri['zone']}) → {row['foreign_club']}"
        )
    print("\nFiles:")
    for k, path in paths.items():
        print(f"  {k}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
