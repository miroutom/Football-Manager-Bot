# -*- coding: utf-8 -*-
"""
Уникальный логотип ЧМ под страну-хозяйку.

Все стили: крупный кубок + цвета флага + «WORLD CUP» + хост + сезон.
"""
from __future__ import annotations

import logging
import math
import os
import random
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError as e:
    raise ImportError("Нужен пакет Pillow: pip install pillow") from e

from bot.squad_pitch import (
    _flag_v3_trip,
    _nation_to_flagcdn_code,
    _pick_font,
)
from utils import season_paths
from utils.squad_graphics_assets import load_flag_png
from utils.wc_branding import LOGO_STYLES, ensure_branding

logger = logging.getLogger(__name__)

_CACHE_DIR = os.path.join(season_paths.PROJECT_ROOT, "assets", "cache", "wc_logos")
_TROPHY = os.path.join(
    season_paths.PROJECT_ROOT, "assets", "history", "trophies", "cup_gold.png"
)

_W, _H = 720, 720

# старые абстрактные стили → читаемые с кубком
_LEGACY_STYLE = {
    "big_year": "trophy_center",
    "horizontal": "trophy_side",
    "ribbon": "trophy_rings",
    "faces": "trophy_bands",
    "swoosh": "trophy_center",
    "burst": "trophy_side",
    "circle": "trophy_rings",
    "stack": "trophy_bands",
}


def clear_logo_cache(season: int | None = None) -> None:
    if not os.path.isdir(_CACHE_DIR):
        return
    if season is None:
        for name in os.listdir(_CACHE_DIR):
            if name.endswith(".png"):
                try:
                    os.remove(os.path.join(_CACHE_DIR, name))
                except OSError:
                    pass
        return
    path = os.path.join(_CACHE_DIR, f"season_{int(season)}.png")
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def logo_cache_path(season: int) -> str:
    return os.path.join(_CACHE_DIR, f"season_{int(season)}.png")


def _palette(host: str) -> tuple[tuple[int, int, int], ...]:
    trip = _flag_v3_trip(_nation_to_flagcdn_code(host))
    if trip:
        return trip
    h = abs(hash(host.casefold()))
    return (
        ((h >> 0) & 255, (h >> 8) & 255, (h >> 16) & 255),
        (255, 255, 255),
        ((h >> 4) & 200, (h >> 12) & 200, (h >> 20) & 200),
    )


def _load_trophy(max_h: int) -> Image.Image | None:
    if not os.path.isfile(_TROPHY):
        return None
    try:
        im = Image.open(_TROPHY).convert("RGBA")
    except OSError:
        return None
    # обрезать пустые края альфы — кубок крупнее и чётче
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)
    tw, th = im.size
    scale = max_h / max(th, 1)
    nw, nh = max(1, int(tw * scale)), max(1, int(th * scale))
    return im.resize((nw, nh), Image.Resampling.LANCZOS)


