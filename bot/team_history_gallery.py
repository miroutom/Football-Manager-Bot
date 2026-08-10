# -*- coding: utf-8 -*-
"""Доп. PNG галереи Истории: сравнение, H2H, менеджеры, динамика, теплокарта, обложка."""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from bot.squad_pitch import _paste_crest_natural, _pick_font, _try_load_crest_rgba
from bot.team_history import (
    ClubLegend,
    _penalties_pair,
    _norm as _team_norm,
    compare_clubs,
    club_career_goals,
    club_career_conceded,
    club_matches_in_season,
    cl_stage_short,
    compute_result_streaks,
    format_match_score_with_pens,
    format_season_tag,
    find_pvp_kryptonites,
    aggregate_pvp_kryptonites_by_team,
    hall_of_fame_global,
    head_to_head,
    is_nation_name,
    league_winners_heatmap,
    list_history_seasons,
    manager_side_stats,
    nation_career_goals,
    prestige_dynamics,
    season_cover_data,
    titled_players_for_team,
    titled_players_global,
    TitledPlayer,
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


def _paste_side_mark(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    name: str,
    cx: int,
    cy: int,
    size: int,
    *,
    nation: bool,
) -> None:
    if nation:
        from bot.report_gfx import paste_nation_flag

        paste_nation_flag(im, draw, nation=name, cx=cx, cy=cy, size=size)
        return
    crest = _try_load_crest_rgba(name)
    if crest is not None:
        _paste_crest_natural(im, crest, cx, cy, size)


def render_compare_clubs_png(team_a: str, team_b: str) -> bytes:
    data = compare_clubs(team_a, team_b)
    pa, pb = data["a"], data["b"]
    h2h = data["h2h"]
    is_nat = data.get("kind") == "nation" or is_nation_name(pa.team)
    col_a = (70, 140, 230)
    col_b = (230, 120, 100)
    draw_c = (200, 180, 90)

    h2h_block = 280
    h = 110 + 210 + 28 + h2h_block + 36
    im = _gradient_bg(h).convert("RGBA")
    draw = ImageDraw.Draw(im)
    title = "Сравнение сборных" if is_nat else "Сравнение клубов"
    y = _title(draw, title, f"{pa.team}  vs  {pb.team}")
    mid = _CANVAS_W // 2
    font_n = _pick_font(28, bold=True)
    font_m = _pick_font(17)
    font_b = _pick_font(20, bold=True)
    font_sm = _pick_font(14)
    font_kpi = _pick_font(26, bold=True)

    for p, x0, accent in ((pa, _PAD, col_a), (pb, mid + 10, col_b)):
        card_w = mid - _PAD - 10
        draw.rounded_rectangle(
            [x0, y, x0 + card_w, y + 200],
            radius=14,
            fill=_CARD,
            outline=accent,
            width=2,
        )
        _paste_side_mark(im, draw, p.team, x0 + 40, y + 44, 56, nation=is_nat)
        draw.text((x0 + 80, y + 18), p.team, font=font_n, fill=_TEXT)
        if is_nat:
            lines = [
                f"Престиж: {p.score:.0f}",
                f"Чемп. ЧМ: {p.league_titles}",
                f"Лучший игрок ЧМ: {p.awards}",
                f"OVR заявки: {p.roster_ovr:g}",
            ]
        else:
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
    y += 30

    draw.rounded_rectangle(
        [_PAD, y, _CANVAS_W - _PAD, y + h2h_block],
        radius=16,
        fill=_CARD,
        outline=_LINE,
    )
    played = int(h2h["played"] or 0)
    wa = int(h2h["wins_a"] or 0)
    wb = int(h2h["wins_b"] or 0)
    dr = int(h2h["draws"] or 0)
    ga = int(h2h["goals_a"] or 0)
    gb = int(h2h["goals_b"] or 0)

    if played <= 0:
        draw.text(
            (_PAD + 24, y + 110),
            "Матчей в журналах не найдено.",
            font=font_m,
            fill=_DIM,
        )
        return _to_png(im.convert("RGB"))

    # KPI chips
    kpis = [
        (f"Победы · {pa.team}", str(wa), col_a),
        ("Ничьи", str(dr), draw_c),
        (f"Победы · {pb.team}", str(wb), col_b),
        ("Голы", f"{ga}:{gb}", _GOLD),
    ]
    gap = 10
    chip_w = (_CANVAS_W - 2 * _PAD - 32 - 3 * gap) // 4
    chip_y = y + 16
    for i, (lab, val, accent) in enumerate(kpis):
        x0 = _PAD + 16 + i * (chip_w + gap)
        draw.rounded_rectangle(
            [x0, chip_y, x0 + chip_w, chip_y + 64],
            radius=10,
            fill=(22, 32, 50),
            outline=accent,
        )
        top = _fit(draw, lab, font_sm, chip_w - 12)
        tw = draw.textbbox((0, 0), top, font=font_sm)[2]
        draw.text((x0 + (chip_w - tw) // 2, chip_y + 8), top, font=font_sm, fill=_DIM)
        vw = draw.textbbox((0, 0), val, font=font_kpi)[2]
        draw.text((x0 + (chip_w - vw) // 2, chip_y + 30), val, font=font_kpi, fill=_TEXT)

    # Segmented W–D–L bar
    bar_y = chip_y + 84
    draw.text((_PAD + 16, bar_y), f"Результаты · {played} матч(ей)", font=font_sm, fill=_DIM)
    bar_y += 24
    bar_x0 = _PAD + 16
    bar_x1 = _CANVAS_W - _PAD - 16
    bar_h = 36
    total_seg = max(played, 1)
    segs = [
        (wa, col_a, f"{pa.team} {wa}"),
        (dr, draw_c, f"ничьи {dr}"),
        (wb, col_b, f"{pb.team} {wb}"),
    ]
    draw.rounded_rectangle(
        [bar_x0, bar_y, bar_x1, bar_y + bar_h],
        radius=10,
        fill=(18, 26, 40),
        outline=_LINE,
    )
    active = [(n, col) for n, col, _lab in segs if n > 0]
    cursor = float(bar_x0)
    span = float(bar_x1 - bar_x0)
    for i, (n, col) in enumerate(active):
        if i == len(active) - 1:
            right = float(bar_x1)
        else:
            right = cursor + span * (n / total_seg)
        left_i, right_i = int(cursor), int(right)
        if right_i > left_i:
            draw.rectangle([left_i, bar_y + 1, right_i, bar_y + bar_h - 1], fill=col)
            w = right_i - left_i
            if w >= 36:
                label = str(n)
                lw = draw.textbbox((0, 0), label, font=font_b)[2]
                draw.text(
                    (left_i + (w - lw) // 2, bar_y + 6),
                    label,
                    font=font_b,
                    fill=(16, 22, 34),
                )
        cursor = right

    # Legend under bar
    lx = bar_x0
    for n, col, lab in segs:
        draw.rounded_rectangle([lx, bar_y + bar_h + 12, lx + 14, bar_y + bar_h + 26], radius=3, fill=col)
        draw.text(
            (lx + 20, bar_y + bar_h + 10),
            _fit(draw, lab, font_sm, 280),
            font=font_sm,
            fill=_DIM,
        )
        lx += 300

    # Goals duel bars
    goals_y = bar_y + bar_h + 48
    draw.text((_PAD + 16, goals_y), "Голы во встречах", font=font_sm, fill=_DIM)
    goals_y += 22
    max_g = max(ga, gb, 1)
    g_bar_x0 = _PAD + 180
    g_bar_x1 = _CANVAS_W - _PAD - 70
    g_max_w = g_bar_x1 - g_bar_x0
    for i, (name, goals, col) in enumerate(
        ((pa.team, ga, col_a), (pb.team, gb, col_b))
    ):
        yy = goals_y + i * 36
        draw.text(
            (_PAD + 16, yy + 4),
            _fit(draw, name, font_m, 150),
            font=font_m,
            fill=_TEXT,
        )
        bw = int(g_max_w * (goals / max_g)) if max_g else 0
        draw.rounded_rectangle(
            [g_bar_x0, yy, g_bar_x0 + max(bw, 4 if goals else 0), yy + 24],
            radius=8,
            fill=col if goals else _LINE,
        )
        draw.text((g_bar_x1 + 12, yy + 2), str(goals), font=font_b, fill=_TEXT)

    return _to_png(im.convert("RGB"))


def _match_result_for_team(m: dict, team: str) -> tuple[str, int, int, int]:
    """(W|D|L, points, gf, ga) с точки зрения клуба (учитывает пенальти)."""
    from bot.team_history import match_result_for_team

    return match_result_for_team(m, team)


def render_h2h_png(team_a: str, team_b: str) -> bytes:
    if is_nation_name(team_a) != is_nation_name(team_b):
        raise ValueError("H2H только клуб–клуб или сборная–сборная")
    h2h = head_to_head(team_a, team_b)
    ta, tb = str(h2h["team_a"]), str(h2h["team_b"])
    is_nat = is_nation_name(ta)
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

    # Crest / flag duel header
    mid = _CANVAS_W // 2
    header_top = y
    draw.rounded_rectangle(
        [_PAD, header_top, _CANVAS_W - _PAD, header_top + 110],
        radius=16,
        fill=_CARD,
        outline=_LINE,
    )
    _paste_side_mark(im, draw, ta, _PAD + 70, header_top + 55, 64, nation=is_nat)
    _paste_side_mark(
        im, draw, tb, _CANVAS_W - _PAD - 70, header_top + 55, 64, nation=is_nat
    )
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
    parsed: list[tuple[dict, str, int, int, str, str]] = []
    for m in show:
        res, _pts, gf, ga = _match_result_for_team(m, ta)
        max_g = max(max_g, gf, ga)
        pens = _penalties_pair(m)
        sc_lab = f"{gf}:{ga}"
        if pens is not None:
            ph, pa = pens
            if _team_norm(str(m.get("home") or "")) == _team_norm(ta):
                sc_lab = f"{gf}:{ga} п{ph}:{pa}"
            else:
                sc_lab = f"{gf}:{ga} п{pa}:{ph}"
        parsed.append(
            (m, res, gf, ga, f"{format_season_tag(m.get('_season'))}·м{m.get('day')}", sc_lab)
        )
    n = max(1, len(parsed))
    slot_w = (chart_right - chart_left) / n
    pair_gap = 4
    bar_w = max(8, min(22, int((slot_w - 16 - pair_gap) / 2)))

    for i, (m, res, gf, ga, lab, sc_lab) in enumerate(parsed):
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
        scw = draw.textbbox((0, 0), sc_lab, font=font_sm)[2]
        draw.text((cx - scw // 2, chart_top), sc_lab, font=font_sm, fill=_GOLD if "п" in sc_lab else _TEXT)
        lw = draw.textbbox((0, 0), lab, font=font_sm)[2]
        draw.text((cx - lw // 2, chart_bot + 6), lab, font=font_sm, fill=_DIM)

    y += chart_h + 18

    # Match list
    draw.text((_PAD, y), "Встречи", font=font_b, fill=_TEXT)
    y += 28
    res_col = {"W": win_c, "D": draw_c, "L": lose_c}
    for m, res, gf, ga, _lab, _sc in parsed:
        sn = m.get("_season")
        day = m.get("day")
        lg = str(m.get("league") or "")
        meta = f"{format_season_tag(sn) if sn else '?'} · м{day} · {lg}"
        score = format_match_score_with_pens(m)

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
    clubs_r = list(roman["top_clubs"] or [])
    clubs_l = list(lika["top_clubs"] or [])
    n_clubs = max(len(clubs_r), len(clubs_l), 1)
    row_h = 30
    stats_block = 168
    chart_h = 150
    card_h = stats_block + 28 + n_clubs * row_h + 16
    h = 110 + chart_h + 20 + card_h + 36
    im = _gradient_bg(min(h, 3200)).convert("RGBA")
    draw = ImageDraw.Draw(im)
    y = _title(draw, "Менеджеры", "Roman vs Lika — все клубы, престиж и трофеи")
    font_n = _pick_font(28, bold=True)
    font_m = _pick_font(16)
    font_b = _pick_font(18, bold=True)
    font_sm = _pick_font(13)
    font_kpi = _pick_font(24, bold=True)
    mid = _CANVAS_W // 2

    # Comparison bars (total prestige)
    draw.rounded_rectangle(
        [_PAD, y, _CANVAS_W - _PAD, y + chart_h],
        radius=14,
        fill=_CARD,
        outline=_LINE,
    )
    draw.text((_PAD + 16, y + 10), "Суммарный престиж", font=font_b, fill=_TEXT)
    max_tot = max(float(roman["prestige_total"]), float(lika["prestige_total"]), 1.0)
    bar_left = _PAD + 120
    bar_right = _CANVAS_W - _PAD - 80
    bar_max_w = bar_right - bar_left
    for i, (st, col) in enumerate(((roman, _ROMAN), (lika, _LIKA))):
        yy = y + 48 + i * 44
        draw.text((_PAD + 16, yy + 4), st["label"], font=font_b, fill=col)
        bw = int(bar_max_w * (float(st["prestige_total"]) / max_tot))
        draw.rounded_rectangle(
            [bar_left, yy, bar_left + max(bw, 8), yy + 28],
            radius=8,
            fill=col,
        )
        val = f"{st['prestige_total']:.0f}"
        draw.text((bar_left + max(bw, 8) + 10, yy + 4), val, font=font_kpi, fill=_TEXT)
    y += chart_h + 16

    for st, clubs, col, x0 in (
        (roman, clubs_r, _ROMAN, _PAD),
        (lika, clubs_l, _LIKA, mid + 8),
    ):
        card_w = mid - _PAD - 8
        draw.rounded_rectangle(
            [x0, y, x0 + card_w, y + card_h],
            radius=16,
            fill=_CARD,
            outline=col,
            width=2,
        )
        draw.text((x0 + 16, y + 12), st["label"], font=font_n, fill=col)
        draw.text(
            (x0 + 16, y + 48),
            f"клубов: {len(clubs)} · ср. {st['avg_prestige']:.0f}",
            font=font_sm,
            fill=_DIM,
        )
        # mini KPIs
        kpis = [
            ("Чемп.", str(st["league_titles"])),
            ("ЛЧ", str(st["cl_titles"])),
            ("Нагр.", str(st["awards"])),
        ]
        kx = x0 + 16
        for lab, val in kpis:
            draw.rounded_rectangle([kx, y + 72, kx + 70, y + 118], radius=8, fill=(22, 32, 50), outline=_LINE)
            tw = draw.textbbox((0, 0), lab, font=font_sm)[2]
            draw.text((kx + (70 - tw) // 2, y + 76), lab, font=font_sm, fill=_DIM)
            vw = draw.textbbox((0, 0), val, font=font_b)[2]
            draw.text((kx + (70 - vw) // 2, y + 94), val, font=font_b, fill=_TEXT)
            kx += 78

        draw.text((x0 + 16, y + stats_block - 22), "Все клубы", font=font_b, fill=_GOLD)
        yy = y + stats_block + 4
        max_score = max((p.score for p in clubs), default=1.0) or 1.0
        name_w = 200
        bar_x0 = x0 + 250
        bar_x1 = x0 + card_w - 56
        for i, p in enumerate(clubs, 1):
            crest = _try_load_crest_rgba(p.team)
            if crest is not None:
                _paste_crest_natural(im, crest, x0 + 28, yy + 12, 22)
            rank_c = _GOLD if i <= 3 else _DIM
            draw.text((x0 + 44, yy + 4), f"{i:02d}", font=font_sm, fill=rank_c)
            draw.text(
                (x0 + 70, yy + 4),
                _fit(draw, p.team, font_m, name_w),
                font=font_m,
                fill=_TEXT,
            )
            bw = int((bar_x1 - bar_x0) * (p.score / max_score)) if max_score else 0
            if p.score > 0:
                draw.rounded_rectangle(
                    [bar_x0, yy + 8, bar_x0 + max(bw, 3), yy + 20],
                    radius=4,
                    fill=col,
                )
            sc = f"{p.score:.0f}"
            draw.text((bar_x1 + 6, yy + 4), sc, font=font_sm, fill=_TEXT)
            yy += row_h
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


def _hof_stat_cols() -> list[tuple[str, str]]:
    """(ключ, заголовок) — порядок колонок зала славы."""
    return [
        ("matches", "И"),
        ("goals", "Г"),
        ("assists", "А"),
        ("ga", "Г+А"),
        ("potm", "POTM"),
    ]


def _hof_row_values(leg: ClubLegend) -> dict[str, int]:
    g = int(leg.goals or 0)
    a = int(leg.assists or 0)
    return {
        "matches": int(leg.matches or 0),
        "goals": g,
        "assists": a,
        "ga": g + a,
        "potm": int(leg.potm or 0),
    }


def _render_hof_table(
    *,
    title: str,
    subtitle: str,
    rows: list[ClubLegend],
    show_club: bool,
    crest_team: str | None = None,
) -> bytes:
    """Таблица легенд: шапка И / Г / А / Г+А / POTM, без score."""
    cols = _hof_stat_cols()
    font_b = _pick_font(20, bold=True)
    font_sm = _pick_font(14)
    font_r = _pick_font(22, bold=True)
    font_head = _pick_font(14, bold=True)
    font_num = _pick_font(19, bold=True)

    row_h = 46
    head_h = 34
    n = max(1, len(rows))
    table_h = head_h + n * row_h + 12
    extra_crest = 8
    h = 118 + extra_crest + table_h + 36
    im = _gradient_bg(min(h, 2800)).convert("RGBA")
    draw = ImageDraw.Draw(im)
    y = _title(draw, title, subtitle)

    if crest_team:
        crest = _try_load_crest_rgba(crest_team)
        if crest is not None:
            _paste_crest_natural(im, crest, _CANVAS_W - _PAD - 36, 48, 52)

    # Column geometry
    col_w = 92
    potm_w = 108
    stats_right = _CANVAS_W - _PAD - 20
    stats_span = (len(cols) - 1) * col_w + potm_w
    stats_left = stats_right - stats_span
    name_x = _PAD + 96
    name_max = stats_left - name_x - 20

    def _col_center(i: int) -> int:
        if i < len(cols) - 1:
            return stats_left + i * col_w + col_w // 2
        return stats_left + (len(cols) - 1) * col_w + potm_w // 2

    table_top = y
    table_bot = y + table_h
    draw.rounded_rectangle(
        [_PAD, table_top, _CANVAS_W - _PAD, table_bot],
        radius=14,
        fill=_CARD,
        outline=_LINE,
        width=1,
    )

    # Header
    hy = table_top + 4
    draw.rounded_rectangle(
        [_PAD + 4, hy, _CANVAS_W - _PAD - 4, hy + head_h],
        radius=8,
        fill=(18, 26, 42),
    )
    draw.text((_PAD + 18, hy + 8), "#", font=font_head, fill=_DIM)
    draw.text((name_x, hy + 8), "Игрок", font=font_head, fill=_DIM)
    for i, (_key, lab) in enumerate(cols):
        cx = _col_center(i)
        lw = draw.textbbox((0, 0), lab, font=font_head)[2]
        draw.text((cx - lw // 2, hy + 8), lab, font=font_head, fill=_GOLD)

    medal = {1: (255, 214, 110), 2: (198, 208, 224), 3: (205, 148, 98)}
    y = hy + head_h

    for i, leg in enumerate(rows, 1):
        top = y
        club = (getattr(leg, "club", "") or "") if show_club else (crest_team or "")
        # zebra
        if i % 2 == 0:
            draw.rectangle(
                [_PAD + 4, top, _CANVAS_W - _PAD - 4, top + row_h],
                fill=(24, 34, 54),
            )
        # top-3 left accent
        if i <= 3:
            draw.rounded_rectangle(
                [_PAD + 6, top + 8, _PAD + 10, top + row_h - 8],
                radius=2,
                fill=medal[i],
            )

        rank_c = medal.get(i, _DIM)
        draw.text((_PAD + 18, top + 11), f"{i:02d}", font=font_r, fill=rank_c)

        if club:
            crest = _try_load_crest_rgba(club)
            if crest is not None:
                _paste_crest_natural(im, crest, _PAD + 70, top + row_h // 2, 24)
        draw.text(
            (name_x, top + 5),
            _fit(draw, leg.name, font_b, name_max),
            font=font_b,
            fill=_TEXT,
        )
        if show_club:
            meta = f"{club or '—'} · {leg.position or '—'} · {leg.overall or '—'}"
        else:
            meta = f"{leg.position or '—'} · OVR {leg.overall or '—'}"
        draw.text(
            (name_x, top + 26),
            _fit(draw, meta, font_sm, name_max),
            font=font_sm,
            fill=_DIM,
        )

        vals = _hof_row_values(leg)
        for ci, (key, _lab) in enumerate(cols):
            cx = _col_center(ci)
            val = str(vals[key])
            vw = draw.textbbox((0, 0), val, font=font_num)[2]
            fill = _GOLD if key == "ga" else _TEXT
            draw.text((cx - vw // 2, top + 12), val, font=font_num, fill=fill)

        # separator (except last)
        if i < n:
            draw.line(
                [_PAD + 16, top + row_h - 1, _CANVAS_W - _PAD - 16, top + row_h - 1],
                fill=(40, 54, 78),
                width=1,
            )
        y += row_h

    return _to_png(im.convert("RGB"))


def render_hall_of_fame_png(*, limit: int = 20) -> bytes:
    rows = hall_of_fame_global(limit=limit)
    return _render_hof_table(
        title="Зал славы",
        subtitle=None,
        rows=rows,
        show_club=True,
    )


def render_club_hall_of_fame_png(team: str) -> bytes:
    from bot.team_history import club_legends

    rows = club_legends(team, limit=15)
    return _render_hof_table(
        title=f"Зал славы · {team}",
        subtitle=None,
        rows=rows,
        show_club=False,
        crest_team=team,
    )


def render_club_career_goals_png(
    *,
    limit: int | None = None,
    offset: int = 0,
    page_size: int | None = None,
    page_label: str | None = None,
) -> bytes:
    """Таблица голов клубов пула: лига / ЛЧ / всего (опционально страница)."""
    all_rows = club_career_goals(pool_only=True)
    if limit is not None:
        all_rows = all_rows[: max(1, int(limit))]
    if page_size is not None:
        rows = all_rows[offset : offset + int(page_size)]
        rank0 = offset
    else:
        rows = all_rows
        rank0 = 0

    font_b = _pick_font(20, bold=True)
    font_r = _pick_font(22, bold=True)
    font_head = _pick_font(14, bold=True)
    font_num = _pick_font(19, bold=True)

    row_h = 44
    head_h = 34
    n = max(1, len(rows))
    table_h = head_h + n * row_h + 12
    h = 118 + table_h + 36
    im = _gradient_bg(min(h, 3200)).convert("RGBA")
    draw = ImageDraw.Draw(im)
    sub = "Все сезоны · забитые мячи · лига / ЛЧ / сумма"
    if page_label:
        sub = f"{sub} · стр. {page_label}"
    y = _title(draw, "Голы клубов", sub)

    cols = [("league_gf", "Лига"), ("cl_gf", "ЛЧ"), ("total_gf", "Всего")]
    col_w = 120
    stats_right = _CANVAS_W - _PAD - 24
    stats_span = len(cols) * col_w
    stats_left = stats_right - stats_span
    name_x = _PAD + 96
    name_max = stats_left - name_x - 16

    def _col_center(i: int) -> int:
        return stats_left + i * col_w + col_w // 2

    table_top = y
    table_bot = y + table_h
    draw.rounded_rectangle(
        [_PAD, table_top, _CANVAS_W - _PAD, table_bot],
        radius=14,
        fill=_CARD,
        outline=_LINE,
        width=1,
    )

    hy = table_top + 4
    draw.rounded_rectangle(
        [_PAD + 4, hy, _CANVAS_W - _PAD - 4, hy + head_h],
        radius=8,
        fill=(18, 26, 42),
    )
    draw.text((_PAD + 18, hy + 8), "#", font=font_head, fill=_DIM)
    draw.text((name_x, hy + 8), "Клуб", font=font_head, fill=_DIM)
    for i, (_key, lab) in enumerate(cols):
        cx = _col_center(i)
        lw = draw.textbbox((0, 0), lab, font=font_head)[2]
        draw.text((cx - lw // 2, hy + 8), lab, font=font_head, fill=_GOLD)

    medal = {1: (255, 214, 110), 2: (198, 208, 224), 3: (205, 148, 98)}
    y = hy + head_h

    for i, row in enumerate(rows):
        rank = rank0 + i + 1
        top = y
        if i % 2 == 1:
            draw.rectangle(
                [_PAD + 4, top, _CANVAS_W - _PAD - 4, top + row_h],
                fill=(24, 34, 54),
            )
        if rank <= 3:
            draw.rounded_rectangle(
                [_PAD + 6, top + 8, _PAD + 10, top + row_h - 8],
                radius=2,
                fill=medal[rank],
            )

        rank_c = medal.get(rank, _DIM)
        draw.text((_PAD + 18, top + 10), f"{rank:02d}", font=font_r, fill=rank_c)

        crest = _try_load_crest_rgba(row.team)
        if crest is not None:
            _paste_crest_natural(im, crest, _PAD + 70, top + row_h // 2, 24)
        draw.text(
            (name_x, top + 11),
            _fit(draw, row.team, font_b, name_max),
            font=font_b,
            fill=_TEXT,
        )

        vals = {
            "league_gf": row.league_gf,
            "cl_gf": row.cl_gf,
            "total_gf": row.total_gf,
        }
        for ci, (key, _lab) in enumerate(cols):
            cx = _col_center(ci)
            val = str(vals[key])
            vw = draw.textbbox((0, 0), val, font=font_num)[2]
            fill = _GOLD if key == "total_gf" else _TEXT
            draw.text((cx - vw // 2, top + 11), val, font=font_num, fill=fill)
        y += row_h

    return _to_png(im.convert("RGB"))


def render_club_career_goals_pages(*, page_size: int = 10) -> list[bytes]:
    """Все клубы пула страницами по ``page_size`` (по умолчанию 10 → 4 фото)."""
    rows = club_career_goals(pool_only=True)
    total = len(rows)
    page_size = max(1, int(page_size))
    n_pages = max(1, (total + page_size - 1) // page_size)
    pages: list[bytes] = []
    for p in range(n_pages):
        off = p * page_size
        pages.append(
            render_club_career_goals_png(
                offset=off,
                page_size=page_size,
                page_label=f"{p + 1}/{n_pages}",
            )
        )
    return pages


def render_nation_career_goals_png(
    *,
    offset: int = 0,
    page_size: int | None = None,
    page_label: str | None = None,
) -> bytes:
    """Голы сборных только в матчах ЧМ."""
    from bot.report_gfx import paste_nation_flag

    all_rows = nation_career_goals()
    if page_size is not None:
        rows = all_rows[offset : offset + int(page_size)]
        rank0 = offset
    else:
        rows = all_rows
        rank0 = 0

    font_b = _pick_font(20, bold=True)
    font_r = _pick_font(22, bold=True)
    font_head = _pick_font(14, bold=True)
    font_num = _pick_font(19, bold=True)

    row_h = 44
    head_h = 34
    n = max(1, len(rows))
    table_h = head_h + n * row_h + 12
    h = 118 + table_h + 36
    im = _gradient_bg(min(h, 3200)).convert("RGBA")
    draw = ImageDraw.Draw(im)
    title = "Голы сборных · ЧМ"
    if page_label:
        title = f"{title} · {page_label}"
    y = _title(draw, title, "Сумма голов во всех матчах Чемпионата мира")
    name_x = _PAD + 100
    name_max = 520
    goals_x = _CANVAS_W - _PAD - 80

    table_top = y
    draw.rounded_rectangle(
        [_PAD, table_top, _CANVAS_W - _PAD, table_top + table_h],
        radius=14,
        fill=_CARD,
        outline=_LINE,
        width=1,
    )
    hy = table_top + 4
    draw.rounded_rectangle(
        [_PAD + 4, hy, _CANVAS_W - _PAD - 4, hy + head_h],
        radius=8,
        fill=(18, 26, 42),
    )
    draw.text((_PAD + 18, hy + 8), "#", font=font_head, fill=_DIM)
    draw.text((name_x, hy + 8), "Сборная", font=font_head, fill=_DIM)
    gw = draw.textbbox((0, 0), "Голы", font=font_head)[2]
    draw.text((goals_x - gw // 2, hy + 8), "Голы", font=font_head, fill=_GOLD)

    medal = {1: (255, 214, 110), 2: (198, 208, 224), 3: (205, 148, 98)}
    y = hy + head_h
    if not rows:
        draw.text((_PAD + 18, y + 12), "Матчей ЧМ в журналах пока нет.", font=font_b, fill=_DIM)
        return _to_png(im.convert("RGB"))

    for i, row in enumerate(rows):
        rank = rank0 + i + 1
        top = y
        if i % 2 == 1:
            draw.rectangle(
                [_PAD + 4, top, _CANVAS_W - _PAD - 4, top + row_h],
                fill=(24, 34, 54),
            )
        if rank <= 3:
            draw.rounded_rectangle(
                [_PAD + 6, top + 8, _PAD + 10, top + row_h - 8],
                radius=2,
                fill=medal[rank],
            )
        rank_c = medal.get(rank, _DIM)
        draw.text((_PAD + 18, top + 10), f"{rank:02d}", font=font_r, fill=rank_c)
        paste_nation_flag(im, draw, nation=row.team, cx=_PAD + 70, cy=top + row_h // 2, size=24)
        draw.text(
            (name_x, top + 11),
            _fit(draw, row.team, font_b, name_max),
            font=font_b,
            fill=_TEXT,
        )
        val = str(row.total_gf)
        vw = draw.textbbox((0, 0), val, font=font_num)[2]
        draw.text((goals_x - vw // 2, top + 11), val, font=font_num, fill=_GOLD)
        y += row_h

    return _to_png(im.convert("RGB"))


def render_nation_career_goals_pages(*, page_size: int = 16) -> list[bytes]:
    rows = nation_career_goals()
    total = len(rows)
    page_size = max(1, int(page_size))
    n_pages = max(1, (total + page_size - 1) // page_size) if total else 1
    pages: list[bytes] = []
    for p in range(n_pages):
        off = p * page_size
        pages.append(
            render_nation_career_goals_png(
                offset=off,
                page_size=page_size,
                page_label=f"{p + 1}/{n_pages}",
            )
        )
    return pages


def render_club_career_conceded_png(
    *,
    limit: int | None = None,
    offset: int = 0,
    page_size: int | None = None,
    page_label: str | None = None,
) -> bytes:
    """Таблица пропущенных: лига / ЛЧ / всего (меньше — лучше)."""
    all_rows = club_career_conceded(pool_only=True)
    if limit is not None:
        all_rows = all_rows[: max(1, int(limit))]
    if page_size is not None:
        rows = all_rows[offset : offset + int(page_size)]
        rank0 = offset
    else:
        rows = all_rows
        rank0 = 0

    font_b = _pick_font(20, bold=True)
    font_r = _pick_font(22, bold=True)
    font_head = _pick_font(14, bold=True)
    font_num = _pick_font(19, bold=True)

    row_h = 44
    head_h = 34
    n = max(1, len(rows))
    table_h = head_h + n * row_h + 12
    h = 118 + table_h + 36
    im = _gradient_bg(min(h, 3200)).convert("RGBA")
    draw = ImageDraw.Draw(im)
    sub = "Все сезоны · пропущенные · лига / ЛЧ / сумма · меньше лучше"
    if page_label:
        sub = f"{sub} · стр. {page_label}"
    y = _title(draw, "Пропущенные клубов", sub)

    cols = [("league_ga", "Лига"), ("cl_ga", "ЛЧ"), ("total_ga", "Всего")]
    col_w = 120
    stats_right = _CANVAS_W - _PAD - 24
    stats_span = len(cols) * col_w
    stats_left = stats_right - stats_span
    name_x = _PAD + 96
    name_max = stats_left - name_x - 16

    def _col_center(i: int) -> int:
        return stats_left + i * col_w + col_w // 2

    table_top = y
    table_bot = y + table_h
    draw.rounded_rectangle(
        [_PAD, table_top, _CANVAS_W - _PAD, table_bot],
        radius=14,
        fill=_CARD,
        outline=_LINE,
        width=1,
    )

    hy = table_top + 4
    draw.rounded_rectangle(
        [_PAD + 4, hy, _CANVAS_W - _PAD - 4, hy + head_h],
        radius=8,
        fill=(18, 26, 42),
    )
    draw.text((_PAD + 18, hy + 8), "#", font=font_head, fill=_DIM)
    draw.text((name_x, hy + 8), "Клуб", font=font_head, fill=_DIM)
    for i, (_key, lab) in enumerate(cols):
        cx = _col_center(i)
        lw = draw.textbbox((0, 0), lab, font=font_head)[2]
        draw.text((cx - lw // 2, hy + 8), lab, font=font_head, fill=_GOLD)

    medal = {1: (255, 214, 110), 2: (198, 208, 224), 3: (205, 148, 98)}
    y = hy + head_h

    for i, row in enumerate(rows):
        rank = rank0 + i + 1
        top = y
        if i % 2 == 1:
            draw.rectangle(
                [_PAD + 4, top, _CANVAS_W - _PAD - 4, top + row_h],
                fill=(24, 34, 54),
            )
        if rank <= 3:
            draw.rounded_rectangle(
                [_PAD + 6, top + 8, _PAD + 10, top + row_h - 8],
                radius=2,
                fill=medal[rank],
            )

        rank_c = medal.get(rank, _DIM)
        draw.text((_PAD + 18, top + 10), f"{rank:02d}", font=font_r, fill=rank_c)

        crest = _try_load_crest_rgba(row.team)
        if crest is not None:
            _paste_crest_natural(im, crest, _PAD + 70, top + row_h // 2, 24)
        draw.text(
            (name_x, top + 11),
            _fit(draw, row.team, font_b, name_max),
            font=font_b,
            fill=_TEXT,
        )

        vals = {
            "league_ga": row.league_ga,
            "cl_ga": row.cl_ga,
            "total_ga": row.total_ga,
        }
        for ci, (key, _lab) in enumerate(cols):
            cx = _col_center(ci)
            val = str(vals[key])
            vw = draw.textbbox((0, 0), val, font=font_num)[2]
            fill = _GOLD if key == "total_ga" else _TEXT
            draw.text((cx - vw // 2, top + 11), val, font=font_num, fill=fill)
        y += row_h

    return _to_png(im.convert("RGB"))


def render_club_career_conceded_pages(*, page_size: int = 10) -> list[bytes]:
    rows = club_career_conceded(pool_only=True)
    total = len(rows)
    page_size = max(1, int(page_size))
    n_pages = max(1, (total + page_size - 1) // page_size)
    pages: list[bytes] = []
    for p in range(n_pages):
        off = p * page_size
        pages.append(
            render_club_career_conceded_png(
                offset=off,
                page_size=page_size,
                page_label=f"{p + 1}/{n_pages}",
            )
        )
    return pages


def render_club_player_influence_png(team: str, *, min_played: int = 10) -> bytes:
    """Балл влияния: Win% (сжатый) + объём + доступность + чуть статы."""
    from bot.team_history import club_player_win_influence

    rows = club_player_win_influence(team, min_played=min_played, limit=25)
    font_b = _pick_font(20, bold=True)
    font_r = _pick_font(22, bold=True)
    font_head = _pick_font(14, bold=True)
    font_num = _pick_font(18, bold=True)
    font_m = _pick_font(16)

    if not rows:
        h = 280
        im = _gradient_bg(h).convert("RGBA")
        draw = ImageDraw.Draw(im)
        y = _title(
            draw,
            f"Влияние · {team}",
            f"Основа: матчи клуба−травмы · ᵇ/ʳ скамья и резерв: matches БД · ≥{min_played}",
        )
        draw.text(
            (_PAD, y + 8),
            f"Нет игроков с ≥{min_played} матчами.",
            font=font_m,
            fill=_DIM,
        )
        return _to_png(im.convert("RGB"))

    row_h = 42
    head_h = 34
    n = len(rows)
    table_h = head_h + n * row_h + 12
    h = 150 + table_h + 40
    im = _gradient_bg(min(h, 3200)).convert("RGBA")
    draw = ImageDraw.Draw(im)
    y = _title(
        draw,
        f"Влияние · {team}",
        f"Основа: клуб−травмы · ᵇскамья/ʳрезерв: matches БД · ≥{min_played} · Win%+объём+стата",
    )

    name_x = _PAD + 70
    cols_x = [
        (_CANVAS_W - _PAD - 430, "В-Н-П"),
        (_CANVAS_W - _PAD - 310, "Матч"),
        (_CANVAS_W - _PAD - 220, "Травма"),
        (_CANVAS_W - _PAD - 130, "Win%"),
        (_CANVAS_W - _PAD - 50, "Балл"),
    ]

    table_top = y
    table_bot = y + table_h
    draw.rounded_rectangle(
        [_PAD, table_top, _CANVAS_W - _PAD, table_bot],
        radius=14,
        fill=_CARD,
        outline=_LINE,
        width=1,
    )
    hy = table_top + 4
    draw.rounded_rectangle(
        [_PAD + 4, hy, _CANVAS_W - _PAD - 4, hy + head_h],
        radius=8,
        fill=(18, 26, 42),
    )
    draw.text((_PAD + 18, hy + 8), "#", font=font_head, fill=_DIM)
    draw.text((name_x, hy + 8), "Игрок", font=font_head, fill=_DIM)
    for cx, lab in cols_x:
        lw = draw.textbbox((0, 0), lab, font=font_head)[2]
        draw.text((cx - lw // 2, hy + 8), lab, font=font_head, fill=_GOLD)

    medal = {1: (255, 214, 110), 2: (198, 208, 224), 3: (205, 148, 98)}
    y = hy + head_h
    for i, row in enumerate(rows):
        rank = i + 1
        top = y
        if i % 2 == 1:
            draw.rectangle(
                [_PAD + 4, top, _CANVAS_W - _PAD - 4, top + row_h],
                fill=(24, 34, 54),
            )
        if rank <= 3:
            draw.rounded_rectangle(
                [_PAD + 6, top + 8, _PAD + 10, top + row_h - 8],
                radius=2,
                fill=medal[rank],
            )
        draw.text(
            (_PAD + 18, top + 10),
            f"{rank:02d}",
            font=font_r,
            fill=medal.get(rank, _DIM),
        )
        st_mark = {"start": "", "bench": "ᵇ", "reserve": "ʳ"}.get(
            (row.status or "").strip().lower(), ""
        )
        label = f"{row.player}{st_mark}"
        if row.position:
            label = f"{label} · {row.position}"
        draw.text(
            (name_x, top + 10),
            _fit(draw, label, font_b, cols_x[0][0] - name_x - 24),
            font=font_b,
            fill=_TEXT,
        )
        wdl = f"{row.wins}-{row.draws}-{row.losses}"
        for cx, val in (
            (cols_x[0][0], wdl),
            (cols_x[1][0], str(row.played)),
            (cols_x[2][0], str(row.missed_injury)),
            (cols_x[3][0], f"{row.win_pct:.0f}%"),
            (cols_x[4][0], f"{row.score:.0f}"),
        ):
            vw = draw.textbbox((0, 0), val, font=font_num)[2]
            fill = _GOLD if cx == cols_x[4][0] else _TEXT
            draw.text((cx - vw // 2, top + 10), val, font=font_num, fill=fill)
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
    results_chrono: list[str] = []
    for m in sorted(rows, key=lambda x: (int(x.get("day") or 0), str(x.get("league") or ""))):
        res, pts, gf, ga = _match_result_for_team(m, team)
        results_chrono.append(res)
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
    streaks = compute_result_streaks(results_chrono)

    chart_h = 260
    show = rows[:40]
    list_h = 28 + len(show) * 34 + (24 if len(rows) > len(show) else 0)
    kpi_block_h = 88 + 84  # основная полоска + серии
    h = 150 + kpi_block_h + chart_h + 28 + list_h + 36
    im = _gradient_bg(min(h, 2800)).convert("RGBA")
    draw = ImageDraw.Draw(im)
    y = _title(
        draw,
        f"Матчи · {team}",
        f"{format_season_tag(season)} · {len(rows)} матч. · очки по месяцам",
    )

    def _kpi_row(items: list[tuple[str, str]], top: int) -> None:
        n = len(items)
        gap = 12
        card_w = (_CANVAS_W - 2 * _PAD - (n - 1) * gap) // n
        for i, (lab, val) in enumerate(items):
            x0 = _PAD + i * (card_w + gap)
            draw.rounded_rectangle([x0, top, x0 + card_w, top + 72], radius=12, fill=_CARD, outline=_LINE)
            tw = draw.textbbox((0, 0), lab, font=font_sm)[2]
            draw.text((x0 + (card_w - tw) // 2, top + 10), lab, font=font_sm, fill=_DIM)
            vw = draw.textbbox((0, 0), val, font=font_kpi)[2]
            draw.text((x0 + (card_w - vw) // 2, top + 32), val, font=font_kpi, fill=_TEXT)

    _kpi_row(
        [
            ("В-Н-П", f"{w}-{d}-{l}"),
            ("Очки", str(pts_total)),
            ("Голы", f"{gf_t}:{ga_t}"),
            ("Разн.", f"{gf_t - ga_t:+d}"),
        ],
        y,
    )
    y += 84
    _kpi_row(
        [
            ("Без пор. · макс", str(streaks["unbeaten"])),
            ("Победы · макс", str(streaks["wins"])),
            ("Лузы · макс", str(streaks["losses"])),
        ],
        y,
    )
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


def render_pvp_kryptonite_teams_png(*, min_played: int = 3) -> bytes:
    """Таблица клубов: сколько kryptonite-серий и против кого."""
    summary = aggregate_pvp_kryptonites_by_team(min_played=min_played)
    font_m = _pick_font(17)
    font_sm = _pick_font(14)
    font_b = _pick_font(20, bold=True)
    font_h = _pick_font(13, bold=True)
    row_h = 40
    header_h = 36
    table_h = header_h + max(1, len(summary)) * row_h + 16
    h = 130 + table_h + 36
    im = _gradient_bg(min(h, 3600)).convert("RGBA")
    draw = ImageDraw.Draw(im)
    y = _title(
        draw,
        "PVP-криптониты · по клубам",
        f"Сколько соперников клуб не проигрывал {min_played}+ матчей · клубов: {len(summary)}",
    )

    x0, x1 = _PAD, _CANVAS_W - _PAD
    col_team = x0 + 12
    col_cnt = x0 + 340
    col_ops = x0 + 470
    ops_max_w = x1 - col_ops - 16

    draw.rounded_rectangle([x0, y, x1, y + table_h], radius=14, fill=_CARD, outline=_LINE)
    hy = y + 10
    for cx, lab in (
        (col_team, "Команда"),
        (col_cnt, "Серий"),
        (col_ops, "Противники"),
    ):
        draw.text((cx, hy), lab, font=font_h, fill=_DIM)
    draw.line([(x0 + 12, y + header_h - 4), (x1 - 12, y + header_h - 4)], fill=_LINE, width=1)

    if not summary:
        draw.text(
            (x0 + 16, y + header_h + 12),
            "Таких серий пока нет в журналах матчей.",
            font=font_m,
            fill=_DIM,
        )
        return _to_png(im.convert("RGB"))

    for i, row in enumerate(summary):
        ry = y + header_h + i * row_h
        if i % 2 == 1:
            draw.rectangle([x0 + 8, ry, x1 - 8, ry + row_h - 2], fill=(22, 32, 50))
        team = str(row.get("team") or "")
        cnt = int(row.get("count") or 0)
        ops = " · ".join(str(x) for x in (row.get("opponents") or []))
        draw.text((col_team, ry + 10), _fit(draw, team, font_m, 300), font=font_m, fill=_ROMAN)
        draw.text((col_cnt + 8, ry + 8), str(cnt), font=font_b, fill=_GOLD)
        draw.text((col_ops, ry + 10), _fit(draw, ops, font_m, ops_max_w), font=font_m, fill=_TEXT)

    foot = "Сортировка по числу серий · внутри строки — по числу матчей с соперником"
    draw.text((_PAD, y + table_h + 12), foot, font=font_sm, fill=_DIM)
    return _to_png(im.convert("RGB"))


def render_pvp_kryptonite_list_png(*, min_played: int = 3) -> bytes:
    """Список клубных пар, где одна команда не проигрывала другой 3+ матчей."""
    rows = find_pvp_kryptonites(min_played=min_played)
    font_m = _pick_font(17)
    font_sm = _pick_font(14)
    font_b = _pick_font(20, bold=True)
    row_h = 44
    header_h = 36
    table_h = header_h + max(1, len(rows)) * row_h + 16
    h = 130 + table_h + 36
    im = _gradient_bg(min(h, 3600)).convert("RGBA")
    draw = ImageDraw.Draw(im)
    y = _title(
        draw,
        "PVP-криптониты",
        f"Клуб не проигрывал сопернику {min_played}+ матчей · всего пар: {len(rows)}",
    )

    x0, x1 = _PAD, _CANVAS_W - _PAD
    draw.rounded_rectangle([x0, y, x1, y + table_h], radius=14, fill=_CARD, outline=_LINE)
    hy = y + 10
    for cx, lab in (
        (x0 + 12, "Кто не проигрывал"),
        (x0 + 340, "Соперник"),
        (x0 + 620, "Матчи"),
        (x0 + 720, "W-D-L"),
        (x0 + 860, "Голы"),
    ):
        draw.text((cx, hy), lab, font=_pick_font(13, bold=True), fill=_DIM)
    draw.line([(x0 + 12, y + header_h - 4), (x1 - 12, y + header_h - 4)], fill=_LINE, width=1)

    if not rows:
        draw.text(
            (x0 + 16, y + header_h + 12),
            "Таких серий пока нет в журналах матчей.",
            font=font_m,
            fill=_DIM,
        )
        return _to_png(im.convert("RGB"))

    win_c = (90, 190, 140)
    draw_c = (200, 180, 90)
    for i, r in enumerate(rows):
        ry = y + header_h + i * row_h
        if i % 2 == 1:
            draw.rectangle([x0 + 8, ry, x1 - 8, ry + row_h - 2], fill=(22, 32, 50))
        dom, vic = str(r["dominant"]), str(r["victim"])
        played = int(r.get("played") or 0)
        wins = int(r.get("wins") or 0)
        dr = int(r.get("draws") or 0)
        losses = int(r.get("losses") or 0)
        if r.get("all_draws"):
            wdl = f"0-{dr}-0"
            note = "все ничьи"
        else:
            wdl = f"{wins}-{dr}-{losses}"
            note = ""
        h2h = head_to_head(dom, vic)
        if _team_norm(str(h2h["team_a"])) == _team_norm(dom):
            goals = f"{h2h['goals_a']}:{h2h['goals_b']}"
        else:
            goals = f"{h2h['goals_b']}:{h2h['goals_a']}"

        draw.text((x0 + 12, ry + 12), _fit(draw, dom, font_m, 300), font=font_m, fill=_ROMAN)
        draw.text((x0 + 340, ry + 12), _fit(draw, vic, font_m, 260), font=font_m, fill=_TEXT)
        draw.text((x0 + 620, ry + 12), str(played), font=font_b, fill=_GOLD)
        draw.text((x0 + 720, ry + 12), wdl, font=font_m, fill=win_c if wins else draw_c)
        draw.text((x0 + 860, ry + 12), goals, font=font_m, fill=_DIM)
        if note:
            draw.text((x0 + 980, ry + 14), note, font=font_sm, fill=_DIM)

    foot = "Нажми пару в клавиатуре (стр. ← →) — полная хронология встреч"
    draw.text((_PAD, y + table_h + 12), foot, font=font_sm, fill=_DIM)
    return _to_png(im.convert("RGB"))


def render_pvp_kryptonite_detail_png(dominant: str, victim: str) -> bytes:
    """Все встречи пары, где ``dominant`` не проигрывал ``victim``."""
    h2h = head_to_head(dominant, victim)
    dom = str(h2h["team_a"])
    vic = str(h2h["team_b"])
    matches = list(h2h.get("matches") or [])
    font_m = _pick_font(16)
    font_sm = _pick_font(14)
    font_b = _pick_font(20, bold=True)
    font_n = _pick_font(26, bold=True)

    row_h = 36
    list_h = 28 + max(1, len(matches)) * row_h + 16
    h = 180 + 90 + list_h + 40
    im = _gradient_bg(min(h, 4000)).convert("RGBA")
    draw = ImageDraw.Draw(im)
    y = _title(draw, "PVP-криптонит · хронология", f"{dom}  →  {vic}")

    mid = _CANVAS_W // 2
    header_top = y
    draw.rounded_rectangle(
        [_PAD, header_top, _CANVAS_W - _PAD, header_top + 100],
        radius=16,
        fill=_CARD,
        outline=_LINE,
    )
    _paste_side_mark(im, draw, dom, _PAD + 70, header_top + 50, 56, nation=False)
    _paste_side_mark(im, draw, vic, _CANVAS_W - _PAD - 70, header_top + 50, 56, nation=False)
    draw.text((_PAD + 120, header_top + 24), _fit(draw, dom, font_n, 360), font=font_n, fill=_TEXT)
    bw = draw.textbbox((0, 0), vic, font=font_n)[2]
    draw.text((_CANVAS_W - _PAD - 120 - bw, header_top + 24), vic, font=font_n, fill=_TEXT)
    sub = f"{h2h['played']} матчей · {dom} не проигрывал · голы {h2h['goals_a']}:{h2h['goals_b']}"
    sw = draw.textbbox((0, 0), sub, font=font_sm)[2]
    draw.text((mid - sw // 2, header_top + 62), sub, font=font_sm, fill=_DIM)
    y = header_top + 116

    wa = int(h2h["wins_a"])
    dr = int(h2h["draws"])
    losses = int(h2h["wins_b"])
    kpis = [
        ("Победы", str(wa), _ROMAN),
        ("Ничьи", str(dr), (200, 180, 90)),
        ("Поражения", str(losses), (220, 110, 110)),
    ]
    gap = 14
    card_w = (_CANVAS_W - 2 * _PAD - 2 * gap) // 3
    for i, (lab, val, accent) in enumerate(kpis):
        x0 = _PAD + i * (card_w + gap)
        draw.rounded_rectangle([x0, y, x0 + card_w, y + 72], radius=12, fill=_CARD, outline=accent)
        tw = draw.textbbox((0, 0), lab, font=font_sm)[2]
        draw.text((x0 + (card_w - tw) // 2, y + 10), lab, font=font_sm, fill=_DIM)
        vw = draw.textbbox((0, 0), val, font=font_b)[2]
        draw.text((x0 + (card_w - vw) // 2, y + 34), val, font=font_b, fill=_TEXT)
    y += 88

    draw.text((_PAD, y), "Все матчи", font=font_b, fill=_TEXT)
    y += 28
    res_col = {"W": (90, 190, 140), "D": (200, 180, 90), "L": (220, 110, 110)}
    for m in matches:
        res, _pts, gf, ga = _match_result_for_team(m, dom)
        lg = str(m.get("league") or "")
        sn = format_season_tag(m.get("_season"))
        day = m.get("day")
        score = format_match_score_with_pens(m)
        line = f"{sn}·м{day} · {lg} · {score}"
        if m.get("cl_phase"):
            line += f" ({m.get('cl_phase')})"
        draw.rounded_rectangle([_PAD, y + 2, _PAD + 28, y + 24], radius=6, fill=res_col.get(res, _LINE))
        cw = draw.textbbox((0, 0), res, font=font_sm)[2]
        draw.text((_PAD + (28 - cw) // 2, y + 4), res, font=font_sm, fill=(16, 22, 34))
        draw.text((_PAD + 40, y + 4), _fit(draw, line, font_m, _CANVAS_W - _PAD - 50), font=font_m, fill=_TEXT)
        y += row_h

    return _to_png(im.convert("RGB"))


def _render_titled_players_png(
    rows: list[TitledPlayer],
    *,
    title: str,
    subtitle: str | None = None,
    offset: int = 0,
    page_label: str | None = None,
) -> bytes:
    """Таблица титулованных игроков: лига / ЛЧ / награды / сумма."""
    font_b = _pick_font(19, bold=True)
    font_sm = _pick_font(13)
    font_r = _pick_font(22, bold=True)
    font_head = _pick_font(13, bold=True)
    font_num = _pick_font(18, bold=True)

    row_h = 46
    head_h = 34
    n = max(1, len(rows)) if rows else 1
    table_h = head_h + n * row_h + 12
    h = 118 + table_h + 36
    im = _gradient_bg(min(h, 3200)).convert("RGBA")
    draw = ImageDraw.Draw(im)
    sub = subtitle or "Титулы лиг · ЛЧ · личные награды · сумма"
    if page_label:
        sub = f"{sub} · стр. {page_label}"
    y = _title(draw, title, sub)

    cols = [
        ("league_titles", "Лига"),
        ("cl_titles", "ЛЧ"),
        ("individual_awards", "Нагр"),
        ("total_titles", "Σ"),
    ]
    col_w = 72
    stats_right = _CANVAS_W - _PAD - 16
    stats_span = len(cols) * col_w
    stats_left = stats_right - stats_span
    name_x = _PAD + 96
    name_max = stats_left - name_x - 16

    def _col_center(i: int) -> int:
        return stats_left + i * col_w + col_w // 2

    table_top = y
    table_bot = y + table_h
    draw.rounded_rectangle(
        [_PAD, table_top, _CANVAS_W - _PAD, table_bot],
        radius=14,
        fill=_CARD,
        outline=_LINE,
        width=1,
    )

    hy = table_top + 4
    draw.rounded_rectangle(
        [_PAD + 4, hy, _CANVAS_W - _PAD - 4, hy + head_h],
        radius=8,
        fill=(18, 26, 42),
    )
    draw.text((_PAD + 18, hy + 8), "#", font=font_head, fill=_DIM)
    draw.text((name_x, hy + 8), "Игрок", font=font_head, fill=_DIM)
    for i, (_key, lab) in enumerate(cols):
        cx = _col_center(i)
        lw = draw.textbbox((0, 0), lab, font=font_head)[2]
        draw.text((cx - lw // 2, hy + 8), lab, font=font_head, fill=_GOLD)

    if not rows:
        draw.text(
            (name_x, hy + head_h + 14),
            "Нет данных по выбранному фильтру.",
            font=font_sm,
            fill=_DIM,
        )
        return _to_png(im.convert("RGB"))

    medal = {1: (255, 214, 110), 2: (198, 208, 224), 3: (205, 148, 98)}
    y = hy + head_h

    for i, row in enumerate(rows):
        rank = offset + i + 1
        top = y
        if i % 2 == 1:
            draw.rectangle(
                [_PAD + 4, top, _CANVAS_W - _PAD - 4, top + row_h],
                fill=(24, 34, 54),
            )
        if rank <= 3:
            draw.rounded_rectangle(
                [_PAD + 6, top + 8, _PAD + 10, top + row_h - 8],
                radius=2,
                fill=medal.get(rank, _LINE),
            )

        rank_c = medal.get(rank, _DIM)
        draw.text((_PAD + 18, top + 11), f"{rank:02d}", font=font_r, fill=rank_c)

        crest = _try_load_crest_rgba(row.team)
        if crest is not None:
            _paste_crest_natural(im, crest, _PAD + 70, top + row_h // 2, 24)
        draw.text(
            (name_x, top + 5),
            _fit(draw, row.name, font_b, name_max),
            font=font_b,
            fill=_TEXT,
        )
        meta = f"{row.team} · {row.position or '—'}"
        draw.text(
            (name_x, top + 26),
            _fit(draw, meta, font_sm, name_max),
            font=font_sm,
            fill=_DIM,
        )

        vals = {
            "league_titles": row.league_titles,
            "cl_titles": row.cl_titles,
            "individual_awards": row.individual_awards,
            "total_titles": row.total_titles,
        }
        for ci, (key, _lab) in enumerate(cols):
            cx = _col_center(ci)
            val = str(vals[key])
            vw = draw.textbbox((0, 0), val, font=font_num)[2]
            fill = _GOLD if key == "total_titles" else _TEXT
            draw.text((cx - vw // 2, top + 12), val, font=font_num, fill=fill)
        y += row_h

    return _to_png(im.convert("RGB"))


def render_titled_players_global_pages(*, page_size: int = 14) -> list[bytes]:
    rows = titled_players_global(min_total=3)
    if not rows:
        return [
            _render_titled_players_png(
                [],
                title="Титулованные игроки",
                subtitle="Нет игроков с 3+ титулами",
            )
        ]
    page_size = max(1, int(page_size))
    n_pages = max(1, (len(rows) + page_size - 1) // page_size)
    pages: list[bytes] = []
    for p in range(n_pages):
        off = p * page_size
        chunk = rows[off : off + page_size]
        pages.append(
            _render_titled_players_png(
                chunk,
                title="Титулованные игроки",
                subtitle="3+ титула · сортировка по сумме",
                offset=off,
                page_label=f"{p + 1}/{n_pages}",
            )
        )
    return pages


def render_titled_players_club_pages(
    team: str,
    *,
    page_size: int = 20,
) -> list[bytes]:
    rows = titled_players_for_team(team, min_total=1)
    if not rows:
        return [
            _render_titled_players_png(
                [],
                title=f"Титулованные · {team}",
                subtitle="Нет игроков с 1+ командным титулом в клубе",
            )
        ]
    page_size = max(1, int(page_size))
    n_pages = max(1, (len(rows) + page_size - 1) // page_size)
    pages: list[bytes] = []
    for p in range(n_pages):
        off = p * page_size
        chunk = rows[off : off + page_size]
        pages.append(
            _render_titled_players_png(
                chunk,
                title=f"Титулованные · {team}",
                subtitle="1+ командный титул · выиграно в этом клубе",
                offset=off,
                page_label=f"{p + 1}/{n_pages}" if n_pages > 1 else None,
            )
        )
    return pages


def render_titled_players_club_png(team: str) -> bytes:
    """Одна страница (legacy); предпочтительно ``render_titled_players_club_pages``."""
    pages = render_titled_players_club_pages(team, page_size=20)
    return pages[0]

