# -*- coding: utf-8 -*-
"""
Таблица лиги / ЛЧ — инфографика с эмблемами клубов.
"""
from __future__ import annotations

import logging
import os
import pickle
from typing import Any

try:
    from PIL import Image, ImageDraw
except ImportError as e:
    raise ImportError("Нужен пакет Pillow: pip install pillow") from e

from bot.report_gfx import (
    draw_header_bar,
    kit_accent_stripe,
    paste_crest,
    pick_font,
    png_bytes,
    theme_for_league,
    truncate,
)

logger = logging.getLogger(__name__)

_HEADER_H = 88
_COL_HDR_H = 32
_ROW_H = 44
_CREST = 32
_PAD = 14

# колонки справа от названия
_STAT_KEYS = ("matches", "wins", "draws", "losses", "scored", "missed", "diff", "points")
_STAT_LABELS = ("И", "В", "Н", "П", "ЗМ", "ПМ", "РМ", "О")
_STAT_W = 42
_NAME_LEFT = 78  # после # и crest
_RANK_W = 36


def collect_standings_rows(
    league_code: str,
    season_num: int | None = None,
) -> tuple[str, list[dict[str, Any]], str | None]:
    """
    Возвращает (title, rows, note).
    row: name, matches, wins, draws, losses, scored, missed, diff, points
    """
    from main import LEAGUES
    from teams import get_sorted_teams
    from utils import season_paths

    league = next((x for x in LEAGUES.values() if x["code"] == league_code), None)
    if not league:
        return f"Неизвестная лига: {league_code}", [], None

    note = None
    if season_num is None:
        teams = league["teams"]
        title = league["name"]
        if league_code == "cl":
            from match_results import compute_cl_group_standings_from_journal

            teams = compute_cl_group_standings_from_journal(teams.keys())
            note = "групповой этап · нокаут не входит"
    else:
        from bot.services import ARCHIVE_PICKLE_BY_LEAGUE

        pkl_name = ARCHIVE_PICKLE_BY_LEAGUE.get(league_code)
        if not pkl_name:
            return f"Неизвестная лига: {league_code}", [], None
        base = season_paths.season_archive_directory(season_num)
        pkl_path = os.path.join(base, "pickle", pkl_name)
        if not os.path.isfile(pkl_path):
            return f"Нет архива сезона {season_num}", [], None
        with open(pkl_path, "rb") as f:
            teams = pickle.load(f)
        title = f"{league['name']} · сезон {season_num}"
        if league_code == "cl":
            from match_results import compute_cl_group_standings_from_journal

            jpath = os.path.join(base, "match_results.json")
            if os.path.isfile(jpath):
                teams = compute_cl_group_standings_from_journal(
                    teams.keys(), journal_path=jpath
                )
            note = "групповой этап · нокаут не входит"

    rows: list[dict[str, Any]] = []
    for name, team in get_sorted_teams(teams):
        diff = int(team.difference)
        rows.append(
            {
                "name": str(name),
                "matches": int(team.matches),
                "wins": int(team.wins),
                "draws": int(team.draws),
                "losses": int(team.losses),
                "scored": int(team.scored),
                "missed": int(team.missed),
                "diff": diff,
                "points": int(team.points),
            }
        )
    return title, rows, note


def render_standings_infographic_png_bytes(
    league_code: str,
    season_num: int | None = None,
) -> list[bytes]:
    title, rows, note = collect_standings_rows(league_code, season_num)
    theme = theme_for_league(league_code)
    if not rows:
        # пустая заглушка
        im = Image.new("RGB", (640, 160), theme.bg)
        draw = ImageDraw.Draw(im)
        draw_header_bar(
            draw, theme=theme, width=640, height=_HEADER_H, title=title or "Таблица", subtitle=note
        )
        draw.text((24, 110), "Нет данных", fill=theme.text_dim, font=pick_font(18))
        return [png_bytes(im)]

    n_stats = len(_STAT_LABELS)
    canvas_w = _NAME_LEFT + 220 + n_stats * _STAT_W + _PAD
    # имя — гибкая ширина
    name_col_w = 200
    canvas_w = _RANK_W + 12 + _CREST + 12 + name_col_w + n_stats * _STAT_W + _PAD * 2

    h = _HEADER_H + _COL_HDR_H + len(rows) * _ROW_H + 12
    im = Image.new("RGB", (canvas_w, h), theme.bg)
    draw = ImageDraw.Draw(im)

    sub = note
    if season_num is None and not note:
        sub = "текущий сезон"
    elif season_num is not None and note:
        sub = note
    elif season_num is not None:
        sub = f"архив · сезон {season_num}"

    draw_header_bar(
        draw,
        theme=theme,
        width=canvas_w,
        height=_HEADER_H,
        title=title,
        subtitle=sub,
    )

    # column headers
    hdr_y0 = _HEADER_H
    hdr_y1 = _HEADER_H + _COL_HDR_H
    draw.rectangle([0, hdr_y0, canvas_w, hdr_y1], fill=theme.row_b if not _dark_bg(theme) else theme.row_a)
    hdr_font = pick_font(12, bold=True)
    name_font = pick_font(18, bold=True)
    val_font = pick_font(17, bold=True)
    rank_font = pick_font(14, bold=True)
    crest_font = pick_font(10, bold=True)

    name_x = _RANK_W + 8 + _CREST + 10
    stat_left = name_x + name_col_w
    fill_hdr = theme.text_dim
    draw.text((name_x, (hdr_y0 + hdr_y1) // 2), "КОМАНДА", fill=fill_hdr, font=hdr_font, anchor="lm")
    for i, lab in enumerate(_STAT_LABELS):
        cx = stat_left + i * _STAT_W + _STAT_W // 2
        col_fill = theme.highlight if lab == "О" else fill_hdr
        draw.text((cx, (hdr_y0 + hdr_y1) // 2), lab, fill=col_fill, font=hdr_font, anchor="mm")

    light = not _dark_bg(theme)
    for i, row in enumerate(rows):
        y0 = hdr_y1 + i * _ROW_H
        y1 = y0 + _ROW_H
        bg = theme.row_a if i % 2 == 0 else theme.row_b
        draw.rectangle([0, y0, canvas_w, y1], fill=bg)
        kit_accent_stripe(draw, team=row["name"], x0=0, y0=y0, y1=y1, width=4)

        cy = y0 + _ROW_H // 2
        draw.text(
            (_RANK_W // 2 + 4, cy),
            str(i + 1),
            fill=theme.text_dim,
            font=rank_font,
            anchor="mm",
        )
        crest_cx = _RANK_W + 8 + _CREST // 2
        paste_crest(
            im,
            draw,
            team=row["name"],
            cx=crest_cx,
            cy=cy,
            size=_CREST,
            crest_font=crest_font,
            light_placeholder=light,
        )
        nm = truncate(draw, str(row["name"]), name_font, name_col_w - 8)
        draw.text((name_x, cy), nm, fill=theme.text, font=name_font, anchor="lm")

        for si, key in enumerate(_STAT_KEYS):
            cx = stat_left + si * _STAT_W + _STAT_W // 2
            val = row[key]
            if key == "diff":
                text = f"+{val}" if val > 0 else str(val)
            else:
                text = str(val)
            fill = theme.highlight if key == "points" else theme.text
            draw.text((cx, cy), text, fill=fill, font=val_font, anchor="mm")

    return [png_bytes(im)]


def _dark_bg(theme) -> bool:
    rgb = theme.bg
    return (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) < 140
