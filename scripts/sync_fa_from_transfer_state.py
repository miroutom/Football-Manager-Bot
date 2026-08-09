#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Добавить в ``free_agents.db`` всех игроков из transfer_window_state, которых не хватает для apply.

Берёт: ``free_agents`` в state, baseline_home → Free Agent, трансферы Free Agent → клуб.

  python3 scripts/sync_fa_from_transfer_state.py \\
    ~/Downloads/transfer_window_state_summer_draft.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _player_loc(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    loc: dict[str, dict[str, Any]] = {}
    for team in data.get("teams") or []:
        for zone in ("start", "bench", "reserve"):
            for p in team.get(zone) or []:
                if p and p.get("id") and p.get("name"):
                    loc[str(p["id"])] = dict(p)
    for p in data.get("free_agents") or []:
        if p and p.get("id") and p.get("name"):
            loc[str(p["id"])] = dict(p)
    return loc


def collect_fa_seed_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    loc = _player_loc(data)
    baseline: dict[str, str] = dict(data.get("baseline_home") or {})
    by_key: dict[tuple[str, str], dict[str, Any]] = {}

    def put(row: dict[str, Any]) -> None:
        name = str(row.get("name") or "").strip()
        pos = str(row.get("position") or "").strip().upper()
        if not name or not pos:
            return
        key = (name, pos)
        cur = by_key.get(key)
        if cur is None or int(row.get("overall") or 0) > int(cur.get("overall") or 0):
            by_key[key] = row

    for p in data.get("free_agents") or []:
        if p and p.get("name"):
            put(dict(p))

    for pid, home in baseline.items():
        if str(home).strip() != "Free Agent":
            continue
        p = loc.get(str(pid))
        if p:
            put(p)

    for t in data.get("transfers") or []:
        if str(t.get("from_team") or "").strip() != "Free Agent":
            continue
        name = str(t.get("name") or "").strip()
        pos = str(t.get("position") or "").strip().upper()
        if not name:
            continue
        tid = str(t.get("id") or "")
        src = loc.get(tid) if tid else None
        row = dict(src or t)
        row.setdefault("name", name)
        if pos:
            row["position"] = pos
        put(row)

    return list(by_key.values())


def main() -> int:
    p = argparse.ArgumentParser(description="Sync missing free agents from transfer state JSON.")
    p.add_argument("state", help="transfer_window_state_*.json")
    args = p.parse_args()

    path = Path(args.state).expanduser()
    if not path.is_file():
        print("Not found:", path, file=sys.stderr)
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    rows = collect_fa_seed_rows(data)
    from utils.free_agents_db import ensure_free_agent_player, fa_player_exists

    added = 0
    skipped = 0
    for row in rows:
        name = str(row.get("name") or "").strip()
        pos = str(row.get("position") or "").strip().upper()
        if not name or not pos:
            continue
        if fa_player_exists(name, pos):
            skipped += 1
            continue
        ovr = int(row.get("overall") or 72)
        pid = row.get("person_id")
        ensure_free_agent_player(
            name=name,
            position=pos,
            overall=ovr,
            nation=(row.get("nation") or None),
            status=str(row.get("status") or "bench"),
            person_id=int(pid) if pid is not None else None,
            nickname=(row.get("nickname") or None),
        )
        added += 1
        print(f"  + {name} {pos} {ovr}")

    print(f"FA sync: +{added}, already in db: {skipped}, candidates: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
