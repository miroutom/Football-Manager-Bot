# -*- coding: utf-8 -*-
"""
Таблица лиги / ЛЧ / ЧМ — инфографика с эмблемами клубов или флагами наций.
"""
from __future__ import annotations

import logging
import os
import pickle
from typing import Any

try:
    from PIL import Image, ImageDraw
except ImportError as e:
    raise ImportError("Нужен пакет Pillow: pip install pillow") from e

from bot.report_gfx import (
    draw_header_bar,
    paste_row_emblem,
    pick_font,
    png_bytes,
    theme_for_league,
    truncate,
)

logger = logging.getLogger(__name__)

_HEADER_H = 88
_COL_HDR_H = 32
_ROW_H = 44
_CREST = 32
_PAD = 14

# колонки справа от названия
_STAT_KEYS = ("matches", "wins", "draws", "losses", "scored", "missed", "diff", "points")
_STAT_LABELS = ("И", "В", "Н", "П", "ЗМ", "ПМ", "РМ", "О")
_STAT_W = 42
_NAME_LEFT = 78  # после # и crest
_RANK_W = 36

_WC_GROUPS_PER_PAGE = 3
_WC_GROUP_GAP = 18
_WC_GROUP_TITLE_H = 28


def collect_standings_rows(
    league_code: str,
    season_num: int | None = None,
) -> tuple[str, list[dict[str, Any]], str | None]:
    """
    Возвращает (title, rows, note).
    row: name, matches, wins, draws, losses, scored, missed, diff, points
    """
    code = (league_code or "").strip().lower()
    if code in ("wc", "world_cup"):
        # для совместимости: плоский список всех групп подряд
        groups = collect_wc_group_standings(season_num)
        rows: list[dict[str, Any]] = []
        for g in groups.get("groups") or []:
            for r in g.get("rows") or []:
                rows.append(r)
        title = groups.get("title") or "ЧМ"
        return title, rows, groups.get("note")

    from main import LEAGUES
    from teams import get_sorted_teams
    from utils import season_paths

    league = next((x for x in LEAGUES.values() if x["code"] == league_code), None)
    if not league:
        return f"Неизвестная лига: {league_code}", [], None

    note = None
    if season_num is None:
        teams = league["teams"]
        title = league["name"]
        if league_code == "cl":
            from match_results import compute_cl_group_standings_from_journal

            teams = compute_cl_group_standings_from_journal(teams.keys())
            note = "групповой этап · нокаут не входит"
    else:
        from bot.services import ARCHIVE_PICKLE_BY_LEAGUE

        pkl_name = ARCHIVE_PICKLE_BY_LEAGUE.get(league_code)
        if not pkl_name:
            return f"Неизвестная лига: {league_code}", [], None
        base = season_paths.season_archive_directory(season_num)
        pkl_path = os.path.join(base, "pickle", pkl_name)
        if not os.path.isfile(pkl_path):
            return f"Нет архива сезона {season_num}", [], None
        with open(pkl_path, "rb") as f:
            teams = pickle.load(f)
        title = f"{league['name']} · сезон {season_num}"
        if league_code == "cl":
            from match_results import compute_cl_group_standings_from_journal

            jpath = os.path.join(base, "match_results.json")
            if os.path.isfile(jpath):
                teams = compute_cl_group_standings_from_journal(
                    teams.keys(), journal_path=jpath
                )
            note = "групповой этап · нокаут не входит"

    rows = []
    for name, team in get_sorted_teams(teams):
        diff = int(team.difference)
        rows.append(
            {
                "name": str(name),
                "matches": int(team.matches),
                "wins": int(team.wins),
                "draws": int(team.draws),
                "losses": int(team.losses),
                "scored": int(team.scored),
                "missed": int(team.missed),
                "diff": diff,
                "points": int(team.points),
            }
        )
    return title, rows, note


