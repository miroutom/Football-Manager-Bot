#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Выровнять person_id лига/ЛЧ (один человек — один id)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.person_id_unify import unify_split_person_ids


def main() -> int:
    dry = "--dry-run" in sys.argv
    if dry:
        from utils.person_id_unify import build_name_team_canonical_map

        canon = build_name_team_canonical_map()
        print(json.dumps({f"{a}|{b}": v for (a, b), v in sorted(canon.items())}, ensure_ascii=False, indent=2))
        print(f"groups to fix: {len(canon)}")
        return 0
    result = unify_split_person_ids(rebuild_common=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
