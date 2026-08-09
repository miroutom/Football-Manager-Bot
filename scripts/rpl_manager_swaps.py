#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Свапы РПЛ ↔ топ-лиги внутри одного менеджера (Roman / Lika).

Игрок 75–79 из клуба топ-лиги ↔ игрок 80+ той же позиции из РПЛ-клуба того же менеджера.
Если 80+ на позиции в РПЛ не осталось — любой игрок той же позиции с рейтингом выше (например Вейга 75 → Палмер 78).
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


def _load_formations() -> list[dict[str, Any]]:
    path = _ROOT / "tools" / "transfer_window_app" / "rosters.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("formations") or []


def _formation_for(team: dict, formations: list[dict[str, Any]]) -> dict[str, Any] | None:
    fid = int(team.get("formation_id") or 1)
    return next((f for f in formations if int(f.get("id") or 0) == fid), None)


def _team_squad_complete(team: dict, formations: list[dict[str, Any]]) -> bool:
    from utils.transfer_squad_quota import evaluate_team_squad

    return bool(evaluate_team_squad(team, _formation_for(team, formations)).get("complete"))


def _try_swap_pair(
    w: PlRef,
    s: PlRef,
    *,
    foreign_team: dict,
    rpl_team: dict,
    formations: list[dict[str, Any]],
) -> bool:
    """Свап только если оба клуба остаются с валидной заявкой (32 + слоты замен)."""
    ia = _extract_identity(w.player)
    ib = _extract_identity(s.player)
    _swap_identity(w, s)
    ok = _team_squad_complete(foreign_team, formations) and _team_squad_complete(
        rpl_team, formations
    )
    if not ok:
        _apply_identity(w.player, ia, team=w.team)
        _apply_identity(s.player, ib, team=s.team)
    return ok


def _pair_teams(foreign: list[str], rpl: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for i, f in enumerate(foreign):
        pairs.append((f, rpl[i % len(rpl)]))
    return pairs


def _candidates_at_pos(
    pool: list[PlRef],
    pos: str,
    *,
    used_keys: set[tuple[str, str]],
    min_ovr: int,
    strict_gt: int | None = None,
) -> list[PlRef]:
    out: list[PlRef] = []
    for r in pool:
        if r.key in used_keys:
            continue
        if str(r.player.get("position") or "") != pos:
            continue
        ovr = int(r.player.get("overall") or 0)
        if ovr < min_ovr:
            continue
        if strict_gt is not None and ovr <= strict_gt:
            continue
        out.append(r)
    out.sort(
        key=lambda r: (-int(r.player.get("overall") or 0), r.player.get("name") or "")
    )
    return out


def _find_swaps_for_pair(
    foreign_team: dict,
    rpl_team: dict,
    *,
    rpl_pool: list[dict],
    used_keys: set[tuple[str, str]],
) -> list[tuple[PlRef, PlRef, str]]:
    weak = [
        r
        for r in _iter_players(foreign_team)
        if 75 <= int(r.player.get("overall") or 0) <= 79 and r.key not in used_keys
    ]
    paired_rpl = _iter_players(rpl_team)
    all_rpl: list[PlRef] = []
    for rt in rpl_pool:
        all_rpl.extend(_iter_players(rt))

    weak.sort(
        key=lambda r: (
            _ZONE_RANK.get(r.zone, 9),
            int(r.player.get("overall") or 0),
            r.player.get("name") or "",
        )
    )

    swaps: list[tuple[PlRef, PlRef, str]] = []
    for w in weak:
        pos = str(w.player.get("position") or "")
        weak_ovr = int(w.player.get("overall") or 0)
        pick: PlRef | None = None
        tier = "80+"

        cands = _candidates_at_pos(paired_rpl, pos, used_keys=used_keys, min_ovr=80)
        if cands:
            pick = cands[0]
        else:
            cands = _candidates_at_pos(
                paired_rpl, pos, used_keys=used_keys, min_ovr=1, strict_gt=weak_ovr
            )
            if cands:
                pick = cands[0]
                tier = "upgrade"
            else:
                others = [r for r in all_rpl if r.team != rpl_team.get("name")]
                cands = _candidates_at_pos(
                    others, pos, used_keys=used_keys, min_ovr=1, strict_gt=weak_ovr
                )
                if cands:
                    pick = cands[0]
                    tier = "upgrade"

        if pick is None:
            continue
        swaps.append((w, pick, tier))
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
    rpl_teams = [by_name[n] for n in rpl_order if n in by_name]
    formations = _load_formations()
    used: set[tuple[str, str]] = set()
    log: list[dict[str, Any]] = []
    skipped = 0

    for foreign_name, rpl_name in _pair_teams(foreign_order, rpl_order):
        ft = by_name.get(foreign_name)
        rt = by_name.get(rpl_name)
        if not ft or not rt:
            continue
        for w, s, tier in _find_swaps_for_pair(
            ft, rt, rpl_pool=rpl_teams, used_keys=used
        ):
            weak_name = w.player.get("name")
            weak_pos = w.player.get("position")
            weak_ovr = w.player.get("overall")
            strong_name = s.player.get("name")
            strong_pos = s.player.get("position")
            strong_ovr = s.player.get("overall")
            weak_key = w.key
            strong_key = s.key
            rpl_side = by_name.get(s.team) or rt
            if not _try_swap_pair(
                w, s, foreign_team=ft, rpl_team=rpl_side, formations=formations
            ):
                skipped += 1
                continue
            used.add(weak_key)
            used.add(strong_key)
            log.append(
                {
                    "manager": manager,
                    "tier": tier,
                    "foreign_club": foreign_name,
                    "rpl_club": rpl_name,
                    "rpl_club_in": s.team,
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
    if skipped:
        log.append({"_skipped_invalid": skipped})
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

    from utils.transfer_squad_quota import evaluate_all_teams, format_missing_hint

    formations = _load_formations()
    ev = evaluate_all_teams(state.get("teams") or [], formations)
    incomplete = [r for r in ev.get("teams") or [] if not r.get("complete")]

    real_log = [r for r in all_log if "_skipped_invalid" not in r]
    skipped = next((r.get("_skipped_invalid") for r in all_log if "_skipped_invalid" in r), 0)

    print(f"Swaps: {len(real_log)} (Lika {sum(1 for r in real_log if r.get('manager')=='Lika')}, "
          f"Roman {sum(1 for r in real_log if r.get('manager')=='Roman')}, skipped {skipped})")
    for row in real_log:
        fo = row["foreign_out"]
        ri = row["rpl_in"]
        tier = row.get("tier") or "80+"
        rpl_from = row.get("rpl_club_in") or row["rpl_club"]
        print(
            f"  [{row['manager']}|{tier}] {row['foreign_club']}↔{row['rpl_club']}: "
            f"{fo['name']} {fo['position']} {fo['overall']} ({fo['zone']}) → {rpl_from}  |  "
            f"{ri['name']} {ri['position']} {ri['overall']} ({ri['zone']}) → {row['foreign_club']}"
        )
    print("\nFiles:")
    for k, path in paths.items():
        print(f"  {k}: {path}")
    if incomplete:
        print(f"\nНеполные заявки после свапов: {len(incomplete)}")
        for r in incomplete:
            print(f"  {r['team']}: {format_missing_hint(r)}")
    else:
        print("\nВсе клубы с валидной заявкой (32 + слоты замен).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
