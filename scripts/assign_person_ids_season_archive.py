#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Фаза 3: ``person_id`` в архиве сезона (``db/season_N/``) + связь с активным сезоном.

1. Группировка внутри архива (как фаза 2): трансфер, league/cl-эпизод.
2. ``person_id`` из сезона-эталона (по умолчанию active): совпадение (имя, клуб, позиция).
3. Трансфер в архиве + один ``person_id`` на это имя в S2 → тот же id.
4. Иначе новый id (игрок только в старом сезоне).

Примеры::

  python3 scripts/assign_person_ids_season_archive.py --season 1
  python3 scripts/assign_person_ids_season_archive.py --season 1 --link-season 2 --apply
  python3 scripts/assign_person_ids_season_archive.py --season 1 --apply \\
    --overrides data/person_id_season1_overrides.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import season_paths
from utils.migrate_player_person_id import migrate_person_id_for_sqlite
from utils.person_registry import (
    allocate_person_id,
    init_registry_db,
    sync_registry_after_backfill,
)

_ACTIVE_MOD_PATH = Path(__file__).resolve().parent / "assign_person_ids_active_season.py"
_REVIEW_CSV = ROOT / "data" / "person_id_season1_review.csv"
_REVIEW_XLSX = ROOT / "data" / "person_id_season1_review.xlsx"
_PREVIEW_JSON = ROOT / "data" / "person_id_season1_review_groups.json"
_DEFAULT_OVERRIDES = ROOT / "data" / "person_id_season1_overrides.json"


