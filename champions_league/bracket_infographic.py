# -*- coding: utf-8 -*-
"""
PNG-сетка плей-офф ЛЧ: дерево как раньше (светлый стиль), данные только из журнала.

Счета и победители те же, что у ``bracket_html.py`` / HTML-сетки: ``match_results.json``
(league=cl, без групповой фазы). В каждой карточке только две строки — команда и её счёт
(домашний матч этой команды в стыке).
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    raise ImportError("Нужен Pillow: pip install pillow") from e

from champions_league.bracket_html import (
    _load_cl_scores_and_penalties,
    build_cl_bracket_state,
    tie_score_pair_strings,
)


_SANS_PATHS: tuple[Path, ...] = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/Library/Fonts/Tahoma.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
)


def _font(path: Path | None, size: int) -> ImageFont.FreeTypeFont:
    if path is not None and path.exists():
        try:
            return ImageFont.truetype(str(path), size=size)
        except OSError:
            pass
    for p in _SANS_PATHS:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _pick_fonts() -> tuple[ImageFont.FreeTypeFont, ImageFont.FreeTypeFont, ImageFont.FreeTypeFont]:
    bold_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    reg_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if bold_path.exists() and reg_path.exists():
        return (
            ImageFont.truetype(str(bold_path), 22),
            ImageFont.truetype(str(bold_path), 15),
            ImageFont.truetype(str(reg_path), 13),
        )
    return _font(None, 22), _font(None, 15), _font(None, 13)


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
    """
    Одна PNG: та же логика счётов, что у HTML-сетки (журнал ``match_results.json``).
    Только команды и счёт в карточках.
    """
    scores, pen_by_tie = _load_cl_scores_and_penalties()
    st = build_cl_bracket_state(scores, pen_by_tie)

    title_font, header_font, body_font = _pick_fonts()
    score_font = header_font

    BG = (237, 242, 247)
    HEADER_BLUE = (37, 99, 235)
    HEADER_BLUE_DARK = (29, 78, 216)
    LINE_BLUE = (59, 130, 246)
    CARD_FILL = (219, 234, 254)
    CARD_EDGE = (147, 197, 253)
    TEAM_BAND = (255, 255, 255)
    EDGE_TEAM = (226, 232, 240)
    TEXT_MAIN = (15, 23, 42)
    TEXT_MUTED = (71, 85, 105)
    PEN_HTML = (20, 58, 92)
    WHITE = (255, 255, 255)

    ROW_LINE = 22
    CARD_PAD_V = 6
    CARD_PAD_H = 8
    CARD_BODY = CARD_PAD_V * 2 + ROW_LINE * 2
    SECTION_GAP = 10
    section_h = CARD_BODY + SECTION_GAP

    W = 1340
    HDR_H = 82
    PAD_TOP = 18
    n_r2 = 8
    content_h = int(n_r2 * section_h + 48)
    H = HDR_H + content_h + 36

    im = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(im)

    draw.rectangle((0, 0, W, HDR_H), fill=HEADER_BLUE)
    draw.rectangle((0, HDR_H - 4, W, HDR_H), fill=HEADER_BLUE_DARK)

    draw.text((28, 14), title, font=title_font, fill=WHITE)
    tw, _ = _text_size(draw, title, title_font)
    draw.text((28 + tw + 12, 18), season_label, font=header_font, fill=(191, 219, 254))
    draw.text((28, 48), subtitle, font=header_font, fill=(224, 231, 255))

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
        draw.text((x_cols[i], y0), lab, font=header_font, fill=HEADER_BLUE)
        draw.line((x_cols[i], y0 + 22, x_cols[i] + col_w[i], y0 + 22), fill=LINE_BLUE, width=2)

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
            pen_color=PEN_HTML,
        )

    for i in range(8):
        cy = yi(y_centers_r1_r2[i])
        draw.line((x1_right, cy, x2_left, cy), fill=LINE_BLUE, width=2)

    # --- R2 ---
    for i, m in enumerate(st["round_2"]):
        cy = y_centers_r1_r2[i]
        box_h = CARD_BODY + SECTION_GAP - 4
        top = cy - box_h / 2
        _rounded_rect(draw, (x2, top, x2 + w2, top + CARD_BODY), CARD_FILL, CARD_EDGE, 6)
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
            pen_color=PEN_HTML,
        )

    # Линии к четвертьфиналам
    for j in range(4):
        yl = r3_centers[j]
        i0, i1 = 2 * j, 2 * j + 1
        yy0, yy1 = y_centers_r1_r2[i0], y_centers_r1_r2[i1]
        mx = (x2_right + x3_left) // 2
        draw.line((x2_right, yi(yy0), mx, yi(yy0)), fill=LINE_BLUE, width=2)
        draw.line((x2_right, yi(yy1), mx, yi(yy1)), fill=LINE_BLUE, width=2)
        draw.line((mx, yi(yy0), mx, yi(yy1)), fill=LINE_BLUE, width=2)
        ym = (yy0 + yy1) / 2
        draw.line((mx, yi(ym), mx, yi(yl)), fill=LINE_BLUE, width=2)
        draw.line((mx, yi(yl), x3_left, yi(yl)), fill=LINE_BLUE, width=2)

    # --- Четвертьфиналы ---
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
            pen_color=PEN_HTML,
        )

    # Линии к полуфиналам
    for j in range(2):
        cy = sf_centers[j]
        i0, i1 = 2 * j, 2 * j + 1
        ya, yb = r3_centers[i0], r3_centers[i1]
        mx = (x3_right + x4_left) // 2
        draw.line((x3_right, yi(ya), mx, yi(ya)), fill=LINE_BLUE, width=2)
        draw.line((x3_right, yi(yb), mx, yi(yb)), fill=LINE_BLUE, width=2)
        draw.line((mx, yi(ya), mx, yi(yb)), fill=LINE_BLUE, width=2)
        ym = (ya + yb) / 2
        draw.line((mx, yi(ym), mx, yi(cy)), fill=LINE_BLUE, width=2)
        draw.line((mx, yi(cy), x4_left, yi(cy)), fill=LINE_BLUE, width=2)

    # --- Полуфиналы ---
    for j, cy in enumerate(sf_centers):
        m = st["semi_finals"][j]
        top = cy - bh_q / 2
        _rounded_rect(draw, (x4, top, x4 + w4, top + CARD_BODY), CARD_FILL, CARD_EDGE, 8)
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
            pen_color=PEN_HTML,
        )

    # Линии к финалу
    mx_f = (x4_right + x5_left) // 2
    ya, yb = sf_centers[0], sf_centers[1]
    draw.line((x4_right, yi(ya), mx_f, yi(ya)), fill=LINE_BLUE, width=2)
    draw.line((x4_right, yi(yb), mx_f, yi(yb)), fill=LINE_BLUE, width=2)
    draw.line((mx_f, yi(ya), mx_f, yi(yb)), fill=LINE_BLUE, width=2)
    ym_sf = (ya + yb) / 2
    draw.line((mx_f, yi(ym_sf), mx_f, yi(fcy)), fill=LINE_BLUE, width=2)
    draw.line((mx_f, yi(fcy), x5_left, yi(fcy)), fill=LINE_BLUE, width=2)

    # --- Финал (одна игра — одна строка счёта по центру) ---
    fin = st["final"]
    fh, fa = fin["home"], fin["away"]
    sc = fin["score"]
    sh, sa = sc[0], sc[1]
    top = fcy - 40
    box_h = 80
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
    draw.text((cx - twm // 2, y1 + th1 + 4), mid_txt, font=score_font, fill=PEN_HTML)
    tw2, _ = _text_size(draw, t2, body_font)
    draw.text((cx - tw2 // 2, y1 + th1 + thm + 10), t2, font=body_font, fill=TEXT_MUTED if nm_muted_a else TEXT_MAIN)

    buf = BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
