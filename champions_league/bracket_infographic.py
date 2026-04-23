# -*- coding: utf-8 -*-
"""
PNG-сетка плей-офф ЛЧ: дерево, данные из журнала (как HTML).

Стиль: тёмный фон «стадион / ЛЧ», светлые карточки, линии-акценты, опционально Montserrat VF
в ``assets/fonts/Montserrat-VF.ttf`` (fallback — DejaVu).

Фон (опционально): ``assets/cl_bracket_background.png`` (или .jpg / .webp) — масштабируется с
обрезкой под размер PNG. Если файла нет — прежний градиент.

Трофей: ``assets/cl_trophy.png`` / ``cl_trophy.webp``. PNG с альфой — как есть; частый случай
«без фона», сохранённый как RGB с чёрным (0,0,0) — удаляется по яркости; светлый однотонный фон —
матовка через разницу с эталонным серым.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps, ImageStat
except ImportError as e:
    raise ImportError("Нужен Pillow: pip install pillow") from e

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[misc, assignment]

from champions_league.bracket_html import (
    _load_cl_scores_and_penalties,
    build_cl_bracket_state,
    tie_score_pair_strings,
)


_MODULE_DIR = Path(__file__).resolve().parent
_MONTserrat_VF = _MODULE_DIR / "assets" / "fonts" / "Montserrat-VF.ttf"
_CL_TROPHY_PNG = _MODULE_DIR / "assets" / "cl_trophy.png"
_CL_TROPHY_WEBP = _MODULE_DIR / "assets" / "cl_trophy.webp"

_CL_BG_CANDIDATES: tuple[Path, ...] = (
    _MODULE_DIR / "assets" / "cl_bracket_background.png",
    _MODULE_DIR / "assets" / "cl_bracket_background.jpg",
    _MODULE_DIR / "assets" / "cl_bracket_background.webp",
)

_SANS_PATHS: tuple[Path, ...] = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/Library/Fonts/Tahoma.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
)


def _font_legacy(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (_SANS_PATHS[0], _SANS_PATHS[1]) if bold else (_SANS_PATHS[1], _SANS_PATHS[0])
    for p in candidates:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _montserrat(size: int, variation: str) -> ImageFont.FreeTypeFont | None:
    if not _MONTserrat_VF.is_file():
        return None
    try:
        f = ImageFont.truetype(str(_MONTserrat_VF), size=size)
        if hasattr(f, "set_variation_by_name"):
            try:
                f.set_variation_by_name(variation)
            except OSError:
                pass
        return f
    except OSError:
        return None


def _pick_fonts() -> tuple[ImageFont.FreeTypeFont, ImageFont.FreeTypeFont, ImageFont.FreeTypeFont]:
    """Заголовок (крупный), подзаголовки колонок, текст карточек."""
    t = _montserrat(23, "Bold") or _font_legacy(23, bold=True)
    h = _montserrat(14, "SemiBold") or _font_legacy(14, bold=True)
    b = _montserrat(13, "Medium") or _font_legacy(13, bold=False)
    return (t, h, b)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    if hasattr(draw, "textbbox"):
        x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
        return x1 - x0, y1 - y0
    try:
        return font.getsize(text)  # type: ignore[attr-defined]
    except Exception:
        return (len(text) * 8, 16)


def _truncate(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> str:
    if _text_size(draw, text, font)[0] <= max_w:
        return text
    ell = "…"
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        cand = text[:mid].rstrip() + ell
        if _text_size(draw, cand, font)[0] <= max_w:
            low = mid
        else:
            high = mid - 1
    return text[: low if low > 0 else 1].rstrip() + ell


def _rounded_rect(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    fill: tuple[int, int, int],
    outline: tuple[int, int, int],
    radius: int = 6,
) -> None:
    if hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=1)
    else:
        draw.rectangle(xy, fill=fill, outline=outline)


def _fill_vertical_gradient(im: Image.Image, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> None:
    """Вертикальный градиент по всей высоте (RGB)."""
    w, h = im.size
    draw_tmp = ImageDraw.Draw(im)
    hm = max(h - 1, 1)
    for y in range(h):
        t = y / hm
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        draw_tmp.rectangle((0, y, w, y + 1), fill=(r, g, b))


def _background_asset_path() -> Path | None:
    for p in _CL_BG_CANDIDATES:
        if p.is_file():
            return p
    return None


def _resize_cover_crop(bg: Image.Image, tw: int, th: int) -> Image.Image:
    """Увеличить фон так, чтобы заполнить (tw, th), обрезать по центру."""
    bw, bh = bg.size
    scale = max(tw / bw, th / bh)
    nw = max(1, int(round(bw * scale)))
    nh = max(1, int(round(bh * scale)))
    resized = bg.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - tw) // 2)
    top = max(0, (nh - th) // 2)
    return resized.crop((left, top, left + tw, top + th)).convert("RGB")


def _rgb_studio_black_to_rgba(rgb: Image.Image, mx_cutoff: int = 20) -> Image.Image:
    """Студийный чёрный фон (RGB ~0,0,0 или почти) → прозрачность по max(R,G,B)."""
    if np is None:
        return _pil_black_background_to_rgba(rgb, lum_cutoff=mx_cutoff)
    arr = np.asarray(rgb)
    mx = np.max(arr, axis=2)
    a = np.where(mx > mx_cutoff, 255, 0).astype(np.uint8)
    return Image.fromarray(np.dstack([arr, a]), "RGBA")


def _pil_black_background_to_rgba(rgb: Image.Image, lum_cutoff: int = 20) -> Image.Image:
    """То же без numpy: по яркости канала L — чёрный фон убирается на любом сервере."""
    lum = rgb.convert("L")
    alpha = lum.point(lambda p, c=lum_cutoff: 0 if p <= c else 255)
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def _fraction_pure_black(rgb: Image.Image) -> float:
    if np is None:
        return 0.0
    mx = np.max(np.asarray(rgb), axis=2)
    return float((mx == 0).mean())


def _fraction_near_black(rgb: Image.Image, mx_cutoff: int = 22) -> float:
    if np is None:
        # грубая оценка по гистограмме L
        lum = rgb.convert("L")
        h = lum.histogram()
        total = sum(h)
        dark = sum(h[: mx_cutoff + 1])
        return dark / total if total else 0.0
    mx = np.max(np.asarray(rgb), axis=2)
    return float((mx <= mx_cutoff).mean())


def _looks_like_dark_studio_rgb(rgb: Image.Image) -> bool:
    """Фон чёрный / почти чёрный (Adobe «без фона», сохранённый как RGB)."""
    if _fraction_pure_black(rgb) > 0.08:
        return True
    if _fraction_near_black(rgb) > 0.45:
        return True
    try:
        mean_lum = ImageStat.Stat(rgb.convert("L")).mean[0]
        if mean_lum < 95:
            return True
    except Exception:
        pass
    return False


def _draw_subtle_sparkles(im: Image.Image, n: int = 42, seed: int = 42) -> None:
    """Лёгкие «блёстки» на фоне (очень тускло)."""
    import random

    rnd = random.Random(seed)
    w, h = im.size
    px = im.load()
    for _ in range(n):
        x, y = rnd.randint(8, w - 9), rnd.randint(80, h - 9)
        base = px[x, y]
        lift = rnd.randint(18, 38)
        px[x, y] = tuple(min(255, c + lift) for c in base)


def _trophy_asset_path() -> Path | None:
    if _CL_TROPHY_PNG.is_file():
        return _CL_TROPHY_PNG
    if _CL_TROPHY_WEBP.is_file():
        return _CL_TROPHY_WEBP
    return None


def _prepare_trophy_rgba(rgb: Image.Image, ref_bg: tuple[int, int, int] = (252, 252, 252)) -> Image.Image:
    """Убрать однотонный светлый фон: альфа из карты расхождения с эталоном (мягкая кромка)."""
    ref = Image.new("RGB", rgb.size, ref_bg)
    diff = ImageChops.difference(rgb, ref).convert("L")
    alpha = diff.point(lambda p: min(255, max(0, (p - 12) * 11)))
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def _rgba_has_real_alpha(im: Image.Image) -> bool:
    if im.mode != "RGBA":
        return False
    lo, hi = im.split()[3].getextrema()
    return lo < 240


def _load_trophy_rgba(max_height: int = 120) -> Image.Image | None:
    """Готовое RGBA, высота не больше max_height."""
    path = _trophy_asset_path()
    if path is None:
        return None
    try:
        src = ImageOps.exif_transpose(Image.open(path))
        if src.mode == "RGBA" and _rgba_has_real_alpha(src):
            rgba_src: Image.Image = src
            rw, rh = rgba_src.size
            if rh > max_height:
                scale = max_height / rh
                rgba_src = rgba_src.resize((max(1, int(rw * scale)), max_height), Image.Resampling.LANCZOS)
            return rgba_src.convert("RGBA")

        rgb = src.convert("RGB")
        rw, rh = rgb.size
        if rh > max_height:
            scale = max_height / rh
            rgb = rgb.resize((max(1, int(rw * scale)), max_height), Image.Resampling.LANCZOS)

        if _looks_like_dark_studio_rgb(rgb):
            resized = _rgb_studio_black_to_rgba(rgb)
        else:
            resized = _prepare_trophy_rgba(rgb)
        return resized.convert("RGBA")
    except OSError:
        return None


def _paste_trophy_or_draw_fallback(im: Image.Image, draw: ImageDraw.ImageDraw, cx: int, card_top: int, gap: int = 8) -> None:
    tro = _load_trophy_rgba()
    if tro is not None:
        tw, th = tro.size
        x = int(cx - tw / 2)
        y = int(card_top - gap - th)
        im.paste(tro, (x, y), tro)
        return
    bot = card_top - gap
    _draw_cl_trophy_vector_fallback(draw, cx, bot)


def _draw_cl_trophy_vector_fallback(draw: ImageDraw.ImageDraw, cx: int, bot: int, scale: float = 1.0) -> None:
    """Если файла трофея нет — простая золотая иконка (как раньше)."""
    s = scale
    gold = (218, 185, 95)
    gold_mid = (196, 158, 72)
    gold_dark = (142, 108, 42)
    gold_hi = (252, 238, 200)

    bw = int(48 * s)
    bh = int(9 * s)
    stem_w = int(13 * s)
    stem_h = int(26 * s)
    cup_w = int(52 * s)
    cup_h = int(22 * s)
    ear = int(7 * s)

    _rounded_rect(draw, (cx - bw // 2, bot - bh, cx + bw // 2, bot), gold_dark, gold, 4)
    stem_top = bot - bh - stem_h
    draw.rectangle((cx - stem_w // 2, stem_top, cx + stem_w // 2, bot - bh), fill=gold_mid, outline=gold)

    bowl_bot = stem_top
    bowl_top = bowl_bot - cup_h
    cup_poly = [
        (cx - cup_w // 2 + ear, bowl_bot),
        (cx + cup_w // 2 - ear, bowl_bot),
        (cx + cup_w // 2, bowl_top + int(6 * s)),
        (cx - cup_w // 2, bowl_top + int(6 * s)),
    ]
    draw.polygon(cup_poly, fill=gold, outline=gold_dark)
    draw.ellipse(
        (cx - cup_w // 2, bowl_top - int(5 * s), cx + cup_w // 2, bowl_top + int(10 * s)),
        fill=gold_hi,
        outline=gold_mid,
    )


def _draw_tie_two_lines(
    draw: ImageDraw.ImageDraw,
    inner_left: int,
    inner_right: int,
    top_y: int,
    row_a: tuple[str, str],
    row_b: tuple[str, str],
    *,
    line_gap: int,
    name_font: ImageFont.FreeTypeFont,
    score_font: ImageFont.FreeTypeFont,
    fill_name_row1: tuple[int, int, int],
    fill_name_row2: tuple[int, int, int],
    fill_score: tuple[int, int, int],
    pen_color: tuple[int, int, int],
) -> None:
    def one_line(y: int, row: tuple[str, str], fill_name: tuple[int, int, int]) -> None:
        name, score_full = row
        max_name_w = inner_right - inner_left - 52
        tn = _truncate(draw, name, name_font, max_name_w)
        draw.text((inner_left, y), tn, font=name_font, fill=fill_name)

        score_main = score_full
        pen_suf = ""
        if " (" in score_full and score_full.endswith(")"):
            score_main, pen_suf = score_full.rsplit(" (", 1)
            pen_suf = "(" + pen_suf
        tw_main, _ = _text_size(draw, score_main, score_font)
        x_score = inner_right - tw_main
        if pen_suf:
            tw_pen, _ = _text_size(draw, " " + pen_suf, score_font)
            x_score -= tw_pen
        draw.text((x_score, y), score_main, font=score_font, fill=fill_score)
        if pen_suf:
            xp = inner_right - _text_size(draw, pen_suf, score_font)[0]
            draw.text((xp, y), pen_suf, font=score_font, fill=pen_color)

    one_line(top_y, row_a, fill_name_row1)
    one_line(top_y + line_gap, row_b, fill_name_row2)


def _fills_for_match(m: dict, *, muted: tuple[int, int, int], main: tuple[int, int, int]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    h = str(m["home"]).startswith("победитель")
    a = str(m["away"]).startswith("победитель")
    return (muted if h else main, muted if a else main)


def render_cl_bracket_infographic_png_bytes(
    *,
    season_label: str = "2025/26",
    title: str = "Лига чемпионов",
    subtitle: str = "Плей-офф",
) -> bytes:
    scores, pen_by_tie = _load_cl_scores_and_penalties()
    st = build_cl_bracket_state(scores, pen_by_tie)

    title_font, header_font, body_font = _pick_fonts()
    score_font = _montserrat(13, "SemiBold") or header_font

    # Фон: глубокий сине-ночной (ассоциация с ЛЧ)
    BG_TOP = (10, 22, 52)
    BG_BOT = (18, 38, 78)
    HEADER_BAR = (8, 16, 42)
    HEADER_ACCENT = (6, 12, 36)
    LINE_CLR = (120, 185, 255)
    CARD_FILL = (248, 250, 252)
    CARD_EDGE = (190, 205, 228)
    CARD_FILL_ALT = (241, 246, 252)
    TEAM_BAND = (255, 255, 255)
    EDGE_TEAM = (210, 218, 235)
    TEXT_MAIN = (18, 28, 52)
    TEXT_MUTED = (110, 125, 150)
    PEN_CLR = (30, 90, 160)
    TITLE_COLOR = (245, 248, 255)
    SUB_TINT = (190, 210, 245)
    COL_HDR = (170, 200, 240)

    ROW_LINE = 22
    CARD_PAD_V = 6
    CARD_PAD_H = 8
    CARD_BODY = CARD_PAD_V * 2 + ROW_LINE * 2
    SECTION_GAP = 10
    section_h = CARD_BODY + SECTION_GAP

    W = 1340
    HDR_H = 88
    PAD_TOP = 18
    n_r2 = 8
    content_h = int(n_r2 * section_h + 48)
    H = HDR_H + content_h + 36

    im = Image.new("RGB", (W, H), BG_TOP)
    bg_file = _background_asset_path()
    if bg_file is not None:
        try:
            bg_img = ImageOps.exif_transpose(Image.open(bg_file)).convert("RGB")
            im.paste(_resize_cover_crop(bg_img, W, H), (0, 0))
        except OSError:
            _fill_vertical_gradient(im, BG_TOP, BG_BOT)
            _draw_subtle_sparkles(im)
    else:
        _fill_vertical_gradient(im, BG_TOP, BG_BOT)
        _draw_subtle_sparkles(im)
    draw = ImageDraw.Draw(im)

    draw.rectangle((0, 0, W, HDR_H), fill=HEADER_BAR)
    draw.rectangle((0, HDR_H - 3, W, HDR_H), fill=HEADER_ACCENT)

    draw.text((28, 16), title, font=title_font, fill=TITLE_COLOR)
    tw, _ = _text_size(draw, title, title_font)
    draw.text((28 + tw + 14, 20), season_label, font=header_font, fill=SUB_TINT)
    draw.text((28, 52), subtitle, font=body_font, fill=SUB_TINT)

    col_titles = (
        "Стыковые матчи",
        "1/8 финала",
        "Четвертьфиналы",
        "Полуфиналы",
        "Финал",
    )
    x_cols = (24, 298, 598, 878, 1128)
    col_w = (248, 268, 248, 228, 188)

    y0 = HDR_H + PAD_TOP
    for i, lab in enumerate(col_titles):
        draw.text((x_cols[i], y0), lab, font=header_font, fill=COL_HDR)
        draw.line((x_cols[i], y0 + 22, x_cols[i] + col_w[i], y0 + 22), fill=LINE_CLR, width=2)

    y_content = y0 + 34

    y_centers_r1_r2: list[float] = []
    for i in range(8):
        base = y_content + i * section_h
        y_centers_r1_r2.append(base + section_h / 2)

    x1, w1 = x_cols[0], col_w[0]
    x2, w2 = x_cols[1], col_w[1]
    x3, w3 = x_cols[2], col_w[2]
    x4, w4 = x_cols[3], col_w[3]
    x5, w5 = x_cols[4], col_w[4]

    x1_right = x1 + w1
    x2_left = x2
    x2_right = x2 + w2
    x3_left = x3
    x3_right = x3 + w3
    x4_left = x4
    x4_right = x4 + w4
    x5_left = x5

    r3_centers = [
        (y_centers_r1_r2[0] + y_centers_r1_r2[1]) / 2,
        (y_centers_r1_r2[2] + y_centers_r1_r2[3]) / 2,
        (y_centers_r1_r2[4] + y_centers_r1_r2[5]) / 2,
        (y_centers_r1_r2[6] + y_centers_r1_r2[7]) / 2,
    ]
    sf_centers = [(r3_centers[0] + r3_centers[1]) / 2, (r3_centers[2] + r3_centers[3]) / 2]
    fcy = (sf_centers[0] + sf_centers[1]) / 2

    bh_q = CARD_BODY + 4

    def yi(y: float) -> int:
        return int(round(y))

    # --- R1 ---
    for i, m in enumerate(st["round_1"]):
        base = y_content + i * section_h
        _rounded_rect(draw, (x1, base, x1 + w1, base + CARD_BODY), TEAM_BAND, EDGE_TEAM, 5)
        rows = tie_score_pair_strings(m["home"], m["away"], scores, pen_by_tie)
        inner_l = x1 + CARD_PAD_H
        inner_r = x1 + w1 - CARD_PAD_H
        _draw_tie_two_lines(
            draw,
            inner_l,
            inner_r,
            base + CARD_PAD_V,
            rows[0],
            rows[1],
            line_gap=ROW_LINE,
            name_font=body_font,
            score_font=score_font,
            fill_name_row1=TEXT_MAIN,
            fill_name_row2=TEXT_MAIN,
            fill_score=TEXT_MAIN,
            pen_color=PEN_CLR,
        )

    for i in range(8):
        cy = yi(y_centers_r1_r2[i])
        draw.line((x1_right, cy, x2_left, cy), fill=LINE_CLR, width=2)

    # --- R2 ---
    for i, m in enumerate(st["round_2"]):
        cy = y_centers_r1_r2[i]
        box_h = CARD_BODY + SECTION_GAP - 4
        top = cy - box_h / 2
        _rounded_rect(draw, (x2, top, x2 + w2, top + CARD_BODY), CARD_FILL_ALT, CARD_EDGE, 6)
        rows = tie_score_pair_strings(m["home"], m["away"], scores, pen_by_tie)
        inner_l = x2 + CARD_PAD_H
        inner_r = x2 + w2 - CARD_PAD_H
        f1 = TEXT_MAIN
        f2 = TEXT_MUTED if str(m["away"]).startswith("победитель") else TEXT_MAIN
        _draw_tie_two_lines(
            draw,
            inner_l,
            inner_r,
            top + CARD_PAD_V,
            rows[0],
            rows[1],
            line_gap=ROW_LINE,
            name_font=body_font,
            score_font=score_font,
            fill_name_row1=f1,
            fill_name_row2=f2,
            fill_score=TEXT_MAIN,
            pen_color=PEN_CLR,
        )

    for j in range(4):
        yl = r3_centers[j]
        i0, i1 = 2 * j, 2 * j + 1
        yy0, yy1 = y_centers_r1_r2[i0], y_centers_r1_r2[i1]
        mx = (x2_right + x3_left) // 2
        draw.line((x2_right, yi(yy0), mx, yi(yy0)), fill=LINE_CLR, width=2)
        draw.line((x2_right, yi(yy1), mx, yi(yy1)), fill=LINE_CLR, width=2)
        draw.line((mx, yi(yy0), mx, yi(yy1)), fill=LINE_CLR, width=2)
        ym = (yy0 + yy1) / 2
        draw.line((mx, yi(ym), mx, yi(yl)), fill=LINE_CLR, width=2)
        draw.line((mx, yi(yl), x3_left, yi(yl)), fill=LINE_CLR, width=2)

    for j, cy in enumerate(r3_centers):
        m = st["round_3"][j]
        top = cy - bh_q / 2
        _rounded_rect(draw, (x3, top, x3 + w3, top + CARD_BODY), CARD_FILL, CARD_EDGE, 8)
        rows = tie_score_pair_strings(m["home"], m["away"], scores, pen_by_tie)
        inner_l = x3 + CARD_PAD_H
        inner_r = x3 + w3 - CARD_PAD_H
        f1, f2 = _fills_for_match(m, muted=TEXT_MUTED, main=TEXT_MAIN)
        _draw_tie_two_lines(
            draw,
            inner_l,
            inner_r,
            top + CARD_PAD_V,
            rows[0],
            rows[1],
            line_gap=ROW_LINE,
            name_font=body_font,
            score_font=score_font,
            fill_name_row1=f1,
            fill_name_row2=f2,
            fill_score=TEXT_MAIN,
            pen_color=PEN_CLR,
        )

    for j in range(2):
        cy = sf_centers[j]
        i0, i1 = 2 * j, 2 * j + 1
        ya, yb = r3_centers[i0], r3_centers[i1]
        mx = (x3_right + x4_left) // 2
        draw.line((x3_right, yi(ya), mx, yi(ya)), fill=LINE_CLR, width=2)
        draw.line((x3_right, yi(yb), mx, yi(yb)), fill=LINE_CLR, width=2)
        draw.line((mx, yi(ya), mx, yi(yb)), fill=LINE_CLR, width=2)
        ym = (ya + yb) / 2
        draw.line((mx, yi(ym), mx, yi(cy)), fill=LINE_CLR, width=2)
        draw.line((mx, yi(cy), x4_left, yi(cy)), fill=LINE_CLR, width=2)

    for j, cy in enumerate(sf_centers):
        m = st["semi_finals"][j]
        top = cy - bh_q / 2
        _rounded_rect(draw, (x4, top, x4 + w4, top + CARD_BODY), CARD_FILL_ALT, CARD_EDGE, 8)
        rows = tie_score_pair_strings(m["home"], m["away"], scores, pen_by_tie)
        inner_l = x4 + CARD_PAD_H
        inner_r = x4 + w4 - CARD_PAD_H
        f1, f2 = _fills_for_match(m, muted=TEXT_MUTED, main=TEXT_MAIN)
        _draw_tie_two_lines(
            draw,
            inner_l,
            inner_r,
            top + CARD_PAD_V,
            rows[0],
            rows[1],
            line_gap=ROW_LINE,
            name_font=body_font,
            score_font=score_font,
            fill_name_row1=f1,
            fill_name_row2=f2,
            fill_score=TEXT_MAIN,
            pen_color=PEN_CLR,
        )

    mx_f = (x4_right + x5_left) // 2
    ya, yb = sf_centers[0], sf_centers[1]
    draw.line((x4_right, yi(ya), mx_f, yi(ya)), fill=LINE_CLR, width=2)
    draw.line((x4_right, yi(yb), mx_f, yi(yb)), fill=LINE_CLR, width=2)
    draw.line((mx_f, yi(ya), mx_f, yi(yb)), fill=LINE_CLR, width=2)
    ym_sf = (ya + yb) / 2
    draw.line((mx_f, yi(ym_sf), mx_f, yi(fcy)), fill=LINE_CLR, width=2)
    draw.line((mx_f, yi(fcy), x5_left, yi(fcy)), fill=LINE_CLR, width=2)

    fin = st["final"]
    fh, fa = fin["home"], fin["away"]
    sc = fin["score"]
    sh, sa = sc[0], sc[1]
    top = fcy - 40
    box_h = 80
    cx5 = x5 + w5 // 2
    _paste_trophy_or_draw_fallback(im, draw, cx5, top)

    _rounded_rect(draw, (x5, top, x5 + w5, top + box_h), CARD_FILL, CARD_EDGE, 10)
    cx = x5 + w5 // 2
    nm_muted_h = fh.startswith("победитель")
    nm_muted_a = fa.startswith("победитель")
    t1 = _truncate(draw, fh, body_font, w5 - 16)
    t2 = _truncate(draw, fa, body_font, w5 - 16)
    y1 = top + 8
    tw1, th1 = _text_size(draw, t1, body_font)
    draw.text((cx - tw1 // 2, y1), t1, font=body_font, fill=TEXT_MUTED if nm_muted_h else TEXT_MAIN)
    mid_txt = "— : —" if sh is None or sa is None else f"{sh} : {sa}"
    twm, thm = _text_size(draw, mid_txt, score_font)
    draw.text((cx - twm // 2, y1 + th1 + 4), mid_txt, font=score_font, fill=PEN_CLR)
    tw2, _ = _text_size(draw, t2, body_font)
    draw.text((cx - tw2 // 2, y1 + th1 + thm + 10), t2, font=body_font, fill=TEXT_MUTED if nm_muted_a else TEXT_MAIN)

    buf = BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
