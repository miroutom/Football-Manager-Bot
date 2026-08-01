# -*- coding: utf-8 -*-
"""
Инфографики операционных отчётов: статус, календарь, журнал, пропуски.
"""
from __future__ import annotations

import logging
from typing import Any

try:
    from PIL import Image, ImageDraw
except ImportError as e:
    raise ImportError("Нужен пакет Pillow: pip install pillow") from e

from bot.report_gfx import (
    LeagueTheme,
    draw_header_bar,
    paste_crest,
    pick_font,
    png_bytes,
    theme_for_league,
    truncate,
)

logger = logging.getLogger(__name__)

_HEADER_H = 88
_ROW_H = 48
_ROWS_PAGE = 16
_CREST = 28

_STATUS_THEME = LeagueTheme(
    "status", "Статус",
    (245, 247, 252), (22, 48, 92), (255, 255, 255), (236, 240, 248),
    (64, 140, 220), (20, 28, 40), (100, 112, 132), (64, 140, 220),
)
_SCHED_THEME = LeagueTheme(
    "sch", "Календарь",
    (242, 248, 246), (16, 72, 58), (255, 255, 255), (230, 242, 236),
    (40, 160, 120), (18, 32, 28), (90, 120, 110), (40, 160, 120),
)
_JOURNAL_THEME = LeagueTheme(
    "jrnl", "Журнал",
    (18, 24, 36), (28, 40, 62), (24, 34, 52), (30, 42, 64),
    (120, 170, 255), (240, 244, 250), (150, 165, 190), (255, 210, 90),
)
_SKIP_THEME = LeagueTheme(
    "skip", "Пропуски",
    (252, 246, 236), (120, 72, 20), (255, 252, 246), (248, 236, 214),
    (220, 140, 40), (40, 28, 16), (130, 100, 70), (220, 140, 40),
)

_LEAGUE_SHORT = {
    "rpl": "РПЛ",
    "eng": "АПЛ",
    "esp": "ЛаЛ",
    "ita": "СеА",
    "ger": "Бун",
    "cl": "ЛЧ",
    "wc": "ЧМ",
}


def render_status_infographic_png_bytes() -> list[bytes]:
    from main import LEAGUES, count_remaining_in_schedule, load_or_generate_mixed_schedule
    from match_results import count_journal_by_entry_type, count_recorded_matches
    from skipped_matches import load_skipped_matches
    from utils.season_paths import get_active_season

    mixed = load_or_generate_mixed_schedule()
    remaining = count_remaining_in_schedule(mixed)
    total = sum(len(d["matches"]) for d in mixed)
    journal_n = count_recorded_matches()
    play_n, sim_n = count_journal_by_entry_type()
    skipped_n = len(load_skipped_matches())
    season = get_active_season()

    theme = _STATUS_THEME
    w, h = 720, 480
    im = Image.new("RGB", (w, h), theme.bg)
    draw = ImageDraw.Draw(im)
    draw_header_bar(
        draw,
        theme=theme,
        width=w,
        height=_HEADER_H,
        title=f"СТАТУС · сезон {season}",
        subtitle=None,
    )

    # KPI cards — 2 ряда по 3
    kpis = [
        ("В календаре", str(total), False),
        ("Осталось", str(remaining), True),
        ("Пропуски", str(skipped_n), False),
        ("Игра", str(play_n), False),
        ("Симуляция", str(sim_n), False),
        ("В журнале", str(journal_n), False),
    ]
    card_w = 210
    gap = 18
    x0 = 24
    y0 = _HEADER_H + 20
    title_f = pick_font(13)
    val_f = pick_font(28, bold=True)
    for i, (lab, val, accent_val) in enumerate(kpis):
        col = i % 3
        row = i // 3
        x = x0 + col * (card_w + gap)
        y = y0 + row * 92
        draw.rounded_rectangle(
            [x, y, x + card_w, y + 78],
            radius=10,
            fill=theme.row_a,
            outline=theme.accent,
            width=2,
        )
        draw.text((x + 12, y + 12), lab, fill=theme.text_dim, font=title_f)
        fill = theme.accent if accent_val else theme.text
        draw.text((x + 12, y + 36), val, fill=fill, font=val_f)

    # league played
    y = y0 + 196
    draw.text((24, y), "Сыграно по лигам (таблицы)", fill=theme.text, font=pick_font(16, bold=True))
    y += 28
    name_f = pick_font(15)
    for key, league in LEAGUES.items():
        teams = league["teams"]
        played = sum(t.matches for t in teams.values()) // 2
        code = league.get("code") or key
        th = theme_for_league(str(code))
        draw.rectangle([24, y, 28, y + 22], fill=th.accent)
        draw.text((36, y + 2), f"{league['name']}", fill=theme.text, font=name_f)
        draw.text((520, y + 2), str(played), fill=theme.highlight, font=pick_font(16, bold=True))
        y += 28

    return [png_bytes(im)]


