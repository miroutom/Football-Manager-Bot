#!/usr/bin/env python3
"""
Читает экспорт FC24 Live Editor quick_match_score_v5.json (Windows: Desktop/fm_bot_probe).

Примеры:
  python scripts/fc24_read_quick_match_score.py
  python scripts/fc24_read_quick_match_score.py --path "C:/Users/BAZA/Desktop/fm_bot_probe/quick_match_score_v5.json"
  python scripts/fc24_read_quick_match_score.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def default_probe_dir() -> Path:
    profile = os.environ.get("USERPROFILE") or os.environ.get("HOME") or str(Path.home())
    return Path(profile) / "Desktop" / "fm_bot_probe"


def default_json_path() -> Path:
    return default_probe_dir() / "quick_match_score_v5.json"


def load_quick_match_score(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Score file not found: {path}")
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def format_score_line(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        err = data.get("error") or "unknown error"
        return f"ERROR: {err}"
    home = data.get("home_team_name") or f"team_{data.get('home_team_id')}"
    away = data.get("away_team_name") or f"team_{data.get('away_team_id')}"
    hs = data.get("home_score")
    aws = data.get("away_score")
    return f"{home} {hs}:{aws} {away}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read FC24 quick match score export (v5)")
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Path to quick_match_score_v5.json (default: ~/Desktop/fm_bot_probe/...)",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON to stdout")
    parser.add_argument(
        "--watch-dir",
        type=Path,
        default=None,
        help="Probe directory (overrides default Desktop/fm_bot_probe)",
    )
    args = parser.parse_args(argv)

    if args.path:
        json_path = args.path
    elif args.watch_dir:
        json_path = args.watch_dir / "quick_match_score_v5.json"
    else:
        json_path = default_json_path()

    try:
        data = load_quick_match_score(json_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to read score: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_score_line(data))
        if data.get("ok"):
            print(
                f"  home_id={data.get('home_team_id')} "
                f"away_id={data.get('away_team_id')} "
                f"block={data.get('match_block_ptr')}"
            )
        validation = data.get("validation") or {}
        if validation:
            print(f"  validation warnings: {validation}", file=sys.stderr)

    return 0 if data.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
