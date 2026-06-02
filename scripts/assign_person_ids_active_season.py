#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Фаза 2: назначить ``person_id`` в активном сезоне (league + cl + common).

По умолчанию — dry-run: отчёт CSV/JSON для проверки, без записи в БД.

Правила авто-группировки:
  • одна строка → свой person_id;
  • уже есть person_id → та же группа;
  • одинаковое полное имя + (left_team у одной, у другой нет) → один человек (трансфер);
  • эпизод league/cl: (имя, клуб, позиция, left_team) → один id в обеих БД;
  • несколько **активных** строк с одним именем в разных клубах → needs_review, не склеивать.

Ручные правки перед --apply: ``data/person_id_active_overrides.json``::

  {
    "merge_row_keys": [
      ["league:midfielders:1061", "league:midfielders:1077", "cl:midfielders:806", "cl:midfielders:814"]
    ],
    "split_row_keys": []
  }

Примеры::

  python3 scripts/assign_person_ids_active_season.py
  python3 scripts/assign_person_ids_active_season.py --apply
  python3 scripts/assign_person_ids_active_season.py --apply --overrides data/person_id_active_overrides.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils import season_paths
from utils.person_registry import (
    allocate_person_id,
    init_registry_db,
    row_person_id,
    sync_registry_after_backfill,
)

_ALL = (Forward, Midfielder, Defender, Goalkeeper)
_TABLE = {
    Forward: "forwards",
    Midfielder: "midfielders",
    Defender: "defenders",
    Goalkeeper: "goalkeepers",
}
_REVIEW_CSV = ROOT / "data" / "person_id_active_season_review.csv"
_PREVIEW_JSON = ROOT / "data" / "person_id_active_season_groups.json"
_DEFAULT_OVERRIDES = ROOT / "data" / "person_id_active_overrides.json"


@dataclass
class RowRef:
    idx: int
    db_kind: str
    table: str
    row_id: int
    name: str
    team: str
    position: str
    left_team: bool
    matches: int
    goals: int
    assists: int
    person_id: int | None = None
    parent: int = -1

    @property
    def row_key(self) -> str:
        return f"{self.db_kind}:{self.table}:{self.row_id}"

    @property
    def name_norm(self) -> str:
        return (self.name or "").strip().casefold()

    @property
    def episode_key(self) -> tuple[str, str, str, bool]:
        return (
            self.name_norm,
            (self.team or "").strip().casefold(),
            (self.position or "").strip().upper(),
            bool(self.left_team),
        )


class UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _load_rows(db_kind: str, db_path: str) -> list[RowRef]:
    if not os.path.isfile(db_path):
        return []
    eng = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=eng)
    sess = Session()
    out: list[RowRef] = []
    try:
        base = len(out)
        for Cls in _ALL:
            table = _TABLE[Cls]
            for r in sess.query(Cls).all():
                out.append(
                    RowRef(
                        idx=0,
                        db_kind=db_kind,
                        table=table,
                        row_id=int(r.id or 0),
                        name=str(r.name or ""),
                        team=str(r.team or ""),
                        position=str(r.position or ""),
                        left_team=bool(getattr(r, "left_team", False)),
                        matches=int(getattr(r, "matches", 0) or 0),
                        goals=int(getattr(r, "goals", 0) or 0),
                        assists=int(getattr(r, "assists", 0) or 0),
                        person_id=row_person_id(r),
                    )
                )
    finally:
        sess.close()
        eng.dispose()
    for i, row in enumerate(out):
        row.idx = i
    return out


