# -*- coding: utf-8 -*-
"""Превью новых инфографик отчётов (таблицы / топы / травмы)."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tmp_report_preview", help="папка для PNG")
    ap.add_argument("--league", default="rpl")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from bot.standings_infographic import render_standings_infographic_png_bytes
    from bot.player_board_infographic import (
        render_injuries_infographic_png_pages,
        render_season_top_png_pages,
    )

    for code in (args.league, "cl", "eng"):
        blobs = render_standings_infographic_png_bytes(code)
        (out / f"table_{code}.png").write_bytes(blobs[0])
        print("wrote", out / f"table_{code}.png")

    for metric in ("goals", "assists", "ga"):
        blobs = render_season_top_png_pages(args.league, metric=metric)
        (out / f"top_{args.league}_{metric}.png").write_bytes(blobs[0])
        print("wrote", out / f"top_{args.league}_{metric}.png")

    for i, blob in enumerate(render_injuries_infographic_png_pages()):
        (out / f"injuries_{i}.png").write_bytes(blob)
    print("injuries pages done →", out)


if __name__ == "__main__":
    main()
