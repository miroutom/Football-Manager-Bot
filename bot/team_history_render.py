# -*- coding: utf-8 -*-
"""PNG для раздела «История → Клубы»: рейтинг силы, разрез престижа, досье клуба."""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from bot.squad_pitch import _paste_crest_natural, _pick_font, _try_load_crest_rgba
from bot.team_history import (
    ClubDossier,
    TeamPrestige,
    build_club_dossier,
    cl_stage_short,
    prestige_formula_caption,
    rank_teams_by_prestige,
)

_CANVAS_W = 1200
_PAD = 28
_BG_TOP = (18, 28, 48)
_BG_BOT = (10, 16, 28)
_TEXT = (248, 250, 252)
_DIM = (160, 176, 196)
_GOLD = (255, 214, 110)
_BAR = (56, 130, 220)
_BAR2 = (90, 190, 160)
_CARD = (28, 40, 62)
_LINE = (48, 64, 92)


def _gradient_bg(h: int) -> Image.Image:
    im = Image.new("RGB", (_CANVAS_W, h), _BG_BOT)
    draw = ImageDraw.Draw(im)
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(int(_BG_TOP[i] * (1 - t) + _BG_BOT[i] * t) for i in range(3))
        draw.line([(0, y), (_CANVAS_W, y)], fill=c)
    return im


def _to_png(im: Image.Image) -> bytes:
    buf = BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _draw_title(draw: ImageDraw.ImageDraw, title: str, subtitle: str, y0: int = 18) -> int:
    font_t = _pick_font(42, bold=True)
    font_s = _pick_font(20)
    draw.text((_PAD, y0), title, font=font_t, fill=_TEXT)
    bbox = draw.textbbox((0, 0), title, font=font_t)
    y = y0 + (bbox[3] - bbox[1]) + 8
    draw.text((_PAD, y), subtitle, font=font_s, fill=_DIM)
    bbox2 = draw.textbbox((0, 0), subtitle, font=font_s)
    return y + (bbox2[3] - bbox2[1]) + 18


