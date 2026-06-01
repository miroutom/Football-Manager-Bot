#!/usr/bin/env python3
"""Показать / подчистить data/matches_stats_pending.json (очередь «Стата без матча»)."""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from matches_stats_tracking import (  # noqa: E402
    PENDING_FILE,
    _same_slot,
    load_stats_completed,
    load_stats_pending,
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Удалить матчи, уже в matches_stats_completed.json",
    )
    ap.add_argument(
        "--clear",
        action="store_true",
        help="Очистить очередь полностью (осторожно)",
    )
    args = ap.parse_args()
    rows = load_stats_pending()
    done = load_stats_completed()
    print(f"pending: {len(rows)}  completed: {len(done)}")
    print(f"file: {PENDING_FILE}\n")
    for i, r in enumerate(rows, 1):
        day = r.get("day", "—")
        ph = f" · {r.get('cl_phase')}" if r.get("tournament") == "cl" else ""
        print(
            f"{i:3}. м{day} · {r.get('home')} — {r.get('away')} "
            f"({r.get('tournament', 'league')}{ph})"
        )
    if args.clear:
        if not args.apply:
            print("\n(dry-run) --clear нужен вместе с --apply")
            return
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        print("\nОчередь очищена.")
        return
    if args.apply:
        kept = [r for r in rows if not any(_same_slot(r, c) for c in done)]
        removed = len(rows) - len(kept)
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(kept, f, ensure_ascii=False, indent=2)
        print(f"\nУдалено из pending (уже completed): {removed}, осталось: {len(kept)}")


if __name__ == "__main__":
    main()
