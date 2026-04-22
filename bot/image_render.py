"""
Текстовые отчёты (таблицы, топы) → PNG для Telegram — без переносов строк в ширину чата.
"""
from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    raise ImportError("Нужен пакет Pillow: pip install pillow") from e


# Только моноширинные шрифты с кириллицей (пропорциональный Arial испортит колонки).
_FONT_MONO_PATHS: tuple[Path, ...] = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"),
    Path("/Library/Fonts/Menlo.ttc"),
    Path("/System/Library/Fonts/Supplemental/Courier New.ttf"),
    Path("/System/Library/Fonts/Supplemental/Courier.ttf"),
    Path("C:/Windows/Fonts/cour.ttf"),
    Path("C:/Windows/Fonts/consola.ttf"),
)


def _pick_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_MONO_PATHS:
        try:
            if path.suffix.lower() == ".ttc":
                if path.exists():
                    return ImageFont.truetype(str(path), size=size, index=0)
            elif path.exists():
                return ImageFont.truetype(str(path), size=size)
        except OSError:
            continue
    logger.warning(
        "Не найден моноширинный .ttf/.ttc с кириллицей — загрузка дефолтного шрифта Pillow; "
        "колонки могут съезжать. Установите fonts-dejavu (Linux) или используйте системный Courier."
    )
    return ImageFont.load_default()


def _cell_height(font: ImageFont.FreeTypeFont) -> int:
    ascent, descent = font.getmetrics()
    return ascent + descent + 6


def render_monospace_png_bytes(
    body: str,
    *,
    title: str | None = None,
    font_size: int = 17,
    pad: int = 24,
    bg: tuple[int, int, int] = (252, 252, 252),
    fg: tuple[int, int, int] = (18, 18, 22),
    max_lines_per_image: int = 52,
    max_img_width: int = 2600,
) -> list[bytes]:
    """
    Одна или несколько PNG при очень длинном тексте.
    """
    raw = body.replace("\r\n", "\n").replace("\r", "\n")
    lines_all = raw.split("\n") if raw else [""]

    chunks: list[tuple[str | None, list[str]]] = []
    for start in range(0, len(lines_all), max_lines_per_image):
        slice_lines = lines_all[start : start + max_lines_per_image]
        if start == 0:
            sub_title = title
        else:
            sub_title = (title + " · продолж.") if title else "Продолж."
        chunks.append((sub_title, slice_lines))

    font = _pick_font(font_size)
    title_font = _pick_font(font_size + 5)
    lh = _cell_height(font)

    out_blobs: list[bytes] = []
    for sub_title, text_lines in chunks:
        max_w = pad * 2
        if sub_title:
            bbox_t = title_font.getbbox(sub_title)
            max_w = max(max_w, bbox_t[2] - bbox_t[0] + pad * 2)
        for ln in text_lines:
            bbox = font.getbbox(ln)
            w = bbox[2] - bbox[0]
            max_w = max(max_w, w + pad * 2)
        max_w = min(max(int(max_w), 120), max_img_width)

        bbox_t_h = 0
        if sub_title:
            bb = title_font.getbbox(sub_title)
            bbox_t_h = bb[3] - bb[1] + pad + 12

        h = bbox_t_h + len(text_lines) * lh + pad
        img = Image.new("RGB", (max_w, max(h, 80)), bg)
        draw = ImageDraw.Draw(img)
        y = pad
        if sub_title:
            draw.text((pad, y), sub_title, fill=fg, font=title_font)
            y += bbox_t_h - 8

        for ln in text_lines:
            draw.text((pad, y), ln, fill=fg, font=font)
            y += lh

        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
        out_blobs.append(buf.getvalue())

    return out_blobs
