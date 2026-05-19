#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Добавить в data/player_discipline.json поля «с какого момента» недоступен:

- injuries: ``out_from_month`` (null — вручную задать; до задания травма не блокирует игру)
- suspensions: ``unavailable_from_round`` (null — старое поведение «везде дискв»; задать тур)

Запуск из корня проекта:
  python3 scripts/migrate_discipline_effective_from.py
  python3 scripts/migrate_discipline_effective_from.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PATH = _ROOT / "data" / "player_discipline.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not _PATH.is_file():
        print(f"Нет файла {_PATH}", file=sys.stderr)
        return 1
    data = json.loads(_PATH.read_text(encoding="utf-8"))
    inj_n = susp_n = 0
    for row in data.get("injuries", []):
        if "out_from_month" not in row:
            row["out_from_month"] = None
            inj_n += 1
    for row in data.get("suspensions", []):
        if "unavailable_from_round" not in row:
            row["unavailable_from_round"] = None
            susp_n += 1
    print(f"injuries: добавлено out_from_month → {inj_n}")
    print(f"suspensions: добавлено unavailable_from_round → {susp_n}")
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
