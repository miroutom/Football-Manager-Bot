# -*- coding: utf-8 -*-
"""
Топ-100 за всё время — горизонтальные бары (стиль «Top Goalscorers»).
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
from utils.stats_history_agg import collect_top100_rows

_PAD = 28
_HEADER_H = 108
_ROW_H = 44
_ROWS_PER_PAGE = 25
_RANK_COL_W = 36
_NAME_COL_MAX = 165
_POS_COL_W = 40
_OVR_COL_W = 40
_META_GAP = 8
_BAR_AREA_W = 260
_VALUE_COL_W = 52
_CREST_SIZE = 30

_BG = (252, 252, 254)
_TEXT = (24, 28, 36)
_TEXT_DIM = (100, 108, 124)
_ACCENT = (58, 12, 163)
_BAR_TRACK = (228, 232, 240)

_METRIC_META: dict[int, tuple[str, str, str]] = {
    1: ("ТОП БОМБАРДИРОВ", "голы", "⚽"),
    2: ("ТОП АССИСТЕНТОВ", "передачи", "🎯"),
    3: ("ТОП Г+А", "гол+пас", "📈"),
}


def _metric_value(row: dict, sort_key: int) -> int:
    if sort_key == 2:
        return int(row.get("assists", 0) or 0)
    if sort_key == 3:
        return int(row.get("ga", 0) or 0)
    return int(row.get("goals", 0) or 0)


def _bar_rgb(team: str) -> tuple[int, int, int]:
    kit = kit_for_team(_team_name_as_in_db(team))
    rgb = kit.primary
    lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    if lum > 205:
        if kit.secondary:
            sec = kit.secondary
            lum2 = 0.299 * sec[0] + 0.587 * sec[1] + 0.114 * sec[2]
            if lum2 < 200:
                return sec
        return tuple(max(40, c - 70) for c in rgb)
    return rgb


def _display_name(full_name: str) -> str:
    fn, sn = _name_parts(full_name or "")
    sn_up = (sn or full_name or "?").upper()
    if fn:
        return f"{fn[0].upper()}. {sn_up}"
    return sn_up


def _row_position(row: dict) -> str:
    pos = str(row.get("position") or "").strip().upper()
    return pos or "—"


def _row_overall(row: dict) -> str:
    ovr = int(row.get("overall", 0) or 0)
    return str(ovr) if ovr > 0 else "—"


def _truncate_name(
    draw: ImageDraw.ImageDraw, name: str, font: ImageFont.ImageFont, max_w: int
) -> str:
    s = (name or "").strip()
    if not s:
        return "?"
    if draw.textlength(s, font=font) <= max_w:
        return s
    while len(s) > 2 and draw.textlength(s + "…", font=font) > max_w:
        s = s[:-1]
    return s + "…"


def _draw_ball_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int = 9) -> None:
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(248, 248, 250), outline=(160, 168, 180))
    pr = max(2, r // 3)
    draw.polygon(
        [(cx, cy - pr), (cx + pr, cy + pr // 2), (cx - pr, cy + pr // 2)],
        fill=(40, 44, 52),
    )


def _draw_page(
    *,
    rows: list[dict],
    rank_offset: int,
    global_max: int,
    sort_key: int,
    scope_line: str,
    page_idx: int,
    page_total: int,
    n_cand: int,
) -> bytes:
    title_main, metric_label, _ = _METRIC_META.get(sort_key, ("ТОП-100", "стата", ""))
    n = len(rows)

    title_font = _pick_font(34, bold=True)
    sub_font = _pick_font(17)
    hdr_font = _pick_font(12, bold=True)
    name_font = _pick_font(17, bold=True)
    meta_font = _pick_font(14, bold=True)
    rank_font = _pick_font(15, bold=True)
    val_font = _pick_font(20, bold=True)
    crest_font = _pick_font(11, bold=True)

    tmp = Image.new("RGB", (20, 20))
    tdraw = ImageDraw.Draw(tmp)
    labels = [_display_name(str(r.get("name") or "")) for r in rows]
    name_w = max(
        (int(tdraw.textlength(lbl, font=name_font)) for lbl in labels),
        default=80,
    )
    name_w = min(max(name_w + 8, 90), _NAME_COL_MAX)
    name_x = _PAD + _RANK_COL_W
    meta_left = name_x + name_w + _META_GAP
    pos_cx = meta_left + _POS_COL_W // 2
    ovr_cx = meta_left + _POS_COL_W + _OVR_COL_W // 2
    bar_left = meta_left + _POS_COL_W + _OVR_COL_W + _META_GAP
    bar_right = bar_left + _BAR_AREA_W
    canvas_w = bar_right + _CREST_SIZE + _VALUE_COL_W + _PAD + 20

    h = _PAD + _HEADER_H + n * _ROW_H + _PAD
    im = Image.new("RGB", (canvas_w, max(h, 200)), _BG)
    draw = ImageDraw.Draw(im)

    y0 = _PAD
    draw.text((_PAD, y0), title_main, fill=_ACCENT, font=title_font)
    sub = f"{scope_line} · {metric_label} · кандидатов {n_cand}"
    if page_total > 1:
        sub += f" · стр. {page_idx + 1}/{page_total}"
    draw.text((_PAD, y0 + 42), sub, fill=_TEXT_DIM, font=sub_font)

    hdr_y = _PAD + _HEADER_H - 30
    draw.text((pos_cx, hdr_y), "ПОЗ", fill=_TEXT_DIM, font=hdr_font, anchor="mt")
    draw.text((ovr_cx, hdr_y), "РТГ", fill=_TEXT_DIM, font=hdr_font, anchor="mt")

    bar_max_w = max(80, bar_right - bar_left)
    row_top = _PAD + _HEADER_H

    for i, row in enumerate(rows):
        rank = rank_offset + i + 1
        y = row_top + i * _ROW_H + 6
        cy = y + (_ROW_H - 12) // 2

        draw.text((_PAD, cy), str(rank), fill=_TEXT_DIM, font=rank_font, anchor="lm")

        label = _truncate_name(draw, _display_name(str(row.get("name") or "")), name_font, name_w)
        draw.text((name_x, cy), label, fill=_TEXT, font=name_font, anchor="lm")
        draw.text((pos_cx, cy), _row_position(row), fill=_TEXT_DIM, font=meta_font, anchor="mm")
        draw.text((ovr_cx, cy), _row_overall(row), fill=_TEXT, font=meta_font, anchor="mm")

        val = _metric_value(row, sort_key)
        frac = (val / global_max) if global_max > 0 else 0.0
        bar_w = max(4, int(bar_max_w * frac))
        team = str(row.get("team") or "")
        bar_rgb = _bar_rgb(team)
        track_y1 = cy - 11
        track_y2 = cy + 11
        draw.rounded_rectangle(
            [bar_left, track_y1, bar_right, track_y2],
            radius=8,
            fill=_BAR_TRACK,
        )
        if bar_w > 0:
            draw.rounded_rectangle(
                [bar_left, track_y1, bar_left + bar_w, track_y2],
                radius=8,
                fill=bar_rgb,
            )

        crest_cx = bar_left + bar_w + _CREST_SIZE // 2 + 4
        crest_cy = cy
        team_db = _team_name_as_in_db(team)
        crest = _try_load_crest_rgba(team_db)
        if crest is not None:
            _paste_crest_natural(im, crest, crest_cx, crest_cy, _CREST_SIZE)
        else:
            r = _CREST_SIZE // 2
            draw.ellipse(
                [crest_cx - r, crest_cy - r, crest_cx + r, crest_cy + r],
                fill=bar_rgb,
                outline=(170, 176, 188),
                width=1,
            )
            draw.text(
                (crest_cx, crest_cy),
                _crest_initials(team_db),
                fill=(248, 250, 252),
                font=crest_font,
                anchor="mm",
            )

        val_x = canvas_w - _PAD
        draw.text((val_x, cy), str(val), fill=_TEXT, font=val_font, anchor="rm")
        if sort_key == 1:
            _draw_ball_icon(draw, val_x + 18, cy)

    buf = BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_top100_infographic_png_pages(
    league_code: str,
    sort_key: int = 1,
    limit: int = 100,
    *,
    rows_per_page: int = _ROWS_PER_PAGE,
) -> list[bytes] | str:
    """
    PNG-страницы топ-N или текст ошибки (как ``format_top100_str``).
    """
    scope_line, rows, n_cand, err = collect_top100_rows(
        league_code, limit=limit, sort_key=sort_key
    )
    if err:
        return err
    if not rows:
        return "Нет игроков с голом или передачей."

    global_max = max(_metric_value(r, sort_key) for r in rows) or 1
    chunks: list[list[dict]] = []
    for start in range(0, len(rows), rows_per_page):
        chunks.append(rows[start : start + rows_per_page])
    page_total = len(chunks)

    pages: list[bytes] = []
    for page_idx, chunk in enumerate(chunks):
        pages.append(
            _draw_page(
                rows=chunk,
                rank_offset=page_idx * rows_per_page,
                global_max=global_max,
                sort_key=sort_key,
                scope_line=scope_line or "",
                page_idx=page_idx,
                page_total=page_total,
                n_cand=n_cand,
            )
        )
    return pages