def collect_wc_group_standings(season_num: int | None = None) -> dict[str, Any]:
    """
    Групповые таблицы ЧМ.

    Returns::
      {
        title, note, drawn: bool,
        groups: [{id, title, rows: [...]}, ...]
      }
    """
    from match_results import (
        _norm,
        load_records_and_keys,
        load_records_and_keys_from_path,
    )
    from utils import season_paths
    from utils.wc_tournament import groups_drawn, load_tournament
    from utils.world_cup_format import GROUP_IDS, compute_group_tables

    tour = load_tournament()
    groups_raw = tour.get("groups") or {}
    title = "ЧМ · группы"
    if season_num is not None:
        title = f"ЧМ · группы · сезон {season_num}"

    if not groups_drawn() and not any(groups_raw.get(g) for g in GROUP_IDS):
        return {
            "title": title,
            "note": "жеребьёвка ещё не проведена",
            "drawn": False,
            "groups": [],
        }

    if season_num is None:
        records, _ = load_records_and_keys()
    else:
        base = season_paths.season_archive_directory(season_num)
        jpath = os.path.join(base, "match_results.json")
        if os.path.isfile(jpath):
            records, _ = load_records_and_keys_from_path(jpath)
        else:
            records = []

    results = []
    for m in records:
        if str(m.get("league") or "").strip().lower() not in ("wc", "world_cup"):
            continue
        results.append(
            {
                "home": _norm(m.get("home") or ""),
                "away": _norm(m.get("away") or ""),
                "home_score": m.get("home_score"),
                "away_score": m.get("away_score"),
                "group": m.get("group"),
            }
        )

    # те же имена, что в журнале матчей (_norm = Title)
    groups_norm: dict[str, list[str]] = {}
    for gid in GROUP_IDS:
        teams = [_norm(t) for t in (groups_raw.get(gid) or []) if t]
        groups_norm[gid] = teams

    tables = compute_group_tables(groups_norm, results)
    out_groups: list[dict[str, Any]] = []
    for gid in GROUP_IDS:
        ranked = tables.get(gid) or []
        rows = []
        for r in ranked:
            rows.append(
                {
                    "name": str(r.team),
                    "matches": int(r.played),
                    "wins": int(r.won),
                    "draws": int(r.drawn),
                    "losses": int(r.lost),
                    "scored": int(r.gf),
                    "missed": int(r.ga),
                    "diff": int(r.gd),
                    "points": int(r.points),
                }
            )
        out_groups.append(
            {
                "id": gid,
                "title": f"Группа {gid}",
                "rows": rows,
            }
        )
    return {
        "title": title,
        "note": None,
        "drawn": True,
        "groups": out_groups,
    }


def render_standings_infographic_png_bytes(
    league_code: str,
    season_num: int | None = None,
    *,
    emblem_mode: str | None = None,
) -> list[bytes]:
    code = (league_code or "").strip().lower()
    if code in ("wc", "world_cup"):
        return render_wc_group_standings_png_pages(season_num)

    title, rows, note = collect_standings_rows(league_code, season_num)
    theme = theme_for_league(league_code)
    mode = (
        emblem_mode
        or ("nation" if code in ("wc", "world_cup") else "club")
    )
    mode = mode.strip().lower()
    return _render_single_table_png(
        title=title,
        rows=rows,
        note=note,
        theme=theme,
        mode=mode,
    )


def render_wc_group_standings_png_pages(
    season_num: int | None = None,
) -> list[bytes]:
    """Несколько PNG: по ``_WC_GROUPS_PER_PAGE`` групп на странице, флаги наций."""
    data = collect_wc_group_standings(season_num)
    theme = theme_for_league("wc")
    groups = data.get("groups") or []
    title = data.get("title") or "ЧМ"
    note = data.get("note")

    if not groups:
        im = Image.new("RGB", (640, 160), theme.bg)
        draw = ImageDraw.Draw(im)
        draw_header_bar(
            draw,
            theme=theme,
            width=640,
            height=_HEADER_H,
            title=title,
            subtitle=note,
        )
        draw.text((24, 110), "Нет групп", fill=theme.text_dim, font=pick_font(18))
        return [png_bytes(im)]

    pages: list[bytes] = []
    n = len(groups)
    for page_i in range(0, n, _WC_GROUPS_PER_PAGE):
        chunk = groups[page_i : page_i + _WC_GROUPS_PER_PAGE]
        page_no = page_i // _WC_GROUPS_PER_PAGE + 1
        page_count = (n + _WC_GROUPS_PER_PAGE - 1) // _WC_GROUPS_PER_PAGE
        # номер страницы — только если страниц несколько
        sub = f"стр. {page_no}/{page_count}" if page_count > 1 else None
        pages.append(
            _render_wc_groups_page(
                title=title,
                subtitle=sub,
                groups=chunk,
                theme=theme,
            )
        )
    return pages


