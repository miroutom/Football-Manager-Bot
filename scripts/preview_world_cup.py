# -*- coding: utf-8 -*-
"""
Превью Чемпионата мира (не меняет active_season / не пишет победителей в историю).

  python3 scripts/preview_world_cup.py
  python3 scripts/preview_world_cup.py --demo   # демо-чемпион в слоте сезона 4
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    ap = argparse.ArgumentParser(description="Превью ЧМ: БД + PNG истории")
    ap.add_argument(
        "--demo",
        action="store_true",
        help="Показать демо-чемпиона (Аргентина) в сезоне 4",
    )
    ap.add_argument(
        "-o",
        "--output",
        default=os.path.join(_ROOT, "assets", "history", "_preview_world_cup.png"),
        help="Куда сохранить PNG",
    )
    args = ap.parse_args()

    from utils import season_paths
    from utils.world_cup import (
        ensure_world_cup_db,
        is_world_cup_season,
        load_wc_config,
        load_wc_squads,
        next_world_cup_season,
    )
    from bot.history_render import render_wc_history_png

    active = season_paths.get_active_season()
    print(f"active_season = {active}")
    print(f"is_wc_season  = {is_world_cup_season(active)}")
    print(f"next WC       = {next_world_cup_season(active)}")

    cfg = load_wc_config()
    print(f"config notes  = {cfg.get('notes', '')[:80]}")
    squads = load_wc_squads()
    print(f"squad nations = {list((squads.get('teams') or {}).keys()) or '(пусто — сообщите список)'}")

    wc_path = ensure_world_cup_db(4 if is_world_cup_season(4) else next_world_cup_season())
    print(f"world_cup.db  = {wc_path}")

    png = render_wc_history_png(preview_demo=bool(args.demo))
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "wb") as f:
        f.write(png)
    print(f"PNG           = {args.output} ({len(png)} bytes)")
    print()
    print("В боте: История → 🌍 ЧМ")
    print("Сборные пока пусты — формат заявок: data/world_cup_squads.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
