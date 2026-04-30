# -*- coding: utf-8 -*-
"""PNG «История»: тёмный фон, газонная панель и боковая колонка в духе ``squad_pitch``."""
from __future__ import annotations

import logging
import os
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    raise ImportError("Нужен пакет Pillow: pip install pillow") from e

from bot.season_history_store import timeline_award, timeline_cl, timeline_league
from bot.squad_pitch import (
    _paste_crest_natural,
    _pick_font,
    _team_name_as_in_db,
    _try_load_crest_rgba,
)
from utils.season_paths import get_active_season

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HISTORY_PHOTOS = _PROJECT_ROOT / "assets" / "history" / "photos"
_HISTORY_TROPHIES = _PROJECT_ROOT / "assets" / "history" / "trophies"

_PAGE_BG = (11, 18, 22)
_PAGE_BG_TOP = (17, 28, 34)
_PITCH_FRAME = (71, 85, 105)
_GRASS_LO = (18, 58, 42)
_GRASS_HI = (34, 92, 58)
_SLATE_BRIGHT = (241, 245, 249)
_SLATE_MUTED = (148, 163, 184)
_SIDEBAR_BG = (28, 58, 158)
_SIDEBAR_BG_STRIPE = (22, 48, 130)
_SIDEBAR_EDGE = (96, 165, 250)

_CANVAS_W = 1208
_MARGINS_X = 18
_SIDEBAR_W = 280
_ROW_H = 96
_TOP = 88
_BOTTOM_PAD = 28


def _try_load_photo_rgba(slug: str | None) -> Image.Image | None:
    if not slug:
        return None
    stem = Path(str(slug).strip()).name
    for ext in (".png", ".webp", ".jpg", ".jpeg", ".PNG", ".WEBP", ".JPG"):
        p = _HISTORY_PHOTOS / f"{stem}{ext}"
        if p.is_file():
            try:
                return Image.open(p).convert("RGBA")
            except OSError:
                continue
    return None


def _try_load_trophy_rgba(filename: str) -> Image.Image | None:
    low = filename.lower()
    if low.endswith((".png", ".jpg", ".jpeg", ".webp")):
        candidates = [filename]
    else:
        stem = Path(filename).name
        candidates = [f"{stem}.png", f"{stem}.jpg", f"{stem}.jpeg", f"{stem}.webp"]
    for name in candidates:
        p = _HISTORY_TROPHIES / name
        if not p.is_file():
            continue
        try:
            return Image.open(p).convert("RGBA")
        except OSError:
            continue
    return None


