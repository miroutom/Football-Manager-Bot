# -*- coding: utf-8 -*-
"""CLI: поднять overall игроков РПЛ до пола 75."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--floor", type=int, default=75)
    args = ap.parse_args()

    from utils.raise_rpl_ovr_floor import raise_rpl_overall_floor

    res = raise_rpl_overall_floor(floor=args.floor, dry_run=args.dry_run)
    mode = "DRY-RUN" if args.dry_run else "APPLY"
    print(f"[{mode}] raised {len(res.raised)}, errors {len(res.errors)}")
    for line in res.raised:
        print("  OK", line)
    for line in res.errors:
        print("  ERR", line)
    return 1 if res.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
