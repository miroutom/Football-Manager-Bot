# -*- coding: utf-8 -*-
"""
Уникальный логотип ЧМ под страну-хозяйку.

Стили вдохновлены разнообразием официальных логотипов (год крупно, кубок,
лента, лица, мяч+волна, вспышка, круг, стек) — генеративные, без копирования
офип. активов FIFA.
"""
from __future__ import annotations

import logging
import math
import os
import random
from typing import Any

try:
    from PIL import Image, ImageDraw
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
    # fallback от хеша имени
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
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(work, ((size - nw) // 2, (size - nh) // 2), work)
    return canvas


def _contrast_text(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    lum = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
    return (18, 18, 22) if lum > 150 else (245, 245, 248)


def _fill_bg(im: Image.Image, colors: tuple[tuple[int, int, int], ...], dark: bool) -> None:
    draw = ImageDraw.Draw(im)
    if dark:
        draw.rectangle([0, 0, _W, _H], fill=(8, 10, 14))
        # мягкий градиент акцента
        c0 = colors[0]
        for y in range(_H):
            t = y / max(_H - 1, 1)
            a = int(18 + 40 * (1 - abs(t - 0.45) * 1.6))
            a = max(0, min(70, a))
            overlay = Image.new("RGBA", (_W, 1), (*c0, a))
            im.paste(overlay, (0, y), overlay)
    else:
        draw.rectangle([0, 0, _W, _H], fill=(248, 248, 250))
        c0 = colors[0]
        band = Image.new("RGBA", (_W, _H // 3), (*c0, 36))
        im.paste(band, (0, 0), band)


def _draw_host_year(
    draw: ImageDraw.ImageDraw,
    *,
    host: str,
    year: int,
    y: int,
    fill: tuple[int, int, int],
    center_x: int = _W // 2,
) -> None:
    host_font = _pick_font(42, bold=True)
    year_font = _pick_font(28, bold=True)
    draw.text((center_x, y), host.upper(), fill=fill, font=host_font, anchor="mt")
    draw.text((center_x, y + 52), str(year), fill=fill, font=year_font, anchor="mt")


def _style_big_year(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    host: str,
    year: int,
    colors: tuple[tuple[int, int, int], ...],
    rng: random.Random,
) -> None:
    _fill_bg(im, colors, dark=True)
    yy = str(year)[-2:]
    # крупные цифры года цветами флага
    font = _pick_font(280, bold=True)
    c_main, c_sec = colors[0], colors[1] if len(colors) > 1 else (255, 255, 255)
    draw.text((_W // 2 - 8, _H // 2 - 40), yy[0], fill=c_main, font=font, anchor="mm")
    draw.text((_W // 2 + 8, _H // 2 + 40), yy[1] if len(yy) > 1 else "0", fill=c_sec, font=font, anchor="mm")
    trophy = _load_trophy(340)
    if trophy:
        _paste_c(im, trophy, _W // 2, _H // 2 - 10)
    caption = _pick_font(22, bold=True)
    draw.text((_W // 2, 56), "WORLD CUP", fill=(240, 240, 245), font=caption, anchor="mt")
    _draw_host_year(draw, host=host, year=year, y=_H - 130, fill=(240, 240, 245))
    badge = _flag_badge(host, 64)
    if badge:
        _paste_c(im, badge, _W // 2, _H - 40)


def _style_horizontal(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    host: str,
    year: int,
    colors: tuple[tuple[int, int, int], ...],
    rng: random.Random,
) -> None:
    _fill_bg(im, colors, dark=False)
    accent = colors[0]
    draw.rectangle([0, 0, 18, _H], fill=accent)
    if len(colors) > 1:
        draw.rectangle([18, 0, 30, _H], fill=colors[1])
    if len(colors) > 2:
        draw.rectangle([30, 0, 40, _H], fill=colors[2])
    trophy = _load_trophy(420)
    if trophy:
        _paste_c(im, trophy, 170, _H // 2)
    text_fill = (20, 40, 90)
    draw.text((420, 200), "WORLD CUP", fill=text_fill, font=_pick_font(28, bold=True), anchor="lt")
    draw.text((420, 250), str(year), fill=text_fill, font=_pick_font(72, bold=True), anchor="lt")
    draw.text((420, 340), host.upper(), fill=accent, font=_pick_font(28, bold=True), anchor="lt")
    badge = _flag_badge(host, 72)
    if badge:
        im.paste(badge, (420, 400), badge)


def _style_ribbon(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    host: str,
    year: int,
    colors: tuple[tuple[int, int, int], ...],
    rng: random.Random,
) -> None:
    _fill_bg(im, colors, dark=True)
    # лента-∞ из дуг
    cx, cy = _W // 2, _H // 2 - 40
    for i, col in enumerate(colors):
        offset = i * 10
        bbox1 = [cx - 180 + offset, cy - 90 + offset, cx + 20, cy + 90 - offset]
        bbox2 = [cx - 20, cy - 90 + offset, cx + 180 - offset, cy + 90 - offset]
        draw.arc(bbox1, 200, 340, fill=col, width=22)
        draw.arc(bbox2, 20, 160, fill=col, width=22)
    # узор на нижней дуге
    for _ in range(18):
        ang = rng.uniform(0, math.pi)
        r = rng.randint(40, 120)
        x = int(cx + math.cos(ang) * r)
        y = int(cy + 40 + math.sin(ang) * 35)
        draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=colors[0])
    draw.text((_W // 2, _H - 160), "WORLD CUP", fill=colors[0], font=_pick_font(26, bold=True), anchor="mt")
    draw.text(
        (_W // 2, _H - 110),
        f"{host} {year}",
        fill=(245, 245, 248),
        font=_pick_font(36, bold=True),
        anchor="mt",
    )


def _style_faces(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    host: str,
    year: int,
    colors: tuple[tuple[int, int, int], ...],
    rng: random.Random,
) -> None:
    _fill_bg(im, colors, dark=True)
    faces = [
        (260, 300, 160, colors[0]),
        (460, 310, 150, colors[1] if len(colors) > 1 else (80, 180, 90)),
        (360, 200, 90, colors[2] if len(colors) > 2 else (240, 140, 40)),
    ]
    for cx, cy, r, col in faces:
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
        # улыбка
        draw.arc([cx - r // 2, cy - r // 6, cx + r // 2, cy + r // 2], 20, 160, fill=(20, 20, 24), width=6)
        draw.ellipse([cx - r // 3 - 6, cy - r // 4 - 6, cx - r // 3 + 6, cy - r // 4 + 6], fill=(20, 20, 24))
        draw.ellipse([cx + r // 3 - 6, cy - r // 4 - 6, cx + r // 3 + 6, cy - r // 4 + 6], fill=(20, 20, 24))
    # дуги флага
    draw.arc([80, 180, 280, 480], 200, 320, fill=colors[0], width=10)
    if len(colors) > 1:
        draw.arc([90, 190, 270, 470], 200, 320, fill=colors[1], width=8)
    trophy = _load_trophy(110)
    if trophy:
        _paste_c(im, trophy, _W // 2, 430)
    draw.text((_W // 2, 520), "WORLD CUP", fill=(200, 210, 230), font=_pick_font(22, bold=True), anchor="mt")
    draw.text((_W // 2, 560), host.upper(), fill=colors[0], font=_pick_font(40, bold=True), anchor="mt")
    draw.text((_W // 2, 620), str(year), fill=colors[0], font=_pick_font(32, bold=True), anchor="mt")


def _style_swoosh(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    host: str,
    year: int,
    colors: tuple[tuple[int, int, int], ...],
    rng: random.Random,
) -> None:
    _fill_bg(im, colors, dark=False)
    # мяч из сегментов цветов флага
    cx, cy, r = _W // 2, 250, 110
    for i in range(8):
        col = colors[i % len(colors)]
        a0, a1 = i * 45, (i + 1) * 45
        draw.pieslice([cx - r, cy - r, cx + r, cy + r], a0, a1, fill=col)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(30, 40, 70), width=4)
    # волна-горизонт
    pts = []
    base_y = 380
    for x in range(40, _W - 40, 8):
        yy = base_y + int(28 * math.sin(x / 55.0 + rng.random() * 0.2))
        pts.append((x, yy))
    if len(pts) >= 2:
        draw.line(pts, fill=colors[0], width=28)
    text_fill = (20, 40, 90)
    yy2 = str(year)[-2:]
    draw.text((_W // 2, 450), f"{host.upper()} {yy2}", fill=text_fill, font=_pick_font(48, bold=True), anchor="mt")
    draw.line([160, 520, _W - 160, 520], fill=colors[0], width=3)
    draw.text((_W // 2, 540), "WORLD CUP", fill=(30, 30, 36), font=_pick_font(26, bold=True), anchor="mt")


def _style_burst(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    host: str,
    year: int,
    colors: tuple[tuple[int, int, int], ...],
    rng: random.Random,
) -> None:
    _fill_bg(im, colors, dark=False)
    cx, cy = _W // 2 + 40, 300
    # лучи
    for i in range(16):
        ang = i * (math.pi * 2 / 16) + rng.uniform(-0.05, 0.05)
        r0, r1 = 40, rng.randint(160, 260)
        col = colors[i % len(colors)]
        x0, y0 = cx + math.cos(ang) * r0, cy + math.sin(ang) * r0
        x1, y1 = cx + math.cos(ang) * r1, cy + math.sin(ang) * r1
        draw.line([(x0, y0), (x1, y1)], fill=col, width=18)
    # силуэт «удар» — простая фигура
    body = [
        (cx - 30, cy - 80),
        (cx + 10, cy - 20),
        (cx + 70, cy - 90),
        (cx + 40, cy + 10),
        (cx + 20, cy + 100),
        (cx - 10, cy + 40),
        (cx - 50, cy + 110),
        (cx - 40, cy + 20),
    ]
    draw.polygon(body, fill=(20, 20, 24))
    draw.ellipse([cx + 50, cy - 120, cx + 100, cy - 70], fill=colors[0], outline=(20, 20, 24), width=3)
    draw.rounded_rectangle([40, 520, 420, 640], radius=18, fill=(12, 40, 90))
    draw.text((60, 545), "WORLD CUP", fill=(255, 255, 255), font=_pick_font(28, bold=True), anchor="lt")
    draw.text((60, 585), f"{host.upper()} {year}", fill=colors[0], font=_pick_font(24, bold=True), anchor="lt")


def _style_circle(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    host: str,
    year: int,
    colors: tuple[tuple[int, int, int], ...],
    rng: random.Random,
) -> None:
    _fill_bg(im, colors, dark=True)
    cx, cy, r = _W // 2, _H // 2 - 40, 210
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(250, 250, 252))
    # дуги по краю
    for i, col in enumerate(colors):
        a0 = i * 120 - 30
        draw.arc([cx - r - 8, cy - r - 8, cx + r + 8, cy + r + 8], a0, a0 + 100, fill=col, width=16)
    trophy = _load_trophy(260)
    if trophy:
        _paste_c(im, trophy, cx, cy + 10)
    else:
        draw.ellipse([cx - 40, cy - 80, cx + 40, cy], fill=colors[0])
        draw.rectangle([cx - 18, cy, cx + 18, cy + 90], fill=colors[1] if len(colors) > 1 else colors[0])
    gold = (212, 175, 55)
    draw.text((_W // 2, _H - 150), str(year), fill=gold, font=_pick_font(48, bold=True), anchor="mt")
    draw.text((_W // 2, _H - 95), "WORLD CUP", fill=gold, font=_pick_font(22, bold=True), anchor="mt")
    # хосты разными цветами если составное имя
    parts = host.upper().split()
    if len(parts) >= 2 and len(colors) >= 2:
        draw.text((_W // 2 - 80, _H - 50), parts[0], fill=colors[0], font=_pick_font(28, bold=True), anchor="mt")
        draw.text((_W // 2 + 80, _H - 50), parts[-1], fill=colors[1], font=_pick_font(28, bold=True), anchor="mt")
    else:
        draw.text((_W // 2, _H - 50), host.upper(), fill=colors[0], font=_pick_font(28, bold=True), anchor="mt")


def _style_stack(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    host: str,
    year: int,
    colors: tuple[tuple[int, int, int], ...],
    rng: random.Random,
) -> None:
    """Стек цветных полос флага + кубок + год."""
    _fill_bg(im, colors, dark=True)
    band_h = 70
    y0 = 120
    for i, col in enumerate(colors):
        draw.rectangle([80, y0 + i * band_h, _W - 80, y0 + (i + 1) * band_h], fill=col)
    trophy = _load_trophy(300)
    if trophy:
        _paste_c(im, trophy, _W // 2, 380)
    draw.text((_W // 2, 40), "WORLD CUP", fill=(240, 240, 245), font=_pick_font(24, bold=True), anchor="mt")
    _draw_host_year(draw, host=host, year=year, y=_H - 120, fill=(240, 240, 245))


_STYLE_FN = {
    "big_year": _style_big_year,
    "horizontal": _style_horizontal,
    "ribbon": _style_ribbon,
    "faces": _style_faces,
    "swoosh": _style_swoosh,
    "burst": _style_burst,
    "circle": _style_circle,
    "stack": _style_stack,
}


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
    year = int(brand.get("display_year") or 2026)
    style = str(brand.get("style") or "big_year")
    if style not in _STYLE_FN:
        style = LOGO_STYLES[0]
    seed = int(brand.get("seed") or (n * 17 + 3))
    rng = random.Random(seed)
    colors = _palette(host)

    im = Image.new("RGBA", (_W, _H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(im)
    _STYLE_FN[style](im, draw, host=host, year=year, colors=colors, rng=rng)

    # лёгкий виньет
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
