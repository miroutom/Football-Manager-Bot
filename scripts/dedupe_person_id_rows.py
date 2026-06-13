#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Убрать дубли игроков и выровнять person_id во всех БД."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.person_dedupe import dedupe_all_player_databases


def main() -> None:
    result = dedupe_all_player_databases(rebuild_common=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
