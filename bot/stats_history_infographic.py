# -*- coding: utf-8 -*-
"""
«Стата сезонов» — таблица: эмблема · фамилия · статистика (стиль broadcast-лидерборда).
"""
from __future__ import annotations

import logging
from io import BytesIO

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    raise ImportError("Нужен пакет Pillow: pip install pillow") from e

from bot.squad_pitch import (
    _crest_initials,
    _paste_crest_natural,
    _pick_font,
    _team_name_as_in_db,
    _try_load_crest_rgba,
)
from squad_kit_palette import kit_for_team
from utils.player_names import _name_parts
from utils.stats_history_agg import collect_stats_history_rows

_CANVAS_W = 920
_PAD = 0
_HEADER_H = 96
_ROW_H = 46
_CREST_SIZE = 34
_STAT_COL_W = 92

_BG = (8, 22, 58)
_ROW_A = (14, 38, 88)
_ROW_B = (18, 48, 102)
_STAT_HDR = (28, 72, 138)
_STAT_CELL = (22, 58, 118)
_TEXT = (255, 255, 255)
_TEXT_DIM = (170, 190, 220)

_METRIC_COLS: dict[str, tuple[str, str, str]] = {
    "g": ("БОМБАРДИРЫ", "МАТЧИ", "ГОЛЫ"),
    "goals": ("БОМБАРДИРЫ", "МАТЧИ", "ГОЛЫ"),
    "as": ("АССИСТЕНТЫ", "МАТЧИ", "ПЕРЕДАЧИ"),
    "a": ("АССИСТЕНТЫ", "МАТЧИ", "ПЕРЕДАЧИ"),
    "assists": ("АССИСТЕНТЫ", "МАТЧИ", "ПЕРЕДАЧИ"),
    "ga": ("Г+А", "МАТЧИ", "Г+А"),
    "g+a": ("Г+А", "МАТЧИ", "Г+А"),
    "yc": ("ЖЁЛТЫЕ КАРТОЧКИ", "МАТЧИ", "ЖК"),
    "rc": ("КРАСНЫЕ КАРТОЧКИ", "МАТЧИ", "КК"),
    "cs": ("СУХИЕ МАТЧИ", "МАТЧИ", "СУХИЕ"),
}


def _display_name(full_name: str) -> str:
    fn, sn = _name_parts(full_name or "")
    sn_up = (sn or full_name or "?").upper()
    if fn:
        return f"{fn[0].upper()}. {sn_up}"
    return sn_up


def _stat_values(row: dict, metric: str) -> tuple[int, int]:
    m = (metric or "g").lower()
    matches = int(row.get("matches", 0) or 0)
    if m in ("as", "a", "assists"):
        return matches, int(row.get("assists", 0) or 0)
    if m in ("ga", "g+a"):
        return matches, int(row.get("ga", 0) or 0)
    if m == "yc":
        return matches, int(row.get("yellow_cards", 0) or 0)
    if m == "rc":
        return matches, int(row.get("red_cards", 0) or 0)
    if m == "cs":
        return matches, int(row.get("clean_sheets", 0) or 0)
    return matches, int(row.get("goals", 0) or 0)


def _truncate(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int
) -> str:
    s = text or "?"
    if draw.textlength(s, font=font) <= max_w:
        return s
    while len(s) > 2 and draw.textlength(s + "…", font=font) > max_w:
        s = s[:-1]
    return s + "…"