def _build_groups(
    rows: list[RowRef],
    overrides: dict[str, Any] | None,
) -> tuple[UnionFind, dict[int, str], list[dict[str, Any]]]:
    """Вернуть union-find, rule по idx, список needs_review."""
    uf = UnionFind(len(rows))
    rules: dict[int, str] = {i: "singleton" for i in range(len(rows))}
    needs_review: list[dict[str, Any]] = []

    by_episode: dict[tuple, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_episode[r.episode_key].append(i)

    for indices in by_episode.values():
        if len(indices) > 1:
            root = indices[0]
            for j in indices[1:]:
                uf.union(root, j)
                rules[j] = "episode_league_cl"

    by_name: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_name[r.name_norm].append(i)

    for name_norm, indices in by_name.items():
        if not name_norm or len(indices) <= 1:
            continue
        active = [i for i in indices if not rows[i].left_team]
        left = [i for i in indices if rows[i].left_team]

        active_slots = {(rows[i].team, rows[i].position) for i in active}
        if len(active_slots) > 1:
            needs_review.append(
                {
                    "reason": "multi_active_same_name",
                    "name": rows[active[0]].name,
                    "slots": sorted(f"{t} {p}" for t, p in active_slots),
                    "row_keys": sorted({rows[i].row_key for i in active}),
                }
            )
            continue

        if len(active_slots) == 1 and left:
            slot = next(iter(active_slots))
            hub = next(
                i for i in active if (rows[i].team, rows[i].position) == slot
            )
            for li in left:
                uf.union(hub, li)
                rules[li] = "transfer_same_name"
            for i in active:
                uf.union(hub, i)
                rules[i] = "transfer_same_name"

    pid_groups: dict[int, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        if r.person_id is not None:
            pid_groups[r.person_id].append(i)
    for inds in pid_groups.values():
        if len(inds) > 1:
            root = inds[0]
            for j in inds[1:]:
                uf.union(root, j)
                rules[j] = "existing_person_id"

    if overrides:
        for group_keys in overrides.get("merge_row_keys") or []:
            key_to_idx = {rows[i].row_key: i for i in range(len(rows))}
            ids = [key_to_idx[k] for k in group_keys if k in key_to_idx]
            if len(ids) >= 2:
                root = ids[0]
                for j in ids[1:]:
                    uf.union(root, j)
                    rules[j] = "override_merge"

        split_keys = set(overrides.get("split_row_keys") or [])
        if split_keys:
            needs_review.append(
                {
                    "reason": "manual_split_requested",
                    "row_keys": sorted(split_keys),
                }
            )

    return uf, rules, needs_review


def _components(uf: UnionFind, n: int) -> dict[int, list[int]]:
    comp: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        comp[uf.find(i)].append(i)
    return comp


def _propose_person_ids(
    rows: list[RowRef],
    comp: dict[int, list[int]],
) -> dict[int, int]:
    """root_idx -> person_id."""
    out: dict[int, int] = {}
    for root, members in comp.items():
        existing = [rows[i].person_id for i in members if rows[i].person_id]
        if existing:
            out[root] = min(existing)
        else:
            sample = rows[members[0]]
            out[root] = -1
    return out


def _write_review_csv(
    path: Path,
    rows: list[RowRef],
    uf: UnionFind,
    rules: dict[int, str],
    proposed: dict[int, int],
    needs_review: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    review_keys = set()
    for item in needs_review:
        for k in item.get("row_keys") or []:
            review_keys.add(k)

    comp = _components(uf, len(rows))
    root_to_gid: dict[int, str] = {}
    gid = 0
    for root in sorted(comp.keys(), key=lambda r: -len(comp[r])):
        gid += 1
        root_to_gid[root] = f"g{gid:04d}"

    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "group_id",
                "person_id_proposed",
                "needs_review",
                "rule",
                "row_key",
                "db",
                "table",
                "row_id",
                "name",
                "team",
                "position",
                "left_team",
                "matches",
                "goals",
                "assists",
                "person_id_current",
            ]
        )
        for root, members in sorted(
            comp.items(),
            key=lambda kv: (rows[kv[1][0]].name_norm, rows[kv[1][0]].team),
        ):
            gid_s = root_to_gid[root]
            pid = proposed.get(root, -1)
            pid_s = "" if pid < 0 else str(pid)
            flag = "yes" if any(rows[i].row_key in review_keys for i in members) else ""
            for i in sorted(members, key=lambda x: (rows[x].db_kind, rows[x].row_id)):
                r = rows[i]
                w.writerow(
                    [
                        gid_s,
                        pid_s,
                        flag,
                        rules.get(i, ""),
                        r.row_key,
                        r.db_kind,
                        r.table,
                        r.row_id,
                        r.name,
                        r.team,
                        r.position,
                        "1" if r.left_team else "0",
                        r.matches,
                        r.goals,
                        r.assists,
                        r.person_id or "",
                    ]
                )


def _write_preview_json(
    path: Path,
    rows: list[RowRef],
    uf: UnionFind,
    proposed: dict[int, int],
    needs_review: list[dict[str, Any]],
) -> None:
    comp = _components(uf, len(rows))
    groups = []
    for root, members in sorted(comp.items(), key=lambda kv: -len(kv[1])):
        if len(members) == 1 and proposed.get(root, -1) < 0:
            continue
        groups.append(
            {
                "person_id_proposed": proposed.get(root) if proposed.get(root, -1) > 0 else None,
                "row_keys": [rows[i].row_key for i in members],
                "sample": f"{rows[members[0]].name} · {rows[members[0]].team}",
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(
            {"groups": groups, "needs_review": needs_review},
            f,
            ensure_ascii=False,
            indent=2,
        )


def _apply_to_db(
    db_path: str,
    assignments: dict[tuple[str, int], int],
) -> int:
    """(table, row_id) -> person_id для одной sqlite."""
    if not os.path.isfile(db_path):
        return 0
    eng = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=eng)
    sess = Session()
    n = 0
    try:
        for Cls in _ALL:
            table = _TABLE[Cls]
            for r in sess.query(Cls).all():
                rid = int(r.id or 0)
                pid = assignments.get((table, rid))
                if pid is None:
                    continue
                if row_person_id(r) != pid:
                    r.person_id = pid
                    n += 1
        sess.commit()
    finally:
        sess.close()
        eng.dispose()
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description="Назначить person_id в активном сезоне")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Записать в league/cl и пересобрать common",
    )
    ap.add_argument(
        "--overrides",
        type=str,
        default="",
        help=f"JSON с merge_row_keys (по умолчанию {_DEFAULT_OVERRIDES.name} если есть)",
    )
    ap.add_argument(
        "--csv",
        type=str,
        default=str(_REVIEW_CSV),
        help="Путь к review CSV",
    )
    args = ap.parse_args()

    init_registry_db()
    season = season_paths.get_active_season()
    league_path = season_paths.get_league_db_path()
    cl_path = season_paths.get_cl_db_path()

    rows: list[RowRef] = []
    rows.extend(_load_rows("league", league_path))
    rows.extend(_load_rows("cl", cl_path))
    if not rows:
        print("Нет строк в активном сезоне.")
        return

    overrides_path = Path(args.overrides) if args.overrides else _DEFAULT_OVERRIDES
    overrides: dict[str, Any] | None = None
    if overrides_path.is_file():
        with overrides_path.open(encoding="utf-8") as f:
            overrides = json.load(f)
        print(f"Overrides: {overrides_path}")

    uf, rules, needs_review = _build_groups(rows, overrides)
    comp = _components(uf, len(rows))
    proposed_roots = _propose_person_ids(rows, comp)

    if args.apply:
        for root, pid in list(proposed_roots.items()):
            if pid < 0:
                members = comp[root]
                sample = rows[members[0]]
                proposed_roots[root] = allocate_person_id(
                    notes=f"{sample.name} · {sample.team}"
                )

    proposed_by_idx: dict[int, int] = {}
    for root, members in comp.items():
        pid = proposed_roots[root]
        for i in members:
            proposed_by_idx[i] = pid

    _write_review_csv(
        Path(args.csv),
        rows,
        uf,
        rules,
        proposed_roots,
        needs_review,
    )
    _write_preview_json(_PREVIEW_JSON, rows, uf, proposed_roots, needs_review)

    multi = [g for g in comp.values() if len(g) > 1]
    print(f"Сезон {season}: строк {len(rows)}, групп {len(comp)}, связок 2+ строк: {len(multi)}")
    print(f"needs_review: {len(needs_review)}")
    for item in needs_review:
        print(f"  · {item.get('reason')}: {item.get('name') or item.get('row_keys')}")
    print(f"CSV: {args.csv}")
    print(f"JSON: {_PREVIEW_JSON}")

    if not args.apply:
        print("\nDry-run. Проверьте CSV; при необходимости правьте overrides и запустите с --apply")
        return

    if needs_review and not overrides:
        print(
            "\nВнимание: есть needs_review без overrides. "
            "Продолжаем apply (спорные имена останутся в разных группах)."
        )

    league_assign: dict[tuple[str, int], int] = {}
    cl_assign: dict[tuple[str, int], int] = {}
    all_pids: list[int] = []
    for i, r in enumerate(rows):
        pid = proposed_by_idx[i]
        all_pids.append(pid)
        target = league_assign if r.db_kind == "league" else cl_assign
        target[(r.table, r.row_id)] = pid

    n_l = _apply_to_db(league_path, league_assign)
    n_c = _apply_to_db(cl_path, cl_assign)
    sync_registry_after_backfill(all_pids)

    from utils.common_db import rebuild_common_database

    rebuild_common_database()
    print(f"\nПрименено: league {n_l} строк, cl {n_c} строк; common пересобран.")

    null_l = _count_null(league_path)
    null_c = _count_null(cl_path)
    print(f"Осталось NULL: league {null_l}, cl {null_c}")


def _count_null(db_path: str) -> int:
    total = 0
    eng = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=eng)
    sess = Session()
    try:
        for Cls in _ALL:
            for r in sess.query(Cls).all():
                if row_person_id(r) is None:
                    total += 1
    finally:
        sess.close()
        eng.dispose()
    return total


if __name__ == "__main__":
    main()
