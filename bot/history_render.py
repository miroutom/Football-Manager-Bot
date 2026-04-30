# -*- coding: utf-8 -*-
"""
PNG «История»: сетка как на референсах (клубы — эмблемы + сезон; личные награды — карточка с «золотой» плашкой).

- Без сайдбара «Хронология», без зелёного «газона».
- ЛЧ: фон из ``champions_league/assets/cl_bracket_background.*`` (как у сетки плей-офф), иначе тёмно-синий градиент.
- Нац. лиги: тёмно-синий / сине-фиолетовый градиент.
- Личные награды: тёплый тёмный фон, опционально полупрозрачный трофей по центру, золотой наклонный блок за фото.
- Порядок ячеек: от более нового сезона к старым (слева направо, сверху вниз).
"""
from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
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
_CL_ASSETS_DIR = _PROJECT_ROOT / "champions_league" / "assets"
_CL_BG_CANDIDATES: tuple[Path, ...] = (
    _CL_ASSETS_DIR / "cl_bracket_background.png",
    _CL_ASSETS_DIR / "cl_bracket_background.jpg",
    _CL_ASSETS_DIR / "cl_bracket_background.webp",
)

# Холст под ширину Telegram
_CANVAS_W = 1200
_COLS = 5
_PAD = 22
_HEADER_TOP = 20
_TITLE_GAP = 6

_TEXT = (248, 250, 252)
_TEXT_DIM = (186, 198, 210)
_GOLD_PANEL = (218, 170, 45, 220)
_GOLD_PANEL_EDGE = (255, 220, 120, 90)


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


def _fill_vertical_gradient_rgb(
    im: Image.Image, top: tuple[int, int, int], bottom: tuple[int, int, int]
) -> None:
    w, h = im.size
    draw = ImageDraw.Draw(im)
    hm = max(h - 1, 1)
    for y in range(h):
        t = y / hm
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))


