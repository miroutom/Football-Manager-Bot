# -*- coding: utf-8 -*-
"""
Списки игроков с эмблемами клубов: топы сезона, стата клуба, травмы.
"""
from __future__ import annotations

import logging
from typing import Any, Sequence

try:
    from PIL import Image, ImageDraw
except ImportError as e:
    raise ImportError("Нужен пакет Pillow: pip install pillow") from e

from bot.report_gfx import (
    INJURY_THEME,
    PLAYER_BOARD_DARK,
    LeagueTheme,
    display_player_name,
    draw_header_bar,
    paste_crest,
    pick_font,
    png_bytes,
    theme_for_league,
    truncate,
)

logger = logging.getLogger(__name__)

_HEADER_H = 88
_COL_H = 28
_ROW_H = 44
_CREST = 32
_ROWS_PER_PAGE = 22
_RANK_W = 34
_NAME_LEFT = 78
_STAT_W = 56


def _collect_season_top_rows(
    league_code: str,
    *,
    metric: str,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """metric: goals | assists | ga"""
    from player_stats import LEAGUE_TEAMS, get_session
    from data.defender import Defender
    from data.forward import Forward
    from data.midfielder import Midfielder
    from bot.services import tournament_db_for_league

    tournament = tournament_db_for_league(league_code)
    session = get_session(tournament)
    filter_teams = None
    if league_code and league_code != "cl" and league_code in LEAGUE_TEAMS:
        filter_teams = [t.lower() for t in LEAGUE_TEAMS[league_code]]
    elif league_code == "cl":
        import teams as teams_mod

        filter_teams = [t.lower() for t in teams_mod.teams_champ_league.keys()]

    rows: list[dict[str, Any]] = []
    for Cls in (Forward, Midfielder, Defender):
        try:
            for p in session.query(Cls).all():
                if filter_teams and (p.team or "").lower() not in filter_teams:
                    continue
                g = int(p.goals or 0)
                a = int(p.assists or 0)
                ga = int(getattr(p, "ga", None) or (g + a))
                if metric == "goals" and g <= 0:
                    continue
                if metric == "assists" and a <= 0:
                    continue
                if metric == "ga" and ga <= 0:
                    continue
                rows.append(
                    {
                        "name": p.name,
                        "team": p.team,
                        "position": p.position,
                        "overall": int(getattr(p, "overall", 0) or 0),
                        "matches": int(p.matches or 0),
                        "goals": g,
                        "assists": a,
                        "ga": ga,
                    }
                )
        except Exception:
            logger.exception("season top collect")
    if metric == "assists":
        rows.sort(key=lambda x: (-x["assists"], -x["goals"], str(x["name"]).casefold()))
    elif metric == "ga":
        rows.sort(key=lambda x: (-x["ga"], -x["goals"], str(x["name"]).casefold()))
    else:
        rows.sort(key=lambda x: (-x["goals"], -x["assists"], str(x["name"]).casefold()))
    return rows[:limit]


def collect_club_scorer_rows(
    team: str,
    *,
    tournament: str = "league",
    session=None,
) -> list[dict[str, Any]]:
    from data.defender import Defender
    from data.forward import Forward
    from data.midfielder import Midfielder
    from player_stats import _team_name_as_in_db, get_session
    from utils.player_names import player_display_name

    team_db = _team_name_as_in_db(team)
    own_session = session is None
    if own_session:
        session = get_session(tournament)
    rows: list[dict[str, Any]] = []
    try:
        for Cls in (Forward, Midfielder, Defender):
            for p in session.query(Cls).filter_by(team=team_db).all():
                g = int(p.goals or 0)
                a = int(p.assists or 0)
                if g <= 0 and a <= 0:
                    continue
                rows.append(
                    {
                        "name": player_display_name(p),
                        "team": team_db,
                        "position": p.position,
                        "overall": int(getattr(p, "overall", 0) or 0),
                        "matches": int(p.matches or 0),
                        "goals": g,
                        "assists": a,
                        "ga": int(getattr(p, "ga", None) or (g + a)),
                    }
                )
    finally:
        pass
    rows.sort(key=lambda x: (-x["ga"], -x["goals"], str(x["name"]).casefold()))
    return rows


def render_player_board_pages(
    *,
    title: str,
    subtitle: str | None,
    rows: Sequence[dict[str, Any]],
    columns: Sequence[tuple[str, str]],
    theme: LeagueTheme | None = None,
    highlight_key: str | None = None,
    show_team_crest: bool = True,
    rows_per_page: int = _ROWS_PER_PAGE,
) -> list[bytes]:
    """
    columns: list of (key, label), e.g. [("goals","Г"), ("assists","А"), ("ga","Г+А")]
    """
    theme = theme or PLAYER_BOARD_DARK
    if not rows:
        im = Image.new("RGB", (720, 160), theme.bg)
        draw = ImageDraw.Draw(im)
        draw_header_bar(
            draw, theme=theme, width=720, height=_HEADER_H, title=title, subtitle=subtitle
        )
        draw.text((24, 110), "Нет данных", fill=theme.text_dim, font=pick_font(18))
        return [png_bytes(im)]

    n_cols = len(columns)
    name_w = 210
    canvas_w = _NAME_LEFT + name_w + 70 + n_cols * _STAT_W + 16
    pages: list[bytes] = []
    total_pages = (len(rows) + rows_per_page - 1) // rows_per_page

    for page_i in range(total_pages):
        chunk = rows[page_i * rows_per_page : (page_i + 1) * rows_per_page]
        h = _HEADER_H + _COL_H + len(chunk) * _ROW_H + 10
        im = Image.new("RGB", (canvas_w, h), theme.bg)
        draw = ImageDraw.Draw(im)
        sub = subtitle or ""
        if total_pages > 1:
            sub = (sub + " · " if sub else "") + f"стр. {page_i + 1}/{total_pages}"
        draw_header_bar(
            draw, theme=theme, width=canvas_w, height=_HEADER_H, title=title, subtitle=sub or None
        )

        hdr_y0 = _HEADER_H
        hdr_y1 = _HEADER_H + _COL_H
        draw.rectangle([0, hdr_y0, canvas_w, hdr_y1], fill=theme.header)
        hdr_font = pick_font(11, bold=True)
        name_font = pick_font(17, bold=True)
        meta_font = pick_font(13)
        val_font = pick_font(17, bold=True)
        rank_font = pick_font(13, bold=True)
        crest_font = pick_font(10, bold=True)

        draw.text(
            (_NAME_LEFT, (hdr_y0 + hdr_y1) // 2),
            "ИГРОК",
            fill=theme.text_dim,
            font=hdr_font,
            anchor="lm",
        )
        stat_left = _NAME_LEFT + name_w + 8
        for i, (_, lab) in enumerate(columns):
            cx = stat_left + i * _STAT_W + _STAT_W // 2
            fill = theme.highlight if highlight_key and columns[i][0] == highlight_key else theme.text_dim
            draw.text((cx, (hdr_y0 + hdr_y1) // 2), lab, fill=fill, font=hdr_font, anchor="mm")

        for i, row in enumerate(chunk):
            y0 = hdr_y1 + i * _ROW_H
            y1 = y0 + _ROW_H
            bg = theme.row_a if i % 2 == 0 else theme.row_b
            draw.rectangle([0, y0, canvas_w, y1], fill=bg)
            cy = y0 + _ROW_H // 2
            rank = page_i * rows_per_page + i + 1
            draw.text(
                (_RANK_W // 2, cy),
                str(rank),
                fill=theme.text_dim,
                font=rank_font,
                anchor="mm",
            )
            team = str(row.get("team") or "")
            if show_team_crest and team:
                paste_crest(
                    im,
                    draw,
                    team=team,
                    cx=_RANK_W + 6 + _CREST // 2,
                    cy=cy,
                    size=_CREST,
                    crest_font=crest_font,
                )
            name = display_player_name(str(row.get("name") or ""))
            pos = str(row.get("position") or row.get("pos") or "").strip().upper() or "—"
            meta = f"  {pos}"
            meta_w = int(draw.textlength(meta, font=meta_font))
            max_name = max(80, name_w - meta_w - 4)
            name_d = truncate(draw, name, name_font, max_name)
            draw.text((_NAME_LEFT, cy), name_d, fill=theme.text, font=name_font, anchor="lm")
            nx = _NAME_LEFT + int(draw.textlength(name_d, font=name_font))
            draw.text((nx, cy), meta, fill=theme.text_dim, font=meta_font, anchor="lm")

            for si, (key, _) in enumerate(columns):
                cx = stat_left + si * _STAT_W + _STAT_W // 2
                val = row.get(key, 0)
                fill = theme.highlight if highlight_key == key else theme.text
                draw.text((cx, cy), str(val), fill=fill, font=val_font, anchor="mm")

        pages.append(png_bytes(im))
    return pages


def render_season_top_png_pages(
    league_code: str,
    *,
    metric: str,
    limit: int = 25,
) -> list[bytes]:
    theme = theme_for_league(league_code)
    # топы — тёмная доска с акцентом лиги в header
    board = LeagueTheme(
        theme.code,
        theme.title,
        PLAYER_BOARD_DARK.bg,
        theme.header if theme.code != "eng" else (40, 10, 50),
        PLAYER_BOARD_DARK.row_a,
        PLAYER_BOARD_DARK.row_b,
        theme.accent,
        PLAYER_BOARD_DARK.text,
        PLAYER_BOARD_DARK.text_dim,
        theme.highlight if theme.code == "cl" else PLAYER_BOARD_DARK.highlight,
    )
    titles = {
        "goals": "БОМБАРДИРЫ",
        "assists": "АССИСТЕНТЫ",
        "ga": "ГОЛ + ПАС",
    }
    cols = {
        "goals": [("goals", "Г"), ("assists", "А"), ("ga", "Г+А")],
        "assists": [("assists", "А"), ("goals", "Г"), ("ga", "Г+А")],
        "ga": [("ga", "Г+А"), ("goals", "Г"), ("assists", "А")],
    }
    hl = {"goals": "goals", "assists": "assists", "ga": "ga"}[metric]
    rows = _collect_season_top_rows(league_code, metric=metric, limit=limit)
    return render_player_board_pages(
        title=titles[metric],
        subtitle=theme.title,
        rows=rows,
        columns=cols[metric],
        theme=board,
        highlight_key=hl,
    )


def render_club_scorers_png_pages(
    *,
    team: str,
    title: str,
    rows: Sequence[dict[str, Any]],
    league_code: str | None = None,
) -> list[bytes]:
    theme = theme_for_league(league_code) if league_code else PLAYER_BOARD_DARK
    board = LeagueTheme(
        theme.code,
        theme.title,
        PLAYER_BOARD_DARK.bg,
        theme.header,
        PLAYER_BOARD_DARK.row_a,
        PLAYER_BOARD_DARK.row_b,
        theme.accent,
        PLAYER_BOARD_DARK.text,
        PLAYER_BOARD_DARK.text_dim,
        PLAYER_BOARD_DARK.highlight,
    )
    return render_player_board_pages(
        title=team.upper() if team else "КЛУБ",
        subtitle=title,
        rows=rows,
        columns=[
            ("matches", "И"),
            ("goals", "Г"),
            ("assists", "А"),
            ("ga", "Г+А"),
        ],
        theme=board,
        highlight_key="ga",
        show_team_crest=True,
    )


def render_club_goalscorers_png_for_bot(
    league_code: str,
    team_index: int,
    scope: str,
    *,
    season_mode: str = "cur",
    season_num: int | None = None,
) -> tuple[str, list[bytes]]:
    """
    PNG статы клуба.
    season_mode: cur | life | sn
    Returns (caption_title, png_pages).
    """
    from bot.services import (
        _archived_season_db_path_for_goalscorers,
        _cumulative_db_path_for_goalscorers_scope,
        _goalscorers_session_from_path,
        teams_ordered_for_goalscorers,
        teams_ordered_for_goalscorers_season_archive,
        tournament_for_goalscorers_scope,
    )

    tournament = tournament_for_goalscorers_scope(scope)
    scope_lab = {"league": "лига", "cl": "ЛЧ", "common": "лига+ЛЧ"}.get(tournament, tournament)

    if season_mode == "cur":
        teams = teams_ordered_for_goalscorers(league_code)
        team = teams[team_index]
        rows = collect_club_scorer_rows(team, tournament=tournament)
        title = f"{scope_lab} · текущий сезон"
    elif season_mode == "life":
        import os

        teams = teams_ordered_for_goalscorers(league_code)
        team = teams[team_index]
        p = _cumulative_db_path_for_goalscorers_scope(scope)
        if not os.path.isfile(p):
            return f"Нет БД: {p}", []
        e, S = _goalscorers_session_from_path(p)
        sess = S()
        try:
            rows = collect_club_scorer_rows(team, tournament=tournament, session=sess)
        finally:
            sess.close()
            e.dispose()
        title = f"{scope_lab} · за все время"
    else:
        import os

        sn = int(season_num or 0)
        teams = teams_ordered_for_goalscorers_season_archive(sn, league_code)
        team = teams[team_index]
        p = _archived_season_db_path_for_goalscorers(sn, league_code, scope=tournament)
        if not p or not os.path.isfile(p):
            return f"Нет архива сезона {sn}", []
        e, S = _goalscorers_session_from_path(p)
        sess = S()
        try:
            rows = collect_club_scorer_rows(team, tournament=tournament, session=sess)
        finally:
            sess.close()
            e.dispose()
        title = f"{scope_lab} · сезон {sn}"

    pages = render_club_scorers_png_pages(
        team=team,
        title=title,
        rows=rows,
        league_code=league_code,
    )
    return f"Стата · {team} · {title}", pages


def collect_injury_board_sections() -> dict[str, Any]:
    """Секции для инфографики травм/дисквала (как в ``format_active_injuries_report_text``)."""
    from utils.player_discipline import (
        _get_active_season_or_default,
        _injury_status_label,
        _load,
        _lock,
        get_calendar_month,
    )

    month = get_calendar_month(None)
    season_now = _get_active_season_or_default()
    with _lock:
        st = _load()

    injuries: list[dict[str, Any]] = []
    for inj in st.get("injuries") or []:
        if not isinstance(inj, dict):
            continue
        name = str(inj.get("name") or "?").strip()
        team = str(inj.get("team") or "?").strip()
        kind = (inj.get("type") or "травма").strip() or "травма"
        ofm = inj.get("out_from_month")
        ret = inj.get("return_month")
        st_mark = _injury_status_label(inj, month=month, season_now=season_now)
        if st_mark != "активна":
            continue
        injuries.append(
            {
                "name": name,
                "team": team,
                "position": kind[:12],
                "detail": f"{st_mark} · с{ofm or '?'}→м{ret or '?'}",
                "status": "injury",
            }
        )
    injuries.sort(key=lambda r: (str(r["team"]).casefold(), str(r["name"]).casefold()))

    susp: list[dict[str, Any]] = []
    for row in st.get("suspensions") or []:
        left = int(row.get("matches_left") or 0)
        if left <= 0:
            continue
        from utils.player_discipline import _tournament_label

        lab = _tournament_label(str(row.get("league_code") or ""), str(row.get("scope") or ""))
        susp.append(
            {
                "name": str(row.get("name") or "?"),
                "team": str(row.get("team") or "?"),
                "position": lab,
                "detail": f"ост. {left}",
                "matches_left": left,
                "status": "susp",
            }
        )
    susp.sort(key=lambda r: (str(r["position"]).casefold(), str(r["team"]).casefold()))

    return {
        "month": month,
        "season": season_now,
        "injuries": injuries,
        "suspensions": susp,
    }


def render_injuries_infographic_png_pages() -> list[bytes]:
    """Активные травмы + дисквалы — две секции (могут быть на нескольких страницах)."""
    data = collect_injury_board_sections()
    theme = INJURY_THEME
    pages: list[bytes] = []

    def _section_page(
        title: str,
        subtitle: str,
        rows: list[dict[str, Any]],
        detail_key: str = "detail",
    ) -> bytes:
        canvas_w = 720
        h = _HEADER_H + _COL_H + max(1, len(rows)) * _ROW_H + 12
        im = Image.new("RGB", (canvas_w, h), theme.bg)
        draw = ImageDraw.Draw(im)
        draw_header_bar(
            draw, theme=theme, width=canvas_w, height=_HEADER_H, title=title, subtitle=subtitle
        )
        hdr_y0 = _HEADER_H
        hdr_y1 = _HEADER_H + _COL_H
        draw.rectangle([0, hdr_y0, canvas_w, hdr_y1], fill=theme.header)
        hdr_font = pick_font(11, bold=True)
        name_font = pick_font(17, bold=True)
        meta_font = pick_font(13)
        rank_font = pick_font(13, bold=True)
        crest_font = pick_font(10, bold=True)
        draw.text((_NAME_LEFT, (hdr_y0 + hdr_y1) // 2), "ИГРОК", fill=theme.text_dim, font=hdr_font, anchor="lm")
        draw.text((canvas_w - 16, (hdr_y0 + hdr_y1) // 2), "СТАТУС", fill=theme.text_dim, font=hdr_font, anchor="rm")

        if not rows:
            draw.text(
                (24, hdr_y1 + 16),
                "Пусто",
                fill=theme.text_dim,
                font=pick_font(16),
            )
            return png_bytes(im)

        for i, row in enumerate(rows):
            y0 = hdr_y1 + i * _ROW_H
            y1 = y0 + _ROW_H
            bg = theme.row_a if i % 2 == 0 else theme.row_b
            draw.rectangle([0, y0, canvas_w, y1], fill=bg)
            # accent for injury vs susp
            accent = theme.accent if row.get("status") == "injury" else theme.highlight
            draw.rectangle([0, y0, 4, y1], fill=accent)
            cy = y0 + _ROW_H // 2
            draw.text((_RANK_W // 2, cy), str(i + 1), fill=theme.text_dim, font=rank_font, anchor="mm")
            team = str(row.get("team") or "")
            if team:
                paste_crest(
                    im, draw, team=team, cx=_RANK_W + 6 + _CREST // 2, cy=cy, size=_CREST, crest_font=crest_font
                )
            name = display_player_name(str(row.get("name") or ""))
            pos = str(row.get("position") or "")
            name_d = truncate(draw, name, name_font, 200)
            draw.text((_NAME_LEFT, cy), name_d, fill=theme.text, font=name_font, anchor="lm")
            nx = _NAME_LEFT + int(draw.textlength(name_d, font=name_font))
            if pos:
                draw.text((nx + 6, cy), pos, fill=theme.text_dim, font=meta_font, anchor="lm")
            detail = str(row.get(detail_key) or "")
            draw.text(
                (canvas_w - 16, cy),
                truncate(draw, detail, meta_font, 160),
                fill=theme.highlight if row.get("status") != "injury" else theme.accent,
                font=meta_font,
                anchor="rm",
            )
        return png_bytes(im)

    month = data["month"]
    season = data["season"]
    inj = data["injuries"]
    # paginate injuries
    per = 18
    if not inj:
        pages.append(
            _section_page(
                "ТРАВМЫ",
                f"месяц {month} · сезон {season}",
                [],
            )
        )
    else:
        for pi in range(0, len(inj), per):
            chunk = inj[pi : pi + per]
            pages.append(
                _section_page(
                    "ТРАВМЫ",
                    f"месяц {month} · сезон {season}"
                    + (f" · {pi // per + 1}" if len(inj) > per else ""),
                    chunk,
                )
            )
    pages.append(
        _section_page(
            "ДИСКВАЛЫ",
            f"месяц {month} · сезон {season}",
            data["suspensions"],
        )
    )
    return pages


def render_injuries_season_png_pages(season: int) -> list[bytes]:
    from utils.player_discipline import (
        _get_active_season_or_default,
        _injury_status_label,
        _load,
        _lock,
        get_calendar_month,
    )

    month = get_calendar_month(None)
    season_now = _get_active_season_or_default()
    sn = int(season)
    with _lock:
        st = _load()
    rows: list[dict[str, Any]] = []
    for inj in st.get("injuries") or []:
        if inj.get("season") is None or int(inj.get("season")) != sn:
            continue
        st_mark = _injury_status_label(inj, month=month, season_now=season_now)
        ofm = inj.get("out_from_month")
        ret = inj.get("return_month")
        rows.append(
            {
                "name": str(inj.get("name") or "?"),
                "team": str(inj.get("team") or "?"),
                "position": str(inj.get("type") or "травма")[:12],
                "detail": f"{st_mark} · с{ofm or '?'}→м{ret or '?'}",
                "status": "injury",
            }
        )
    rows.sort(key=lambda r: (str(r["team"]).casefold(), str(r["name"]).casefold()))
    return _injury_simple_pages(
        f"ТРАВМЫ · СЕЗОН {sn}",
        f"месяц {month} · текущий {season_now}",
        rows,
    )


def _injury_simple_pages(title: str, subtitle: str, rows: list[dict[str, Any]]) -> list[bytes]:
    """Reuse injury section layout without inventing fake stats columns."""
    theme = INJURY_THEME
    per = 18
    pages: list[bytes] = []
    chunks = [rows[i : i + per] for i in range(0, max(1, len(rows)), per)] if rows else [[]]
    if not rows:
        chunks = [[]]
    else:
        chunks = [rows[i : i + per] for i in range(0, len(rows), per)]

    for pi, chunk in enumerate(chunks):
        canvas_w = 720
        h = _HEADER_H + _COL_H + max(1, len(chunk)) * _ROW_H + 12
        im = Image.new("RGB", (canvas_w, h), theme.bg)
        draw = ImageDraw.Draw(im)
        sub = subtitle + (f" · {pi + 1}/{len(chunks)}" if len(chunks) > 1 else "")
        draw_header_bar(draw, theme=theme, width=canvas_w, height=_HEADER_H, title=title, subtitle=sub)
        hdr_y0 = _HEADER_H
        hdr_y1 = _HEADER_H + _COL_H
        draw.rectangle([0, hdr_y0, canvas_w, hdr_y1], fill=theme.header)
        hdr_font = pick_font(11, bold=True)
        name_font = pick_font(17, bold=True)
        meta_font = pick_font(13)
        rank_font = pick_font(13, bold=True)
        crest_font = pick_font(10, bold=True)
        draw.text((_NAME_LEFT, (hdr_y0 + hdr_y1) // 2), "ИГРОК", fill=theme.text_dim, font=hdr_font, anchor="lm")
        draw.text((canvas_w - 16, (hdr_y0 + hdr_y1) // 2), "СТАТУС", fill=theme.text_dim, font=hdr_font, anchor="rm")
        if not chunk:
            draw.text((24, hdr_y1 + 16), "Пусто", fill=theme.text_dim, font=pick_font(16))
            pages.append(png_bytes(im))
            continue
        for i, row in enumerate(chunk):
            y0 = hdr_y1 + i * _ROW_H
            y1 = y0 + _ROW_H
            draw.rectangle([0, y0, canvas_w, y1], fill=theme.row_a if i % 2 == 0 else theme.row_b)
            draw.rectangle([0, y0, 4, y1], fill=theme.accent)
            cy = y0 + _ROW_H // 2
            draw.text((_RANK_W // 2, cy), str(pi * per + i + 1), fill=theme.text_dim, font=rank_font, anchor="mm")
            team = str(row.get("team") or "")
            if team:
                paste_crest(im, draw, team=team, cx=_RANK_W + 6 + _CREST // 2, cy=cy, size=_CREST, crest_font=crest_font)
            name = display_player_name(str(row.get("name") or ""))
            name_d = truncate(draw, name, name_font, 200)
            draw.text((_NAME_LEFT, cy), name_d, fill=theme.text, font=name_font, anchor="lm")
            pos = str(row.get("position") or "")
            if pos:
                nx = _NAME_LEFT + int(draw.textlength(name_d, font=name_font))
                draw.text((nx + 6, cy), pos, fill=theme.text_dim, font=meta_font, anchor="lm")
            detail = str(row.get("detail") or "")
            draw.text(
                (canvas_w - 16, cy),
                truncate(draw, detail, meta_font, 200),
                fill=theme.highlight,
                font=meta_font,
                anchor="rm",
            )
        pages.append(png_bytes(im))
    return pages


def render_injury_frequency_png_pages(*, limit: int = 25) -> list[bytes]:
    from utils.player_discipline import (
        _career_player_index,
        _injury_total_months,
        _load,
        _lock,
        _norm,
    )

    with _lock:
        st = _load()
    career = _career_player_index()
    agg: dict[str, dict[str, Any]] = {}
    for inj in st.get("injuries") or []:
        nn = str(inj.get("name_norm") or _norm(str(inj.get("name") or ""))).strip()
        if not nn:
            continue
        name = str(inj.get("name") or nn).strip()
        team = str(inj.get("team") or "?").strip()
        row = agg.get(nn)
        if row is None:
            row = {"name": name, "teams": {}, "periods": 0, "months": 0}
            agg[nn] = row
        row["periods"] += 1
        row["months"] += _injury_total_months(inj)
        if team:
            row["teams"][team] = int(row["teams"].get(team, 0)) + 1

    ranked: list[dict[str, Any]] = []
    for nn, row in agg.items():
        teams_map = row["teams"]
        info = career.get(nn) or {}
        top_team = (
            max(teams_map.items(), key=lambda kv: (kv[1], kv[0]))[0]
            if teams_map
            else str(info.get("team") or "?")
        )
        if info.get("name"):
            row["name"] = str(info["name"])
        ranked.append(
            {
                "name": row["name"],
                "team": top_team,
                "position": str(int(info.get("overall") or 0) or "—"),
                "overall": int(info.get("overall") or 0),
                "goals": int(row["periods"]),
                "assists": int(row["months"]),
                "ga": int(row["periods"]),
                "matches": int(row["months"]),
            }
        )
    ranked.sort(key=lambda r: (-r["goals"], -r["assists"], -r["overall"], str(r["name"]).casefold()))
    show = ranked[: max(1, int(limit))]
    return render_player_board_pages(
        title="ЧАЩЕ ВСЕГО ТРАВМЫ",
        subtitle=None,
        rows=show,
        columns=[("goals", "РАЗ"), ("assists", "МЕС"), ("overall", "OVR")],
        theme=INJURY_THEME,
        highlight_key="goals",
    )


def render_never_injured_png_pages(*, limit: int = 40) -> list[bytes]:
    from utils.player_discipline import _career_player_index, _load, _lock, _norm

    with _lock:
        st = _load()
    injured = {
        str(inj.get("name_norm") or _norm(str(inj.get("name") or ""))).strip()
        for inj in (st.get("injuries") or [])
        if str(inj.get("name_norm") or inj.get("name") or "").strip()
    }
    career = _career_player_index()
    rows: list[dict[str, Any]] = []
    for nn, info in career.items():
        if nn in injured:
            continue
        matches = int(info.get("matches") or 0)
        if matches <= 0:
            continue
        rows.append(
            {
                "name": str(info.get("name") or nn),
                "team": str(info.get("team") or "?"),
                "position": str(info.get("position") or "—"),
                "overall": int(info.get("overall") or 0),
                "matches": matches,
                "goals": matches,
                "assists": int(info.get("overall") or 0),
                "ga": matches,
            }
        )
    rows.sort(key=lambda r: (-r["matches"], -r["overall"], str(r["name"]).casefold()))
    show = rows[: max(1, int(limit))]
    return render_player_board_pages(
        title="БЕЗ ТРАВМ",
        subtitle=None,
        rows=show,
        columns=[("matches", "И"), ("overall", "OVR")],
        theme=INJURY_THEME,
        highlight_key="matches",
    )


def render_position_stats_png_pages(scope: str, group: str) -> list[bytes]:
    from utils.stats_by_position import GROUP_META, collect_group_stats

    meta = GROUP_META.get(group) or {}
    base = str(meta.get("title") or group).upper()
    title = f"{base} · всё время" if scope == "life" else base
    rows = collect_group_stats(scope, group)
    if group == "gk":
        cols = [("matches", "И"), ("clean_sheets", "СУХ"), ("potm", "POTM")]
        # normalize key
        for r in rows:
            r.setdefault("clean_sheets", r.get("clean_sheets", 0))
        hl = "clean_sheets"
    else:
        cols = [("matches", "И"), ("goals", "Г"), ("assists", "А"), ("ga", "Г+А")]
        hl = "ga"
    return render_player_board_pages(
        title=title,
        subtitle=None,
        rows=rows,
        columns=cols,
        theme=PLAYER_BOARD_DARK,
        highlight_key=hl,
    )


def render_players_by_position_png_pages(pos: str) -> list[bytes]:
    from utils.players_by_position import collect_players_by_position
    from utils.season_paths import get_active_season

    data = collect_players_by_position()
    triples = data.get(pos) or []
    rows = [
        {
            "name": sur,
            "team": team,
            "position": pos,
            "overall": ovr,
            "matches": ovr,
            "goals": ovr,
            "assists": 0,
            "ga": ovr,
        }
        for sur, team, ovr in triples
    ]
    return render_player_board_pages(
        title=f"ПОЗИЦИЯ {pos} · сезон {get_active_season()}",
        subtitle=None,
        rows=rows,
        columns=[("overall", "OVR")],
        theme=PLAYER_BOARD_DARK,
        highlight_key="overall",
    )


def render_life_top_png_pages(league_code: str, *, metric: str, limit: int = 30) -> list[bytes]:
    from utils.stats_history_agg import aggregate_life_outfield

    players = aggregate_life_outfield(league_code, merge_by_player=True)
    if metric == "goals":
        players = [p for p in players if int(p.get("goals", 0) or 0) > 0]
        players.sort(key=lambda x: (-x["goals"], -x["assists"]))
        cols = [("goals", "Г"), ("assists", "А"), ("ga", "Г+А")]
        hl = "goals"
        title = "БОМБАРДИРЫ · ВСЁ ВРЕМЯ"
    elif metric == "assists":
        players = [p for p in players if int(p.get("assists", 0) or 0) > 0]
        players.sort(key=lambda x: (-x["assists"], -x["goals"]))
        cols = [("assists", "А"), ("goals", "Г"), ("ga", "Г+А")]
        hl = "assists"
        title = "АССИСТЫ · ВСЁ ВРЕМЯ"
    else:
        players = [p for p in players if int(p.get("ga", 0) or 0) > 0]
        players.sort(key=lambda x: (-x["ga"], -x["goals"]))
        cols = [("ga", "Г+А"), ("goals", "Г"), ("assists", "А")]
        hl = "ga"
        title = "Г+А · ВСЁ ВРЕМЯ"
    theme = theme_for_league(league_code if league_code != "a" else "cl")
    board = LeagueTheme(
        theme.code,
        theme.title,
        PLAYER_BOARD_DARK.bg,
        theme.header,
        PLAYER_BOARD_DARK.row_a,
        PLAYER_BOARD_DARK.row_b,
        theme.accent,
        PLAYER_BOARD_DARK.text,
        PLAYER_BOARD_DARK.text_dim,
        PLAYER_BOARD_DARK.highlight,
    )
    return render_player_board_pages(
        title=title,
        subtitle=theme.title,
        rows=players[:limit],
        columns=cols,
        theme=board,
        highlight_key=hl,
    )


def render_all_clubs_scorers_png_pages(
    league_code: str,
    *,
    season_mode: str = "cur",
    season_num: int | None = None,
) -> list[bytes]:
    """По странице на клуб (с голами/пассами)."""
    from bot.services import (
        teams_ordered_for_goalscorers,
        teams_ordered_for_goalscorers_season_archive,
    )

    if season_mode == "sn":
        teams = teams_ordered_for_goalscorers_season_archive(int(season_num or 0), league_code)
    else:
        teams = teams_ordered_for_goalscorers(league_code)
    pages: list[bytes] = []
    for idx, _team in enumerate(teams):
        _cap, blobs = render_club_goalscorers_png_for_bot(
            league_code,
            idx,
            "league",
            season_mode=season_mode if season_mode != "life" else "life",
            season_num=season_num,
        )
        # for life/cur we used scope league only in this helper — fix: call with proper scope
        if blobs:
            pages.extend(blobs)
    return pages or render_player_board_pages(
        title="КЛУБЫ",
        subtitle="нет данных",
        rows=[],
        columns=[("ga", "Г+А")],
        theme=PLAYER_BOARD_DARK,
    )