def _match_list_theme(kind: str) -> LeagueTheme:
    if kind == "journal":
        return _JOURNAL_THEME
    if kind == "skip":
        return _SKIP_THEME
    return _SCHED_THEME


def render_match_list_png_pages(
    *,
    title: str,
    subtitle: str | None,
    rows: list[dict[str, Any]],
    kind: str = "schedule",
    rows_per_page: int = _ROWS_PAGE,
) -> list[bytes]:
    """
    row keys: home, away, league, day|round, score (optional), meta (optional), status (optional)
    """
    theme = _match_list_theme(kind)
    if not rows:
        im = Image.new("RGB", (780, 160), theme.bg)
        draw = ImageDraw.Draw(im)
        draw_header_bar(
            draw, theme=theme, width=780, height=_HEADER_H, title=title, subtitle=subtitle
        )
        draw.text((24, 110), "Нет матчей", fill=theme.text_dim, font=pick_font(18))
        return [png_bytes(im)]

    canvas_w = 820
    pages: list[bytes] = []
    total_pages = (len(rows) + rows_per_page - 1) // rows_per_page
    for page_i in range(total_pages):
        chunk = rows[page_i * rows_per_page : (page_i + 1) * rows_per_page]
        h = _HEADER_H + len(chunk) * _ROW_H + 16
        im = Image.new("RGB", (canvas_w, h), theme.bg)
        draw = ImageDraw.Draw(im)
        sub = subtitle or ""
        if total_pages > 1:
            sub = (sub + " · " if sub else "") + f"{page_i + 1}/{total_pages}"
        draw_header_bar(
            draw, theme=theme, width=canvas_w, height=_HEADER_H, title=title, subtitle=sub or None
        )
        name_f = pick_font(15, bold=True)
        meta_f = pick_font(12)
        score_f = pick_font(16, bold=True)
        crest_f = pick_font(9, bold=True)
        for i, row in enumerate(chunk):
            y0 = _HEADER_H + i * _ROW_H
            y1 = y0 + _ROW_H
            bg = theme.row_a if i % 2 == 0 else theme.row_b
            draw.rectangle([0, y0, canvas_w, y1], fill=bg)
            cy = y0 + _ROW_H // 2
            lg = str(row.get("league") or "").lower()
            lg_lab = _LEAGUE_SHORT.get(lg, lg.upper() or "—")
            day = row.get("day") if row.get("day") is not None else row.get("round")
            left_meta = f"{lg_lab}"
            if day is not None:
                left_meta += f" · м{day}"
            meta = str(row.get("meta") or "").strip()
            if meta:
                # короткие подписи — иначе «Симуляция» обрезается
                if meta == "Симуляция":
                    meta = "сим"
                elif meta == "Игра":
                    meta = "игра"
                left_meta += f" · {meta}"
            draw.text((12, cy), left_meta, fill=theme.text_dim, font=meta_f, anchor="lm")

            home = str(row.get("home") or "?")
            away = str(row.get("away") or "?")
            hx = 130
            paste_crest(im, draw, team=home, cx=hx, cy=cy, size=_CREST, crest_font=crest_f)
            hn = truncate(draw, home, name_f, 150)
            draw.text((hx + _CREST // 2 + 8, cy), hn, fill=theme.text, font=name_f, anchor="lm")

            score = row.get("score")
            mid_x = canvas_w // 2 + 20
            if score:
                draw.text((mid_x, cy), str(score), fill=theme.highlight, font=score_f, anchor="mm")
            else:
                draw.text((mid_x, cy), "—", fill=theme.text_dim, font=score_f, anchor="mm")

            ax = canvas_w - 40
            paste_crest(im, draw, team=away, cx=ax, cy=cy, size=_CREST, crest_font=crest_f)
            an = truncate(draw, away, name_f, 150)
            draw.text((ax - _CREST // 2 - 8, cy), an, fill=theme.text, font=name_f, anchor="rm")

            if row.get("status"):
                draw.text(
                    (canvas_w - 8, y0 + 4),
                    str(row["status"]),
                    fill=theme.accent,
                    font=meta_f,
                    anchor="rt",
                )
        pages.append(png_bytes(im))
    return pages


def collect_schedule_rows(
    league_filter: str | None,
    match_filter_code: str,
    session_kind: str | None = None,
) -> tuple[str, str, list[dict[str, Any]]]:
    """Для remaining/all — слоты календаря; для played — журнал."""
    from player_stats import LEAGUE_NAMES

    if match_filter_code == "played":
        from match_results import load_records_and_keys

        records, _ = load_records_and_keys()
        rows: list[dict[str, Any]] = []
        for r in records:
            lg = str(r.get("league") or "")
            if league_filter and lg != league_filter:
                continue
            hs, aws = r.get("home_score"), r.get("away_score")
            score = f"{hs}:{aws}" if hs is not None and aws is not None else None
            meta = ""
            if lg == "cl" and r.get("cl_phase"):
                meta = str(r.get("cl_phase"))
            rows.append(
                {
                    "home": r.get("home"),
                    "away": r.get("away"),
                    "league": lg,
                    "day": r.get("day"),
                    "score": score,
                    "meta": meta,
                }
            )
        # last 200
        rows = rows[-200:]
        title = "СЫГРАННЫЕ"
        sub = LEAGUE_NAMES.get(league_filter or "", "все лиги") if league_filter else "все лиги"
        return title, sub, rows

    from main import list_remaining_schedule_matches, load_or_generate_mixed_schedule
    from match_results import is_match_played, cl_phase_from_mixed_schedule_line
    from config.leagues_config import manager_session_label

    mixed = load_or_generate_mixed_schedule()
    sk = session_kind if session_kind in ("sim", "game") else None

    if match_filter_code == "remaining":
        slots = list_remaining_schedule_matches(
            mixed, league_filter=league_filter, session_kind=sk
        )
        rows = []
        for s in slots:
            lab = manager_session_label(s["home"], s["away"])
            rows.append(
                {
                    "home": s["home"],
                    "away": s["away"],
                    "league": s["league_code"],
                    "day": s["day"],
                    "meta": lab or "",
                    "status": "",
                }
            )
        title = "ОСТАЛОСЬ"
    else:
        # all slots
        rows = []
        from main import get_teams_by_league

        for day_data in mixed:
            day_num = day_data["day"]
            for match_str in day_data["matches"]:
                parts = match_str.split(";")
                if len(parts) < 3:
                    continue
                home, away, league_code = parts[0], parts[1], parts[2]
                if league_filter and league_code != league_filter:
                    continue
                cl_ph = (
                    cl_phase_from_mixed_schedule_line(match_str, day=day_num)
                    if league_code == "cl"
                    else None
                )
                teams = get_teams_by_league(league_code)
                if not teams:
                    continue
                played = is_match_played(home, away, league_code, cl_phase=cl_ph)
                lab = manager_session_label(home, away)
                if sk == "sim" and lab != "Симуляция":
                    continue
                if sk == "game" and lab != "Игра":
                    continue
                meta = lab or ""
                if league_code == "cl" and cl_ph:
                    meta = (meta + " · " if meta else "") + str(cl_ph)
                rows.append(
                    {
                        "home": home,
                        "away": away,
                        "league": league_code,
                        "day": day_num,
                        "meta": meta,
                        "status": "✓" if played else "",
                        "score": None,
                    }
                )
        title = "КАЛЕНДАРЬ"

    sub = LEAGUE_NAMES.get(league_filter or "", "все лиги") if league_filter else "все лиги"
    if sk == "sim":
        sub += " · сим"
    elif sk == "game":
        sub += " · игра"
    return title, sub, rows


def collect_journal_rows(limit: int = 120) -> tuple[str, str, list[dict[str, Any]]]:
    from match_results import load_records_and_keys

    records, _ = load_records_and_keys()
    tail = records[-limit:] if limit else records
    rows = []
    for r in tail:
        lg = str(r.get("league") or "")
        hs, aws = r.get("home_score"), r.get("away_score")
        score = f"{hs}:{aws}" if hs is not None and aws is not None else None
        meta = ""
        if lg == "cl" and r.get("cl_phase"):
            meta = str(r.get("cl_phase"))
        rows.append(
            {
                "home": r.get("home"),
                "away": r.get("away"),
                "league": lg,
                "day": r.get("day"),
                "score": score,
                "meta": meta,
            }
        )
    # show newest first visually
    rows = list(reversed(rows))
    return "ЖУРНАЛ", f"последние {len(rows)} из {len(records)}", rows


def collect_skipped_rows() -> tuple[str, str, list[dict[str, Any]]]:
    from skipped_matches import load_skipped_matches

    matches = load_skipped_matches()
    rows = []
    for m in matches:
        meta = ""
        if m.get("tournament") == "cl" and m.get("cl_phase"):
            meta = str(m.get("cl_phase"))
        rows.append(
            {
                "home": m.get("home"),
                "away": m.get("away"),
                "league": m.get("tournament"),
                "round": m.get("round"),
                "meta": meta,
                "status": "skip",
            }
        )
    rows.sort(
        key=lambda r: (
            str(r.get("league") or ""),
            int(r.get("round") or 0),
            str(r.get("home") or ""),
        )
    )
    return "ПРОПУЩЕННЫЕ", f"{len(rows)} матч(ей)", rows


def render_schedule_infographic(
    league_filter: str | None,
    match_filter_code: str,
    session_kind: str | None = None,
) -> list[bytes]:
    title, sub, rows = collect_schedule_rows(league_filter, match_filter_code, session_kind)
    kind = "journal" if match_filter_code == "played" else "schedule"
    return render_match_list_png_pages(title=title, subtitle=sub, rows=rows, kind=kind)


def render_journal_infographic(limit: int = 120) -> list[bytes]:
    title, sub, rows = collect_journal_rows(limit)
    return render_match_list_png_pages(title=title, subtitle=sub, rows=rows, kind="journal")


def render_skipped_infographic() -> list[bytes]:
    title, sub, rows = collect_skipped_rows()
    return render_match_list_png_pages(title=title, subtitle=sub, rows=rows, kind="skip")


def render_next_match_infographic_png_bytes() -> list[bytes]:
    """Карточка следующего матча по календарю."""
    from main import find_next_match_in_schedule, load_or_generate_mixed_schedule
    from config.leagues_config import manager_session_label
    from player_stats import LEAGUE_NAMES

    sch = load_or_generate_mixed_schedule()
    day, match_str, home, away, league_code = find_next_match_in_schedule(sch)
    theme = theme_for_league(league_code) if league_code else _SCHED_THEME
    w, h = 720, 280
    im = Image.new("RGB", (w, h), theme.bg)
    draw = ImageDraw.Draw(im)
    if not home:
        draw_header_bar(
            draw, theme=theme, width=w, height=_HEADER_H, title="СЛЕДУЮЩИЙ МАТЧ", subtitle="календарь пуст"
        )
        draw.text((24, 140), "Нет несыгранных матчей", fill=theme.text_dim, font=pick_font(18))
        return [png_bytes(im)]

    lg = LEAGUE_NAMES.get(league_code or "", league_code or "")
    lab = manager_session_label(home, away) or ""
    sub = f"{lg} · месяц {day}" + (f" · {lab}" if lab else "")
    draw_header_bar(
        draw, theme=theme, width=w, height=_HEADER_H, title="СЛЕДУЮЩИЙ МАТЧ", subtitle=sub
    )
    cy = 180
    crest_f = pick_font(14, bold=True)
    name_f = pick_font(22, bold=True)
    paste_crest(im, draw, team=home, cx=160, cy=cy, size=56, crest_font=crest_f)
    paste_crest(im, draw, team=away, cx=560, cy=cy, size=56, crest_font=crest_f)
    draw.text((160, cy + 48), truncate(draw, home, name_f, 200), fill=theme.text, font=name_f, anchor="mt")
    draw.text((560, cy + 48), truncate(draw, away, name_f, 200), fill=theme.text, font=name_f, anchor="mt")
    draw.text((w // 2, cy), "VS", fill=theme.accent, font=pick_font(28, bold=True), anchor="mm")
    return [png_bytes(im)]


