# -*- coding: utf-8 -*-
"""
Общие примитивы для инфографик отчётов бота: эмблемы, обрезка текста, темы лиг.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    raise ImportError("Нужен пакет Pillow: pip install pillow") from e

from bot.squad_pitch import (
    _crest_initials,
    _paste_crest_natural,
    _pick_font,
    _team_name_as_in_db,
    _try_load_crest_rgba,
)
from squad_kit_palette import kit_for_team


@dataclass(frozen=True)
class LeagueTheme:
    code: str
    title: str
    bg: tuple[int, int, int]
    header: tuple[int, int, int]
    row_a: tuple[int, int, int]
    row_b: tuple[int, int, int]
    accent: tuple[int, int, int]
    text: tuple[int, int, int]
    text_dim: tuple[int, int, int]
    highlight: tuple[int, int, int]


# Каждая лига — свой характер (не «фиолетовый AI-дефолт»).
_LEAGUE_THEMES: dict[str, LeagueTheme] = {
    "rpl": LeagueTheme(
        "rpl", "РПЛ",
        (246, 248, 252), (18, 52, 110), (255, 255, 255), (236, 242, 250),
        (200, 16, 46), (18, 24, 38), (100, 112, 132), (18, 52, 110),
    ),
    "eng": LeagueTheme(
        "eng", "АПЛ",
        (245, 247, 250), (55, 0, 60), (255, 255, 255), (238, 232, 242),
        (0, 255, 133), (20, 16, 28), (110, 100, 120), (55, 0, 60),
    ),
    "esp": LeagueTheme(
        "esp", "Ла Лига",
        (252, 248, 242), (140, 28, 28), (255, 255, 255), (250, 240, 228),
        (244, 185, 66), (32, 24, 18), (120, 100, 80), (140, 28, 28),
    ),
    "ita": LeagueTheme(
        "ita", "Серия А",
        (244, 248, 252), (0, 70, 140), (255, 255, 255), (232, 240, 248),
        (0, 120, 200), (16, 28, 44), (90, 110, 130), (0, 70, 140),
    ),
    "ger": LeagueTheme(
        "ger", "Бундеслига",
        (250, 250, 250), (28, 28, 28), (255, 255, 255), (240, 240, 240),
        (220, 0, 0), (20, 20, 20), (100, 100, 100), (220, 0, 0),
    ),
    "cl": LeagueTheme(
        "cl", "Лига чемпионов",
        (8, 16, 42), (12, 28, 72), (14, 32, 78), (18, 40, 92),
        (212, 175, 55), (245, 245, 250), (160, 175, 210), (212, 175, 55),
    ),
    "wc": LeagueTheme(
        "wc", "ЧМ",
        (8, 40, 28), (12, 70, 48), (14, 58, 42), (18, 72, 52),
        (250, 210, 80), (245, 250, 245), (160, 200, 180), (250, 210, 80),
    ),
}

_DEFAULT_THEME = LeagueTheme(
    "?", "Лига",
    (248, 248, 250), (30, 40, 60), (255, 255, 255), (238, 240, 244),
    (40, 100, 180), (20, 24, 32), (110, 118, 132), (40, 100, 180),
)

# Тёмная «игрок-лист» (бомбардиры / стата клуба) — как stats_history.
PLAYER_BOARD_DARK = LeagueTheme(
    "players", "Игроки",
    (8, 22, 58), (14, 38, 88), (14, 38, 88), (18, 48, 102),
    (255, 230, 120), (255, 255, 255), (170, 190, 220), (255, 230, 120),
)

# Травмы / дисциплина — холодный сланец + медкрасный акцент.
INJURY_THEME = LeagueTheme(
    "inj", "Травмы",
    (24, 28, 36), (36, 42, 54), (32, 38, 48), (40, 46, 58),
    (220, 72, 72), (245, 246, 248), (160, 168, 180), (255, 196, 72),
)


def theme_for_league(code: str | None) -> LeagueTheme:
    c = (code or "").strip().lower()
    if c in ("wc", "world_cup"):
        try:
            from bot.wc_logo import theme_colors_for_wc
            from utils import season_paths

            cols = theme_colors_for_wc(season_paths.get_active_season())
            c0 = cols[0]
            c1 = cols[1] if len(cols) > 1 else (250, 210, 80)
            # тёмный фон, акцент — цвет хоста
            header = (
                max(8, c0[0] // 3),
                max(12, c0[1] // 3),
                max(16, c0[2] // 3),
            )
            return LeagueTheme(
                "wc",
                "ЧМ",
                (8, 16, 22),
                header,
                (14, 28, 36),
                (18, 36, 44),
                c1 if c1 != (255, 255, 255) else c0,
                (245, 250, 245),
                (160, 190, 180),
                c0,
            )
        except Exception:
            pass
    return _LEAGUE_THEMES.get(c, _DEFAULT_THEME)


def pick_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    return _pick_font(size, bold=bold)


def truncate(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_w: int,
) -> str:
    s = (text or "").strip() or "?"
    if draw.textlength(s, font=font) <= max_w:
        return s
    while len(s) > 2 and draw.textlength(s + "…", font=font) > max_w:
        s = s[:-1]
    return s + "…"


def paste_crest(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    team: str,
    cx: int,
    cy: int,
    size: int = 34,
    crest_font: ImageFont.ImageFont | None = None,
    light_placeholder: bool = False,
) -> None:
    """Эмблема клуба или круг с инициалами в цветах формы."""
    team_db = _team_name_as_in_db(team)
    kit = kit_for_team(team_db)
    crest = _try_load_crest_rgba(team_db)
    if crest is not None:
        _paste_crest_natural(im, crest, cx, cy, size)
        return
    r = size // 2
    outline = (200, 210, 230) if light_placeholder else (120, 140, 180)
    txt = (255, 255, 255) if not light_placeholder else (255, 255, 255)
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        fill=kit.primary,
        outline=outline,
        width=1,
    )
    font = crest_font or pick_font(max(9, size // 3), bold=True)
    draw.text(
        (cx, cy),
        _crest_initials(team_db),
        fill=txt,
        font=font,
        anchor="mm",
    )


def kit_accent_stripe(
    draw: ImageDraw.ImageDraw,
    *,
    team: str,
    x0: int,
    y0: int,
    y1: int,
    width: int = 4,
) -> None:
    """Узкая полоска цвета клуба слева от строки таблицы."""
    kit = kit_for_team(_team_name_as_in_db(team))
    draw.rectangle([x0, y0, x0 + max(1, width), y1], fill=kit.primary)


def display_player_name(full_name: str) -> str:
    from utils.player_names import _name_parts

    fn, sn = _name_parts(full_name or "")
    sn_up = (sn or full_name or "?").upper()
    if fn:
        return f"{fn[0].upper()}. {sn_up}"
    return sn_up


def png_bytes(im: Image.Image) -> bytes:
    from io import BytesIO

    buf = BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def draw_header_bar(
    draw: ImageDraw.ImageDraw,
    *,
    theme: LeagueTheme,
    width: int,
    height: int,
    title: str,
    subtitle: str | None = None,
) -> None:
    draw.rectangle([0, 0, width, height], fill=theme.header)
    draw.rectangle([0, height - 4, width, height], fill=theme.accent)
    title_font = pick_font(28, bold=True)
    sub_font = pick_font(14)
    title_fill = (255, 255, 255) if _is_dark(theme.header) else theme.text
    dim = (190, 200, 220) if _is_dark(theme.header) else theme.text_dim
    draw.text((18, 14 if subtitle else 22), title, fill=title_fill, font=title_font)
    if subtitle:
        draw.text(
            (18, 50),
            truncate(draw, subtitle, sub_font, width - 36),
            fill=dim,
            font=sub_font,
        )


def _is_dark(rgb: tuple[int, int, int]) -> bool:
    return (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) < 140


def paste_nation_flag(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    nation: str,
    cx: int,
    cy: int,
    size: int = 34,
) -> None:
    """Флаг сборной (flagcdn) по центру (cx, cy); fallback — круг с инициалами."""
    from bot.squad_pitch import (
        _crest_initials,
        _nation_to_flagcdn_code,
        _team_name_as_in_db,
    )
    from utils.squad_graphics_assets import load_flag_png

    nat = (nation or "").strip()
    fcode = _nation_to_flagcdn_code(nat)
    fimg = load_flag_png(fcode) if fcode else None
    if fimg is not None:
        work = fimg.convert("RGBA")
        # вписать в квадрат size×size
        tw, th = work.size
        scale = min(size / max(tw, 1), size / max(th, 1))
        nw, nh = max(1, int(tw * scale)), max(1, int(th * scale))
        work = work.resize((nw, nh), Image.Resampling.LANCZOS)
        x0 = cx - nw // 2
        y0 = cy - nh // 2
        im.paste(work, (x0, y0), work)
        return
    # fallback
    from squad_kit_palette import kit_for_team

    team_db = _team_name_as_in_db(nat)
    kit = kit_for_team(team_db)
    r = size // 2
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        fill=kit.primary,
        outline=(200, 210, 230),
        width=1,
    )
    font = pick_font(max(9, size // 3), bold=True)
    draw.text((cx, cy), _crest_initials(team_db or nat or "?"), fill=(255, 255, 255), font=font, anchor="mm")


def paste_row_emblem(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    label: str,
    cx: int,
    cy: int,
    size: int = 34,
    mode: str = "club",
    crest_font: ImageFont.ImageFont | None = None,
    light_placeholder: bool = False,
) -> None:
    """``mode``: ``club`` (эмблема клуба) или ``nation`` (флаг сборной)."""
    if (mode or "club").strip().lower() in ("nation", "flag", "wc", "national"):
        paste_nation_flag(im, draw, nation=label, cx=cx, cy=cy, size=size)
        return
    paste_crest(
        im,
        draw,
        team=label,
        cx=cx,
        cy=cy,
        size=size,
        crest_font=crest_font,
        light_placeholder=light_placeholder,
    )
