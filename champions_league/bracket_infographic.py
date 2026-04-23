# -*- coding: utf-8 -*-
"""
PNG-сетка плей-офф ЛЧ в виде инфографики (колонки, блоки команд, связи между раундами).
Стиль ориентирован на типичную «спортивную» сетку (светлый фон, синие акценты).
Логика дерева — bracket_cl_playoff_24 из knockout_bracket.py.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Sequence

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    raise ImportError("Нужен Pillow: pip install pillow") from e

from champions_league.knockout_bracket import bracket_cl_playoff_24


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
    # первый доступный sans из списка
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


def render_cl_bracket_infographic_png_bytes(
    r1_pairs: Sequence[tuple[str, str]] | None = None,
    r2_seeds: Sequence[str] | None = None,
    *,
    season_label: str = "2025/26",
    title: str = "Лига чемпионов",
    subtitle: str = "Плей-офф",
) -> bytes:
    """
    Одна PNG: сетка 24 команд (R1 стыки → R2 посевы → R3 → ПФ → финал).
    """
    tree = bracket_cl_playoff_24(r1_pairs=r1_pairs, r2_seeds=r2_seeds)

    title_font, header_font, body_font = _pick_fonts()
    small_font = body_font

    # палитра (близко к спортивным инфографикам)
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
    WHITE = (255, 255, 255)

    W = 1340
    HDR_H = 82
    PAD_TOP = 18
    ROW_H = 26
    SECTION_GAP = 10
    section_h = 2 * ROW_H + SECTION_GAP  # блок одного стыка R1 + два имени

    n_r2 = 8
    content_h = int(n_r2 * section_h + 48)
    H = HDR_H + content_h + 36

    im = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(im)

    # шапка
    draw.rectangle((0, 0, W, HDR_H), fill=HEADER_BLUE)
    draw.rectangle((0, HDR_H - 4, W, HDR_H), fill=HEADER_BLUE_DARK)

    t_main = title
    t_sub = subtitle
    draw.text((28, 14), t_main, font=title_font, fill=WHITE)
    tw, _ = _text_size(draw, t_main, title_font)
    draw.text((28 + tw + 12, 18), season_label, font=header_font, fill=(191, 219, 254))
    draw.text((28, 48), t_sub, font=header_font, fill=(224, 231, 255))

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
    # заголовки колонок
    cx = x_cols
    for i, lab in enumerate(col_titles):
        draw.text((cx[i], y0), lab, font=header_font, fill=HEADER_BLUE)
        draw.line((cx[i], y0 + 22, cx[i] + col_w[i], y0 + 22), fill=LINE_BLUE, width=2)

    y_content = y0 + 34
    pad_x_text = 8

    # центры по вертикали для каждого стыка R1 (= строка R2 i)
    y_centers_r1_r2: list[float] = []
    for i in range(8):
        base = y_content + i * section_h
        y_centers_r1_r2.append(base + section_h / 2)

    x1 = x_cols[0]
    w1 = col_w[0]
    x2 = x_cols[1]
    w2 = col_w[1]
    x3 = x_cols[2]
    w3 = col_w[2]
    x4 = x_cols[3]
    w4 = col_w[3]
    x5 = x_cols[4]
    w5 = col_w[4]

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

    labels_r3 = ("Пара 1", "Пара 2", "Пара 3", "Пара 4")
    bh = 52

    def yi(y: float) -> int:
        return int(round(y))

    # --- Колонка 1: пары R1 ---
    for i, tie in enumerate(tree["round_1"]):
        base = y_content + i * section_h
        h_team = tie["home_first_leg"]
        a_team = tie["away_first_leg"]
        box = (x1, base, x1 + w1, base + section_h - 2)
        _rounded_rect(draw, box, TEAM_BAND, EDGE_TEAM, 5)

        hn = _truncate(draw, h_team, body_font, w1 - 2 * pad_x_text)
        an = _truncate(draw, a_team, body_font, w1 - 2 * pad_x_text)
        draw.text((x1 + pad_x_text, base + 4), hn, font=body_font, fill=TEXT_MAIN)
        draw.text((x1 + pad_x_text, base + ROW_H + 2), an, font=body_font, fill=TEXT_MAIN)

    # Линии к 1/8 (под следующими блоками)
    for i in range(8):
        cy = yi(y_centers_r1_r2[i])
        draw.line((x1_right, cy, x2_left, cy), fill=LINE_BLUE, width=2)

    # --- Колонка 2: посев vs победитель R1 ---
    for i, t in enumerate(tree["round_2"]):
        seed = str(t["seed"])
        cy = y_centers_r1_r2[i]
        box_h = section_h - 4
        top = cy - box_h / 2
        box = (x2, top, x2 + w2, top + box_h)
        _rounded_rect(draw, box, CARD_FILL, CARD_EDGE, 6)

        line1 = _truncate(draw, seed, header_font, w2 - 2 * pad_x_text)
        draw.text((x2 + pad_x_text, top + 6), line1, font=header_font, fill=TEXT_MAIN)
        draw.text((x2 + pad_x_text, top + 26), "vs", font=small_font, fill=TEXT_MUTED)
        sub = f"победитель стыка {i + 1}"
        draw.text((x2 + pad_x_text, top + 44), sub, font=small_font, fill=TEXT_MUTED)

    # Линии к четвертьфиналам
    for j in range(4):
        yl = r3_centers[j]
        i0, i1 = 2 * j, 2 * j + 1
        y0, y1 = y_centers_r1_r2[i0], y_centers_r1_r2[i1]
        mx = (x2_right + x3_left) // 2
        draw.line((x2_right, yi(y0), mx, yi(y0)), fill=LINE_BLUE, width=2)
        draw.line((x2_right, yi(y1), mx, yi(y1)), fill=LINE_BLUE, width=2)
        draw.line((mx, yi(y0), mx, yi(y1)), fill=LINE_BLUE, width=2)
        ym = (y0 + y1) / 2
        draw.line((mx, yi(ym), mx, yi(yl)), fill=LINE_BLUE, width=2)
        draw.line((mx, yi(yl), x3_left, yi(yl)), fill=LINE_BLUE, width=2)

    # Четвертьфиналы
    for j, cy in enumerate(r3_centers):
        top = cy - bh / 2
        box = (x3, top, x3 + w3, top + bh)
        _rounded_rect(draw, box, CARD_FILL, CARD_EDGE, 8)
        draw.text((x3 + pad_x_text, top + 8), labels_r3[j], font=header_font, fill=TEXT_MAIN)
        draw.text((x3 + pad_x_text, top + 30), "по итогам 1/8", font=small_font, fill=TEXT_MUTED)

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

    # Полуфиналы
    for j, cy in enumerate(sf_centers):
        top = cy - bh / 2
        box = (x4, top, x4 + w4, top + bh)
        _rounded_rect(draw, box, CARD_FILL, CARD_EDGE, 8)
        draw.text((x4 + pad_x_text, top + 10), f"Полуфинал {j + 1}", font=header_font, fill=TEXT_MAIN)

    # Линии к финалу
    mx_f = (x4_right + x5_left) // 2
    ya, yb = sf_centers[0], sf_centers[1]
    draw.line((x4_right, yi(ya), mx_f, yi(ya)), fill=LINE_BLUE, width=2)
    draw.line((x4_right, yi(yb), mx_f, yi(yb)), fill=LINE_BLUE, width=2)
    draw.line((mx_f, yi(ya), mx_f, yi(yb)), fill=LINE_BLUE, width=2)
    ym_sf = (ya + yb) / 2
    draw.line((mx_f, yi(ym_sf), mx_f, yi(fcy)), fill=LINE_BLUE, width=2)
    draw.line((mx_f, yi(fcy), x5_left, yi(fcy)), fill=LINE_BLUE, width=2)

    # Финал
    top = fcy - 36
    box = (x5, top, x5 + w5, top + 72)
    _rounded_rect(draw, box, CARD_FILL, CARD_EDGE, 10)
    draw.text((x5 + pad_x_text, top + 16), "Финал", font=header_font, fill=TEXT_MAIN)
    draw.text((x5 + pad_x_text, top + 42), "один матч", font=small_font, fill=TEXT_MUTED)

    buf = BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
