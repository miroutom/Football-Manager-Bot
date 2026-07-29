#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DEBUG: предложения overall по клубу (без записи в БД).

Пример:
  python3 scripts/debug_ovr_club.py Мю
  python3 scripts/debug_ovr_club.py Сити --limit 12
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    ap = argparse.ArgumentParser(description="DEBUG OVR advice for a club")
    ap.add_argument("team", nargs="?", default="Мю", help="Клуб (как в БД), по умолчанию Мю")
    ap.add_argument("--limit", type=int, default=18)
    ap.add_argument("--min-ovr", type=int, default=78)
    ap.add_argument("--png", action="store_true", help="сохранить monospace PNG")
    args = ap.parse_args()

    from utils.ovr_debug_advice import advise_club_ovr, format_ovr_advice_report

    rows = advise_club_ovr(args.team, min_overall=args.min_ovr, limit=args.limit)
    text = format_ovr_advice_report(args.team, rows)
    print(text)

    # короткий итог
    up = [r for r in rows if r.delta > 0]
    down = [r for r in rows if r.delta < 0]
    stay = [r for r in rows if r.delta == 0]
    print(
        f"Итого: ↑{len(up)}  ↓{len(down)}  ={len(stay)}  "
        f"(показано {len(rows)} игроков, OVR≥{args.min_ovr})"
    )
    if up:
        print("  поднять:", ", ".join(f"{r.name} {r.current}→{r.suggested}" for r in up))
    if down:
        print("  снизить:", ", ".join(f"{r.name} {r.current}→{r.suggested}" for r in down))

    if args.png:
        from bot.image_render import render_monospace_png_bytes

        blobs = render_monospace_png_bytes(text, title=f"DEBUG OVR · {args.team}")
        out_dir = os.path.join(ROOT, "career_poll_reports")
        os.makedirs(out_dir, exist_ok=True)
        for i, blob in enumerate(blobs):
            path = os.path.join(out_dir, f"debug_ovr_{args.team}_{i}.png")
            with open(path, "wb") as f:
                f.write(blob)
            print("PNG:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
