# -*- coding: utf-8 -*-
"""
PNG «История»: чемпионы — 10 колонок; личные награды — 5 колонок,
карточки в стиле FUT: прямоугольник, фото (обрезка голова-по-пояс) по ширине карточки,
по центру и прижато к верху полосы имён; эмблема, позиция и флаг — в левом верхнем углу;
номер сезона в круге справа сверху; тёмная полоса с именем/фамилией снизу.

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

# ─── Цвета карточки — тёплые тёмные (под коричневый фон) ──────────
_CARD_BG = (38, 32, 24)                 # тёмно-коричневый
_CARD_BORDER = (85, 72, 48)             # золотисто-коричневая рамка
_CARD_NAMEPLATE = (18, 15, 10)          # почти чёрный тёплый
_CARD_NAMEPLATE_BORDER = (85, 72, 48)   # совпадает с рамкой карточки
_SEASON_CIRCLE_STROKE = (85, 72, 48)    # обводка круга = рамка карточки
_SEASON_CIRCLE_FILL = (38, 32, 24)      # заливка круга = фон карточки
_SEASON_COLOR = (255, 235, 130)         # золотая цифра
_POS_TEXT = (210, 200, 170)             # текст позиции
_POS_BORDER = (90, 82, 65)             # линия nameplate
_INFO_TEXT_DIM = (120, 110, 90)         # тусклый текст (прочерки)

# ── Фиксированные размеры карточки (НЕ зависят от количества) ────
_CARD_W_FIXED = 148                     # ширина карточки px
_CARD_H_FIXED = 185                     # высота карточки px
_NAMEPLATE_H_FIXED = 38                 # высота полосы имени


def _season_card_label(season: int | str | None) -> str:
    """Текст номера сезона для круга на карточке (без падений на нестандартных данных)."""
    if season is None:
        return "?"
    try:
        return str(int(season))
    except (TypeError, ValueError):
        t = str(season).strip()
        return t if t else "?"


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
    Обрезает фото «голова по пояс» с ДИНАМИЧЕСКИМ зумом:
    - Маленькие фото (портреты) — берём верхние 60%, мягкий зум
    - Большие/альбомные — берём верхние 80%, минимальный зум
    - Итого все выглядят примерно одинаково
    """
    img = photo.convert("RGBA")
    pw, ph = img.size

    # Динамический crop: чем больше фото, тем меньше обрезаем
    aspect = pw / max(ph, 1)
    if aspect > 1.2:
        # Альбомное (Рёль 1200×800) — берём 80%, меньше зум
        crop_ratio = 0.80
    elif aspect > 0.85:
        # Почти квадратное — 70%
        crop_ratio = 0.70
    else:
        # Портрет (Мартинез 736×1071) — 60%
        crop_ratio = 0.60

    crop_bottom = int(ph * crop_ratio)
    crop_bottom = max(crop_bottom, 10)
    crop_bottom = min(crop_bottom, ph)
    img = img.crop((0, 0, pw, crop_bottom))
    pw, ph = img.size

    # Center-crop до пропорций target
    target_ratio = target_w / target_h
    current_ratio = pw / max(ph, 1)

    if current_ratio > target_ratio:
        new_w = int(ph * target_ratio)
        left = (pw - new_w) // 2
        img = img.crop((left, 0, left + new_w, ph))
    elif current_ratio < target_ratio:
        new_h = int(pw / target_ratio)
        img = img.crop((0, 0, pw, new_h))

    # Динамический scale + лёгкий boost — игрок крупнее; крупные исходники чуть сжимаем
    orig_area = photo.size[0] * photo.size[1]
    target_area = target_w * target_h
    if orig_area > target_area * 6:
        scale = 0.98
    elif orig_area > target_area * 3:
        scale = 1.02
    else:
        scale = 1.06

    zoom_boost = 1.05
    final_w = max(1, int(round(target_w * scale * zoom_boost)))
    final_h = max(1, int(round(target_h * scale * zoom_boost)))
    img = img.resize((final_w, final_h), Image.Resampling.LANCZOS)

    out = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    if final_w >= target_w and final_h >= target_h:
        left = max(0, (final_w - target_w) // 2)
        top = max(0, final_h - target_h)
        chip = img.crop((left, top, left + target_w, top + target_h))
        out.paste(chip, (0, 0))
        return out

    ox = (target_w - final_w) // 2
    oy = target_h - final_h
    out.paste(img, (ox, oy))
    return out


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


def _special_cup_meta(grade: str) -> tuple[str, tuple[int, int, int], tuple[int, int, int], str]:
    """filename, glow RGB, caption RGB, short label."""
    if grade == "platinum":
        return (
            "cup_platinum.png",
            (180, 210, 240),
            (220, 235, 255),
            "Платина",
        )
    return (
        "cup_gold.png",
        (255, 200, 60),
        (255, 220, 110),
        "Золото",
    )


def _draw_radial_glow(
    im: Image.Image,
    cx: int,
    cy: int,
    radius: int,
    rgb: tuple[int, int, int],
    *,
    peak_alpha: int = 110,
) -> None:
    """Мягкое сияние под кубком / вокруг эмблемы."""
    if radius < 6:
        return
    size = radius * 2 + 2
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r, g, b = rgb
    for i in range(radius, 0, -1):
        t = i / radius
        a = int(peak_alpha * (1.0 - t) ** 1.6)
        if a <= 0:
            continue
        gd.ellipse(
            [radius - i, radius - i, radius + i, radius + i],
            fill=(r, g, b, a),
        )
    im.alpha_composite(glow, (int(cx - radius), int(cy - radius)))


def _paste_special_cup_badge(
    im: Image.Image,
    grade: str,
    cx: int,
    cy: int,
    *,
    max_h: int = 44,
) -> None:
    """Золотой / платиновый кубок с сиянием."""
    filename, glow_rgb, _cap, _lab = _special_cup_meta(grade)
    tro = _try_load_trophy_rgba(filename)
    if tro is None:
        return
    _draw_radial_glow(im, cx, cy, max(18, max_h // 2 + 8), glow_rgb, peak_alpha=130)
    _paste_trophy_thumb(im, tro, cx, cy, max_h)


# ═══════════════════════════════════════════════════════════════════
#  Сетка клубов (Лиги + ЛЧ) — 10 колонок
# ═══════════════════════════════════════════════════════════════════

def _render_club_grid_png(
    *,
    title: str,
    subtitle: str | None,
    rows: list[tuple[int, str | None]],
    use_cl_background: bool,
    competition: str = "league",
    league_code: str | None = None,
) -> bytes:
    from bot.team_history import campaign_special_cup

    ordered = list(reversed(rows))
    n = len(ordered)
    if n == 0:
        ordered = [(get_active_season(), None)]
        n = 1

    # precompute special cups for champions
    grades: list[str | None] = []
    for season, team in ordered:
        if not team:
            grades.append(None)
            continue
        grades.append(
            campaign_special_cup(
                team,
                int(season),
                competition=competition,
                league_code=league_code,
            )
        )

    cols = _COLS_CLUB
    inner_w = _CANVAS_W - 2 * _PAD
    cell_w = inner_w // cols
    crest_max = min(52, int(cell_w * 0.55))
    cup_h = min(40, int(crest_max * 0.85))
    cap_font = _pick_font(14, bold=True)
    badge_font = _pick_font(11, bold=True)
    legend_font = _pick_font(13)

    _tmp = Image.new("RGB", (20, 20))
    _td = ImageDraw.Draw(_tmp)
    _cb = _td.textbbox((0, 0), "Сезон 9", font=cap_font)
    _cap_h = _cb[3] - _cb[1]
    _bb = _td.textbbox((0, 0), "Платина", font=badge_font)
    _badge_h = _bb[3] - _bb[1]

    pad_v = 10
    gap = 4
    row_gap = 14
    # crest + optional cup row + caption + optional badge
    cell_h = (
        pad_v
        + crest_max
        + 4
        + cup_h
        + gap
        + _cap_h
        + 2
        + _badge_h
        + pad_v
        + row_gap
    )
    n_rows = (n + cols - 1) // cols
    header_bottom = _measure_header_bottom(title, subtitle)
    legend_h = 36
    final_h = header_bottom + n_rows * cell_h + legend_h + _PAD

    if use_cl_background:
        im = _background_cl_rgb(_CANVAS_W, final_h).convert("RGBA")
    else:
        im = _background_league_rgb(_CANVAS_W, final_h).convert("RGBA")

    draw = ImageDraw.Draw(im)
    _draw_header(draw, _CANVAS_W, title, subtitle)

    for idx, ((season, team), grade) in enumerate(zip(ordered, grades)):
        col = idx % cols
        row = idx // cols
        x0 = _PAD + col * cell_w
        y0 = header_bottom + row * cell_h
        cx = x0 + cell_w // 2
        cy_crest = y0 + pad_v + crest_max // 2

        if grade:
            _, glow_rgb, cap_rgb, label = _special_cup_meta(grade)
            # кольцо-сияние за эмблемой
            _draw_radial_glow(
                im, cx, cy_crest, crest_max // 2 + 14, glow_rgb, peak_alpha=90
            )
            # тонкая рамка
            ring = crest_max // 2 + 4
            draw.ellipse(
                [cx - ring, cy_crest - ring, cx + ring, cy_crest + ring],
                outline=cap_rgb + (180,),
                width=2,
            )

        _paste_crest_cell(im, team, cx, cy_crest, crest_max, draw)

        cy_cup = y0 + pad_v + crest_max + 4 + cup_h // 2
        if grade:
            _paste_special_cup_badge(im, grade, cx, cy_cup, max_h=cup_h)
        else:
            # пустое место той же высоты — сетка ровная
            pass

        cap = f"Сезон {season}"
        cb = draw.textbbox((0, 0), cap, font=cap_font)
        cw = cb[2] - cb[0]
        cap_y = y0 + pad_v + crest_max + 4 + cup_h + gap
        draw.text(
            (cx - cw // 2, cap_y),
            cap,
            fill=_TEXT,
            font=cap_font,
        )
        if grade:
            _, _, cap_rgb, label = _special_cup_meta(grade)
            bb = draw.textbbox((0, 0), label, font=badge_font)
            bw = bb[2] - bb[0]
            draw.text(
                (cx - bw // 2, cap_y + _cap_h + 2),
                label,
                fill=cap_rgb,
                font=badge_font,
            )

    # легенда внизу
    legend_y = header_bottom + n_rows * cell_h + 4
    leg = (
        "Золотой кубок — чемпион без поражений  ·  "
        "Платиновый — чемпион без ничьих и поражений"
    )
    if competition == "cl":
        leg = (
            "ЛЧ: группа/лига + плей-офф  ·  "
            "Золото — без поражений  ·  Платина — только победы"
        )
    lb = draw.textbbox((0, 0), leg, font=legend_font)
    draw.text(
        ((_CANVAS_W - (lb[2] - lb[0])) // 2, legend_y),
        leg,
        fill=_TEXT_DIM,
        font=legend_font,
    )

    buf = BytesIO()
    im.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_league_history_png(league_code: str, league_title: str) -> bytes:
    mx = get_active_season()
    rows = timeline_league(league_code, mx)
    return _render_club_grid_png(
        title=league_title,
        subtitle="Чемпионы по сезонам · золото / платина за идеальный путь",
        rows=rows,
        use_cl_background=False,
        competition="league",
        league_code=league_code,
    )


def render_cl_history_png() -> bytes:
    mx = get_active_season()
    rows = timeline_cl(mx)
    return _render_club_grid_png(
        title="Лига чемпионов",
        subtitle="Победители · золото / платина за кампанию без поражений",
        rows=rows,
        use_cl_background=True,
        competition="cl",
        league_code=None,
    )


# ═══════════════════════════════════════════════════════════════════
#  Личные награды — карточки FUT
# ═══════════════════════════════════════════════════════════════════
#
#  ┌──────────────────────────────┐
#  │[ЭП]                    [1]○  │  ← герб / POS / флаг слева сверху; сезон справа
#  │ POS                          │
#  │ 🇦🇷         ФОТО по центру    │
#  ├──────────────────────────────┤
#  │       имя / фамилия          │
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
    season: int | str | None,
    player: str | None,
    club: str | None,
    slug: str | None,
    season_font,
    pos_font,
    given_font,
    family_font,
) -> None:
    """Рисует одну карточку награды."""
    card_radius = 5
    info_pad = 6
    icon_size = 22
    item_gap = 1
    circle_r = 14
    photo_margin = 2

    x1 = x0 + card_w - 1
    y1 = y0 + card_h - 1
    np_y = y1 - nameplate_h + 1

    # ── 1. Фон карточки ──
    draw.rounded_rectangle(
        (x0, y0, x1, y1),
        radius=card_radius,
        fill=_CARD_BG,
        outline=_CARD_BORDER,
        width=2,
    )

    # Зона фото — почти вся ширина карточки; низ вплотную к полосе имени (центр внутри зоны)
    photo_area_top = y0 + photo_margin
    photo_area_h = max(8, np_y - photo_area_top)
    photo_area_w = max(16, card_w - 2 * photo_margin)
    photo_area_left = x0 + photo_margin
    card_cx = x0 + card_w // 2

    # ── 2. Фото по центру карточки (горизонтально), прижато к низу зоны ──
    photo = _try_load_photo_rgba(slug)
    if photo is not None:
        cropped = _crop_head_to_waist(photo, photo_area_w, photo_area_h)
        if cropped.mode != "RGBA":
            cropped = cropped.convert("RGBA")
        # Ровно photo_area_w×h: внутри уже центр по горизонтали и прижатие к низу зоны
        im.alpha_composite(cropped, (photo_area_left, photo_area_top))
    else:
        mark_sz = min(36, int(photo_area_w * 0.32), int(photo_area_h * 0.32))
        _draw_unknown_mark(
            im, draw,
            card_cx,
            photo_area_top + photo_area_h // 2,
            mark_sz, light=True,
        )

    # ── 3. Левый верх: эмблема, позиция, флаг (поверх фото) ──
    col_cx = x0 + info_pad + icon_size // 2
    info_y = y0 + 6

    pos_db, nat_db = None, None
    if player and str(player).strip():
        pos_db, nat_db = _lookup_position_nation(str(player).strip(), club)

    if club and str(club).strip():
        cr = _try_load_crest_rgba(_team_name_as_in_db(str(club).strip()))
        if cr is not None:
            _paste_crest_natural(
                im, cr, col_cx, info_y + icon_size // 2, icon_size,
            )
    info_y += icon_size + item_gap

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

    if nat_db:
        flag_x = col_cx - _FLAG_W // 2
        flag_y = info_y + (icon_size - _FLAG_H) // 2
        _paste_or_draw_flag(im, draw, int(flag_x), int(flag_y), nat_db)
    else:
        fw = min(_FLAG_W, icon_size)
        fh = min(_FLAG_H, icon_size - 4)
        fx = col_cx - fw // 2
        fy = info_y + (icon_size - fh) // 2
        draw.rectangle(
            (fx, fy, fx + fw, fy + fh),
            fill=(32, 28, 20), outline=(60, 52, 38),
        )

    # ── 4. Тёмная полоса снизу С РАМКОЙ ──
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

    # ── 5. Номер сезона — круг в углу; рисуем последним и на свежем Draw, чтобы не терялся
    season_txt = _season_card_label(season)
    circle_cx = x1 - 4
    circle_cy = y0 + 4
    draw_top = ImageDraw.Draw(im)
    draw_top.ellipse(
        (circle_cx - circle_r, circle_cy - circle_r,
         circle_cx + circle_r, circle_cy + circle_r),
        fill=_SEASON_CIRCLE_FILL,
        outline=_SEASON_CIRCLE_STROKE,
        width=2,
    )
    draw_top.text(
        (circle_cx, circle_cy), season_txt,
        fill=_SEASON_COLOR, font=season_font, anchor="mm",
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
