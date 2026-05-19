#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Травмы: уникальный ``key`` на каждый период (игрок+клуб+с+до), без слияния строк.

Запуск из корня:
  python3 scripts/migrate_injuries_period_keys.py
  python3 scripts/migrate_injuries_period_keys.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PATH = _ROOT / "data" / "player_discipline.json"


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _key(name: str, team: str, out_from: int, ret: int) -> str:
    return f"{_norm(name)}|{_norm(team)}|{out_from}|{ret}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not _PATH.is_file():
        print(f"Нет {_PATH}", file=sys.stderr)
        return 1
    data = json.loads(_PATH.read_text(encoding="utf-8"))
    added_keys = 0
    for inj in data.get("injuries", []):
        ofm = inj.get("out_from_month")
        ret = inj.get("return_month")
        if ofm is None or ret is None:
            continue
        k = _key(
            str(inj.get("name") or ""),
            str(inj.get("team") or ""),
            int(ofm),
            int(ret),
        )
        if inj.get("key") != k:
            inj["key"] = k
            added_keys += 1
    print(f"Обновлено/добавлено key: {added_keys}")
    print(f"Всего периодов травм: {len(data.get('injuries', []))}")
    if args.dry_run:
        print("(dry-run)")
        return 0
    _PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Записано: {_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
