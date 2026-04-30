# -*- coding: utf-8 -*-
"""
PNG «История»: чемпионы — 10 фиксированных колонок; личные награды — 8 колонок,
узкая золотая плашка чуть шире фиксированного кадра фото.

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
# Личные награды — сколько карточек в один ряд
_COLS_AWARD_HISTORY = 8
# Чемпионы лиг / ЛЧ — сколько сезонов в один ряд (узкие ячейки, длинная хронология)
_COLS_CLUB_HISTORY = 10
_PAD = 22
_HEADER_TOP = 20
_TITLE_GAP = 22

_TEXT = (248, 250, 252)
_TEXT_DIM = (186, 198, 210)
_GOLD_PANEL = (218, 170, 45, 220)
_GOLD_PANEL_EDGE = (255, 220, 120, 90)
_GOLD_TEXT = (255, 230, 130)
_GOLD_BRIGHT = (255, 215, 0)


def _club_sentence_case(club: str) -> str:
    """Первая буква заглавная, остальные строчные (Интер, Бавария)."""
    s = (club or "").strip()
    if not s:
        return ""
    return s[0].upper() + s[1:].lower()


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
    """Тёплый тёмный фон — золотисто-коричневый градиент как на референсе."""
    im = Image.new("RGB", (w, h), (44, 34, 20))
    _fill_vertical_gradient_rgb(im, (62, 48, 28), (22, 16, 10))
    return im


def _add_noise_grain(im: Image.Image, intensity: int = 18) -> None:
    """Добавляем лёгкую зернистость для «журнального» вида."""
    import random
    pixels = im.load()
    w, h = im.size
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            noise = random.randint(-intensity, intensity)
            r, g, b = pixels[x, y][:3] if isinstance(pixels[x, y], tuple) and len(pixels[x, y]) >= 3 else (pixels[x, y], pixels[x, y], pixels[x, y])
            pixels[x, y] = (
                max(0, min(255, r + noise)),
                max(0, min(255, g + noise)),
                max(0, min(255, b + noise)),
            )


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


def _scatter_watermark_trophies(im: Image.Image, tro: Image.Image, alpha: int = 20) -> None:
    """Разбрасываем полупрозрачные трофеи по фону для «премиального» вида."""
    w, h = im.size
    positions = [
        (int(w * 0.12), int(h * 0.25)),
        (int(w * 0.88), int(h * 0.20)),
        (int(w * 0.50), int(h * 0.50)),
        (int(w * 0.15), int(h * 0.75)),
        (int(w * 0.85), int(h * 0.78)),
        (int(w * 0.35), int(h * 0.15)),
        (int(w * 0.65), int(h * 0.85)),
    ]
    sizes = [0.18, 0.15, 0.22, 0.14, 0.16, 0.12, 0.13]
    for (px, py), sz in zip(positions, sizes):
        t = tro.copy()
        target = int(min(w, h) * sz)
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
        left = max(0, min(w - nw, px - nw // 2))
        top = max(0, min(h - nh, py - nh // 2))
        im.paste(t, (left, top), t)


def _draw_header(
    draw: ImageDraw.ImageDraw,
    w: int,
    title: str,
    subtitle: str | None,
) -> int:
    """Рисует заголовок по центру; возвращает нижнюю границу блока (y)."""
    title_font = _pick_font(36, bold=True)
    sub_font = _pick_font(18, bold=False)
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
    tmp = Image.new("RGB", (_CANVAS_W, 300))
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
    fill = (30, 36, 48) if not light else (55, 52, 38)
    outline = _GOLD_BRIGHT if light else (200, 210, 225)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill, outline=outline, width=2)
    f = _pick_font(max(14, min(size // 2, 26)), bold=True)
    draw.text((cx, cy), "?", fill=_GOLD_TEXT, font=f, anchor="mm")


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


def _slanted_gold_layer(band_w: int, band_h: int, skew: int | None = None) -> Image.Image:
    """
    Узкий золотой параллелограмм шириной ``band_w`` (чуть шире фото), без растягивания на всю ячейку.
    """
    if band_w < 12 or band_h < 8:
        return Image.new("RGBA", (max(band_w, 1), max(band_h, 1)), (0, 0, 0, 0))
    sk = skew if skew is not None else max(6, min(10, band_w // 14))
    layer = Image.new("RGBA", (band_w, band_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    pts = [
        (sk, 0),
        (band_w, 0),
        (band_w - sk, band_h),
        (0, band_h),
    ]
    d.polygon(pts, fill=(218, 170, 45, 200))
    edge_pts = [
        (sk, 0),
        (min(sk + 5, band_w - 1), 0),
        (min(5, band_w - 1), band_h),
        (0, band_h),
    ]
    d.polygon(edge_pts, fill=(255, 220, 100, 140))
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
    if thumb.mode != "RGBA":
        thumb = thumb.convert("RGBA")
    im.alpha_composite(thumb, (left, top))


def _paste_photo_bust_crop(
    im: Image.Image,
    photo: Image.Image,
    cx: int,
    cy_top: int,
    box_w: int,
    box_h: int,
) -> None:
    """
    Фиксированный кадр ``box_w×box_h``: масштаб как ``cover``, обрезка **сверху**
    (портрет «от головы к поясу» для вертикальных фото).
    """
    if box_w < 4 or box_h < 4:
        return
    img = photo.convert("RGBA")
    pw, ph = img.size
    if pw < 1 or ph < 1:
        return
    scale = max(box_w / pw, box_h / ph)
    nw = max(1, int(round(pw * scale)))
    nh = max(1, int(round(ph * scale)))
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - box_w) // 2)
    top = 0
    if nh < box_h:
        top = 0
        crop_h = nh
    else:
        crop_h = box_h
    crop_w = min(box_w, nw)
    crop_h = min(crop_h, nh)
    img = img.crop((left, top, left + crop_w, top + crop_h))
    if img.size != (box_w, box_h):
        img = img.resize((box_w, box_h), Image.Resampling.LANCZOS)
    w, h = img.size
    im.alpha_composite(img, (int(cx - w // 2), int(cy_top)))


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
    if t.mode != "RGBA":
        t = t.convert("RGBA")
    im.alpha_composite(t, (int(cx - w // 2), int(cy - h // 2)))


def _draw_cell_border(draw: ImageDraw.ImageDraw, x0: int, y0: int, w: int, h: int) -> None:
    """Тонкая золотистая рамка вокруг ячейки."""
    draw.rectangle(
        (x0, y0, x0 + w, y0 + h),
        outline=(180, 145, 50, 120),
        width=2,
    )


def _render_club_grid_png(
        *,
        title: str,
        subtitle: str | None,
        rows: list[tuple[int, str | None]],
        use_cl_background: bool,
) -> bytes:
    """rows: (season, team_or_None) из ``timeline_*`` в порядке 1..N по возрастанию.

    На картинке нужен обратный порядок: **самый новый сезон слева** (в т.ч. неизвестный),
    старые уходят вправо — поэтому ``reversed``.
    """
    ordered = list(reversed(rows))
    n = len(ordered)
    if n == 0:
        ordered = [(get_active_season(), None)]
        n = 1

    inner_w = _CANVAS_W - 2 * _PAD
    cap_font = _pick_font(15, bold=True)
    _tmp = Image.new("RGB", (20, 20))
    _td = ImageDraw.Draw(_tmp)
    _cb_cap = _td.textbbox((0, 0), "Сезон 9", font=cap_font)
    _cap_h = _cb_cap[3] - _cb_cap[1]
    pad_v = 8
    gap_crest_label = 6
    row_gap = 12
    # Ровная сетка: всегда ``cols`` колонок фиксированной ширины (сезон 0 — слева, дальше вправо).
    cols = _COLS_CLUB_HISTORY
    cell_w_fixed = inner_w // cols
    crest_max = min(56, int(cell_w_fixed * 0.62))
    cell_h = pad_v + crest_max + gap_crest_label + _cap_h + pad_v + row_gap
    n_rows = (n + cols - 1) // cols
    header_bottom = _measure_header_bottom(title, subtitle)
    final_h = header_bottom + n_rows * cell_h + _PAD
    if use_cl_background:
        im = _background_cl_rgb(_CANVAS_W, final_h).convert("RGBA")
    else:
        im = _background_league_rgb(_CANVAS_W, final_h).convert("RGBA")
    draw = ImageDraw.Draw(im)
    _draw_header(draw, _CANVAS_W, title, subtitle)
    for idx, (season, team) in enumerate(ordered):
        col = idx % cols
        row = idx // cols
        x0 = _PAD + col * cell_w_fixed
        y0 = header_bottom + row * cell_h
        cx = x0 + cell_w_fixed // 2
        cy_crest = y0 + pad_v + crest_max // 2
        _paste_crest_cell(im, team, cx, cy_crest, crest_max, draw)
        cap = f"Сезон {season}"
        cb = draw.textbbox((0, 0), cap, font=cap_font)
        cw = cb[2] - cb[0]
        draw.text(
            (cx - cw // 2, y0 + pad_v + crest_max + gap_crest_label),
            cap,
            fill=_TEXT,
            font=cap_font,
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
    # timeline_award даёт сезоны 1..N по возрастанию; на экране — новый слева
    ordered = list(reversed(rows))
    n = len(ordered)
    if n == 0:
        ordered = [(get_active_season(), None, None, None)]
        n = 1

    inner_w = _CANVAS_W - 2 * _PAD
    cell_gap_y = 10
    cols = _COLS_AWARD_HISTORY
    cell_w_fixed = inner_w // cols

    n_rows = (n + cols - 1) // cols
    photo_area_h = min(118, max(88, int(cell_w_fixed * 0.48)))
    label_area_h = 56
    cell_h = photo_area_h + label_area_h + cell_gap_y
    # Фото + узкая золотая плашка (фиксированные отступы, не ширина ячейки)
    _gold_pad_each = 6
    photo_box_w = min(108, cell_w_fixed - 2 * _gold_pad_each - 8)
    photo_box_h = photo_area_h - 14
    gold_band_w = photo_box_w + 2 * _gold_pad_each
    title_line = title.upper()
    subtitle_line = "ПОБЕДИТЕЛИ ПО СЕЗОНАМ"
    header_bottom = _measure_header_bottom(title_line, subtitle_line)
    final_h = header_bottom + n_rows * cell_h + _PAD + 10

    im_rgb = _background_award_rgb(_CANVAS_W, final_h)
    im = im_rgb.convert("RGBA")

    tro = _try_load_trophy_rgba(trophy_file)
    if tro is not None:
        _scatter_watermark_trophies(im, tro, alpha=22)

    draw = ImageDraw.Draw(im)
    _draw_header(draw, _CANVAS_W, title_line, subtitle_line)

    name_font = _pick_font(14, bold=True)
    season_font = _pick_font(13, bold=True)

    for idx, entry in enumerate(ordered):
        col = idx % cols
        row = idx // cols
        season = entry[0]
        player = entry[1] if len(entry) > 1 else None
        club = entry[2] if len(entry) > 2 else None
        slug = entry[3] if len(entry) > 3 else None

        x0 = _PAD + col * cell_w_fixed
        y0 = header_bottom + row * cell_h
        cx = x0 + cell_w_fixed // 2

        gold = _slanted_gold_layer(gold_band_w, photo_area_h)
        gold_x = int(cx - gold_band_w // 2)
        im.alpha_composite(gold, (gold_x, y0))

        cy_photo_top = y0 + 6
        photo = _try_load_photo_rgba(slug)
        if photo is not None:
            _paste_photo_bust_crop(
                im, photo, cx, cy_photo_top, photo_box_w, photo_box_h
            )
        else:
            mark_size = min(44, int(photo_box_w * 0.42), int(photo_box_h * 0.55))
            _draw_unknown_mark(
                im,
                draw,
                cx,
                cy_photo_top + photo_box_h // 2,
                mark_size,
                light=True,
            )

        max_tw = cell_w_fixed - 8
        y_label = y0 + photo_area_h + 8

        if player:
            last_name = (
                player.strip().split()[-1].upper() if player.strip() else "—"
            )
            if club:
                line1 = f"{last_name} ({_club_sentence_case(club)})"
            else:
                line1 = last_name
        else:
            line1 = "—"

        line1 = _truncate(draw, line1, name_font, max_tw)
        lb = draw.textbbox((0, 0), line1, font=name_font)
        lw = lb[2] - lb[0]
        lh = lb[3] - lb[1]
        draw.text((cx - lw // 2, y_label), line1, fill=_TEXT, font=name_font)

        line2 = f"{season} СЕЗОН"
        sb = draw.textbbox((0, 0), line2, font=season_font)
        sw = sb[2] - sb[0]
        draw.text(
            (cx - sw // 2, y_label + lh + 8),
            line2,
            fill=_GOLD_TEXT,
            font=season_font,
        )

    buf = BytesIO()
    im.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()

