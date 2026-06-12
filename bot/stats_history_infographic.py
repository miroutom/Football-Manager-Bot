# -*- coding: utf-8 -*-
"""
«Стата сезонов» — таблица: эмблема · игрок · матчи · голы · ассисты · Г+А.
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

_HEADER_H = 96
_ROW_H = 46
_CREST_SIZE = 34
_NAME_LEFT = 52
_CREST_CX = 28
_STAT_COL_W = 56
_PAD_RIGHT = 12

_BG = (8, 22, 58)
_ROW_A = (14, 38, 88)
_ROW_B = (18, 48, 102)
_STAT_HDR = (28, 72, 138)
_STAT_CELL = (22, 58, 118)
_TEXT = (255, 255, 255)
_TEXT_DIM = (170, 190, 220)
_TEXT_HIGHLIGHT = (255, 230, 120)

_OUTFIELD_METRICS = frozenset({"g", "goals", "as", "a", "assists", "ga", "g+a"})
_OUTFIELD_HEADERS = ("МАТЧИ", "ГОЛЫ", "АСС", "Г+А")
_SORT_COL_IDX = {
    "g": 1,
    "goals": 1,
    "as": 2,
    "a": 2,
    "assists": 2,
    "ga": 3,
    "g+a": 3,
}

_METRIC_TITLES: dict[str, str] = {
    "g": "БОМБАРДИРЫ",
    "goals": "БОМБАРДИРЫ",
    "as": "АССИСТЕНТЫ",
    "a": "АССИСТЕНТЫ",
    "assists": "АССИСТЕНТЫ",
    "ga": "Г+А",
    "g+a": "Г+А",
    "yc": "ЖЁЛТЫЕ КАРТОЧКИ",
    "rc": "КРАСНЫЕ КАРТОЧКИ",
    "cs": "СУХИЕ МАТЧИ",
}

_SIMPLE_HEADERS: dict[str, tuple[str, str]] = {
    "yc": ("МАТЧИ", "ЖК"),
    "rc": ("МАТЧИ", "КК"),
    "cs": ("МАТЧИ", "СУХИЕ"),
}


def _is_outfield_metric(metric: str) -> bool:
    return (metric or "g").lower() in _OUTFIELD_METRICS


def _display_name(full_name: str) -> str:
    fn, sn = _name_parts(full_name or "")
    sn_up = (sn or full_name or "?").upper()
    if fn:
        return f"{fn[0].upper()}. {sn_up}"
    return sn_up


def _outfield_values(row: dict) -> tuple[int, int, int, int]:
    g = int(row.get("goals", 0) or 0)
    a = int(row.get("assists", 0) or 0)
    ga = int(row.get("ga", 0) or 0) or (g + a)
    return int(row.get("matches", 0) or 0), g, a, ga


def _simple_values(row: dict, metric: str) -> tuple[int, int]:
    m = (metric or "g").lower()
    matches = int(row.get("matches", 0) or 0)
    if m == "yc":
        return matches, int(row.get("yellow_cards", 0) or 0)
    if m == "rc":
        return matches, int(row.get("red_cards", 0) or 0)
    return matches, int(row.get("clean_sheets", 0) or 0)


def _truncate(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int
) -> str:
    s = text or "?"
    if draw.textlength(s, font=font) <= max_w:
        return s
    while len(s) > 2 and draw.textlength(s + "…", font=font) > max_w:
        s = s[:-1]
    return s + "…"


def _paste_crest(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    team: str,
    cx: int,
    cy: int,
    crest_font: ImageFont.ImageFont,
) -> None:
    team_db = _team_name_as_in_db(team)
    kit = kit_for_team(team_db)
    crest = _try_load_crest_rgba(team_db)
    if crest is not None:
        _paste_crest_natural(im, crest, cx, cy, _CREST_SIZE)
        return
    r = _CREST_SIZE // 2
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        fill=kit.primary,
        outline=(120, 140, 180),
        width=1,
    )
    draw.text(
        (cx, cy),
        _crest_initials(team_db),
        fill=_TEXT,
        font=crest_font,
        anchor="mm",
    )


def _layout_for_page(
    rows: list[dict],
    metric: str,
    *,
    name_font: ImageFont.ImageFont,
    draw: ImageDraw.ImageDraw,
) -> tuple[int, int, int, list[str], int]:
    """canvas_w, stat_left, name_max_w, headers, highlight_idx (-1 = none)."""
    m = (metric or "g").lower()
    if _is_outfield_metric(m):
        headers = list(_OUTFIELD_HEADERS)
        highlight = _SORT_COL_IDX.get(m, -1)
        labels = [_display_name(str(r.get("name") or "")) for r in rows]
        name_w = max(
            (int(draw.textlength(lbl, font=name_font)) for lbl in labels),
            default=80,
        )
        name_w = min(max(name_w + 10, 100), 210)
        stat_left = _NAME_LEFT + name_w + 10
        canvas_w = stat_left + len(headers) * _STAT_COL_W + _PAD_RIGHT
        return canvas_w, stat_left, name_w, headers, highlight

    h1, h2 = _SIMPLE_HEADERS.get(m, ("МАТЧИ", "ГОЛЫ"))
    headers = [h1, h2]
    labels = [_display_name(str(r.get("name") or "")) for r in rows]
    name_w = max(
        (int(draw.textlength(lbl, font=name_font)) for lbl in labels),
        default=80,
    )
    name_w = min(max(name_w + 10, 100), 210)
    stat_left = _NAME_LEFT + name_w + 10
    canvas_w = stat_left + 2 * _STAT_COL_W + _PAD_RIGHT
    return canvas_w, stat_left, name_w, headers, 1


def _draw_table_page(
    *,
    title: str,
    rows: list[dict],
    metric: str,
    page_idx: int = 0,
    page_total: int = 1,
) -> bytes:
    m = (metric or "g").lower()
    n = len(rows)

    title_font = _pick_font(30, bold=True)
    sub_font = _pick_font(15)
    hdr_font = _pick_font(12, bold=True)
    name_font = _pick_font(18, bold=True)
    val_font = _pick_font(19, bold=True)
    crest_font = _pick_font(10, bold=True)

    tmp = Image.new("RGB", (20, 20))
    tdraw = ImageDraw.Draw(tmp)
    canvas_w, stat_left, name_max_w, headers, highlight_idx = _layout_for_page(
        rows, m, name_font=name_font, draw=tdraw
    )

    h = _HEADER_H + n * _ROW_H + 8
    im = Image.new("RGB", (canvas_w, max(h, 120)), _BG)
    draw = ImageDraw.Draw(im)

    main_title = f"ТОП {_METRIC_TITLES.get(m, 'СТАТИСТИКА')}"
    draw.text((16, 18), main_title, fill=_TEXT, font=title_font)
    sub_parts: list[str] = []
    if title:
        sub_parts.append(title.split(" — ", 1)[0])
    if page_total > 1:
        sub_parts.append(f"стр. {page_idx + 1}/{page_total}")
    if sub_parts:
        sub = _truncate(draw, " · ".join(sub_parts), sub_font, canvas_w - 32)
        draw.text((16, 56), sub, fill=_TEXT_DIM, font=sub_font)

    hdr_y = _HEADER_H - 34
    draw.rectangle([stat_left, hdr_y, canvas_w, hdr_y + 28], fill=_STAT_HDR)
    col_centers = [
        stat_left + _STAT_COL_W // 2 + i * _STAT_COL_W for i in range(len(headers))
    ]
    for i, hdr in enumerate(headers):
        fill = _TEXT_HIGHLIGHT if i == highlight_idx else _TEXT
        draw.text((col_centers[i], hdr_y + 6), hdr, fill=fill, font=hdr_font, anchor="mt")

    outfield = _is_outfield_metric(m)

    for i, row in enumerate(rows):
        y0 = _HEADER_H + i * _ROW_H
        y1 = y0 + _ROW_H
        row_bg = _ROW_A if i % 2 == 0 else _ROW_B
        draw.rectangle([0, y0, canvas_w, y1], fill=row_bg)
        draw.rectangle([stat_left, y0, canvas_w, y1], fill=_STAT_CELL)

        cy = y0 + _ROW_H // 2
        team = str(row.get("team") or "")
        _paste_crest(im, draw, team=team, cx=_CREST_CX, cy=cy, crest_font=crest_font)

        label = _truncate(
            draw, _display_name(str(row.get("name") or "")), name_font, name_max_w
        )
        draw.text((_NAME_LEFT, cy), label, fill=_TEXT, font=name_font, anchor="lm")

        if outfield:
            vals = _outfield_values(row)
        else:
            vals = _simple_values(row, m)

        for j, val in enumerate(vals):
            fill = _TEXT_HIGHLIGHT if j == highlight_idx else _TEXT
            draw.text(
                (col_centers[j], cy), str(val), fill=fill, font=val_font, anchor="mm"
            )

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