def _resize_cover_crop(bg: Image.Image, tw: int, th: int) -> Image.Image:
    bw, bh = bg.size
    scale = max(tw / bw, th / bh)
    nw = max(1, int(round(bw * scale)))
    nh = max(1, int(round(bh * scale)))
    resized = bg.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - tw) // 2)
    top = max(0, (nh - th) // 2)
    return resized.crop((left, top, left + tw, top + th)).convert("RGB")


def _background_cl_rgb(w: int, h: int) -> Image.Image:
    im = Image.new("RGB", (w, h), (10, 18, 40))
    for p in _CL_BG_CANDIDATES:
        if p.is_file():
            try:
                bg = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
                return _resize_cover_crop(bg, w, h)
            except OSError:
                continue
    _fill_vertical_gradient_rgb(im, (14, 32, 62), (6, 10, 24))
    return im


def _background_league_rgb(w: int, h: int) -> Image.Image:
    im = Image.new("RGB", (w, h), (12, 16, 36))
    _fill_vertical_gradient_rgb(im, (22, 28, 58), (8, 12, 28))
    return im


def _background_award_rgb(w: int, h: int) -> Image.Image:
    im = Image.new("RGB", (w, h), (24, 18, 14))
    _fill_vertical_gradient_rgb(im, (42, 32, 22), (14, 10, 12))
    return im


def _watermark_trophy(im: Image.Image, tro: Image.Image, alpha: int = 35) -> None:
    w, h = im.size
    t = tro.copy()
    target = min(w, h) * 0.55
    tw, th = t.size
    scale = target / max(tw, th)
    nw = max(1, int(tw * scale))
    nh = max(1, int(th * scale))
    t = t.resize((nw, nh), Image.Resampling.LANCZOS)
    if t.mode != "RGBA":
        t = t.convert("RGBA")
    a = t.split()[3]
    a = a.point(lambda p: int(p * alpha / 255))
    t.putalpha(a)
    im.paste(t, ((w - nw) // 2, (h - nh) // 2), t)


def _draw_header(
    draw: ImageDraw.ImageDraw,
    w: int,
    title: str,
    subtitle: str | None,
) -> int:
    """Рисует заголовок по центру; возвращает нижнюю границу блока (y)."""
    title_font = _pick_font(26, bold=True)
    sub_font = _pick_font(14, bold=False)
    y = _HEADER_TOP
    tb = draw.textbbox((0, 0), title, font=title_font)
    tw = tb[2] - tb[0]
    draw.text(((w - tw) // 2, y), title, fill=_TEXT, font=title_font)
    y += tb[3] - tb[1] + _TITLE_GAP
    if subtitle:
        sb = draw.textbbox((0, 0), subtitle, font=sub_font)
        sw = sb[2] - sb[0]
        draw.text(((w - sw) // 2, y), subtitle, fill=_TEXT_DIM, font=sub_font)
        y += sb[3] - sb[1] + 8
    else:
        y += 8
    return y + 8


def _measure_header_bottom(title: str, subtitle: str | None) -> int:
    """Высота блока заголовка (нижний y) для расчёта размера холста."""
    tmp = Image.new("RGB", (_CANVAS_W, 240))
    d = ImageDraw.Draw(tmp)
    return _draw_header(d, _CANVAS_W, title, subtitle)


def _draw_unknown_mark(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    size: int,
    *,
    light: bool = False,
) -> None:
    r = size // 2
    fill = (30, 36, 48) if not light else (55, 62, 78)
    outline = _TEXT if light else (200, 210, 225)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill, outline=outline, width=2)
    f = _pick_font(max(20, size // 2), bold=True)
    draw.text((cx, cy), "?", fill=_TEXT, font=f, anchor="mm")


def _paste_crest_cell(
    im: Image.Image,
    team: str | None,
    cx: int,
    cy: int,
    max_side: int,
    draw: ImageDraw.ImageDraw,
) -> None:
    if team:
        cr = _try_load_crest_rgba(_team_name_as_in_db(team))
        if cr is not None:
            _paste_crest_natural(im, cr, cx, cy, max_side)
            return
    _draw_unknown_mark(im, draw, cx, cy, max_side, light=True)


def _slanted_gold_layer(cell_w: int, cell_h: int, skew: int = 14) -> Image.Image:
    layer = Image.new("RGBA", (cell_w, cell_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    pts = [(skew, 4), (cell_w - 4, 4), (cell_w - skew - 4, cell_h - 16), (4, cell_h - 16)]
    d.polygon(pts, fill=_GOLD_PANEL, outline=_GOLD_PANEL_EDGE)
    return layer


def _paste_photo_in_cell(
    im: Image.Image,
    photo: Image.Image,
    cx: int,
    cy_top: int,
    max_w: int,
    max_h: int,
) -> None:
    thumb = photo.copy()
    thumb.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    w, h = thumb.size
    left = int(cx - w // 2)
    top = int(cy_top)
    im.alpha_composite(thumb, (left, top))


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    b = draw.textbbox((0, 0), text, font=font)
    return b[2] - b[0]


def _truncate(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int) -> str:
    if not text:
        return text
    if _text_width(draw, text, font) <= max_w:
        return text
    ell = "…"
    for i in range(len(text), 0, -1):
        cand = text[:i].rstrip() + ell
        if _text_width(draw, cand, font) <= max_w:
            return cand
    return ell


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


def _render_club_grid_png(
    *,
    title: str,
    subtitle: str | None,
    rows: list[tuple[int, str | None]],
    use_cl_background: bool,
) -> bytes:
    """rows: (season, team_or_None); порядок — новые сезоны первыми."""
    ordered = list(reversed(rows))
    n = len(ordered)
    if n == 0:
        ordered = [(get_active_season(), None)]

    inner_w = _CANVAS_W - 2 * _PAD
    cell_w = inner_w // _COLS
    cell_h = cell_w + 36
    n_rows = (n + _COLS - 1) // _COLS
    header_bottom = _measure_header_bottom(title, subtitle)
    final_h = header_bottom + n_rows * cell_h + _PAD
    if use_cl_background:
        im = _background_cl_rgb(_CANVAS_W, final_h).convert("RGBA")
    else:
        im = _background_league_rgb(_CANVAS_W, final_h).convert("RGBA")
    draw = ImageDraw.Draw(im)
    _draw_header(draw, _CANVAS_W, title, subtitle)
    crest_max = min(64, int(cell_w * 0.62))
    cell_outline = (88, 98, 128)
    for idx, (season, team) in enumerate(ordered):
        col = idx % _COLS
        row = idx // _COLS
        x0 = _PAD + col * cell_w
        y0 = header_bottom + row * cell_h
        cx = x0 + cell_w // 2
        cy_crest = y0 + 8 + crest_max // 2
        xy = (x0 + 2, y0 + 2, x0 + cell_w - 3, y0 + cell_h - 4)
        if hasattr(draw, "rounded_rectangle"):
            draw.rounded_rectangle(xy, radius=8, outline=cell_outline, width=1)
        else:
            draw.rectangle(xy, outline=cell_outline, width=1)
        _paste_crest_cell(im, team, cx, cy_crest, crest_max, draw)
        cap = f"Сезон {season}"
        cf = _pick_font(15, bold=True)
        cb = draw.textbbox((0, 0), cap, font=cf)
        cw = cb[2] - cb[0]
        draw.text(
            (cx - cw // 2, y0 + 12 + crest_max + 4),
            cap,
            fill=_TEXT,
            font=cf,
        )

    buf = BytesIO()
    im.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_league_history_png(league_code: str, league_title: str) -> bytes:
    mx = get_active_season()
    rows = timeline_league(league_code, mx)
    return _render_club_grid_png(
        title=league_title,
        subtitle="Чемпионы по сезонам",
        rows=rows,
        use_cl_background=False,
    )


def render_cl_history_png() -> bytes:
    mx = get_active_season()
    rows = timeline_cl(mx)
    return _render_club_grid_png(
        title="Лига чемпионов",
        subtitle="Победители по сезонам",
        rows=rows,
        use_cl_background=True,
    )


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
    ordered = list(reversed(rows))
    n = len(ordered)
    if n == 0:
        ordered = [(get_active_season(), None, None, None)]

    inner_w = _CANVAS_W - 2 * _PAD
    cell_w = inner_w // _COLS
    cell_h = int(cell_w * 1.35) + 52
    n_rows = (n + _COLS - 1) // _COLS
    title_line = title.upper()
    header_bottom = _measure_header_bottom(title_line, "ПО СЕЗОНАМ")
    final_h = header_bottom + n_rows * cell_h + _PAD
    im_rgb = _background_award_rgb(_CANVAS_W, final_h)
    im = im_rgb.convert("RGBA")
    tro = _try_load_trophy_rgba(trophy_file)
    if tro is not None:
        _watermark_trophy(im, tro, alpha=38)

    draw = ImageDraw.Draw(im)
    _draw_header(draw, _CANVAS_W, title_line, "ПО СЕЗОНАМ")

    photo_max_w = cell_w - 18
    photo_max_h = int(cell_h * 0.48)
    trophy_h = min(52, int(cell_h * 0.28))

    for idx, (season, player, club, slug) in enumerate(ordered):
        col = idx % _COLS
        row = idx // _COLS
        x0 = _PAD + col * cell_w
        y0 = header_bottom + row * cell_h
        cx = x0 + cell_w // 2

        gold = _slanted_gold_layer(cell_w - 8, int(cell_h * 0.72))
        im.alpha_composite(gold, (x0 + 4, y0 + 4))

        cy_photo_top = y0 + 14
        photo = _try_load_photo_rgba(slug)
        if photo is not None:
            _paste_photo_in_cell(im, photo, cx, cy_photo_top, photo_max_w, photo_max_h)
        else:
            _draw_unknown_mark(
                im,
                draw,
                cx,
                cy_photo_top + photo_max_h // 2,
                min(photo_max_w, photo_max_h) - 8,
                light=True,
            )

        if tro is not None:
            _paste_trophy_thumb(
                im,
                tro,
                cx + max(8, cell_w // 2 - 44),
                y0 + 22 + photo_max_h // 2,
                trophy_h,
            )

        line_a = (player or "—").strip().upper()
        if line_a == "—":
            line_a = "—"
        line_b = f"(СЕЗОН {season})"
        name_font = _pick_font(13, bold=True)
        sea_font = _pick_font(12, bold=True)
        max_tw = cell_w - 10
        line_a = _truncate(draw, line_a, name_font, max_tw)
        nb = draw.textbbox((0, 0), line_a, font=name_font)
        nw = nb[2] - nb[0]
        y_label = y0 + int(cell_h * 0.72) + 4
        draw.text((cx - nw // 2, y_label), line_a, fill=_TEXT, font=name_font)
        sb = draw.textbbox((0, 0), line_b, font=sea_font)
        sw = sb[2] - sb[0]
        draw.text((cx - sw // 2, y_label + (nb[3] - nb[1]) + 2), line_b, fill=_TEXT_DIM, font=sea_font)
        if club and player:
            cf = _pick_font(11, bold=False)
            cc = _truncate(draw, club, cf, max_tw)
            cb = draw.textbbox((0, 0), cc, font=cf)
            cw = cb[2] - cb[0]
            draw.text(
                (cx - cw // 2, y_label + (nb[3] - nb[1]) + (sb[3] - sb[1]) + 6),
                cc,
                fill=_TEXT_DIM,
                font=cf,
            )

    buf = BytesIO()
    im.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
