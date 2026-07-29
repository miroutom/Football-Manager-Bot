# -*- coding: utf-8 -*-
"""CLI: вернуть OVR травмированным с мес. 6+ к зимней выгрузке составов."""
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
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--from-month", type=int, default=6)
    args = ap.parse_args()

    from utils.restore_injury_ovr_winter import restore_injury_ovr_from_winter

    res = restore_injury_ovr_from_winter(
        season=args.season,
        from_month=args.from_month,
        dry_run=args.dry_run,
    )
    mode = "DRY-RUN" if args.dry_run else "APPLY"
    print(f"[{mode}] restore {len(res.restored)}, same {len(res.skipped_same)}, "
          f"missing {len(res.missing_target)}, errors {len(res.errors)}")
    for line in res.restored:
        print("  OK", line)
    for line in res.skipped_same:
        print("  = ", line)
    for line in res.missing_target:
        print("  ??", line)
    for line in res.errors:
        print("  ERR", line)
    return 1 if res.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
