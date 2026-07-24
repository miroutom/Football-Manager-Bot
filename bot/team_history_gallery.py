# -*- coding: utf-8 -*-
"""Доп. PNG галереи Истории: сравнение, H2H, менеджеры, динамика, теплокарта, обложка."""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from bot.squad_pitch import _paste_crest_natural, _pick_font, _try_load_crest_rgba
from bot.team_history import (
    ClubLegend,
    compare_clubs,
    club_matches_in_season,
    cl_stage_short,
    format_season_tag,
    hall_of_fame_global,
    head_to_head,
    league_winners_heatmap,
    list_history_seasons,
    manager_side_stats,
    prestige_dynamics,
    season_cover_data,
)
from player_stats import LEAGUE_NAMES

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
_ROMAN = (70, 140, 230)
_LIKA = (230, 140, 70)


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


def _fit(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> str:
    t = text
    while t and draw.textbbox((0, 0), t, font=font)[2] > max_w:
        t = t[:-1]
    if t != text and len(t) > 1:
        t = t[:-1] + "…"
    return t or text[:1]


def _title(draw, title: str, subtitle: str, y0: int = 18) -> int:
    ft = _pick_font(36, bold=True)
    fs = _pick_font(18)
    draw.text((_PAD, y0), title, font=ft, fill=_TEXT)
    y = y0 + draw.textbbox((0, 0), title, font=ft)[3] + 6
    draw.text((_PAD, y), subtitle, font=fs, fill=_DIM)
    return y + draw.textbbox((0, 0), subtitle, font=fs)[3] + 16


def render_compare_clubs_png(team_a: str, team_b: str) -> bytes:
    data = compare_clubs(team_a, team_b)
    pa, pb = data["a"], data["b"]
    h2h = data["h2h"]
    h = 620
    im = _gradient_bg(h).convert("RGBA")
    draw = ImageDraw.Draw(im)
    y = _title(draw, "Сравнение клубов", f"{pa.team}  vs  {pb.team}")
    mid = _CANVAS_W // 2
    font_n = _pick_font(28, bold=True)
    font_m = _pick_font(18)
    font_b = _pick_font(22, bold=True)

    for side, p, x0 in ((0, pa, _PAD), (1, pb, mid + 10)):
        draw.rounded_rectangle([x0, y, x0 + mid - _PAD - 10, y + 200], radius=14, fill=_CARD, outline=_LINE)
        crest = _try_load_crest_rgba(p.team)
        if crest is not None:
            _paste_crest_natural(im, crest, x0 + 40, y + 44, 56)
        draw.text((x0 + 80, y + 18), p.team, font=font_n, fill=_TEXT)
        lines = [
            f"Престиж: {p.score:.0f}",
            f"Чемп. лиги: {p.league_titles}",
            f"ЛЧ: {p.cl_titles} · пик {cl_stage_short(p.best_cl_stage)}",
            f"OVR: {p.roster_ovr:g} · награды: {p.awards}",
        ]
        yy = y + 80
        for line in lines:
            draw.text((x0 + 20, yy), line, font=font_m, fill=_DIM if "OVR" in line else _TEXT)
            yy += 26

    y += 220
    draw.text((_PAD, y), "Очные встречи (все журналы)", font=font_b, fill=_TEXT)
    y += 32
    draw.rounded_rectangle([_PAD, y, _CANVAS_W - _PAD, y + 90], radius=12, fill=_CARD, outline=_LINE)
    summary = (
        f"Игр: {h2h['played']}   "
        f"{pa.team} побед {h2h['wins_a']}   "
        f"ничьих {h2h['draws']}   "
        f"{pb.team} побед {h2h['wins_b']}   "
        f"голы {h2h['goals_a']}:{h2h['goals_b']}"
    )
    draw.text((_PAD + 20, y + 30), summary, font=font_m, fill=_TEXT)
    return _to_png(im.convert("RGB"))


def _match_result_for_team(m: dict, team: str) -> tuple[str, int, int, int]:
    """(W|D|L, points, gf, ga) с точки зрения клуба."""
    from bot.team_history import _norm

    want = _norm(team)
    home = _norm(str(m.get("home") or ""))
    away = _norm(str(m.get("away") or ""))
    hs = int(m.get("home_score") or 0)
    aws = int(m.get("away_score") or 0)
    if home == want:
        gf, ga = hs, aws
    elif away == want:
        gf, ga = aws, hs
    else:
        return "D", 0, 0, 0
    if gf > ga:
        return "W", 3, gf, ga
    if gf < ga:
        return "L", 0, gf, ga
    return "D", 1, gf, ga


def render_h2h_png(team_a: str, team_b: str) -> bytes:
    h2h = head_to_head(team_a, team_b)
    ta, tb = str(h2h["team_a"]), str(h2h["team_b"])
    matches = list(h2h["matches"] or [])
    show = matches[-20:]  # последние встречи на графике/в списке

    font_m = _pick_font(17)
    font_sm = _pick_font(14)
    font_b = _pick_font(20, bold=True)
    font_n = _pick_font(28, bold=True)
    font_kpi = _pick_font(26, bold=True)

    col_a = (70, 140, 230)
    col_b = (230, 120, 100)
    win_c = (90, 190, 140)
    draw_c = (200, 180, 90)
    lose_c = (220, 110, 110)

    chart_h = 280 if show else 0
    list_h = 28 + max(1, len(show)) * 40 + 16
    h = 150 + 130 + 90 + chart_h + 24 + list_h + 40
    im = _gradient_bg(min(h, 2600)).convert("RGBA")
    draw = ImageDraw.Draw(im)
    y = _title(draw, "История противостояния", f"{ta}  vs  {tb}")

    # Crest duel header
    mid = _CANVAS_W // 2
    header_top = y
    draw.rounded_rectangle(
        [_PAD, header_top, _CANVAS_W - _PAD, header_top + 110],
        radius=16,
        fill=_CARD,
        outline=_LINE,
    )
    crest_a = _try_load_crest_rgba(ta)
    crest_b = _try_load_crest_rgba(tb)
    if crest_a is not None:
        _paste_crest_natural(im, crest_a, _PAD + 70, header_top + 55, 64)
    if crest_b is not None:
        _paste_crest_natural(im, crest_b, _CANVAS_W - _PAD - 70, header_top + 55, 64)
    bw = draw.textbbox((0, 0), tb, font=font_n)[2]
    draw.text((_PAD + 120, header_top + 28), ta, font=font_n, fill=_TEXT)
    draw.text((_CANVAS_W - _PAD - 120 - bw, header_top + 28), tb, font=font_n, fill=_TEXT)
    vs = "VS"
    vsw = draw.textbbox((0, 0), vs, font=font_b)[2]
    draw.text((mid - vsw // 2, header_top + 36), vs, font=font_b, fill=_GOLD)
    sub = f"{h2h['played']} матчей · голы {h2h['goals_a']}:{h2h['goals_b']}"
    sw = draw.textbbox((0, 0), sub, font=font_sm)[2]
    draw.text((mid - sw // 2, header_top + 68), sub, font=font_sm, fill=_DIM)
    y = header_top + 126

    # KPI
    kpis = [
        ("Победы", str(h2h["wins_a"]), col_a),
        ("Ничьи", str(h2h["draws"]), draw_c),
        ("Победы", str(h2h["wins_b"]), col_b),
        ("Голы", f"{h2h['goals_a']}:{h2h['goals_b']}", _GOLD),
    ]
    gap = 12
    card_w = (_CANVAS_W - 2 * _PAD - 3 * gap) // 4
    for i, (lab, val, accent) in enumerate(kpis):
        x0 = _PAD + i * (card_w + gap)
        draw.rounded_rectangle([x0, y, x0 + card_w, y + 78], radius=12, fill=_CARD, outline=accent)
        who = ta if i == 0 else (tb if i == 2 else "")
        top_lab = f"{lab}" + (f" · {who}" if who else "")
        top_lab = _fit(draw, top_lab, font_sm, card_w - 16)
        tw = draw.textbbox((0, 0), top_lab, font=font_sm)[2]
        draw.text((x0 + (card_w - tw) // 2, y + 10), top_lab, font=font_sm, fill=_DIM)
        vw = draw.textbbox((0, 0), val, font=font_kpi)[2]
        draw.text((x0 + (card_w - vw) // 2, y + 36), val, font=font_kpi, fill=_TEXT)
    y += 94

    if not matches:
        draw.text((_PAD, y), "Матчей в журналах не найдено.", font=font_m, fill=_DIM)
        return _to_png(im.convert("RGB"))

    # Vertical bars: goals per meeting (A vs B)
    draw.rounded_rectangle(
        [_PAD, y, _CANVAS_W - _PAD, y + chart_h],
        radius=14,
        fill=_CARD,
        outline=_LINE,
    )
    draw.text((_PAD + 16, y + 10), "Голы по встречам", font=font_b, fill=_TEXT)
    lx = _PAD + 320
    draw.rounded_rectangle([lx, y + 14, lx + 16, y + 30], radius=3, fill=col_a)
    draw.text((lx + 22, y + 12), _fit(draw, ta, font_sm, 200), font=font_sm, fill=_DIM)
    lx2 = lx + 240
    draw.rounded_rectangle([lx2, y + 14, lx2 + 16, y + 30], radius=3, fill=col_b)
    draw.text((lx2 + 22, y + 12), _fit(draw, tb, font_sm, 200), font=font_sm, fill=_DIM)

    chart_top = y + 44
    chart_bot = y + chart_h - 36
    chart_left = _PAD + 28
    chart_right = _CANVAS_W - _PAD - 28
    draw.line([chart_left, chart_bot, chart_right, chart_bot], fill=_LINE, width=2)

    max_g = 1
    parsed: list[tuple[dict, str, int, int, str]] = []
    for m in show:
        res, _pts, gf, ga = _match_result_for_team(m, ta)
        max_g = max(max_g, gf, ga)
        parsed.append((m, res, gf, ga, f"{format_season_tag(m.get('_season'))}·м{m.get('day')}"))

    n = max(1, len(parsed))
    slot_w = (chart_right - chart_left) / n
    pair_gap = 4
    bar_w = max(8, min(22, int((slot_w - 16 - pair_gap) / 2)))

    for i, (m, res, gf, ga, lab) in enumerate(parsed):
        cx = chart_left + int(slot_w * (i + 0.5))
        usable = chart_bot - chart_top - 8
        ha = int(usable * (gf / max_g)) if max_g else 0
        hb = int(usable * (ga / max_g)) if max_g else 0
        xa = cx - pair_gap // 2 - bar_w
        xb = cx + pair_gap // 2
        if gf > 0:
            draw.rounded_rectangle([xa, chart_bot - max(ha, 4), xa + bar_w, chart_bot - 1], radius=4, fill=col_a)
        else:
            draw.rounded_rectangle([xa, chart_bot - 5, xa + bar_w, chart_bot - 1], radius=2, fill=_LINE)
        if ga > 0:
            draw.rounded_rectangle([xb, chart_bot - max(hb, 4), xb + bar_w, chart_bot - 1], radius=4, fill=col_b)
        else:
            draw.rounded_rectangle([xb, chart_bot - 5, xb + bar_w, chart_bot - 1], radius=2, fill=_LINE)
        sc = f"{gf}:{ga}"
        scw = draw.textbbox((0, 0), sc, font=font_sm)[2]
        draw.text((cx - scw // 2, chart_top), sc, font=font_sm, fill=_TEXT)
        lw = draw.textbbox((0, 0), lab, font=font_sm)[2]
        draw.text((cx - lw // 2, chart_bot + 6), lab, font=font_sm, fill=_DIM)

    y += chart_h + 18

    # Match list
    draw.text((_PAD, y), "Встречи", font=font_b, fill=_TEXT)
    y += 28
    res_col = {"W": win_c, "D": draw_c, "L": lose_c}
    for m, res, gf, ga, _lab in parsed:
        sn = m.get("_season")
        day = m.get("day")
        lg = str(m.get("league") or "")
        home, away = str(m.get("home") or ""), str(m.get("away") or "")
        hs, aws = m.get("home_score"), m.get("away_score")
        meta = f"{format_season_tag(sn) if sn else '?'} · м{day} · {lg}"
        score = f"{home} {hs}:{aws} {away}"

        draw.rounded_rectangle([_PAD, y, _CANVAS_W - _PAD, y + 34], radius=8, fill=(24, 34, 52), outline=_LINE)
        chip = res
        draw.rounded_rectangle([_PAD + 8, y + 6, _PAD + 36, y + 28], radius=6, fill=res_col.get(res, _LINE))
        cw = draw.textbbox((0, 0), chip, font=font_sm)[2]
        draw.text((_PAD + 8 + (28 - cw) // 2, y + 8), chip, font=font_sm, fill=(16, 22, 34))
        draw.text((_PAD + 48, y + 8), meta, font=font_sm, fill=_DIM)
        draw.text((_PAD + 280, y + 7), _fit(draw, score, font_m, 860), font=font_m, fill=_TEXT)
        y += 40

    if len(matches) > len(show):
        draw.text((_PAD, y + 2), f"…показаны последние {len(show)} из {len(matches)}", font=font_sm, fill=_DIM)
    return _to_png(im.convert("RGB"))


def render_managers_png() -> bytes:
    roman = manager_side_stats("roman")
    lika = manager_side_stats("lika")
    h = 720
    im = _gradient_bg(h).convert("RGBA")
    draw = ImageDraw.Draw(im)
    y = _title(draw, "Менеджеры", "Roman vs Lika — престиж клубов и трофеи")
    font_n = _pick_font(30, bold=True)
    font_m = _pick_font(18)
    font_b = _pick_font(20, bold=True)
    mid = _CANVAS_W // 2
    for side, st, col, x0 in (
        (roman, roman, _ROMAN, _PAD),
        (lika, lika, _LIKA, mid + 8),
    ):
        draw.rounded_rectangle(
            [x0, y, x0 + mid - _PAD - 8, y + 520],
            radius=16,
            fill=_CARD,
            outline=col,
            width=2,
        )
        draw.text((x0 + 20, y + 16), st["label"], font=font_n, fill=col)
        stats = [
            f"Суммарный престиж: {st['prestige_total']:.0f}",
            f"Средний на клуб: {st['avg_prestige']:.0f}",
            f"Чемп. лиг: {st['league_titles']}",
            f"Титулы ЛЧ: {st['cl_titles']}",
            f"Личные награды: {st['awards']}",
        ]
        yy = y + 70
        for line in stats:
            draw.text((x0 + 20, yy), line, font=font_m, fill=_TEXT)
            yy += 28
        draw.text((x0 + 20, yy + 8), "Топ клубов", font=font_b, fill=_GOLD)
        yy += 40
        for i, p in enumerate(st["top_clubs"], 1):
            crest = _try_load_crest_rgba(p.team)
            if crest is not None:
                _paste_crest_natural(im, crest, x0 + 36, yy + 12, 28)
            draw.text((x0 + 60, yy), f"{i}. {p.team} — {p.score:.0f}", font=font_m, fill=_TEXT)
            yy += 36
    return _to_png(im.convert("RGB"))


def render_prestige_dynamics_png(team: str) -> bytes:
    from bot.team_history import compute_team_prestige

    series = prestige_dynamics(team)
    p = compute_team_prestige(team)
    hist_sum = sum(v for _, v in series)
    roster = float(p.roster_pts)
    total = float(p.score)

    h = 620
    im = _gradient_bg(h).convert("RGBA")
    draw = ImageDraw.Draw(im)
    y = _title(
        draw,
        "Динамика престижа",
        f"{team} — вклад трофеев/наград по сезонам (без текущего OVR состава)",
    )
    font_sm = _pick_font(15)
    font_m = _pick_font(17, bold=True)
    font_b = _pick_font(20, bold=True)
    font_kpi = _pick_font(24, bold=True)

    # Explain 118 vs 106: total = sum(seasons) + roster OVR
    cards = [
        ("Сумма сезонов", f"{hist_sum:.0f}"),
        ("+ Состав (OVR)", f"{roster:.0f}"),
        ("= Престиж", f"{total:.0f}"),
    ]
    gap = 12
    card_w = (_CANVAS_W - 2 * _PAD - 2 * gap) // 3
    for i, (lab, val) in enumerate(cards):
        x0 = _PAD + i * (card_w + gap)
        draw.rounded_rectangle([x0, y, x0 + card_w, y + 72], radius=12, fill=_CARD, outline=_LINE)
        tw = draw.textbbox((0, 0), lab, font=font_sm)[2]
        draw.text((x0 + (card_w - tw) // 2, y + 10), lab, font=font_sm, fill=_DIM)
        vw = draw.textbbox((0, 0), val, font=font_kpi)[2]
        draw.text((x0 + (card_w - vw) // 2, y + 34), val, font=font_kpi, fill=_GOLD if i == 2 else _TEXT)
    y += 88
    draw.text(
        (_PAD, y),
        "График ниже — только сезонный вклад (титулы / путь ЛЧ / награды). OVR состава добавляется отдельно.",
        font=font_sm,
        fill=_DIM,
    )
    y += 28

    if not series:
        draw.text((_PAD, y), "Нет данных.", font=_pick_font(18), fill=_DIM)
        return _to_png(im.convert("RGB"))

    chart_top = y + 10
    chart_bot = h - 56
    chart_left = _PAD + 40
    chart_right = _CANVAS_W - _PAD - 20
    max_v = max((v for _, v in series), default=1.0) or 1.0
    draw.rounded_rectangle(
        [_PAD, y, _CANVAS_W - _PAD, chart_bot + 40],
        radius=14,
        fill=_CARD,
        outline=_LINE,
    )
    draw.line([chart_left, chart_bot, chart_right, chart_bot], fill=_LINE, width=2)
    draw.line([chart_left, chart_top, chart_left, chart_bot], fill=_LINE, width=2)
    n = len(series)
    pts = []
    for i, (sn, val) in enumerate(series):
        x = (
            chart_left + int((chart_right - chart_left) * (i / max(1, n - 1)))
            if n > 1
            else (chart_left + chart_right) // 2
        )
        yy = chart_bot - int((chart_bot - chart_top - 20) * (val / max_v)) if max_v else chart_bot
        pts.append((x, yy, sn, val))
    if len(pts) >= 2:
        draw.line([(p[0], p[1]) for p in pts], fill=_BAR2, width=3)
    for x, yy, sn, val in pts:
        draw.ellipse([x - 6, yy - 6, x + 6, yy + 6], fill=_GOLD)
        draw.text((x - 20, chart_bot + 8), format_season_tag(sn), font=font_sm, fill=_DIM)
        draw.text((x - 10, yy - 24), f"{val:.0f}", font=font_m, fill=_TEXT)
    return _to_png(im.convert("RGB"))


def render_heatmap_png() -> bytes:
    data = league_winners_heatmap()
    seasons = data["seasons"]
    codes = data["codes"]
    grid = data["grid"]
    col_w = 180
    row_h = 70
    left = 120
    top = 120
    h = top + len(seasons) * row_h + 60
    w = max(_CANVAS_W, left + len(codes) * col_w + _PAD)
    im = _gradient_bg(h).convert("RGBA")
    if w > _CANVAS_W:
        # stretch canvas
        im = _gradient_bg(h).resize((w, h))
        im = im.convert("RGBA")
    draw = ImageDraw.Draw(im)
    font_t = _pick_font(34, bold=True)
    font_m = _pick_font(16)
    font_sm = _pick_font(14)
    draw.text((_PAD, 20), "Теплокарта чемпионов", font=font_t, fill=_TEXT)
    draw.text((_PAD, 64), "Кто брал лигу в каждом сезоне", font=font_m, fill=_DIM)
    for j, code in enumerate(codes):
        x = left + j * col_w + col_w // 2
        lab = LEAGUE_NAMES.get(code, code)
        tw = draw.textbbox((0, 0), lab, font=font_sm)[2]
        draw.text((x - tw // 2, top - 28), lab, font=font_sm, fill=_DIM)
    palette = {
        "rpl": (90, 120, 160),
        "eng": (70, 100, 200),
        "esp": (200, 140, 60),
        "ita": (80, 160, 100),
        "ger": (160, 80, 80),
    }
    for i, sn in enumerate(seasons):
        y = top + i * row_h
        draw.text((_PAD, y + 22), format_season_tag(sn), font=font_m, fill=_TEXT)
        for j, code in enumerate(codes):
            x0 = left + j * col_w
            winner = grid.get((sn, code))
            col = palette.get(code, _CARD) if winner else (24, 32, 48)
            draw.rounded_rectangle(
                [x0 + 4, y + 6, x0 + col_w - 4, y + row_h - 6],
                radius=10,
                fill=col,
                outline=_LINE,
            )
            if winner:
                crest = _try_load_crest_rgba(winner)
                if crest is not None:
                    _paste_crest_natural(im, crest, x0 + 28, y + row_h // 2, 30)
                draw.text(
                    (x0 + 50, y + 22),
                    _fit(draw, winner, font_sm, col_w - 60),
                    font=font_sm,
                    fill=_TEXT,
                )
            else:
                draw.text((x0 + 20, y + 22), "—", font=font_m, fill=_DIM)
    return _to_png(im.convert("RGB"))


def render_season_cover_png(season: int) -> bytes:
    data = season_cover_data(season)
    h = 780
    im = _gradient_bg(h).convert("RGBA")
    draw = ImageDraw.Draw(im)
    font_t = _pick_font(44, bold=True)
    font_b = _pick_font(24, bold=True)
    font_m = _pick_font(18)
    font_sm = _pick_font(15)
    title = f"Обложка · {format_season_tag(data['season'])}"
    tw = draw.textbbox((0, 0), title, font=font_t)[2]
    draw.text(((_CANVAS_W - tw) // 2, 24), title, font=font_t, fill=_GOLD)
    draw.text((_PAD, 90), "Чемпионы лиг", font=font_b, fill=_TEXT)
    y = 130
    card_w = (_CANVAS_W - 2 * _PAD - 4 * 12) // 5
    for i, code in enumerate(("rpl", "eng", "esp", "ita", "ger")):
        x0 = _PAD + i * (card_w + 12)
        winner = data["leagues"].get(code)
        draw.rounded_rectangle([x0, y, x0 + card_w, y + 150], radius=12, fill=_CARD, outline=_LINE)
        lab = LEAGUE_NAMES.get(code, code)
        lw = draw.textbbox((0, 0), lab, font=font_sm)[2]
        draw.text((x0 + (card_w - lw) // 2, y + 10), lab, font=font_sm, fill=_DIM)
        if winner:
            crest = _try_load_crest_rgba(winner)
            if crest is not None:
                _paste_crest_natural(im, crest, x0 + card_w // 2, y + 70, 52)
            draw.text(
                (x0 + 8, y + 112),
                _fit(draw, winner, font_m, card_w - 16),
                font=font_m,
                fill=_TEXT,
            )
        else:
            draw.text((x0 + card_w // 2 - 10, y + 70), "?", font=font_t, fill=_DIM)

    y = 320
    draw.text((_PAD, y), "Лига чемпионов", font=font_b, fill=_TEXT)
    y += 40
    draw.rounded_rectangle([_PAD, y, _CANVAS_W - _PAD, y + 120], radius=14, fill=_CARD, outline=_GOLD)
    cl = data.get("cl")
    if cl:
        crest = _try_load_crest_rgba(cl)
        if crest is not None:
            _paste_crest_natural(im, crest, _PAD + 70, y + 60, 72)
        draw.text((_PAD + 130, y + 40), cl, font=font_t, fill=_TEXT)
        draw.text((_PAD + 130, y + 90), "Победитель ЛЧ", font=font_m, fill=_GOLD)
    else:
        draw.text((_PAD + 40, y + 45), "Победитель ещё не записан", font=font_m, fill=_DIM)

    y = 500
    draw.text((_PAD, y), "Личные награды", font=font_b, fill=_TEXT)
    y += 36
    aw_w = (_CANVAS_W - 2 * _PAD - 3 * 12) // 4
    for i, (lab, hit) in enumerate((data.get("awards") or {}).items()):
        x0 = _PAD + i * (aw_w + 12)
        draw.rounded_rectangle([x0, y, x0 + aw_w, y + 110], radius=12, fill=(42, 36, 22), outline=(120, 96, 48))
        draw.text((x0 + 14, y + 12), lab, font=font_sm, fill=_GOLD)
        if hit:
            pl, club = hit
            draw.text((x0 + 14, y + 42), _fit(draw, pl, font_m, aw_w - 28), font=font_m, fill=_TEXT)
            draw.text((x0 + 14, y + 72), _fit(draw, club, font_sm, aw_w - 28), font=font_sm, fill=_DIM)
        else:
            draw.text((x0 + 14, y + 50), "—", font=font_m, fill=_DIM)
    return _to_png(im.convert("RGB"))


def render_hall_of_fame_png(*, limit: int = 20) -> bytes:
    rows = hall_of_fame_global(limit=limit)
    row_h = 52
    h = 150 + max(1, len(rows)) * row_h + 50
    im = _gradient_bg(h).convert("RGBA")
    draw = ImageDraw.Draw(im)
    y = _title(draw, "Зал славы", "Лучшие игроки карьеры · лига + ЛЧ · все сезоны")
    font_m = _pick_font(18)
    font_b = _pick_font(18, bold=True)
    font_sm = _pick_font(14)
    font_r = _pick_font(20, bold=True)
    max_score = max((float(leg.score) for leg in rows), default=1.0) or 1.0

    for i, leg in enumerate(rows, 1):
        club = getattr(leg, "club", "") or ""
        top = y
        draw.rounded_rectangle(
            [_PAD, top, _CANVAS_W - _PAD, top + row_h - 6],
            radius=12,
            fill=_CARD,
            outline=_GOLD if i <= 3 else _LINE,
            width=2 if i <= 3 else 1,
        )
        rank_c = _GOLD if i <= 3 else _TEXT
        draw.text((_PAD + 14, top + 14), f"{i:02d}", font=font_r, fill=rank_c)
        if club:
            crest = _try_load_crest_rgba(club)
            if crest is not None:
                _paste_crest_natural(im, crest, _PAD + 70, top + row_h // 2 - 3, 28)
        draw.text((_PAD + 96, top + 8), _fit(draw, leg.name, font_b, 220), font=font_b, fill=_TEXT)
        meta = f"{club or '—'} · {leg.position or '—'} · OVR {leg.overall or '—'}"
        draw.text((_PAD + 96, top + 28), _fit(draw, meta, font_sm, 280), font=font_sm, fill=_DIM)

        # mini bars for G / A / POTM
        stats = [
            ("Г", int(leg.goals), (90, 190, 140)),
            ("А", int(leg.assists), (70, 140, 230)),
            ("P", int(leg.potm), _GOLD),
        ]
        bx = 520
        for lab, val, col in stats:
            draw.text((bx, top + 8), lab, font=font_sm, fill=_DIM)
            bw = int(70 * (val / max(1, max(leg.goals, leg.assists, leg.potm, 1))))
            draw.rounded_rectangle([bx + 18, top + 10, bx + 18 + max(bw, 2 if val else 0), top + 22], radius=4, fill=col)
            draw.text((bx + 100, top + 6), str(val), font=font_m, fill=_TEXT)
            bx += 130

        # score bar
        sw = int(160 * (float(leg.score) / max_score)) if max_score else 0
        draw.rounded_rectangle(
            [_CANVAS_W - _PAD - 180, top + 28, _CANVAS_W - _PAD - 180 + max(sw, 4), top + 40],
            radius=4,
            fill=_BAR2,
        )
        draw.text(
            (_CANVAS_W - _PAD - 170, top + 8),
            f"score {leg.score:.0f} · {leg.matches}и",
            font=font_sm,
            fill=_DIM,
        )
        y += row_h
    return _to_png(im.convert("RGB"))


def render_club_hall_of_fame_png(team: str) -> bytes:
    from bot.team_history import club_legends

    rows = club_legends(team, limit=15)
    row_h = 52
    h = 170 + max(1, len(rows)) * row_h + 50
    im = _gradient_bg(h).convert("RGBA")
    draw = ImageDraw.Draw(im)
    y = _title(draw, f"Зал славы · {team}", "Легенды клуба · лига + ЛЧ · все сезоны")
    crest = _try_load_crest_rgba(team)
    if crest is not None:
        _paste_crest_natural(im, crest, _CANVAS_W - _PAD - 40, 48, 56)

    font_m = _pick_font(18)
    font_b = _pick_font(18, bold=True)
    font_sm = _pick_font(14)
    font_r = _pick_font(20, bold=True)
    max_g = max((int(leg.goals) for leg in rows), default=1) or 1
    max_score = max((float(leg.score) for leg in rows), default=1.0) or 1.0

    for i, leg in enumerate(rows, 1):
        top = y
        draw.rounded_rectangle(
            [_PAD, top, _CANVAS_W - _PAD, top + row_h - 6],
            radius=12,
            fill=_CARD,
            outline=_GOLD if i <= 3 else _LINE,
            width=2 if i <= 3 else 1,
        )
        draw.text((_PAD + 14, top + 14), f"{i:02d}", font=font_r, fill=_GOLD if i <= 3 else _TEXT)
        draw.text((_PAD + 60, top + 8), _fit(draw, leg.name, font_b, 260), font=font_b, fill=_TEXT)
        draw.text(
            (_PAD + 60, top + 28),
            f"{leg.position or '—'} · OVR {leg.overall or '—'} · {leg.matches} игр",
            font=font_sm,
            fill=_DIM,
        )

        # goals bar (dominant stat)
        bar_x0 = 420
        bar_x1 = _CANVAS_W - _PAD - 200
        bw = int((bar_x1 - bar_x0) * (int(leg.goals) / max_g)) if max_g else 0
        draw.text((bar_x0, top + 6), "Голы", font=font_sm, fill=_DIM)
        draw.rounded_rectangle(
            [bar_x0, top + 26, bar_x0 + max(bw, 3 if leg.goals else 0), top + 38],
            radius=5,
            fill=(90, 190, 140),
        )
        draw.text((bar_x1 + 8, top + 8), f"{leg.goals}Г", font=font_b, fill=_TEXT)
        draw.text((bar_x1 + 8, top + 28), f"{leg.assists}А · {leg.potm}P", font=font_sm, fill=_DIM)

        # thin score accent on the right edge
        sh = int(30 * (float(leg.score) / max_score)) if max_score else 0
        draw.rounded_rectangle(
            [_CANVAS_W - _PAD - 10, top + row_h - 10 - max(sh, 4), _CANVAS_W - _PAD - 2, top + row_h - 10],
            radius=3,
            fill=_GOLD if i <= 3 else _BAR,
        )
        y += row_h
    return _to_png(im.convert("RGB"))

def render_club_season_matches_png(team: str, season: int) -> bytes:
    rows = club_matches_in_season(team, season)
    font_m = _pick_font(16)
    font_sm = _pick_font(13)
    font_b = _pick_font(18, bold=True)
    font_kpi = _pick_font(26, bold=True)

    if not rows:
        h = 220
        im = _gradient_bg(h).convert("RGBA")
        draw = ImageDraw.Draw(im)
        y = _title(draw, f"Матчи · {team}", f"{format_season_tag(season)} · нет матчей")
        draw.text((_PAD, y), "В журналах этого сезона матчей клуба нет.", font=font_m, fill=_DIM)
        return _to_png(im.convert("RGB"))

    # stats + points by month
    by_month: dict[int, dict[str, int]] = {}
    w = d = l = gf_t = ga_t = 0
    for m in rows:
        res, pts, gf, ga = _match_result_for_team(m, team)
        day = int(m.get("day") or 0)
        slot = by_month.setdefault(day, {"pts": 0, "gf": 0, "ga": 0, "n": 0, "w": 0, "d": 0, "l": 0})
        slot["pts"] += pts
        slot["gf"] += gf
        slot["ga"] += ga
        slot["n"] += 1
        if res == "W":
            w += 1
            slot["w"] += 1
        elif res == "D":
            d += 1
            slot["d"] += 1
        else:
            l += 1
            slot["l"] += 1
        gf_t += gf
        ga_t += ga
    pts_total = w * 3 + d
    months = sorted(by_month.keys())

    chart_h = 260
    show = rows[:40]
    list_h = 28 + len(show) * 34 + (24 if len(rows) > len(show) else 0)
    h = 150 + 96 + chart_h + 28 + list_h + 36
    im = _gradient_bg(min(h, 2800)).convert("RGBA")
    draw = ImageDraw.Draw(im)
    y = _title(
        draw,
        f"Матчи · {team}",
        f"{format_season_tag(season)} · {len(rows)} матч. · очки по месяцам",
    )

    # KPI strip
    kpis = [
        ("В-Н-П", f"{w}-{d}-{l}"),
        ("Очки", str(pts_total)),
        ("Голы", f"{gf_t}:{ga_t}"),
        ("Разн.", f"{gf_t - ga_t:+d}"),
    ]
    gap = 12
    card_w = (_CANVAS_W - 2 * _PAD - 3 * gap) // 4
    for i, (lab, val) in enumerate(kpis):
        x0 = _PAD + i * (card_w + gap)
        draw.rounded_rectangle([x0, y, x0 + card_w, y + 72], radius=12, fill=_CARD, outline=_LINE)
        tw = draw.textbbox((0, 0), lab, font=font_sm)[2]
        draw.text((x0 + (card_w - tw) // 2, y + 10), lab, font=font_sm, fill=_DIM)
        vw = draw.textbbox((0, 0), val, font=font_kpi)[2]
        draw.text((x0 + (card_w - vw) // 2, y + 32), val, font=font_kpi, fill=_TEXT)
    y += 88

    # Vertical bars by month (points)
    chart_top = y + 8
    chart_bot = chart_top + chart_h - 40
    chart_left = _PAD + 36
    chart_right = _CANVAS_W - _PAD - 20
    draw.rounded_rectangle(
        [_PAD, y, _CANVAS_W - _PAD, y + chart_h],
        radius=14,
        fill=_CARD,
        outline=_LINE,
    )
    draw.text((_PAD + 16, y + 10), "Очки по месяцам", font=font_b, fill=_TEXT)
    draw.text(
        (_PAD + 220, y + 12),
        "столбец = сумма очков (П=3, Н=1) за месяц",
        font=font_sm,
        fill=_DIM,
    )

    max_pts = max((by_month[m]["pts"] for m in months), default=1) or 1
    n = max(1, len(months))
    slot_w = (chart_right - chart_left) / n
    bar_w = max(18, min(56, int(slot_w * 0.55)))
    draw.line([chart_left, chart_bot, chart_right, chart_bot], fill=_LINE, width=2)

    win_c = (90, 190, 140)
    draw_c = (200, 180, 90)
    lose_tone = (70, 110, 180)

    for i, month in enumerate(months):
        slot = by_month[month]
        pts = slot["pts"]
        cx = chart_left + int(slot_w * (i + 0.5))
        bar_h = int((chart_bot - chart_top - 36) * (pts / max_pts)) if max_pts else 0
        x0 = cx - bar_w // 2
        y0 = chart_bot - max(bar_h, 4 if pts > 0 else 0)
        if slot["w"] >= slot["l"] and slot["w"] > 0:
            col = win_c
        elif slot["pts"] > 0:
            col = draw_c
        else:
            col = lose_tone
        if pts > 0:
            draw.rounded_rectangle([x0, y0, x0 + bar_w, chart_bot - 1], radius=6, fill=col)
        else:
            draw.rounded_rectangle([x0, chart_bot - 6, x0 + bar_w, chart_bot - 1], radius=3, fill=_LINE)
        lab = f"м{month}"
        lw = draw.textbbox((0, 0), lab, font=font_sm)[2]
        draw.text((cx - lw // 2, chart_bot + 8), lab, font=font_sm, fill=_DIM)
        if pts > 0:
            ps = str(pts)
            pw = draw.textbbox((0, 0), ps, font=font_b)[2]
            draw.text((cx - pw // 2, y0 - 22), ps, font=font_b, fill=_TEXT)
        ns = f"{slot['n']}и"
        nw = draw.textbbox((0, 0), ns, font=font_sm)[2]
        if bar_h >= 28:
            draw.text((cx - nw // 2, chart_bot - 22), ns, font=font_sm, fill=(20, 28, 40))

    y = y + chart_h + 20

    # Match list with result chips
    draw.text((_PAD, y), "Все матчи", font=font_b, fill=_TEXT)
    y += 28
    res_col = {"W": win_c, "D": draw_c, "L": (220, 110, 110)}
    for m in show:
        res, _pts, gf, ga = _match_result_for_team(m, team)
        lg = str(m.get("league") or "")
        day = m.get("day")
        home = str(m.get("home") or "")
        away = str(m.get("away") or "")
        hs = m.get("home_score")
        aws = m.get("away_score")
        line = f"м{day} · {lg} · {home} {hs}:{aws} {away}"
        if m.get("cl_phase"):
            line += f" ({m.get('cl_phase')})"
        chip = res
        draw.rounded_rectangle([_PAD, y + 2, _PAD + 28, y + 24], radius=6, fill=res_col.get(res, _LINE))
        cw = draw.textbbox((0, 0), chip, font=font_sm)[2]
        draw.text((_PAD + (28 - cw) // 2, y + 4), chip, font=font_sm, fill=(16, 22, 34))
        draw.text((_PAD + 40, y + 4), _fit(draw, line, font_m, _CANVAS_W - _PAD - 50), font=font_m, fill=_TEXT)
        y += 34
    if len(rows) > len(show):
        draw.text((_PAD, y + 4), f"…ещё {len(rows) - len(show)} матчей", font=font_sm, fill=_DIM)
    return _to_png(im.convert("RGB"))
