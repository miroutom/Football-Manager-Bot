# -*- coding: utf-8 -*-
"""Победный состав чемпиона лиги/ЛЧ: схема + статистика игроков сезона."""
from __future__ import annotations

from PIL import Image, ImageDraw

from bot.season_history_store import timeline_cl, timeline_league
from bot.squad_pitch import (
    _pick_font,
    _try_load_crest_rgba,
    load_team_squad_players,
    render_squad_pitch_png_bytes,
)
from bot.team_history import format_season_tag, list_history_seasons
from bot.team_history_gallery import _fit, _gradient_bg, _paste_crest_natural, _title, _to_png

_CANVAS_W = 1200
_PAD = 28
_TEXT = (248, 250, 252)
_DIM = (160, 176, 196)
_GOLD = (255, 214, 110)
_CARD = (28, 40, 62)
_LINE = (48, 64, 92)
_START = (70, 140, 230)
_BENCH = (90, 190, 160)
_RESERVE = (120, 130, 150)


def champion_seasons_league(league_code: str) -> list[tuple[int, str]]:
    """Сезоны с известным чемпионом лиги ``(номер, клуб)``."""
    max_s = max(list_history_seasons() or [1])
    return [(s, t) for s, t in timeline_league(league_code, max_s) if t]


def champion_seasons_cl() -> list[tuple[int, str]]:
    max_s = max(list_history_seasons() or [1])
    return [(s, t) for s, t in timeline_cl(max_s) if t]


def _status_label(st: str | None) -> str:
    sx = (st or "").strip().lower()
    if sx == "start":
        return "С"
    if sx == "bench":
        return "З"
    if sx == "reserve":
        return "Р"
    return "—"


def _status_color(st: str | None) -> tuple[int, int, int]:
    sx = (st or "").strip().lower()
    if sx == "start":
        return _START
    if sx == "bench":
        return _BENCH
    if sx == "reserve":
        return _RESERVE
    return _LINE


def render_champion_squad_stats_png_bytes(
    team: str,
    *,
    season_num: int,
    cl: bool,
    league_title: str | None = None,
) -> bytes:
    tournament = "cl" if cl else "league"
    players = load_team_squad_players(team, tournament, season_num=season_num)
    rows = sorted(
        players,
        key=lambda p: (-int(p.ga or 0), -int(p.goals or 0), -int(p.assists or 0), (p.name or "").lower()),
    )

    font_m = _pick_font(17)
    font_sm = _pick_font(14)
    font_b = _pick_font(20, bold=True)
    font_h = _pick_font(13, bold=True)

    row_h = 34
    header_h = 36
    table_h = header_h + max(1, len(rows)) * row_h + 16
    h = 120 + table_h + 40
    im = _gradient_bg(min(h, 3200)).convert("RGBA")
    draw = ImageDraw.Draw(im)

    scope = "ЛЧ" if cl else (league_title or "Лига")
    y = _title(
        draw,
        "Победный состав · вклад",
        f"{format_season_tag(season_num)} · {scope} · {team}",
    )

    crest = _try_load_crest_rgba(team)
    if crest is not None:
        _paste_crest_natural(im, crest, _CANVAS_W - _PAD - 36, y - 52, 56)

    x0 = _PAD
    x1 = _CANVAS_W - _PAD
    cols = [
        (x0 + 8, 36, "#"),
        (x0 + 52, 320, "Игрок"),
        (x0 + 390, 56, "Поз"),
        (x0 + 460, 44, "С"),
        (x0 + 520, 48, "Г"),
        (x0 + 580, 48, "А"),
        (x0 + 640, 56, "Г+А"),
        (x0 + 720, 56, "OVR"),
    ]

    draw.rounded_rectangle([x0, y, x1, y + table_h], radius=14, fill=_CARD, outline=_LINE)
    hy = y + 10
    for cx, cw, lab in cols:
        draw.text((cx, hy), lab, font=font_h, fill=_DIM)
    draw.line([(x0 + 12, y + header_h - 4), (x1 - 12, y + header_h - 4)], fill=_LINE, width=1)

    if not rows:
        draw.text((x0 + 16, y + header_h + 12), "Игроки в архиве сезона не найдены.", font=font_m, fill=_DIM)
        return _to_png(im.convert("RGB"))

    for i, p in enumerate(rows):
        ry = y + header_h + i * row_h
        if i % 2 == 1:
            draw.rectangle([x0 + 8, ry, x1 - 8, ry + row_h - 2], fill=(22, 32, 50))
        st_col = _status_color(p.status)
        draw.text((cols[0][0], ry + 8), str(i + 1), font=font_sm, fill=_DIM)
        draw.text((cols[1][0], ry + 6), _fit(draw, p.name, font_m, cols[1][1]), font=font_m, fill=_TEXT)
        draw.text((cols[2][0], ry + 8), _fit(draw, p.position or "—", font_sm, cols[2][1]), font=font_sm, fill=_DIM)
        draw.rounded_rectangle(
            [cols[3][0], ry + 8, cols[3][0] + 22, ry + 26],
            radius=4,
            fill=st_col,
        )
        sl = _status_label(p.status)
        sw = draw.textbbox((0, 0), sl, font=font_h)[2]
        draw.text((cols[3][0] + 11 - sw // 2, ry + 7), sl, font=font_h, fill=(255, 255, 255))
        g, a, ga = int(p.goals or 0), int(p.assists or 0), int(p.ga or 0)
        accent = _GOLD if ga > 0 else _TEXT
        draw.text((cols[4][0], ry + 6), str(g), font=font_b if g else font_m, fill=accent if g else _DIM)
        draw.text((cols[5][0], ry + 6), str(a), font=font_b if a else font_m, fill=accent if a else _DIM)
        draw.text((cols[6][0], ry + 6), str(ga), font=font_b if ga else font_m, fill=accent if ga else _DIM)
        draw.text((cols[7][0], ry + 8), str(int(p.overall or 0)), font=font_sm, fill=_DIM)

    foot = "С — старт · З — скамейка · Р — резерв · сортировка по Г+А"
    draw.text((_PAD, y + table_h + 12), foot, font=font_sm, fill=_DIM)
    return _to_png(im.convert("RGB"))


def render_champion_squad_pages(
    team: str,
    *,
    season_num: int,
    cl: bool,
    league_title: str | None = None,
) -> list[bytes]:
    """Два PNG: схема поля и таблица вклада."""
    tournament = "cl" if cl else "league"
    scope = "ЛЧ" if cl else (league_title or "лига")
    extra = f"{format_season_tag(season_num)} · чемпион {scope}"
    pitch = render_squad_pitch_png_bytes(
        team,
        tournament,
        season_num=season_num,
        headline_extra=extra,
    )
    stats = render_champion_squad_stats_png_bytes(
        team,
        season_num=season_num,
        cl=cl,
        league_title=league_title,
    )
    return [pitch, stats]
