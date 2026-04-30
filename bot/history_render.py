# -*- coding: utf-8 -*-
"""
PNG «История»: чемпионы — 10 колонок; личные награды — 5 колонок,
карточки в стиле FUT: прямоугольник, фото (обрезка голова-по-пояс),
номер сезона в углу, эмблема + позиция + флаг слева внутри,
тёмная полоса с именем/фамилией снизу.

Цветовая гамма: тёплые золотисто-бежевые тона.
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

# ─── Пути к ассетам ───────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HISTORY_PHOTOS = _PROJECT_ROOT / "assets" / "history" / "photos"
_HISTORY_TROPHIES = _PROJECT_ROOT / "assets" / "history" / "trophies"
_CL_ASSETS_DIR = _PROJECT_ROOT / "champions_league" / "assets"
_CL_BG_CANDIDATES: tuple[Path, ...] = (
    _CL_ASSETS_DIR / "cl_bracket_background.png",
    _CL_ASSETS_DIR / "cl_bracket_background.jpg",
    _CL_ASSETS_DIR / "cl_bracket_background.webp",
)

# ─── Константы холста ─────────────────────────────────────────────
_CANVAS_W = 1200
_COLS_AWARD = 5
_COLS_CLUB = 10
_PAD = 22
_HEADER_TOP = 20
_TITLE_GAP = 22

# ─── Цвета — тёплая золотисто-бежевая гамма ──────────────────────
_TEXT = (248, 250, 252)
_TEXT_DIM = (186, 198, 210)
_GOLD_TEXT = (255, 230, 130)
_GOLD_BRIGHT = (255, 215, 0)

_CARD_BG = (32, 44, 62)              # тёмно-синий стальной
_CARD_BORDER = (70, 95, 130)         # синеватая рамка
_CARD_NAMEPLATE = (16, 22, 34)       # тёмная полоса снизу
_CARD_NAMEPLATE_BORDER = (70, 95, 130)  # рамка nameplate = рамка карточки
_SEASON_CIRCLE_STROKE = (70, 95, 130)   # обводка круга = рамка карточки
_SEASON_CIRCLE_FILL = (22, 32, 48)      # заливка круга
_SEASON_COLOR = (255, 235, 130)       # золотая цифра
_POS_TEXT = (210, 200, 170)           # текст позиции без плашки
_POS_BORDER = (130, 110, 60)         # линия-разделитель nameplate

# ── Фиксированные размеры карточки (НЕ зависят от количества) ────
_CARD_W_FIXED = 148                     # ширина карточки px
_CARD_H_FIXED = 185                     # высота карточки px
_NAMEPLATE_H_FIXED = 38                 # высота полосы имени


# ═══════════════════════════════════════════════════════════════════
#  Загрузка ассетов
# ═══════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════
#  Обрезка фото: голова-по-пояс, единый размер
# ═══════════════════════════════════════════════════════════════════

def _crop_head_to_waist(
    photo: Image.Image,
    target_w: int,
    target_h: int,
) -> Image.Image:
    """
    Обрезает фото «голова по пояс»:
    - Портрет: берём верхние 65%
    - Альбом: берём верхние 85%
    - Center-crop до пропорций target
    - Ресайз до target_w × target_h
    """
    img = photo.convert("RGBA")
    pw, ph = img.size

    # Отсекаем ноги
    if pw > ph:
        crop_bottom = int(ph * 0.85)
    else:
        crop_bottom = int(ph * 0.65)
    crop_bottom = max(crop_bottom, target_h)
    crop_bottom = min(crop_bottom, ph)
    img = img.crop((0, 0, pw, crop_bottom))
    pw, ph = img.size

    # Center-crop до пропорций target
    target_ratio = target_w / target_h
    current_ratio = pw / ph

    if current_ratio > target_ratio:
        new_w = int(ph * target_ratio)
        left = (pw - new_w) // 2
        img = img.crop((left, 0, left + new_w, ph))
    elif current_ratio < target_ratio:
        new_h = int(pw / target_ratio)
        img = img.crop((0, 0, pw, new_h))

    img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
    return img


# ═══════════════════════════════════════════════════════════════════
#  Фоны
# ═══════════════════════════════════════════════════════════════════

def _fill_vertical_gradient_rgb(
    im: Image.Image, top: tuple[int, int, int], bottom: tuple[int, int, int],
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
    im = Image.new("RGB", (w, h), (44, 34, 20))
    _fill_vertical_gradient_rgb(im, (52, 42, 24), (18, 14, 8))
    return im


def _scatter_watermark_trophies(im: Image.Image, tro: Image.Image, alpha: int = 20) -> None:
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
        top_y = max(0, min(h - nh, py - nh // 2))
        im.paste(t, (left, top_y), t)


# ═══════════════════════════════════════════════════════════════════
#  Заголовок
# ═══════════════════════════════════════════════════════════════════

def _draw_header(
    draw: ImageDraw.ImageDraw, w: int, title: str, subtitle: str | None,
) -> int:
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
    tmp = Image.new("RGB", (_CANVAS_W, 300))
    d = ImageDraw.Draw(tmp)
    return _draw_header(d, _CANVAS_W, title, subtitle)


# ═══════════════════════════════════════════════════════════════════
#  Утилиты текста
# ═══════════════════════════════════════════════════════════════════

def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    b = draw.textbbox((0, 0), text, font=font)
    return b[2] - b[0]


def _text_height(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    b = draw.textbbox((0, 0), text, font=font)
    return b[3] - b[1]


def _truncate(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> str:
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


# ═══════════════════════════════════════════════════════════════════
#  Вспомогательные функции рисования
# ═══════════════════════════════════════════════════════════════════

def _draw_unknown_mark(
    im: Image.Image, draw: ImageDraw.ImageDraw,
    cx: int, cy: int, size: int, *, light: bool = False,
) -> None:
    r = size // 2
    fill = (55, 48, 32) if light else (30, 36, 48)
    outline = (130, 110, 60) if light else (200, 210, 225)
    draw.ellipse(
        (cx - r, cy - r, cx + r, cy + r),
        fill=fill, outline=outline, width=2,
    )
    f = _pick_font(max(14, min(size // 2, 26)), bold=True)
    draw.text(
        (cx, cy), "?",
        fill=_SEASON_COLOR if light else _TEXT,
        font=f, anchor="mm",
    )


def _paste_crest_cell(
    im: Image.Image, team: str | None, cx: int, cy: int,
    max_side: int, draw: ImageDraw.ImageDraw,
) -> None:
    if team:
        cr = _try_load_crest_rgba(_team_name_as_in_db(team))
        if cr is not None:
            _paste_crest_natural(im, cr, cx, cy, max_side)
            return
    _draw_unknown_mark(im, draw, cx, cy, max_side, light=True)


def _split_given_family(full: str) -> tuple[str, str]:
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def _lookup_position_nation(
    player_name: str | None, team: str | None,
) -> tuple[str | None, str | None]:
    """
    Позиция и нация из БД национальных лиг.

    В JSON имя может быть полным («Лаутаро Мартинез»),
    а в БД — только фамилия («Мартинез»).
    Поэтому ищем по:
      1) полному имени
      2) только фамилии (последнее слово)
      3) только имени (первое слово) — на случай «Рёль» vs «Мерлин Рёль»
    """
    if not player_name or not str(player_name).strip():
        logger.debug("_lookup_position_nation: пустое имя")
        return None, None

    nm = player_name.strip()
    raw_t = (team or "").strip()

    try:
        from sqlalchemy import func, or_
        from data.defender import Defender
        from data.forward import Forward
        from data.goalkeeper import Goalkeeper
        from data.midfielder import Midfielder
        from utils.utils import session_league
    except Exception as exc:
        logger.warning("_lookup_position_nation: не удалось импортировать БД: %s", exc)
        return None, None

    # Собираем варианты имени для поиска
    parts = nm.split()
    search_names: list[str] = [nm]                    # «Лаутаро Мартинез»
    if len(parts) > 1:
        search_names.append(parts[-1])                # «Мартинез» — фамилия
        search_names.append(parts[0])                 # «Лаутаро» — имя
    # Убираем дубли, сохраняя порядок
    seen: set[str] = set()
    unique_names: list[str] = []
    for s in search_names:
        sl = s.lower()
        if sl not in seen:
            seen.add(sl)
            unique_names.append(s)

    tl = raw_t.lower()

    for Cls in (Forward, Midfielder, Defender, Goalkeeper):
        for candidate in unique_names:
            try:
                cl = candidate.lower()
                q = session_league.query(Cls).filter(
                    or_(
                        Cls.name == candidate,
                        func.lower(Cls.name) == cl,
                    )
                )
                # Сначала с фильтром по клубу
                if raw_t:
                    row = q.filter(
                        or_(Cls.team == raw_t, func.lower(Cls.team) == tl)
                    ).first()
                    if row is None:
                        row = q.first()
                else:
                    row = q.first()

                if row is not None:
                    pos = (getattr(row, "position", None) or "").strip() or None
                    nat = (getattr(row, "nation", None) or "").strip() or None
                    logger.debug(
                        "_lookup: %s → matched '%s' in %s → pos=%s nat=%s",
                        nm, candidate, Cls.__name__, pos, nat,
                    )
                    return pos, nat
            except Exception:
                logger.debug(
                    "_lookup: ошибка %s / '%s'",
                    Cls.__name__, candidate, exc_info=True,
                )
                continue

    logger.debug("_lookup_position_nation: '%s' не найден ни в одной таблице", nm)
    return None, None


def _paste_trophy_thumb(
    im: Image.Image, tro: Image.Image, cx: int, cy: int, max_h: int,
) -> None:
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


# ═══════════════════════════════════════════════════════════════════
#  Сетка клубов (Лиги + ЛЧ) — 10 колонок
# ═══════════════════════════════════════════════════════════════════

def _render_club_grid_png(
    *, title: str, subtitle: str | None,
    rows: list[tuple[int, str | None]], use_cl_background: bool,
) -> bytes:
    ordered = list(reversed(rows))
    n = len(ordered)
    if n == 0:
        ordered = [(get_active_season(), None)]
        n = 1

    cols = _COLS_CLUB
    inner_w = _CANVAS_W - 2 * _PAD
    cell_w = inner_w // cols
    crest_max = min(56, int(cell_w * 0.62))
    cap_font = _pick_font(15, bold=True)

    _tmp = Image.new("RGB", (20, 20))
    _td = ImageDraw.Draw(_tmp)
    _cb = _td.textbbox((0, 0), "Сезон 9", font=cap_font)
    _cap_h = _cb[3] - _cb[1]

    pad_v = 8
    gap = 6
    row_gap = 12
    cell_h = pad_v + crest_max + gap + _cap_h + pad_v + row_gap
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
        x0 = _PAD + col * cell_w
        y0 = header_bottom + row * cell_h
        cx = x0 + cell_w // 2
        cy_crest = y0 + pad_v + crest_max // 2
        _paste_crest_cell(im, team, cx, cy_crest, crest_max, draw)
        cap = f"Сезон {season}"
        cb = draw.textbbox((0, 0), cap, font=cap_font)
        cw = cb[2] - cb[0]
        draw.text(
            (cx - cw // 2, y0 + pad_v + crest_max + gap),
            cap, fill=_TEXT, font=cap_font,
        )

    buf = BytesIO()
    im.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_league_history_png(league_code: str, league_title: str) -> bytes:
    mx = get_active_season()
    rows = timeline_league(league_code, mx)
    return _render_club_grid_png(
        title=league_title, subtitle="Чемпионы по сезонам",
        rows=rows, use_cl_background=False,
    )


def render_cl_history_png() -> bytes:
    mx = get_active_season()
    rows = timeline_cl(mx)
    return _render_club_grid_png(
        title="Лига чемпионов", subtitle="Победители по сезонам",
        rows=rows, use_cl_background=True,
    )


# ═══════════════════════════════════════════════════════════════════
#  Личные награды — карточки FUT
# ═══════════════════════════════════════════════════════════════════
#
#  ┌──────────────────────────────┐
#  │ [ЭМБЛЕМА 36px]        [1]   │  ← крупная золотая цифра
#  │                              │
#  │ ┌───────┐                    │
#  │ │  POS  │  золотая плашка    │
#  │ └───────┘                    │
#  │ [🇦🇷 флаг]                  │
#  │                              │
#  │      ┌──────────────┐        │
#  │      │              │        │
#  │      │    ФОТО      │        │  ← строго НАД nameplate
#  │      │  (по пояс)   │        │
#  │      └──────────────┘        │
#  ├──────────────────────────────┤  ← золотая линия
#  │       Лаутаро                │
#  │      Мартинез                │  ← увеличенная полоса 50px
#  └──────────────────────────────┘

_AWARD_META = {
    "golden_ball": ("Золотой мяч", "ballon_dor"),
    "golden_boot": ("Золотая бутса", "golden_boot"),
    "golden_glove": ("Золотая перчатка", "golden_glove"),
    "golden_boy": ("Golden Boy", "golden_boy"),
}


def _draw_award_card(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    x0: int, y0: int,
    card_w: int, card_h: int,
    nameplate_h: int,
    *,
    season: int,
    player: str | None,
    club: str | None,
    slug: str | None,
    season_font,
    pos_font,
    given_font,
    family_font,
) -> None:
    """Рисует одну карточку награды — фиксированный компактный размер."""
    card_radius = 5
    info_pad = 6
    icon_size = 28       # единый размер: эмблема, текст позиции, флаг
    item_gap = 3         # зазор между элементами в левой колонке
    circle_r = 16        # радиус круга сезона — КРУПНЫЙ

    x1 = x0 + card_w - 1
    y1 = y0 + card_h - 1

    # ── 1. Фон карточки ──
    draw.rounded_rectangle(
        (x0, y0, x1, y1),
        radius=card_radius,
        fill=_CARD_BG,
        outline=_CARD_BORDER,
        width=2,
    )

    # ── 2. Номер сезона — круг в правом верхнем углу ──
    season_txt = str(int(season)) if season is not None else "?"
    circle_cx = x1 - circle_r - 5
    circle_cy = y0 + circle_r + 3
    draw.ellipse(
        (circle_cx - circle_r, circle_cy - circle_r,
         circle_cx + circle_r, circle_cy + circle_r),
        fill=_SEASON_CIRCLE_FILL,
        outline=_SEASON_CIRCLE_STROKE,
        width=2,
    )
    draw.text(
        (circle_cx, circle_cy), season_txt,
        fill=_SEASON_COLOR, font=season_font, anchor="mm",
    )

    # ── 3. Левая колонка: эмблема, позиция, флаг — ВЫРОВНЕНЫ по центру icon_size ──
    col_cx = x0 + info_pad + icon_size // 2    # центр колонки
    info_y = y0 + 7

    # 3a. Эмблема клуба — центрирована
    if club and str(club).strip():
        cr = _try_load_crest_rgba(_team_name_as_in_db(str(club).strip()))
        if cr is not None:
            _paste_crest_natural(im, cr, col_cx, info_y + icon_size // 2, icon_size)
    info_y += icon_size + item_gap

    # Позиция и нация из БД
    pos_db, nat_db = None, None
    if player and str(player).strip():
        pos_db, nat_db = _lookup_position_nation(str(player).strip(), club)

    # 3b. Позиция — текст, центрирован в колонке
    if pos_db:
        pos_txt = pos_db.upper()
        ptb = draw.textbbox((0, 0), pos_txt, font=pos_font)
        p_w = ptb[2] - ptb[0]
        p_h = ptb[3] - ptb[1]
        draw.text(
            (col_cx - p_w // 2, info_y + (icon_size - p_h) // 2),
            pos_txt, fill=_POS_TEXT, font=pos_font,
        )
    else:
        dash_f = _pick_font(10, bold=False)
        db = draw.textbbox((0, 0), "—", font=dash_f)
        dw = db[2] - db[0]
        draw.text(
            (col_cx - dw // 2, info_y + (icon_size - (db[3] - db[1])) // 2),
            "—", fill=_INFO_TEXT_DIM, font=dash_f,
        )
    info_y += icon_size + item_gap

    # 3c. Флаг нации — центрирован
    if nat_db:
        flag_x = col_cx - _FLAG_W // 2
        _paste_or_draw_flag(im, draw, int(flag_x), int(info_y + (icon_size - _FLAG_H) // 2), nat_db)
    else:
        # Заглушка
        fw, fh = min(_FLAG_W, icon_size), min(_FLAG_H, icon_size - 4)
        fx = col_cx - fw // 2
        fy = info_y + (icon_size - fh) // 2
        draw.rectangle(
            (fx, fy, fx + fw, fy + fh),
            fill=(40, 40, 42), outline=(60, 58, 52),
        )

    # ── 4. Фото — строго НАД nameplate ──
    photo_margin = 3
    photo_area_top = y0 + photo_margin
    photo_area_bottom = y1 - nameplate_h - 4
    photo_area_h = max(8, photo_area_bottom - photo_area_top)
    photo_area_left = x0 + photo_margin
    photo_area_w = max(8, card_w - photo_margin * 2)

    photo = _try_load_photo_rgba(slug)
    if photo is not None:
        cropped = _crop_head_to_waist(photo, photo_area_w, photo_area_h)
        if cropped.mode != "RGBA":
            cropped = cropped.convert("RGBA")
        im.alpha_composite(cropped, (photo_area_left, photo_area_top))
    else:
        mark_sz = min(32, int(photo_area_w * 0.28), int(photo_area_h * 0.28))
        _draw_unknown_mark(
            im, draw,
            x0 + card_w // 2,
            photo_area_top + photo_area_h // 2,
            mark_sz, light=True,
        )

    # ── 5. Тёмная полоса снизу С РАМКОЙ ──
    np_y = y1 - nameplate_h + 1
    draw.rounded_rectangle(
        (x0 + 1, np_y, x1 - 1, y1 - 1),
        radius=card_radius,
        fill=_CARD_NAMEPLATE,
        outline=_CARD_NAMEPLATE_BORDER,
        width=1,
    )
    draw.rectangle(
        (x0 + 2, np_y, x1 - 2, np_y + card_radius),
        fill=_CARD_NAMEPLATE,
    )
    draw.line(
        [(x0 + 2, np_y), (x1 - 2, np_y)],
        fill=_CARD_NAMEPLATE_BORDER, width=1,
    )

    max_tw = card_w - 10
    cx = x0 + card_w // 2

    if player and str(player).strip():
        given, family = _split_given_family(str(player).strip())
    else:
        given, family = "", "—"

    fam_sz = 12
    giv_sz = 9
    for _ in range(8):
        fam_f = _pick_font(fam_sz, bold=True)
        giv_f = _pick_font(giv_sz, bold=False)
        fam_t = _truncate(draw, family, fam_f, max_tw)
        giv_t = _truncate(draw, given, giv_f, max_tw) if given else ""
        if (_text_width(draw, fam_t, fam_f) <= max_tw and
                (not giv_t or _text_width(draw, giv_t, giv_f) <= max_tw)):
            break
        fam_sz = max(8, fam_sz - 1)
        giv_sz = max(7, giv_sz - 1)
    else:
        fam_f = _pick_font(fam_sz, bold=True)
        giv_f = _pick_font(giv_sz, bold=False)
        fam_t = _truncate(draw, family, fam_f, max_tw)
        giv_t = _truncate(draw, given, giv_f, max_tw) if given else ""

    fam_h = _text_height(draw, fam_t, fam_f)
    giv_h = _text_height(draw, giv_t, giv_f) if giv_t else 0
    gap_lines = 2 if giv_t else 0
    total_h = giv_h + gap_lines + fam_h
    ty = np_y + max(3, (nameplate_h - total_h) // 2)

    if giv_t:
        gw = _text_width(draw, giv_t, giv_f)
        draw.text(
            (cx - gw // 2, ty),
            giv_t, fill=(170, 168, 158), font=giv_f,
        )
        ty += giv_h + gap_lines

    fw = _text_width(draw, fam_t, fam_f)
    draw.text(
        (cx - fw // 2, ty),
        fam_t, fill=_TEXT, font=fam_f,
    )


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
        n = 1

    cols = _COLS_AWARD   # 5

    # ── ФИКСИРОВАННЫЕ размеры карточки ──
    card_w = _CARD_W_FIXED           # 148
    card_h = _CARD_H_FIXED           # 185
    nameplate_h = _NAMEPLATE_H_FIXED # 38

    # Зазоры между карточками
    inner_w = _CANVAS_W - 2 * _PAD
    total_cards_w = cols * card_w
    cell_gap = max(6, (inner_w - total_cards_w) // (cols + 1))
    cell_w = card_w + cell_gap
    # Центрируем сетку
    grid_w = cols * cell_w
    grid_left = _PAD + (inner_w - grid_w) // 2

    cell_h = card_h + cell_gap

    n_rows = (n + cols - 1) // cols
    title_line = title.upper()
    subtitle_line = "ПОБЕДИТЕЛИ ПО СЕЗОНАМ"
    header_bottom = _measure_header_bottom(title_line, subtitle_line)
    final_h = header_bottom + n_rows * cell_h + _PAD + 10

    im_rgb = _background_award_rgb(_CANVAS_W, final_h)
    im = im_rgb.convert("RGBA")

    tro = _try_load_trophy_rgba(trophy_file)
    if tro is not None:
        _scatter_watermark_trophies(im, tro, alpha=18)

    draw = ImageDraw.Draw(im)
    _draw_header(draw, _CANVAS_W, title_line, subtitle_line)

    # Шрифты
    season_font = _pick_font(18, bold=True)   # крупный в круге
    pos_font = _pick_font(11, bold=True)
    given_font = _pick_font(9, bold=False)
    family_font = _pick_font(12, bold=True)

    for idx, entry in enumerate(ordered):
        season = entry[0]
        player = entry[1] if len(entry) > 1 else None
        club = entry[2] if len(entry) > 2 else None
        slug = entry[3] if len(entry) > 3 else None

        col = idx % cols
        row = idx // cols
        x0 = grid_left + col * cell_w + cell_gap // 2
        y0 = header_bottom + row * cell_h

        _draw_award_card(
            im, draw, x0, y0, card_w, card_h, nameplate_h,
            season=season, player=player, club=club, slug=slug,
            season_font=season_font, pos_font=pos_font,
            given_font=given_font, family_font=family_font,
        )

    buf = BytesIO()
    im.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