def _render_wc_groups_page(
    *,
    title: str,
    subtitle: str | None,
    groups: list[dict[str, Any]],
    theme,
) -> bytes:
    n_stats = len(_STAT_LABELS)
    name_col_w = 200
    canvas_w = _RANK_W + 12 + _CREST + 12 + name_col_w + n_stats * _STAT_W + _PAD * 2

    body_h = 0
    for g in groups:
        nrows = max(1, len(g.get("rows") or []))
        body_h += _WC_GROUP_TITLE_H + _COL_HDR_H + nrows * _ROW_H + _WC_GROUP_GAP

    h = _HEADER_H + body_h + 8
    im = Image.new("RGB", (canvas_w, h), theme.bg)
    draw = ImageDraw.Draw(im)
    draw_header_bar(
        draw,
        theme=theme,
        width=canvas_w,
        height=_HEADER_H,
        title=title,
        subtitle=subtitle,
    )

    y = _HEADER_H + 4
    light = not _dark_bg(theme)
    for g in groups:
        y = _draw_group_block(
            im,
            draw,
            theme=theme,
            canvas_w=canvas_w,
            y0=y,
            group_title=str(g.get("title") or g.get("id") or ""),
            rows=list(g.get("rows") or []),
            name_col_w=name_col_w,
            mode="nation",
            light=light,
        )
        y += _WC_GROUP_GAP
    return png_bytes(im)


