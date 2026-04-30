# -*- coding: utf-8 -*-
"""
PNG «История»: чемпионы — 10 фиксированных колонок; личные награды — 5 колонок,
карточка: прямоугольник с фото (contain, снизу по центру), в углу номер сезона цифрой,
снизу тёмная полоса с именем и фамилией; справа — эмблема клуба, позиция, флаг из БД лиги.

- Без сайдбара «Хронология», без зелёного «газона».
- ЛЧ: фон из ``champions_league/assets/cl_bracket_background.*`` (как у сетки плей-офф), иначе тёмно-синий градиент.
- Нац. лиги: тёмно-синий / сине-фиолетовый градиент.
- Личные награды: тёплый тёмный фон, опционально полупрозрачный трофей по центру.
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
    _FLAG_H,
    _FLAG_W,
    _paste_crest_natural,
    _paste_or_draw_flag,
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
_COLS_AWARD_HISTORY = 5
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


def _paste_photo_contain_bottom_center(
    im: Image.Image,
    photo: Image.Image,
    left: int,
    top: int,
    box_w: int,
    box_h: int,
) -> None:
    """Вписывает фото в прямоугольник как contain, выравнивание снизу по центру."""
    if box_w < 4 or box_h < 4:
        return
    img = photo.convert("RGBA")
    pw, ph = img.size
    if pw < 1 or ph < 1:
        return
    scale = min(box_w / pw, box_h / ph) * 0.96
    nw = max(1, int(round(pw * scale)))
    nh = max(1, int(round(ph * scale)))
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    x0 = int(left + (box_w - nw) // 2)
    y0 = int(top + box_h - nh)
    im.alpha_composite(img, (x0, y0))


def _split_given_family(full: str) -> tuple[str, str]:
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def _lookup_position_nation(
    player_name: str | None, team: str | None
) -> tuple[str | None, str | None]:
    """Позиция и нация из БД национальной лиги (имя + клуб; без клуба — первое совпадение по имени)."""
    if not player_name or not str(player_name).strip():
        return None, None
    try:
        from sqlalchemy import func, or_

        from data.defender import Defender
        from data.forward import Forward
        from data.goalkeeper import Goalkeeper
        from data.midfielder import Midfielder
        from utils.utils import session_league
    except Exception:
        return None, None

    nm = player_name.strip()
    nml = nm.lower()
    raw_t = (team or "").strip()
    tl = raw_t.lower()

    for Cls in (Forward, Midfielder, Defender, Goalkeeper):
        try:
            q = session_league.query(Cls).filter(
                or_(Cls.name == nm, func.lower(Cls.name) == nml)
            )
            if raw_t:
                row = q.filter(
                    or_(Cls.team == raw_t, func.lower(Cls.team) == tl)
                ).first()
                if row is None:
                    row = q.first()
            else:
                row = q.first()
        except Exception:
            logger.debug("award history: skip %s in DB lookup", Cls.__name__, exc_info=True)
            continue
        if row is not None:
            pos = (getattr(row, "position", None) or "").strip() or None
            nat = (getattr(row, "nation", None) or "").strip() or None
            return pos, nat
    return None, None


def _draw_award_nameplate(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    given: str,
    family: str,
) -> None:
    """Тёмная полоса внизу карточки: имя (мельче) и фамилия; шрифт ужимается при нехватке ширины."""
    draw.rectangle((x, y, x + w - 1, y + h - 1), fill=(12, 16, 28))
    max_tw = max(6, w - 8)
    fam_sz, giv_sz = 12, 9
    fn = (family or "—").strip() or "—"
    gn = (given or "").strip()
    fn_t = fn
    gn_t = ""
    fam_font = _pick_font(fam_sz, bold=True)
    giv_font = _pick_font(giv_sz, bold=False)
    for _ in range(8):
        fam_font = _pick_font(fam_sz, bold=True)
        giv_font = _pick_font(giv_sz, bold=False)
        fn_t = _truncate(draw, fn, fam_font, max_tw)
        gn_t = _truncate(draw, gn, giv_font, max_tw) if gn else ""
        ok_f = _text_width(draw, fn_t, fam_font) <= max_tw
        ok_g = (not gn_t) or (_text_width(draw, gn_t, giv_font) <= max_tw)
        if ok_f and ok_g:
            break
        fam_sz = max(8, fam_sz - 1)
        giv_sz = max(7, giv_sz - 1)

    fb = draw.textbbox((0, 0), fn_t, font=fam_font)
    fh = fb[3] - fb[1]
    gh = 0
    if gn_t:
        gb = draw.textbbox((0, 0), gn_t, font=giv_font)
        gh = gb[3] - gb[1]
    gap = 2 if gn_t else 0
    total = fh + gap + gh
    y_text = y + max(2, (h - total) // 2)
    if gn_t:
        gw = _text_width(draw, gn_t, giv_font)
        draw.text(
            (x + (w - gw) // 2, y_text),
            gn_t,
            fill=(200, 205, 220),
            font=giv_font,
        )
        y_text += gh + gap
    fw = _text_width(draw, fn_t, fam_font)
    draw.text(
        (x + (w - fw) // 2, y_text),
        fn_t,
        fill=_TEXT,
        font=fam_font,
    )


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
    cell_gap_y = 12
    cols = _COLS_AWARD_HISTORY
    cell_w_fixed = inner_w // cols

    margin_h = 5
    side_w = 40
    col_gap = 5
    rect_w = max(96, cell_w_fixed - 2 * margin_h - side_w - col_gap)
    rect_h = min(172, max(136, int(rect_w * 0.95)))
    nameplate_h = 36
    card_radius = 7
    cell_h = rect_h + cell_gap_y

    n_rows = (n + cols - 1) // cols
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

    season_corner_font = _pick_font(17, bold=True)
    pos_font = _pick_font(10, bold=True)
    cream = (252, 246, 236)
    cream_edge = (88, 72, 52)

    for idx, entry in enumerate(ordered):
        col = idx % cols
        row = idx // cols
        season = entry[0]
        player = entry[1] if len(entry) > 1 else None
        club = entry[2] if len(entry) > 2 else None
        slug = entry[3] if len(entry) > 3 else None

        x0 = _PAD + col * cell_w_fixed
        y0 = header_bottom + row * cell_h
        x_card = x0 + margin_h
        y_card = y0 + 6

        draw.rounded_rectangle(
            (x_card, y_card, x_card + rect_w - 1, y_card + rect_h - 1),
            radius=card_radius,
            fill=cream,
            outline=cream_edge,
            width=2,
        )

        photo_top = y_card + 20
        photo_bottom = y_card + rect_h - nameplate_h - 3
        photo_h = max(8, photo_bottom - photo_top)
        photo_left = x_card + 4
        photo_w = max(8, rect_w - 8)
        photo = _try_load_photo_rgba(slug)
        if photo is not None:
            _paste_photo_contain_bottom_center(
                im, photo, photo_left, photo_top, photo_w, photo_h
            )
        else:
            msize = min(46, int(photo_w * 0.45), int(photo_h * 0.5))
            _draw_unknown_mark(
                im,
                draw,
                photo_left + photo_w // 2,
                photo_top + photo_h // 2,
                msize,
                light=True,
            )

        ny = y_card + rect_h - nameplate_h
        if player and str(player).strip():
            gv, fm = _split_given_family(str(player).strip())
            _draw_award_nameplate(draw, x_card, ny, rect_w, nameplate_h, gv, fm)
        else:
            _draw_award_nameplate(draw, x_card, ny, rect_w, nameplate_h, "", "—")

        season_txt = str(int(season)) if season is not None else "?"
        sb = draw.textbbox((0, 0), season_txt, font=season_corner_font)
        sw = sb[2] - sb[0]
        draw.text(
            (x_card + rect_w - 6 - sw, y_card + 5),
            season_txt,
            fill=(36, 28, 20),
            font=season_corner_font,
        )

        x_side = x_card + rect_w + col_gap
        col_cx = x_side + side_w // 2
        if player and str(player).strip():
            pos_db, nat_db = _lookup_position_nation(str(player).strip(), club)
            crest_ms = min(32, side_w - 2)
            y_side = y_card + 5
            if club and str(club).strip():
                cy_crest = y_side + crest_ms // 2
                cr = _try_load_crest_rgba(_team_name_as_in_db(str(club).strip()))
                if cr is not None:
                    _paste_crest_natural(im, cr, col_cx, cy_crest, crest_ms)
                else:
                    _draw_unknown_mark(
                        im,
                        draw,
                        col_cx,
                        cy_crest,
                        max(14, crest_ms // 2),
                        light=True,
                    )
                y_side += crest_ms + 8
            pos_line = (pos_db or "—").strip() or "—"
            pos_line = _truncate(draw, pos_line, pos_font, side_w + 8)
            pb = draw.textbbox((0, 0), pos_line, font=pos_font)
            pw = pb[2] - pb[0]
            ph_pos = pb[3] - pb[1]
            draw.text(
                (col_cx - pw // 2, y_side),
                pos_line,
                fill=(32, 26, 18),
                font=pos_font,
            )
            flag_y = y_side + ph_pos + 6
            _paste_or_draw_flag(
                im, draw, int(col_cx - _FLAG_W // 2), int(flag_y), nat_db
            )
        else:
            dash = "—"
            db = draw.textbbox((0, 0), dash, font=pos_font)
            dw = db[2] - db[0]
            draw.text(
                (col_cx - dw // 2, y_card + rect_h // 2 - 6),
                dash,
                fill=(90, 78, 62),
                font=pos_font,
            )

    buf = BytesIO()
    im.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()