def _fit(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> str:
    t = text
    while t and draw.textbbox((0, 0), t, font=font)[2] > max_w:
        t = t[:-1]
    if t != text and len(t) > 1:
        t = t[:-1] + "…"
    return t or text[:1]


def render_power_ranking_png(*, limit: int | None = None) -> bytes:
    """Рейтинг силы. ``limit=None`` — все клубы (обычно 40)."""
    rows = rank_teams_by_prestige(limit=limit)
    row_h = 48 if len(rows) > 20 else 54
    header_h = 110
    foot_h = 56
    h = header_h + len(rows) * row_h + foot_h
    im = _gradient_bg(h).convert("RGBA")
    draw = ImageDraw.Draw(im)
    y = _draw_title(
        draw,
        "Рейтинг силы клубов",
        prestige_formula_caption(),
    )
    font_r = _pick_font(22, bold=True)
    font_n = _pick_font(24, bold=True)
    font_s = _pick_font(16)
    max_score = max((r.score for r in rows), default=1.0) or 1.0
    bar_x0 = 320
    bar_x1 = _CANVAS_W - _PAD - 90

    for i, r in enumerate(rows, start=1):
        top = y + (i - 1) * row_h
        draw.rounded_rectangle(
            [_PAD, top + 4, _CANVAS_W - _PAD, top + row_h - 4],
            radius=10,
            fill=_CARD,
            outline=_LINE,
        )
        rank_col = _GOLD if i <= 3 else _TEXT
        draw.text((_PAD + 14, top + 14), f"{i:02d}", font=font_r, fill=rank_col)
        crest = _try_load_crest_rgba(r.team)
        if crest is not None:
            _paste_crest_natural(im, crest, _PAD + 88, top + row_h // 2, 36)
        name = _fit(draw, r.team, font_n, 150)
        draw.text((_PAD + 120, top + 12), name, font=font_n, fill=_TEXT)
        meta = f"{r.league_code.upper() or '—'} · OVR {r.roster_ovr:g}"
        draw.text((_PAD + 120, top + 36), meta, font=font_s, fill=_DIM)

        bw = int((bar_x1 - bar_x0) * (r.score / max_score))
        draw.rounded_rectangle(
            [bar_x0, top + 18, bar_x0 + max(bw, 4), top + 36],
            radius=6,
            fill=_BAR if i > 3 else _GOLD,
        )
        draw.text((bar_x1 + 10, top + 16), f"{r.score:.0f}", font=font_r, fill=_TEXT)

    foot = _pick_font(16)
    draw.text(
        (_PAD, h - 36),
        "Топ учитывает вес лиги: чемпион РПЛ даёт меньше престижа, чем титул АПЛ / путь в ЛЧ.",
        font=foot,
        fill=_DIM,
    )
    return _to_png(im.convert("RGB"))


def render_prestige_breakdown_png(*, limit: int = 10) -> bytes:
    rows = rank_teams_by_prestige(limit=limit)
    keys = ["Лига", "ЛЧ титул", "ЛЧ путь", "Состав", "Награды"]
    colors = [
        (70, 140, 220),
        (255, 190, 70),
        (120, 200, 160),
        (180, 140, 230),
        (230, 120, 120),
    ]
    row_h = 58
    header_h = 120
    legend_h = 48
    h = header_h + len(rows) * row_h + legend_h + 40
    im = _gradient_bg(h).convert("RGBA")
    draw = ImageDraw.Draw(im)
    y = _draw_title(
        draw,
        "Из чего складывается престиж",
        "Стек-бар: вклад лиги / ЛЧ / состава / наград (топ клубов)",
    )
    # legend
    font_l = _pick_font(16)
    lx = _PAD
    for lab, col in zip(keys, colors):
        draw.rounded_rectangle([lx, y, lx + 16, y + 16], radius=3, fill=col)
        draw.text((lx + 22, y - 1), lab, font=font_l, fill=_DIM)
        lx += 22 + draw.textbbox((0, 0), lab, font=font_l)[2] + 18
    y += 28

    font_n = _pick_font(22, bold=True)
    font_s = _pick_font(15)
    max_score = max((r.score for r in rows), default=1.0) or 1.0
    bar_x0 = 210
    bar_x1 = _CANVAS_W - _PAD - 70

    for i, r in enumerate(rows):
        top = y + i * row_h
        draw.rounded_rectangle(
            [_PAD, top + 4, _CANVAS_W - _PAD, top + row_h - 4],
            radius=10,
            fill=_CARD,
            outline=_LINE,
        )
        crest = _try_load_crest_rgba(r.team)
        if crest is not None:
            _paste_crest_natural(im, crest, _PAD + 30, top + row_h // 2, 34)
        draw.text((_PAD + 56, top + 16), _fit(draw, r.team, font_n, 140), font=font_n, fill=_TEXT)

        x = bar_x0
        parts = [float(r.breakdown.get(k, 0.0)) for k in keys]
        for val, col in zip(parts, colors):
            if val <= 0:
                continue
            w = max(3, int((bar_x1 - bar_x0) * (val / max_score)))
            draw.rectangle([x, top + 20, x + w, top + 38], fill=col)
            x += w
        draw.text((bar_x1 + 8, top + 16), f"{r.score:.0f}", font=font_n, fill=_TEXT)
        tiny = (
            f"чемп.{r.league_titles} · ЛЧ {r.cl_titles} · "
            f"лучш. {cl_stage_short(r.best_cl_stage)}"
        )
        draw.text((_PAD + 56, top + 38), tiny, font=font_s, fill=_DIM)

    return _to_png(im.convert("RGB"))


def render_club_dossier_png(team: str) -> bytes:
    from bot.team_history import format_season_list, format_season_tag

    d: ClubDossier = build_club_dossier(team)
    p: TeamPrestige = d.prestige

    awards_block_h = 0
    if d.awards:
        awards_block_h = 36 + ((len(d.awards[:6]) + 1) // 2) * 56 + 12
    legends_h = 52 + max(1, len(d.legends)) * 32
    h = 560 + awards_block_h + legends_h
    im = _gradient_bg(h).convert("RGBA")
    draw = ImageDraw.Draw(im)

    font_t = _pick_font(44, bold=True)
    font_s = _pick_font(20)
    font_b = _pick_font(22, bold=True)
    font_m = _pick_font(18)
    font_sm = _pick_font(15)
    font_kpi = _pick_font(28, bold=True)
    font_kpi_sm = _pick_font(20, bold=True)

    # Header centered-ish with crest
    crest = _try_load_crest_rgba(d.team)
    if crest is not None:
        _paste_crest_natural(im, crest, _CANVAS_W // 2 - 160, 52, 64)
    title = d.team
    tw = draw.textbbox((0, 0), title, font=font_t)[2]
    draw.text(((_CANVAS_W - tw) // 2 + 20, 22), title, font=font_t, fill=_TEXT)
    sub = f"{d.league_title} · престиж {p.score:.0f} · OVR состава {p.roster_ovr:g}"
    sw = draw.textbbox((0, 0), sub, font=font_s)[2]
    draw.text(((_CANVAS_W - sw) // 2, 78), sub, font=font_s, fill=_DIM)

    # KPI cards — equal width, centered value
    kpis = [
        ("Чемп. лиги", str(p.league_titles), False),
        ("ЛЧ", str(p.cl_titles), False),
        ("Лучш. ЛЧ", cl_stage_short(p.best_cl_stage), True),
        ("Награды", str(p.awards), False),
    ]
    gap = 14
    card_w = (_CANVAS_W - 2 * _PAD - 3 * gap) // 4
    y0 = 118
    for i, (lab, val, small) in enumerate(kpis):
        x0 = _PAD + i * (card_w + gap)
        draw.rounded_rectangle(
            [x0, y0, x0 + card_w, y0 + 86],
            radius=12,
            fill=_CARD,
            outline=_LINE,
        )
        lw = draw.textbbox((0, 0), lab, font=font_sm)[2]
        draw.text((x0 + (card_w - lw) // 2, y0 + 10), lab, font=font_sm, fill=_DIM)
        fval = font_kpi_sm if small or len(val) > 4 else font_kpi
        # shrink until fits
        while draw.textbbox((0, 0), val, font=fval)[2] > card_w - 16 and fval.size > 14:
            fval = _pick_font(max(14, fval.size - 2), bold=True)
        vw = draw.textbbox((0, 0), val, font=fval)[2]
        draw.text(
            (x0 + (card_w - vw) // 2, y0 + 38),
            val,
            font=fval,
            fill=_GOLD if i < 2 else _TEXT,
        )

    y = 224
    draw.text((_PAD, y), "Трофеи и путь в ЛЧ", font=font_b, fill=_TEXT)
    y += 34
    league_txt = format_season_list(d.league_titles_by_season)
    cl_txt = format_season_list(d.cl_titles_by_season)
    draw.text((_PAD, y), f"Чемпионства лиги: {league_txt}", font=font_m, fill=_TEXT)
    y += 28
    draw.text((_PAD, y), f"Победы в ЛЧ: {cl_txt}", font=font_m, fill=_TEXT)
    y += 28
    if d.cl_stages:
        stage_line = " · ".join(
            f"{format_season_tag(sn)} — {cl_stage_short(st)}" for sn, st in d.cl_stages
        )
    else:
        stage_line = "нет данных плей-офф"
    draw.text(
        (_PAD, y),
        _fit(draw, f"Стадии ЛЧ: {stage_line}", font_m, _CANVAS_W - 2 * _PAD),
        font=font_m,
        fill=_TEXT,
    )
    y += 36

    # Prestige bars — full width, centered block
    draw.text((_PAD, y), "Вклад в престиж", font=font_b, fill=_TEXT)
    y += 28
    parts = list(p.breakdown.items())
    max_p = max((v for _, v in parts), default=1.0) or 1.0
    label_w = 100
    bar_x0 = _PAD + label_w
    bar_x1 = _CANVAS_W - _PAD - 56
    for lab, val in parts:
        draw.text((_PAD, y), lab, font=font_sm, fill=_DIM)
        bw = int((bar_x1 - bar_x0) * (val / max_p)) if max_p else 0
        draw.rounded_rectangle(
            [bar_x0, y + 2, bar_x0 + max(bw, 2 if val else 0), y + 16],
            radius=4,
            fill=_BAR2 if lab.startswith("ЛЧ") else _BAR,
        )
        draw.text((bar_x1 + 10, y), f"{val:.0f}", font=font_sm, fill=_TEXT)
        y += 24

    y += 12
    # Awards as cards
    if d.awards:
        draw.text((_PAD, y), "Личные награды", font=font_b, fill=_TEXT)
        y += 30
        aw_w = (_CANVAS_W - 2 * _PAD - gap) // 2
        for i, (lab, sn, pl) in enumerate(d.awards[:6]):
            col = i % 2
            row = i // 2
            x0 = _PAD + col * (aw_w + gap)
            ay = y + row * 56
            draw.rounded_rectangle(
                [x0, ay, x0 + aw_w, ay + 48],
                radius=10,
                fill=(42, 36, 22),
                outline=(120, 96, 48),
            )
            draw.text((x0 + 14, ay + 6), lab, font=font_sm, fill=_GOLD)
            draw.text(
                (x0 + 14, ay + 24),
                _fit(draw, f"{format_season_tag(sn)} · {pl}", font_m, aw_w - 28),
                font=font_m,
                fill=_TEXT,
            )
        y += ((len(d.awards[:6]) + 1) // 2) * 56 + 8

    draw.text((_PAD, y), "Легенды клуба (лига + ЛЧ за все сезоны)", font=font_b, fill=_TEXT)
    y += 28
    table_top = y
    row_h = 32
    table_h = 40 + max(1, len(d.legends)) * row_h
    draw.rounded_rectangle(
        [_PAD, table_top, _CANVAS_W - _PAD, table_top + table_h],
        radius=12,
        fill=_CARD,
        outline=_LINE,
    )
    # columns: # | name | pos | ovr | M | G | A | POTM
    cols = [
        (_PAD + 16, "#", 36),
        (_PAD + 52, "Игрок", 250),
        (_PAD + 320, "Поз", 50),
        (_PAD + 390, "OVR", 50),
        (_PAD + 460, "И", 50),
        (_PAD + 520, "Г", 50),
        (_PAD + 580, "А", 50),
        (_PAD + 640, "POTM", 70),
    ]
    hy = table_top + 10
    for x, lab, _w in cols:
        draw.text((x, hy), lab, font=font_sm, fill=_DIM)
    y = hy + 26
    draw.line([_PAD + 12, y - 4, _CANVAS_W - _PAD - 12, y - 4], fill=_LINE, width=1)

    if not d.legends:
        draw.text((_PAD + 16, y + 4), "Пока мало данных по игрокам клуба.", font=font_m, fill=_DIM)
    else:
        for i, leg in enumerate(d.legends, start=1):
            draw.text((_PAD + 16, y), f"{i:02d}", font=font_m, fill=_GOLD if i <= 3 else _TEXT)
            draw.text((_PAD + 52, y), _fit(draw, leg.name, font_m, 250), font=font_m, fill=_TEXT)
            draw.text((_PAD + 320, y), leg.position, font=font_m, fill=_DIM)
            ovr_s = str(leg.overall) if leg.overall else "—"
            draw.text((_PAD + 390, y), ovr_s, font=font_m, fill=_TEXT)
            draw.text((_PAD + 460, y), f"{leg.matches}", font=font_m, fill=_TEXT)
            draw.text((_PAD + 520, y), f"{leg.goals}", font=font_m, fill=_TEXT)
            draw.text((_PAD + 580, y), f"{leg.assists}", font=font_m, fill=_TEXT)
            draw.text((_PAD + 640, y), f"{leg.potm}", font=font_m, fill=_TEXT)
            y += row_h

    return _to_png(im.convert("RGB"))


def render_league_titles_chart_png() -> bytes:
    """Сколько чемпионств у клубов с учётом веса лиги (визуальный fairness-check)."""
    from bot.season_history_store import load_history
    from player_stats import LEAGUE_NAMES

    hist = load_history()
    # raw titles + weighted
    raw: dict[str, int] = {}
    weighted: dict[str, float] = {}
    league_of: dict[str, str] = {}
    from bot.team_history import LEAGUE_TITLE_WEIGHT

    for code, rows in (hist.get("league_winners") or {}).items():
        w = float(LEAGUE_TITLE_WEIGHT.get(str(code), 0.7))
        for row in rows or []:
            if not row or len(row) < 2:
                continue
            team = str(row[1]).strip()
            if not team:
                continue
            raw[team] = raw.get(team, 0) + 1
            weighted[team] = weighted.get(team, 0.0) + w
            league_of[team] = str(code)

    items = sorted(weighted.items(), key=lambda x: (-x[1], -raw.get(x[0], 0), x[0].casefold()))
    items = items[:12]
    row_h = 52
    h = 130 + len(items) * row_h + 50
    im = _gradient_bg(h).convert("RGBA")
    draw = ImageDraw.Draw(im)
    y = _draw_title(
        draw,
        "Чемпионства лиг (с весом)",
        "Слева «сырые» титулы, справа — вклад в престиж (РПЛ дешевле топ-лиг)",
    )
    font_n = _pick_font(22, bold=True)
    font_s = _pick_font(16)
    max_w = max((v for _, v in items), default=1.0) or 1.0
    for i, (team, wv) in enumerate(items):
        top = y + i * row_h
        draw.rounded_rectangle(
            [_PAD, top + 4, _CANVAS_W - _PAD, top + row_h - 4],
            radius=10,
            fill=_CARD,
            outline=_LINE,
        )
        crest = _try_load_crest_rgba(team)
        if crest is not None:
            _paste_crest_natural(im, crest, _PAD + 30, top + row_h // 2, 34)
        lc = league_of.get(team, "")
        draw.text(
            (_PAD + 56, top + 10),
            f"{team} · {LEAGUE_NAMES.get(lc, lc)}",
            font=font_n,
            fill=_TEXT,
        )
        draw.text(
            (_PAD + 56, top + 34),
            f"титулов: {raw.get(team, 0)}  ·  вес: {wv:.2f}",
            font=font_s,
            fill=_DIM,
        )
        bx0 = 520
        bw = int(520 * (wv / max_w))
        draw.rounded_rectangle(
            [bx0, top + 18, bx0 + max(bw, 4), top + 36],
            radius=6,
            fill=_BAR2,
        )
    return _to_png(im.convert("RGB"))