def _load_active_assign_module():
    name = "person_id_active_assign"
    spec = importlib.util.spec_from_file_location(name, _ACTIVE_MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _slot_key(name: str, team: str, position: str) -> tuple[str, str, str]:
    return (
        (name or "").strip().casefold(),
        (team or "").strip().casefold(),
        (position or "").strip().upper(),
    )


def _build_link_season_maps(
    pa: Any, link_season: int
) -> tuple[dict[tuple[str, str, str], int], dict[str, set[int]]]:
    """(имя, клуб, позиция) → person_id и имя → множество id из сезона-эталона."""
    d = season_paths.season_archive_directory(link_season)
    league = os.path.join(d, season_paths.SEASON_LEAGUE_NAME)
    cl = os.path.join(d, season_paths.SEASON_CL_NAME)
    anchor: dict[tuple[str, str, str], int] = {}
    by_name: dict[str, set[int]] = defaultdict(set)
    for db_kind, path in (("league", league), ("cl", cl)):
        for row in pa._load_rows(db_kind, path):
            if row.person_id is None:
                continue
            sk = _slot_key(row.name, row.team, row.position)
            anchor[sk] = min(anchor.get(sk, row.person_id), row.person_id)
            by_name[row.name_norm].add(row.person_id)
    return anchor, dict(by_name)


def _split_groups_by_link_pids(pa: Any, uf: Any, rows: list[Any], anchor: dict) -> int:
    comp = pa._components(uf, len(rows))
    split = 0
    for members in comp.values():
        pids = set()
        for i in members:
            r = rows[i]
            sk = _slot_key(r.name, r.team, r.position)
            if sk in anchor:
                pids.add(anchor[sk])
        if len(pids) <= 1:
            continue
        for i in members:
            uf.parent[i] = i
        split += 1
    return split


def _propose_archive_person_ids(
    pa: Any,
    rows: list[Any],
    comp: dict[int, list[int]],
    anchor: dict[tuple[str, str, str], int],
    by_name: dict[str, set[int]],
    overrides: dict[str, Any] | None,
) -> tuple[dict[int, int], dict[int, str], list[dict[str, Any]]]:
    """root → person_id; root → rule label; conflicts for review."""
    force = (overrides or {}).get("force_person_id") or {}
    key_to_idx = {rows[i].row_key: i for i in range(len(rows))}
    proposed: dict[int, int] = {}
    pid_rules: dict[int, str] = {}
    conflicts: list[dict[str, Any]] = []

    for root, members in comp.items():
        pids: set[int] = set()
        rules_hit: list[str] = []

        for i in members:
            rk = rows[i].row_key
            if rk in force:
                pids.add(int(force[rk]))
                rules_hit.append("override_force")
            r = rows[i]
            sk = _slot_key(r.name, r.team, r.position)
            if sk in anchor:
                pids.add(anchor[sk])
                rules_hit.append("link_season_slot")
            if r.person_id is not None:
                pids.add(r.person_id)
                rules_hit.append("existing")

        if len(pids) > 1:
            conflicts.append(
                {
                    "reason": "conflict_person_id",
                    "name": rows[members[0]].name,
                    "person_ids": sorted(pids),
                    "row_keys": [rows[i].row_key for i in members],
                }
            )
            proposed[root] = -1
            pid_rules[root] = "conflict"
            continue

        if len(pids) == 1:
            proposed[root] = next(iter(pids))
            pid_rules[root] = rules_hit[0] if rules_hit else "existing"
            continue

        nm = rows[members[0]].name_norm
        s2p = by_name.get(nm, set())
        active = [i for i in members if not rows[i].left_team]
        left = [i for i in members if rows[i].left_team]
        if len(s2p) == 1 and left and active:
            proposed[root] = next(iter(s2p))
            pid_rules[root] = "link_season_name_transfer"
            continue

        proposed[root] = -1
        pid_rules[root] = "new_allocate"

    return proposed, pid_rules, conflicts


def _apply_pid_rules_to_row_rules(
    rows: list[Any],
    comp: dict[int, list[int]],
    uf: Any,
    base_rules: dict[int, str],
    pid_rules: dict[int, str],
) -> dict[int, str]:
    out = dict(base_rules)
    for root, members in comp.items():
        pr = pid_rules.get(root, "")
        for i in members:
            if pr and pr not in ("new_allocate", "conflict"):
                out[i] = pr
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="person_id в архиве сезона")
    ap.add_argument("--season", type=int, required=True, help="Номер архива (1, 2, …)")
    ap.add_argument(
        "--link-season",
        type=int,
        default=0,
        help="Сезон-эталон person_id (0 = active_season)",
    )
    ap.add_argument("--apply", action="store_true", help="Записать в БД + common")
    ap.add_argument("--overrides", type=str, default="")
    ap.add_argument("--csv", type=str, default=str(_REVIEW_CSV))
    ap.add_argument("--xlsx", type=str, default=str(_REVIEW_XLSX))
    args = ap.parse_args()

    pa = _load_active_assign_module()
    init_registry_db()

    sn = int(args.season)
    link_sn = int(args.link_season or season_paths.get_active_season())
    arch = season_paths.season_archive_directory(sn)
    league_path = os.path.join(arch, season_paths.SEASON_LEAGUE_NAME)
    cl_path = os.path.join(arch, season_paths.SEASON_CL_NAME)
    common_path = os.path.join(arch, season_paths.SEASON_COMMON_NAME)

    for p in (league_path, cl_path, common_path):
        migrate_person_id_for_sqlite(p, label=f"s{sn}")

    rows: list[Any] = []
    rows.extend(pa._load_rows("league", league_path))
    rows.extend(pa._load_rows("cl", cl_path))
    if not rows:
        print(f"Нет строк в season_{sn}")
        return

    overrides_path = Path(args.overrides) if args.overrides else _DEFAULT_OVERRIDES
    overrides: dict[str, Any] | None = None
    if overrides_path.is_file():
        with overrides_path.open(encoding="utf-8") as f:
            overrides = json.load(f)
        print(f"Overrides: {overrides_path}")

    anchor, by_name = _build_link_season_maps(pa, link_sn)
    print(f"Эталон S{link_sn}: слотов с person_id = {len(anchor)}")

    uf, rules, needs_review = pa._build_groups(rows, overrides)
    n_split = _split_groups_by_link_pids(pa, uf, rows, anchor)
    if n_split:
        print(f"Разъединено групп (разные person_id в S{link_sn}): {n_split}")
    comp = pa._components(uf, len(rows))
    proposed, pid_rules, conflicts = _propose_archive_person_ids(
        pa, rows, comp, anchor, by_name, overrides
    )
    needs_review = needs_review + conflicts
    rules = _apply_pid_rules_to_row_rules(rows, comp, uf, rules, pid_rules)

    if args.apply:
        for root, pid in list(proposed.items()):
            if pid < 0 and pid_rules.get(root) != "conflict":
                sample = rows[comp[root][0]]
                proposed[root] = allocate_person_id(
                    notes=f"S{sn} {sample.name} · {sample.team}"
                )

    proposed_by_idx: dict[int, int] = {}
    for root, members in comp.items():
        pid = proposed[root]
        if pid_rules.get(root) == "conflict":
            continue
        for i in members:
            proposed_by_idx[i] = pid

    pa._write_review_reports(
        rows,
        uf,
        rules,
        proposed,
        needs_review,
        csv_path=Path(args.csv),
        xlsx_path=Path(args.xlsx),
    )
    with _PREVIEW_JSON.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "season": sn,
                "link_season": link_sn,
                "needs_review": needs_review,
                "conflicts": conflicts,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    multi = [g for g in comp.values() if len(g) > 1]
    print(f"Архив S{sn}: строк {len(rows)}, групп {len(comp)}, связок 2+: {len(multi)}")
    print(f"needs_review/conflicts: {len(needs_review)}")
    for item in needs_review[:15]:
        print(f"  · {item.get('reason')}: {item.get('name') or item.get('row_keys')}")
    if len(needs_review) > 15:
        print(f"  … ещё {len(needs_review) - 15}")
    print(f"CSV: {args.csv}")
    print(f"XLSX: {args.xlsx}")

    # sanity
    for r in rows:
        if r.name.strip() == "Мартинез" and r.team == "Интер":
            root = uf.find(r.idx)
            print(
                f"Check Мартинез Интер: proposed={proposed.get(root)} "
                f"rule={pid_rules.get(root)}"
            )

    if not args.apply:
        print("\nDry-run. Проверьте XLSX, затем --apply")
        return

    if conflicts:
        print(f"\nВнимание: {len(conflicts)} конфликтов — строки пропущены, см. XLSX")

    league_assign: dict[tuple[str, int], int] = {}
    cl_assign: dict[tuple[str, int], int] = {}
    all_pids: list[int] = []
    for i, r in enumerate(rows):
        pid = proposed_by_idx.get(i)
        if pid is None or pid < 0:
            sk = _slot_key(r.name, r.team, r.position)
            if sk in anchor:
                pid = anchor[sk]
            else:
                pid = allocate_person_id(notes=f"S{sn} {r.name} · {r.team}")
            proposed_by_idx[i] = pid
        all_pids.append(pid)
        tgt = league_assign if r.db_kind == "league" else cl_assign
        tgt[(r.table, r.row_id)] = pid

    n_l = pa._apply_to_db(league_path, league_assign)
    n_c = pa._apply_to_db(cl_path, cl_assign)
    sync_registry_after_backfill(all_pids)

    from utils.common_db import rebuild_common_database_for_disk_paths

    rebuild_common_database_for_disk_paths(league_path, cl_path, common_path)
    print(f"\nПрименено S{sn}: league {n_l}, cl {n_c}; common пересобран.")
    print(f"NULL person_id: league {pa._count_null(league_path)}, cl {pa._count_null(cl_path)}")


if __name__ == "__main__":
    main()