def _draw_unknown_badge(im: Image.Image, draw: ImageDraw.ImageDraw, cx: int, cy: int, side: int) -> None:
    r = side // 2
    draw.ellipse(
        (cx - r, cy - r, cx + r, cy + r),
        fill=(45, 55, 70, 255),
        outline=_SLATE_BRIGHT,
        width=2,
    )
    font = _pick_font(max(22, side // 3), bold=True)
    draw.text((cx, cy), "?", fill=_SLATE_BRIGHT, font=font, anchor="mm")


def _paste_round_thumbnail(im: Image.Image, src: Image.Image, cx: int, cy: int, diam: int) -> None:
    if diam < 8:
        return
    thumb = src.copy()
    thumb.thumbnail((diam, diam), Image.Resampling.LANCZOS)
    w, h = thumb.size
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse((0, 0, w - 1, h - 1), fill=255)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    layer.paste(thumb, (0, 0), thumb)
    layer.putalpha(mask)
    im.alpha_composite(layer, (int(cx - w // 2), int(cy - h // 2)))


def _paste_trophy_thumb(im: Image.Image, tro: Image.Image, cx: int, cy: int, max_h: int) -> None:
    if max_h < 8:
        return
    t = tro.copy()
    th, tw = t.size[1], t.size[0]
    if th > max_h:
        nw = max(1, int(tw * max_h / th))
        t = t.resize((nw, max_h), Image.Resampling.LANCZOS)
    w, h = t.size
    im.alpha_composite(t, (int(cx - w // 2), int(cy - h // 2)))


def _grass_gradient_band(im: Image.Image, y0: int, y1: int, x0: int, x1: int) -> None:
    if y1 <= y0 or x1 <= x0:
        return
    g = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    gd = ImageDraw.Draw(g)
    h = y1 - y0
    for i in range(h):
        t = i / max(1, h - 1)
        r = int(_GRASS_LO[0] + (_GRASS_HI[0] - _GRASS_LO[0]) * t)
        g_ = int(_GRASS_LO[1] + (_GRASS_HI[1] - _GRASS_LO[1]) * t)
        b = int(_GRASS_LO[2] + (_GRASS_HI[2] - _GRASS_LO[2]) * t)
        gd.line([(0, i), (g.size[0], i)], fill=(r, g_, b, 255))
    im.alpha_composite(g, (x0, y0))


def _render_shell(
    title: str,
    subtitle: str | None,
    n_rows: int,
) -> tuple[Image.Image, ImageDraw.ImageDraw, int, int, int]:
    """Возвращает (image, draw, content_x0, content_x1, row0_y)."""
    inner_w = _CANVAS_W - 2 * _MARGINS_X
    pitch_w = inner_w - _SIDEBAR_W - 12
    h = _TOP + n_rows * _ROW_H + _BOTTOM_PAD
    im = Image.new("RGBA", (_CANVAS_W, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    # фон
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(_PAGE_BG[0] + (_PAGE_BG_TOP[0] - _PAGE_BG[0]) * t)
        g = int(_PAGE_BG[1] + (_PAGE_BG_TOP[1] - _PAGE_BG[1]) * t)
        b = int(_PAGE_BG[2] + (_PAGE_BG_TOP[2] - _PAGE_BG[2]) * t)
        draw.line([(0, y), (_CANVAS_W, y)], fill=(r, g, b))
    px0 = _MARGINS_X
    px1 = px0 + pitch_w
    sy0 = 56
    sy1 = h - _BOTTOM_PAD
    draw.rounded_rectangle(
        (px0, sy0, px1, sy1),
        radius=10,
        outline=_PITCH_FRAME,
        width=2,
    )
    _grass_gradient_band(im, sy0 + 4, sy1 - 4, px0 + 4, px1 - 4)
    # боковая панель
    sx0 = px1 + 12
    draw.rounded_rectangle(
        (sx0, sy0, _CANVAS_W - _MARGINS_X, sy1),
        radius=8,
        fill=_SIDEBAR_BG,
        outline=_SIDEBAR_EDGE,
        width=1,
    )
    title_font = _pick_font(30, bold=True)
    sub_font = _pick_font(16, bold=False)
    tw, th = draw.textbbox((0, 0), title, font=title_font)[2:]
    draw.text(
        ((_CANVAS_W - tw) // 2, 18),
        title,
        fill=_SLATE_BRIGHT,
        font=title_font,
    )
    if subtitle:
        sw, _ = draw.textbbox((0, 0), subtitle, font=sub_font)[2:]
        draw.text(
            ((_CANVAS_W - sw) // 2, 18 + th + 4),
            subtitle,
            fill=_SLATE_MUTED,
            font=sub_font,
        )
    # полоски в сайдбаре — подписи
    sb_x = sx0 + 14
    row_y = sy0 + 16
    sb_font = _pick_font(15, bold=True)
    draw.text((sb_x, row_y), "Хронология", fill=_SLATE_BRIGHT, font=sb_font)
    row_y += 36
    hint = _pick_font(13, bold=False)
    draw.text(
        (sb_x, row_y),
        "«?» — сезон\nещё не закрыт\nили данные\nне занесены.",
        fill=_SLATE_MUTED,
        font=hint,
    )
    content_x0 = px0 + 28
    content_x1 = px1 - 28
    row0_y = sy0 + 24
    return im, draw, content_x0, content_x1, row0_y


def render_league_history_png(league_code: str, league_title: str) -> bytes:
    mx = get_active_season()
    rows = timeline_league(league_code, mx)
    im, draw, x0, x1, y0 = _render_shell(league_title, "Чемпионы по сезонам", len(rows))
    crest_slot = 52
    for i, (season, team) in enumerate(rows):
        y = y0 + i * _ROW_H + _ROW_H // 2
        band_top = y0 + i * _ROW_H - 4
        if i % 2 == 0:
            draw.rounded_rectangle(
                (x0 - 8, band_top, x1 + 8, band_top + _ROW_H - 8),
                radius=6,
                fill=(255, 255, 255, 12),
            )
        sf = _pick_font(17, bold=True)
        draw.text((x0, y), f"Сезон {season}", fill=_SLATE_BRIGHT, font=sf, anchor="lm")
        cx = x0 + 200
        if team:
            dbn = _team_name_as_in_db(team)
            cr = _try_load_crest_rgba(dbn)
            if cr is not None:
                _paste_crest_natural(im, cr, cx, y, crest_slot)
            else:
                _draw_unknown_badge(im, draw, cx, y, crest_slot)
        else:
            _draw_unknown_badge(im, draw, cx, y, crest_slot)
        name = team if team else "—"
        nf = _pick_font(20, bold=True)
        draw.text((cx + crest_slot + 36, y), name, fill=_SLATE_BRIGHT, font=nf, anchor="lm")
    buf = BytesIO()
    im.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_cl_history_png() -> bytes:
    mx = get_active_season()
    rows = timeline_cl(mx)
    im, draw, x0, x1, y0 = _render_shell("Лига чемпионов", "Победитель группы (как в таблице бота)", len(rows))
    crest_slot = 52
    for i, (season, team) in enumerate(rows):
        y = y0 + i * _ROW_H + _ROW_H // 2
        band_top = y0 + i * _ROW_H - 4
        if i % 2 == 0:
            draw.rounded_rectangle(
                (x0 - 8, band_top, x1 + 8, band_top + _ROW_H - 8),
                radius=6,
                fill=(255, 255, 255, 12),
            )
        sf = _pick_font(17, bold=True)
        draw.text((x0, y), f"Сезон {season}", fill=_SLATE_BRIGHT, font=sf, anchor="lm")
        cx = x0 + 200
        if team:
            cr = _try_load_crest_rgba(_team_name_as_in_db(team))
            if cr is not None:
                _paste_crest_natural(im, cr, cx, y, crest_slot)
            else:
                _draw_unknown_badge(im, draw, cx, y, crest_slot)
        else:
            _draw_unknown_badge(im, draw, cx, y, crest_slot)
        name = team if team else "—"
        nf = _pick_font(20, bold=True)
        draw.text((cx + crest_slot + 36, y), name, fill=_SLATE_BRIGHT, font=nf, anchor="lm")
    buf = BytesIO()
    im.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


_AWARD_META = {
    "golden_ball": ("Золотой мяч", "ballon_dor"),
    "golden_boot": ("Золотая бутса", "golden_boot"),
    "golden_glove": ("Золотая перчатка", "golden_glove"),
    "golden_boy": ("Golden Boy", "golden_boy"),
}


def render_award_history_png(kind: str) -> bytes:
    if kind not in _AWARD_META:
        kind = "golden_ball"
    title, trophy_file = _AWARD_META[kind]
    mx = get_active_season()
    rows = timeline_award(kind, mx)
    im, draw, x0, x1, y0 = _render_shell(title, "Личная награда по сезонам", len(rows))
    tro = _try_load_trophy_rgba(trophy_file)
    for i, (season, player, club, slug) in enumerate(rows):
        y = y0 + i * _ROW_H + _ROW_H // 2
        band_top = y0 + i * _ROW_H - 4
        if i % 2 == 0:
            draw.rounded_rectangle(
                (x0 - 8, band_top, x1 + 8, band_top + _ROW_H - 8),
                radius=6,
                fill=(255, 255, 255, 10),
            )
        sf = _pick_font(16, bold=True)
        draw.text((x0, y), f"Сезон {season}", fill=_SLATE_BRIGHT, font=sf, anchor="lm")
        tx = x0 + 118
        if tro is not None:
            _paste_trophy_thumb(im, tro, tx, y, 72)
        else:
            draw.text((tx, y), "🏆", fill=_SLATE_BRIGHT, font=_pick_font(28), anchor="mm")
        px = tx + 70
        photo = _try_load_photo_rgba(slug)
        if photo is not None and player:
            _paste_round_thumbnail(im, photo, px + 36, y, 72)
        else:
            _draw_unknown_badge(im, draw, px + 36, y, 64)
        line1 = player if player else "—"
        line2 = club if club else ""
        nf = _pick_font(18, bold=True)
        draw.text((px + 92, y - 14), line1, fill=_SLATE_BRIGHT, font=nf, anchor="lm")
        if line2:
            cf = _pick_font(15, bold=False)
            draw.text((px + 92, y + 14), line2, fill=_SLATE_MUTED, font=cf, anchor="lm")
    buf = BytesIO()
    im.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
