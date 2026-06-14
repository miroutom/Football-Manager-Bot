#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Черновик трансферного окна: анализ + таблица рекомендаций (без применения в БД).

  python3 scripts/transfer_market_draft.py              # отчёт из data/transfer_window_draft.json
  python3 scripts/transfer_market_draft.py --analyze    # только снимок потребностей
  python3 scripts/_build_transfer_draft_data.py         # пересобрать JSON из кураторского списка
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="Черновик трансферов (рекомендации, не apply).")
    p.add_argument(
        "--draft",
        type=Path,
        default=None,
        help="Путь к JSON (по умолчанию data/transfer_window_draft.json)",
    )
    p.add_argument(
        "--analyze",
        action="store_true",
        help="Только анализ составов без таблицы переходов",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Куда сохранить markdown (по умолчанию рядом с JSON)",
    )
    args = p.parse_args()

    from utils.transfer_market_draft import (
        DEFAULT_DRAFT_PATH,
        analyze_teams,
        load_draft,
        render_markdown,
        save_markdown_report,
        validate_draft,
    )

    if args.analyze:
        snaps = analyze_teams()
        for code in ("rpl", "eng", "esp", "ita", "ger"):
            print(f"\n=== {code.upper()} ===")
            for s in sorted(
                (x for x in snaps.values() if x.league == code),
                key=lambda x: -x.strength,
            ):
                print(f"{s.team}: сила {s.strength:.1f}, медиана {s.median_ovr:.0f}")
                if s.deficits:
                    print(f"  нужно: {', '.join(s.deficits)}")
                if s.rpl_stars:
                    print(f"  81+: {'; '.join(s.rpl_stars)}")
                for line in s.top_sell[:4]:
                    print(f"  sell? {line}")
        return 0

    draft_path = args.draft or DEFAULT_DRAFT_PATH
    moves = load_draft(draft_path)
    md_path, errors, warnings = save_markdown_report(
        moves, md_path=args.output, json_path=draft_path
    )
    print(f"Переходов: {len(moves)}")
    print(f"Markdown: {md_path}")
    if warnings:
        print(f"Предупреждения (ВРТ): {len(warnings)}")
        for w in warnings[:8]:
            print(f"  ! {w}")
    if errors:
        print(f"Ошибки баланса: {len(errors)}")
        for e in errors[:12]:
            print(f"  ✗ {e}")
        return 1
    print("Баланс 5+5 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