def _draw_group_block(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    theme,
    canvas_w: int,
    y0: int,
    group_title: str,
    rows: list[dict[str, Any]],
    name_col_w: int,
    mode: str,
    light: bool,
) -> int:
    """Рисует заголовок группы + таблицу; возвращает y после блока."""
    title_font = pick_font(16, bold=True)
    hdr_font = pick_font(12, bold=True)
    name_font = pick_font(18, bold=True)
    val_font = pick_font(17, bold=True)
    rank_font = pick_font(14, bold=True)
    crest_font = pick_font(10, bold=True)

    draw.text(
        (_PAD, y0 + _WC_GROUP_TITLE_H // 2),
        group_title,
        fill=theme.highlight,
        font=title_font,
        anchor="lm",
    )
    y = y0 + _WC_GROUP_TITLE_H

    hdr_y0 = y
    hdr_y1 = y + _COL_HDR_H
    draw.rectangle(
        [0, hdr_y0, canvas_w, hdr_y1],
        fill=theme.row_b if not _dark_bg(theme) else theme.row_a,
    )
    name_x = _RANK_W + 8 + _CREST + 10
    stat_left = name_x + name_col_w
    fill_hdr = theme.text_dim
    draw.text(
        (name_x, (hdr_y0 + hdr_y1) // 2),
        "СБОРНАЯ",
        fill=fill_hdr,
        font=hdr_font,
        anchor="lm",
    )
    for i, lab in enumerate(_STAT_LABELS):
        cx = stat_left + i * _STAT_W + _STAT_W // 2
        col_fill = theme.highlight if lab == "О" else fill_hdr
        draw.text(
            (cx, (hdr_y0 + hdr_y1) // 2),
            lab,
            fill=col_fill,
            font=hdr_font,
            anchor="mm",
        )
    y = hdr_y1

    if not rows:
        draw.rectangle([0, y, canvas_w, y + _ROW_H], fill=theme.row_a)
        draw.text(
            (name_x, y + _ROW_H // 2),
            "—",
            fill=theme.text_dim,
            font=name_font,
            anchor="lm",
        )
        return y + _ROW_H

    for i, row in enumerate(rows):
        y0r = y + i * _ROW_H
        y1r = y0r + _ROW_H
        bg = theme.row_a if i % 2 == 0 else theme.row_b
        draw.rectangle([0, y0r, canvas_w, y1r], fill=bg)
        draw.rectangle([0, y0r, 4, y1r], fill=theme.accent)
        cy = y0r + _ROW_H // 2
        draw.text(
            (_RANK_W // 2 + 4, cy),
            str(i + 1),
            fill=theme.text_dim,
            font=rank_font,
            anchor="mm",
        )
        crest_cx = _RANK_W + 8 + _CREST // 2
        paste_row_emblem(
            im,
            draw,
            label=row["name"],
            cx=crest_cx,
            cy=cy,
            size=_CREST,
            mode=mode,
            crest_font=crest_font,
            light_placeholder=light,
        )
        nm = truncate(draw, str(row["name"]), name_font, name_col_w - 8)
        draw.text((name_x, cy), nm, fill=theme.text, font=name_font, anchor="lm")
        for si, key in enumerate(_STAT_KEYS):
            cx = stat_left + si * _STAT_W + _STAT_W // 2
            val = row[key]
            if key == "diff":
                text = f"+{val}" if val > 0 else str(val)
            else:
                text = str(val)
            fill = theme.highlight if key == "points" else theme.text
            draw.text((cx, cy), text, fill=fill, font=val_font, anchor="mm")
    return y + len(rows) * _ROW_H


def _render_single_table_png(
    *,
    title: str,
    rows: list[dict[str, Any]],
    note: str | None,
    theme,
    mode: str,
) -> list[bytes]:
    if not rows:
        im = Image.new("RGB", (640, 160), theme.bg)
        draw = ImageDraw.Draw(im)
        draw_header_bar(
            draw, theme=theme, width=640, height=_HEADER_H, title=title or "Таблица", subtitle=note
        )
        draw.text((24, 110), "Нет данных", fill=theme.text_dim, font=pick_font(18))
        return [png_bytes(im)]

    n_stats = len(_STAT_LABELS)
    name_col_w = 200
    canvas_w = _RANK_W + 12 + _CREST + 12 + name_col_w + n_stats * _STAT_W + _PAD * 2

    h = _HEADER_H + _COL_HDR_H + len(rows) * _ROW_H + 12
    im = Image.new("RGB", (canvas_w, h), theme.bg)
    draw = ImageDraw.Draw(im)

    # Без служебных «архив / текущий / флаги» — только содержательная note (напр. ЛЧ)
    draw_header_bar(
        draw,
        theme=theme,
        width=canvas_w,
        height=_HEADER_H,
        title=title,
        subtitle=note,
    )

    hdr_y0 = _HEADER_H
    hdr_y1 = _HEADER_H + _COL_HDR_H
    draw.rectangle([0, hdr_y0, canvas_w, hdr_y1], fill=theme.row_b if not _dark_bg(theme) else theme.row_a)
    hdr_font = pick_font(12, bold=True)
    name_font = pick_font(18, bold=True)
    val_font = pick_font(17, bold=True)
    rank_font = pick_font(14, bold=True)
    crest_font = pick_font(10, bold=True)

    name_x = _RANK_W + 8 + _CREST + 10
    stat_left = name_x + name_col_w
    fill_hdr = theme.text_dim
    col_label = "СБОРНАЯ" if mode in ("nation", "flag", "wc", "national") else "КОМАНДА"
    draw.text((name_x, (hdr_y0 + hdr_y1) // 2), col_label, fill=fill_hdr, font=hdr_font, anchor="lm")
    for i, lab in enumerate(_STAT_LABELS):
        cx = stat_left + i * _STAT_W + _STAT_W // 2
        col_fill = theme.highlight if lab == "О" else fill_hdr
        draw.text((cx, (hdr_y0 + hdr_y1) // 2), lab, fill=col_fill, font=hdr_font, anchor="mm")

    light = not _dark_bg(theme)
    for i, row in enumerate(rows):
        y0 = hdr_y1 + i * _ROW_H
        y1 = y0 + _ROW_H
        bg = theme.row_a if i % 2 == 0 else theme.row_b
        draw.rectangle([0, y0, canvas_w, y1], fill=bg)
        draw.rectangle([0, y0, 4, y1], fill=theme.accent)

        cy = y0 + _ROW_H // 2
        draw.text(
            (_RANK_W // 2 + 4, cy),
            str(i + 1),
            fill=theme.text_dim,
            font=rank_font,
            anchor="mm",
        )
        crest_cx = _RANK_W + 8 + _CREST // 2
        paste_row_emblem(
            im,
            draw,
            label=row["name"],
            cx=crest_cx,
            cy=cy,
            size=_CREST,
            mode=mode,
            crest_font=crest_font,
            light_placeholder=light,
        )
        nm = truncate(draw, str(row["name"]), name_font, name_col_w - 8)
        draw.text((name_x, cy), nm, fill=theme.text, font=name_font, anchor="lm")

        for si, key in enumerate(_STAT_KEYS):
            cx = stat_left + si * _STAT_W + _STAT_W // 2
            val = row[key]
            if key == "diff":
                text = f"+{val}" if val > 0 else str(val)
            else:
                text = str(val)
            fill = theme.highlight if key == "points" else theme.text
            draw.text((cx, cy), text, fill=fill, font=val_font, anchor="mm")

    return [png_bytes(im)]


def _dark_bg(theme) -> bool:
    rgb = theme.bg
    return (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) < 140