def _draw_table_page(
    *,
    title: str,
    rows: list[dict],
    metric: str,
    page_idx: int = 0,
    page_total: int = 1,
) -> bytes:
    m = (metric or "g").lower()
    _, col1, col2 = _METRIC_COLS.get(m, ("СТАТИСТИКА", "МАТЧИ", "ГОЛЫ"))
    n = len(rows)
    stat_left = _CANVAS_W - 2 * _STAT_COL_W
    name_left = 56
    name_max_w = stat_left - name_left - 16

    h = _HEADER_H + n * _ROW_H + 8
    im = Image.new("RGB", (_CANVAS_W, max(h, 120)), _BG)
    draw = ImageDraw.Draw(im)

    title_font = _pick_font(30, bold=True)
    sub_font = _pick_font(15)
    hdr_font = _pick_font(13, bold=True)
    name_font = _pick_font(19, bold=True)
    val_font = _pick_font(20, bold=True)
    crest_font = _pick_font(10, bold=True)

    main_title = f"ТОП {_METRIC_COLS.get(m, ('', '', ''))[0]}"
    draw.text((20, 18), main_title, fill=_TEXT, font=title_font)
    sub_parts: list[str] = []
    if title:
        sub_parts.append(title.split(" — ", 1)[0])
    if page_total > 1:
        sub_parts.append(f"стр. {page_idx + 1}/{page_total}")
    if sub_parts:
        sub = _truncate(draw, " · ".join(sub_parts), sub_font, _CANVAS_W - 40)
        draw.text((20, 56), sub, fill=_TEXT_DIM, font=sub_font)

    hdr_y = _HEADER_H - 34
    draw.rectangle([stat_left, hdr_y, _CANVAS_W, hdr_y + 28], fill=_STAT_HDR)
    c1x = stat_left + _STAT_COL_W // 2
    c2x = stat_left + _STAT_COL_W + _STAT_COL_W // 2
    draw.text((c1x, hdr_y + 6), col1, fill=_TEXT, font=hdr_font, anchor="mt")
    draw.text((c2x, hdr_y + 6), col2, fill=_TEXT, font=hdr_font, anchor="mt")

    for i, row in enumerate(rows):
        y0 = _HEADER_H + i * _ROW_H
        y1 = y0 + _ROW_H
        row_bg = _ROW_A if i % 2 == 0 else _ROW_B
        draw.rectangle([0, y0, _CANVAS_W, y1], fill=row_bg)
        draw.rectangle([stat_left, y0, _CANVAS_W, y1], fill=_STAT_CELL)

        cy = y0 + _ROW_H // 2
        team = str(row.get("team") or "")
        team_db = _team_name_as_in_db(team)
        kit = kit_for_team(team_db)
        crest_cx = 30
        crest = _try_load_crest_rgba(team_db)
        if crest is not None:
            _paste_crest_natural(im, crest, crest_cx, cy, _CREST_SIZE)
        else:
            r = _CREST_SIZE // 2
            draw.ellipse(
                [crest_cx - r, cy - r, crest_cx + r, cy + r],
                fill=kit.primary,
                outline=(120, 140, 180),
                width=1,
            )
            draw.text(
                (crest_cx, cy),
                _crest_initials(team_db),
                fill=_TEXT,
                font=crest_font,
                anchor="mm",
            )

        label = _truncate(draw, _display_name(str(row.get("name") or "")), name_font, name_max_w)
        draw.text((name_left, cy), label, fill=_TEXT, font=name_font, anchor="lm")

        v1, v2 = _stat_values(row, m)
        draw.text((c1x, cy), str(v1), fill=_TEXT, font=val_font, anchor="mm")
        draw.text((c2x, cy), str(v2), fill=_TEXT, font=val_font, anchor="mm")

    buf = BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_stats_history_infographic_png(
    scope: str,
    league_code: str,
    metric: str,
    limit: int,
    *,
    season_num: int | None = None,
    role: str | None = None,
    rows_per_page: int = 30,
) -> bytes | str:
    """Одна PNG-страница или текст ошибки."""
    pages = render_stats_history_infographic_pages(
        scope,
        league_code,
        metric,
        limit,
        season_num=season_num,
        role=role,
        rows_per_page=rows_per_page,
    )
    if isinstance(pages, str):
        return pages
    if not pages:
        return "Нет данных."
    return pages[0]


def render_stats_history_infographic_pages(
    scope: str,
    league_code: str,
    metric: str,
    limit: int,
    *,
    season_num: int | None = None,
    role: str | None = None,
    rows_per_page: int = 30,
) -> list[bytes] | str:
    title, rows, err = collect_stats_history_rows(
        scope,
        league_code,
        metric,
        limit,
        season_num=season_num,
        role=role,
    )
    if err:
        return err
    if not rows:
        return "Нет данных."

    chunks: list[list[dict]] = []
    for start in range(0, len(rows), rows_per_page):
        chunks.append(rows[start : start + rows_per_page])
    page_total = len(chunks)
    return [
        _draw_table_page(
            title=title,
            rows=chunk,
            metric=metric,
            page_idx=idx,
            page_total=page_total,
        )
        for idx, chunk in enumerate(chunks)
    ]
