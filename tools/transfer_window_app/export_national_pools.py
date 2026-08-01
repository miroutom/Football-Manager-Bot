#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Экспорт игроков по нациям (клуб + FA) для Transfer Window App."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.transfer_window_app.national_pools import (  # noqa: E402
    build_all_national_pools,
    write_national_pools_json,
    write_national_pools_txt,
)


def main() -> int:
    out_dir = Path.home() / "Downloads"
    out_dir.mkdir(parents=True, exist_ok=True)
    data = build_all_national_pools()
    txt_path = out_dir / "national_pools.txt"
    json_path = out_dir / "national_pools.json"
    write_national_pools_txt(str(txt_path), data)
    write_national_pools_json(str(json_path), data)
    print(
        f"Сборные: {len(data['nations'])} наций, {data['player_count']} игроков\n"
        f"  {txt_path}\n"
        f"  {json_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
