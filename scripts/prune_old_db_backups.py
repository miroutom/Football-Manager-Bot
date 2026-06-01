#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Удалить каталоги/файлы бэкапов в db/ с датой в имени **строго раньше** сегодня.

  python3 scripts/prune_old_db_backups.py           # dry-run
  python3 scripts/prune_old_db_backups.py --apply
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_ROOT = os.path.join(ROOT, "db")

_DATE_RE = re.compile(r"(20\d{6})")


def _dates_in_name(path: str) -> list[date]:
    out: list[date] = []
    for m in _DATE_RE.finditer(os.path.basename(path)):
        try:
            out.append(date(int(m.group(1)[:4]), int(m.group(1)[4:6]), int(m.group(1)[6:8])))
        except ValueError:
            pass
    return out


def _backup_candidates() -> list[str]:
    found: set[str] = set()
    for dirpath, dirnames, _ in os.walk(DB_ROOT):
        for d in dirnames:
            if "backup" in d.casefold():
                found.add(os.path.join(dirpath, d))
    for dirpath, _, filenames in os.walk(DB_ROOT):
        for fn in filenames:
            if "backup" in fn.casefold() and fn.endswith(".db"):
                found.add(os.path.join(dirpath, fn))
    return sorted(found)


def _should_delete(path: str, today: date) -> bool:
    if "backup" not in os.path.basename(path).casefold():
        return False
    dates = _dates_in_name(path)
    if not dates:
        # нет даты в имени — считаем старым (ручные снимки без метки)
        return True
    return max(dates) < today


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--today",
        default=date.today().strftime("%Y%m%d"),
        help="Граница YYYYMMDD (удаляем всё с датой в имени < этого дня)",
    )
    args = ap.parse_args()
    y, m, d = int(args.today[:4]), int(args.today[4:6]), int(args.today[6:8])
    today = date(y, m, d)

    to_delete = [p for p in _backup_candidates() if _should_delete(p, today)]
    if not to_delete:
        print(f"Нет бэкапов старше {today.isoformat()}.")
        return 0

    total = 0
    for p in to_delete:
        if os.path.isdir(p):
            sz = sum(
                os.path.getsize(os.path.join(dp, f))
                for dp, _, fns in os.walk(p)
                for f in fns
            )
        else:
            sz = os.path.getsize(p) if os.path.isfile(p) else 0
        total += sz
        tag = "DELETE" if args.apply else "would delete"
        print(f"{tag}  {os.path.relpath(p, ROOT)}  ({sz / 1024 / 1024:.1f} MiB)")

    print(f"\nВсего: {len(to_delete)} путей, ~{total / 1024 / 1024:.1f} MiB")
    if not args.apply:
        print("Повторите с --apply.")
        return 0

    for p in to_delete:
        if os.path.isdir(p):
            shutil.rmtree(p)
        elif os.path.isfile(p):
            os.remove(p)
    print("Готово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