def _paste_c(im: Image.Image, overlay: Image.Image, cx: int, cy: int) -> None:
    x = int(cx - overlay.width // 2)
    y = int(cy - overlay.height // 2)
    im.paste(overlay, (x, y), overlay)


def _flag_badge(host: str, size: int = 56) -> Image.Image | None:
    fcode = _nation_to_flagcdn_code(host)
    fimg = load_flag_png(fcode) if fcode else None
    if fimg is None:
        return None
    work = fimg.convert("RGBA")
    tw, th = work.size
    scale = min(size / max(tw, 1), size / max(th, 1))
    nw, nh = max(1, int(tw * scale)), max(1, int(th * scale))
    work = work.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size + 8, size + 8), (0, 0, 0, 0))
    # лёгкая рамка
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle(
        [0, 0, size + 7, size + 7], radius=6, fill=(20, 24, 32), outline=(220, 220, 230), width=2
    )
    canvas.paste(work, (4 + (size - nw) // 2, 4 + (size - nh) // 2), work)
    return canvas


def _fill_dark(im: Image.Image, colors: tuple[tuple[int, int, int], ...]) -> None:
    draw = ImageDraw.Draw(im)
    draw.rectangle([0, 0, _W, _H], fill=(12, 14, 20))
    # вертикальные мягкие полосы цветов флага слева
    band_w = 14
    for i, col in enumerate(colors[:3]):
        x0 = 0 + i * band_w
        overlay = Image.new("RGBA", (band_w, _H), (*col, 160))
        im.paste(overlay, (x0, 0), overlay)
    # лёгкое свечение в центре под кубком
    glow = Image.new("RGBA", (_W, _H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    c0 = colors[0]
    for r, a in ((220, 40), (160, 55), (100, 70)):
        gd.ellipse(
            [_W // 2 - r, _H // 2 - 40 - r, _W // 2 + r, _H // 2 - 40 + r],
            fill=(*c0, a),
        )
    glow = glow.filter(ImageFilter.GaussianBlur(28))
    im.alpha_composite(glow)


def _fill_light(im: Image.Image, colors: tuple[tuple[int, int, int], ...]) -> None:
    draw = ImageDraw.Draw(im)
    draw.rectangle([0, 0, _W, _H], fill=(245, 246, 250))
    for i, col in enumerate(colors[:3]):
        overlay = Image.new("RGBA", (_W, 18), (*col, 220))
        im.paste(overlay, (0, 24 + i * 18), overlay)


def _caption_block(
    draw: ImageDraw.ImageDraw,
    *,
    host: str,
    season: int,
    fill: tuple[int, int, int],
    y: int,
) -> None:
    draw.text(
        (_W // 2, y),
        "WORLD CUP",
        fill=fill,
        font=_pick_font(26, bold=True),
        anchor="mt",
    )
    draw.text(
        (_W // 2, y + 40),
        f"{host} · сезон {int(season)}",
        fill=fill,
        font=_pick_font(36, bold=True),
        anchor="mt",
    )


def _style_trophy_center(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    host: str,
    season: int,
    colors: tuple[tuple[int, int, int], ...],
    rng: random.Random,
) -> None:
    _fill_dark(im, colors)
    trophy = _load_trophy(420)
    if trophy:
        _paste_c(im, trophy, _W // 2, _H // 2 - 30)
    else:
        draw.ellipse([_W // 2 - 80, 180, _W // 2 + 80, 340], fill=(212, 175, 55))
    _caption_block(draw, host=host, season=season, fill=(245, 245, 248), y=_H - 150)
    badge = _flag_badge(host, 56)
    if badge:
        _paste_c(im, badge, _W // 2, _H - 48)


def _style_trophy_side(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    host: str,
    season: int,
    colors: tuple[tuple[int, int, int], ...],
    rng: random.Random,
) -> None:
    _fill_light(im, colors)
    accent = colors[0]
    draw.rectangle([0, 0, 28, _H], fill=accent)
    if len(colors) > 1:
        draw.rectangle([28, 0, 40, _H], fill=colors[1])
    trophy = _load_trophy(460)
    if trophy:
        _paste_c(im, trophy, 200, _H // 2 + 10)
    text_fill = (20, 28, 48)
    draw.text((400, 210), "WORLD CUP", fill=text_fill, font=_pick_font(28, bold=True), anchor="lt")
    draw.text(
        (400, 260),
        f"сезон {int(season)}",
        fill=text_fill,
        font=_pick_font(52, bold=True),
        anchor="lt",
    )
    draw.text((400, 340), host, fill=accent, font=_pick_font(34, bold=True), anchor="lt")
    badge = _flag_badge(host, 64)
    if badge:
        im.paste(badge, (400, 400), badge)


def _style_trophy_rings(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    host: str,
    season: int,
    colors: tuple[tuple[int, int, int], ...],
    rng: random.Random,
) -> None:
    _fill_dark(im, colors)
    cx, cy, r = _W // 2, _H // 2 - 50, 230
    # кольца цветов флага
    for i, col in enumerate(colors[:3]):
        rr = r + 18 - i * 14
        draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=col, width=10)
    draw.ellipse([cx - r + 30, cy - r + 30, cx + r - 30, cy + r - 30], fill=(18, 22, 30))
    trophy = _load_trophy(320)
    if trophy:
        _paste_c(im, trophy, cx, cy + 8)
    _caption_block(draw, host=host, season=season, fill=(245, 245, 248), y=_H - 140)
    badge = _flag_badge(host, 52)
    if badge:
        _paste_c(im, badge, _W // 2, _H - 42)


def _style_trophy_bands(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    host: str,
    season: int,
    colors: tuple[tuple[int, int, int], ...],
    rng: random.Random,
) -> None:
    _fill_dark(im, colors)
    # широкие горизонтальные полосы флага за кубком
    band_h = 88
    y0 = 160
    for i, col in enumerate(colors[:3]):
        draw.rectangle([70, y0 + i * band_h, _W - 70, y0 + (i + 1) * band_h - 6], fill=col)
    # полупрозрачная подложка под кубок
    panel = Image.new("RGBA", (_W, _H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle([210, 120, 510, 520], radius=24, fill=(8, 10, 14, 170))
    im.alpha_composite(panel)
    trophy = _load_trophy(360)
    if trophy:
        _paste_c(im, trophy, _W // 2, 320)
    _caption_block(draw, host=host, season=season, fill=(245, 245, 248), y=_H - 140)
    badge = _flag_badge(host, 52)
    if badge:
        _paste_c(im, badge, _W // 2, _H - 42)


_STYLE_FN = {
    "trophy_center": _style_trophy_center,
    "trophy_side": _style_trophy_side,
    "trophy_rings": _style_trophy_rings,
    "trophy_bands": _style_trophy_bands,
}


def _resolve_style(raw: str) -> str:
    s = (raw or "").strip()
    if s in _STYLE_FN:
        return s
    mapped = _LEGACY_STYLE.get(s)
    if mapped in _STYLE_FN:
        return mapped
    return LOGO_STYLES[0]


def render_wc_logo_png_bytes(
    season: int | None = None,
    *,
    branding: dict[str, Any] | None = None,
    use_cache: bool = True,
) -> bytes:
    from utils import season_paths as sp

    n = int(season if season is not None else sp.get_active_season())
    brand = branding or ensure_branding(n)
    cache = logo_cache_path(n)
    if use_cache and os.path.isfile(cache):
        with open(cache, "rb") as f:
            return f.read()

    host = str(brand.get("host") or "Host")
    season_n = int(brand.get("season") or n)
    style = _resolve_style(str(brand.get("style") or LOGO_STYLES[0]))
    seed = int(brand.get("seed") or (n * 17 + 3))
    rng = random.Random(seed)
    colors = _palette(host)

    im = Image.new("RGBA", (_W, _H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(im)
    _STYLE_FN[style](im, draw, host=host, season=season_n, colors=colors, rng=rng)

    rgb = im.convert("RGB")
    out = __import__("io").BytesIO()
    rgb.save(out, format="PNG", optimize=True)
    data = out.getvalue()
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(cache, "wb") as f:
            f.write(data)
    except OSError:
        logger.exception("wc logo cache write")
    return data


def theme_colors_for_wc(season: int | None = None) -> tuple[tuple[int, int, int], ...]:
    brand = ensure_branding(season)
    return _palette(str(brand.get("host") or ""))
