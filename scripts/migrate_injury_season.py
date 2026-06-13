#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проставить ``season`` и обновить ``key`` у травм в data/player_discipline.json.

Записи без ``season`` не блокируют игру (см. utils/player_discipline.py).

Запуск из корня проекта:
  python3 scripts/migrate_injury_season.py --default-season 2
  python3 scripts/migrate_injury_season.py --default-season 2 --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PATH = _ROOT / "data" / "player_discipline.json"


def _norm(s: str) -> str:
    return (s or "").strip().casefold()


def _injury_key(
    name: str,
    team: str,
    out_from_month: int,
    return_month: int,
    season: int,
) -> str:
    return f"{_norm(name)}|{_norm(team)}|{int(season)}|{int(out_from_month)}|{int(return_month)}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--default-season",
        type=int,
        default=2,
        help="Сезон для записей без поля season (по умолчанию 2)",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not _PATH.is_file():
        print(f"Нет файла {_PATH}", file=sys.stderr)
        return 1
    data = json.loads(_PATH.read_text(encoding="utf-8"))
    added = keys = 0
    for row in data.get("injuries", []):
        if row.get("season") is None:
            row["season"] = int(args.default_season)
            added += 1
        season = int(row["season"])
        name = str(row.get("name") or "")
        team = str(row.get("team") or "")
        ofm = row.get("out_from_month")
        ret = row.get("return_month")
        if ofm is None or ret is None:
            continue
        new_key = _injury_key(name, team, int(ofm), int(ret), season)
        if row.get("key") != new_key:
            row["key"] = new_key
            keys += 1
    print(f"season добавлен: {added}, key обновлён: {keys}")
    if args.dry_run:
        print("(dry-run, файл не записан)")
        return 0
    _PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Записано: {_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
