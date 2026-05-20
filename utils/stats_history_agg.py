# -*- coding: utf-8 -*-
"""
Суммарная «стата за всё время» по национальной лиге / ЛЧ из снимков сезонов.

Не использует common_synced с фильтром по клубу лиги: там после merge по (имя, позиция)
голы из РПЛ могут оказаться у строки с клубом Серии А. Здесь суммируются сезоны
отдельно по (имя, клуб, позиция).
"""
from __future__ import annotations

import os
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from player_stats import LEAGUE_NAMES, LEAGUE_TEAMS
from utils import season_paths
from utils.cumulative_db import list_season_archives_with_db

_OUTFIELD = (Forward, Midfielder, Defender)
_ALL = (Forward, Midfielder, Defender, Goalkeeper)


def _norm_team(s: str) -> str:
    return (s or "").strip().casefold()


def _player_key(name: str, team: str, position: str) -> tuple[str, str, str]:
    return (
        (name or "").strip().casefold(),
        _norm_team(team),
        (position or "").strip().upper(),
    )


def _team_filter_set(league_code: str | None) -> set[str] | None:
    if not league_code or league_code in ("a", "all"):
        return None
    if league_code == "cl":
        import teams as teams_mod

        return {_norm_team(t) for t in teams_mod.teams_champ_league.keys()}
    teams = LEAGUE_TEAMS.get(league_code)
    if not teams:
        return None
    return {_norm_team(t) for t in teams}


def _season_db_path(season_num: int, *, cl: bool) -> str | None:
    active = season_paths.get_active_season()
    fname = season_paths.SEASON_CL_NAME if cl else season_paths.SEASON_LEAGUE_NAME
    if season_num == active:
        path = season_paths.get_cl_db_path() if cl else season_paths.get_league_db_path()
        return path if os.path.isfile(path) else None
    base = season_paths.season_archive_directory(season_num)
    path = os.path.join(base, fname)
    return path if os.path.isfile(path) else None


def _open_session(path: str) -> tuple[Session, Any]:
    eng = create_engine(f"sqlite:///{path}")
    return sessionmaker(bind=eng)(), eng


def _fold_outfield_bucket(buckets: dict, p: Any) -> None:
    k = _player_key(p.name, p.team, p.position)
    if k not in buckets:
        buckets[k] = {
            "name": p.name,
            "team": p.team,
            "position": p.position,
            "goals": 0,
            "assists": 0,
            "ga": 0,
            "matches": 0,
        }
    b = buckets[k]
    g = int(getattr(p, "goals", 0) or 0)
    a = int(getattr(p, "assists", 0) or 0)
    b["goals"] += g
    b["assists"] += a
    b["ga"] += int(getattr(p, "ga", 0) or 0) or (g + a)
    b["matches"] += int(getattr(p, "matches", 0) or 0)


def _fold_cards_bucket(buckets: dict, p: Any) -> None:
    k = _player_key(p.name, p.team, p.position)
    if k not in buckets:
        buckets[k] = {
            "name": p.name,
            "team": p.team,
            "position": p.position,
            "yellow_cards": 0,
            "red_cards": 0,
            "matches": 0,
        }
    b = buckets[k]
    b["yellow_cards"] += int(getattr(p, "yellow_cards", 0) or 0)
    b["red_cards"] += int(getattr(p, "red_cards", 0) or 0)
    b["matches"] += int(getattr(p, "matches", 0) or 0)


def _fold_cs_bucket(buckets: dict, p: Any) -> None:
    k = _player_key(p.name, p.team, p.position)
    if k not in buckets:
        buckets[k] = {
            "name": p.name,
            "team": p.team,
            "position": p.position,
            "clean_sheets": 0,
            "matches": 0,
        }
    b = buckets[k]
    b["clean_sheets"] += int(getattr(p, "clean_sheets", 0) or 0)
    b["matches"] += int(getattr(p, "matches", 0) or 0)


def aggregate_life_outfield(league_code: str | None, *, cl: bool = False) -> list[dict]:
    team_set = _team_filter_set("cl" if cl else league_code)
    buckets: dict[tuple[str, str, str], dict] = {}
    seasons = list_season_archives_with_db() if not cl else _list_season_archives_with_cl()
    if not seasons:
        return []

    for sn in seasons:
        path = _season_db_path(sn, cl=cl)
        if not path:
            continue
        session, eng = _open_session(path)
        try:
            for Cls in _OUTFIELD:
                for p in session.query(Cls).all():
                    if team_set is not None and _norm_team(p.team) not in team_set:
                        continue
                    if cl:
                        if int(getattr(p, "goals", 0) or 0) == 0 and int(
                            getattr(p, "assists", 0) or 0
                        ) == 0:
                            continue
                    _fold_outfield_bucket(buckets, p)
        finally:
            session.close()
            eng.dispose()
    return list(buckets.values())


def aggregate_life_cards(league_code: str | None, *, cl: bool = False) -> list[dict]:
    team_set = _team_filter_set("cl" if cl else league_code)
    buckets: dict[tuple[str, str, str], dict] = {}
    seasons = list_season_archives_with_db() if not cl else _list_season_archives_with_cl()
    for sn in seasons:
        path = _season_db_path(sn, cl=cl)
        if not path:
            continue
        session, eng = _open_session(path)
        try:
            for Cls in _ALL:
                for p in session.query(Cls).all():
                    if team_set is not None and _norm_team(p.team) not in team_set:
                        continue
                    _fold_cards_bucket(buckets, p)
        finally:
            session.close()
            eng.dispose()
    return list(buckets.values())


def aggregate_life_clean_sheets(
    league_code: str | None, *, cl: bool = False
) -> tuple[list[dict], list[dict]]:
    team_set = _team_filter_set("cl" if cl else league_code)
    gk_buckets: dict[tuple[str, str, str], dict] = {}
    df_buckets: dict[tuple[str, str, str], dict] = {}
    seasons = list_season_archives_with_db() if not cl else _list_season_archives_with_cl()
    for sn in seasons:
        path = _season_db_path(sn, cl=cl)
        if not path:
            continue
        session, eng = _open_session(path)
        try:
            for p in session.query(Goalkeeper).all():
                if team_set is not None and _norm_team(p.team) not in team_set:
                    continue
                _fold_cs_bucket(gk_buckets, p)
            for p in session.query(Defender).all():
                if team_set is not None and _norm_team(p.team) not in team_set:
                    continue
                _fold_cs_bucket(df_buckets, p)
        finally:
            session.close()
            eng.dispose()
    return list(gk_buckets.values()), list(df_buckets.values())


def _list_season_archives_with_cl() -> list[int]:
    out: list[int] = []
    db_dir = os.path.join(season_paths.PROJECT_ROOT, "db")
    if not os.path.isdir(db_dir):
        return out
    for name in os.listdir(db_dir):
        if not name.startswith("season_"):
            continue
        tail = name.replace("season_", "")
        if not tail.isdigit():
            continue
        n = int(tail)
        cp = os.path.join(db_dir, name, season_paths.SEASON_CL_NAME)
        if os.path.isfile(cp):
            out.append(n)
    active = season_paths.get_active_season()
    if active not in out and os.path.isfile(season_paths.get_cl_db_path()):
        out.append(active)
    return sorted(set(out))


def _life_title_suffix(league_code: str | None, *, cl: bool) -> str:
    if cl:
        name = LEAGUE_NAMES["cl"]
    elif not league_code or league_code in ("a", "all"):
        name = "Все чемпионаты"
    else:
        name = LEAGUE_NAMES.get(league_code, league_code)
    return f" — все сезоны ({name}, по снимкам сезонов)"


def life_has_archive_data(*, cl: bool = False) -> bool:
    if cl:
        return bool(_list_season_archives_with_cl())
    return bool(list_season_archives_with_db())


def format_life_top_scorers(league_code: str | None, limit: int = 30) -> str:
    import contextlib
    import io

    cl = league_code == "cl"
    players = aggregate_life_outfield(league_code if not cl else "cl", cl=cl)
    players = [p for p in players if int(p.get("goals", 0) or 0) > 0]
    players.sort(key=lambda x: (-x["goals"], -x["assists"]))
    if cl:
        league_name = LEAGUE_NAMES["cl"] + _life_title_suffix(None, cl=True)
    elif not league_code or league_code in ("a", "all"):
        league_name = "Все чемпионаты" + _life_title_suffix(None, cl=False)
    else:
        league_name = LEAGUE_NAMES.get(league_code, league_code) + _life_title_suffix(
            league_code, cl=False
        )

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print(f"\n{'='*65}")
        print(f"  ТОП-{limit} БОМБАРДИРОВ - {league_name}")
        print(f"{'='*65}")
        print(
            f"{'#':<4} {'Игрок':<18} {'Команда':<15} {'Поз':<5} {'Г':<4} {'А':<4} {'Г+А':<5}"
        )
        print("-" * 65)
        if not players:
            print("  Нет данных")
        else:
            for i, p in enumerate(players[:limit], 1):
                print(
                    f"{i:<4} {p['name']:<18} {p['team']:<15} {p['position']:<5} "
                    f"{p['goals']:<4} {p['assists']:<4} {p['ga']:<5}"
                )
    return buf.getvalue()


def format_life_top_assists(league_code: str | None, limit: int = 30) -> str:
    import contextlib
    import io

    cl = league_code == "cl"
    players = aggregate_life_outfield(league_code if not cl else "cl", cl=cl)
    players = [p for p in players if int(p.get("assists", 0) or 0) > 0]
    players.sort(key=lambda x: (-x["assists"], -x["goals"]))
    if cl:
        league_name = LEAGUE_NAMES["cl"] + _life_title_suffix(None, cl=True)
    elif not league_code or league_code in ("a", "all"):
        league_name = "Все чемпионаты" + _life_title_suffix(None, cl=False)
    else:
        league_name = LEAGUE_NAMES.get(league_code, league_code) + _life_title_suffix(
            league_code, cl=False
        )

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print(f"\n{'='*65}")
        print(f"  ТОП-{limit} АССИСТЕНТОВ - {league_name}")
        print(f"{'='*65}")
        print(
            f"{'#':<4} {'Игрок':<18} {'Команда':<15} {'Поз':<5} {'А':<4} {'Г':<4} {'Г+А':<5}"
        )
        print("-" * 65)
        if not players:
            print("  Нет данных")
        else:
            for i, p in enumerate(players[:limit], 1):
                print(
                    f"{i:<4} {p['name']:<18} {p['team']:<15} {p['position']:<5} "
                    f"{p['assists']:<4} {p['goals']:<4} {p['ga']:<5}"
                )
    return buf.getvalue()


def format_life_top_ga(league_code: str | None, limit: int = 30) -> str:
    import contextlib
    import io

    cl = league_code == "cl"
    players = aggregate_life_outfield(league_code if not cl else "cl", cl=cl)
    players = [p for p in players if int(p.get("ga", 0) or 0) > 0]
    players.sort(key=lambda x: (-x["ga"], -x["goals"]))
    if cl:
        league_name = LEAGUE_NAMES["cl"] + _life_title_suffix(None, cl=True)
    elif not league_code or league_code in ("a", "all"):
        league_name = "Все чемпионаты" + _life_title_suffix(None, cl=False)
    else:
        league_name = LEAGUE_NAMES.get(league_code, league_code) + _life_title_suffix(
            league_code, cl=False
        )

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print(f"\n{'='*65}")
        print(f"  ТОП-{limit} ПО Г+А - {league_name}")
        print(f"{'='*65}")
        print(
            f"{'#':<4} {'Игрок':<18} {'Команда':<15} {'Поз':<5} {'Г+А':<5} {'Г':<4} {'А':<4}"
        )
        print("-" * 65)
        if not players:
            print("  Нет данных")
        else:
            for i, p in enumerate(players[:limit], 1):
                print(
                    f"{i:<4} {p['name']:<18} {p['team']:<15} {p['position']:<5} "
                    f"{p['ga']:<5} {p['goals']:<4} {p['assists']:<4}"
                )
    return buf.getvalue()


def format_life_top_cards(
    league_code: str | None, metric: str, limit: int = 30
) -> str:
    cl = league_code == "cl"
    rows = aggregate_life_cards(league_code if not cl else "cl", cl=cl)
    m = metric.lower()
    field = "yellow_cards" if m == "yc" else "red_cards"
    title = "жёлтые карточки" if m == "yc" else "красные карточки"
    picked = [r for r in rows if int(r.get(field, 0) or 0) > 0]
    picked.sort(
        key=lambda x: (
            -int(x.get(field, 0) or 0),
            -int(x.get("matches", 0) or 0),
            str(x.get("name", "")).casefold(),
        )
    )
    if cl:
        lg_label = LEAGUE_NAMES["cl"]
    elif not league_code or league_code in ("a", "all"):
        lg_label = "Все чемпионаты"
    else:
        lg_label = LEAGUE_NAMES.get(league_code, league_code)
    out = [f"Топ {title}{_life_title_suffix(league_code, cl=cl)}"]
    out.append(f"Лига: {lg_label}")
    out.append("")
    if not picked:
        out.append("Нет данных.")
        return "\n".join(out)
    out.append(f"{'№':>2} {'Игрок':<24} {'Клуб':<18} {'Матч':>5} {'Знач':>5}")
    for i, r in enumerate(picked[:limit], start=1):
        out.append(
            f"{i:>2} {str(r['name'])[:24]:<24} {str(r['team'])[:18]:<18} "
            f"{int(r.get('matches', 0) or 0):>5} {int(r.get(field, 0) or 0):>5}"
        )
    return "\n".join(out)


def format_life_clean_sheets(
    league_code: str | None, limit: int = 30
) -> tuple[str, str]:
    cl = league_code == "cl"
    gk_rows, df_rows = aggregate_life_clean_sheets(
        league_code if not cl else "cl", cl=cl
    )

    def _sort(rows: list[dict]) -> list[dict]:
        rows = [r for r in rows if int(r.get("clean_sheets", 0) or 0) > 0]
        rows.sort(
            key=lambda x: (
                -int(x.get("clean_sheets", 0) or 0),
                -int(x.get("matches", 0) or 0),
                str(x.get("name", "")).casefold(),
            )
        )
        return rows

    gk_rows = _sort(gk_rows)
    df_rows = _sort(df_rows)
    if cl:
        lg_label = LEAGUE_NAMES["cl"]
    elif not league_code or league_code in ("a", "all"):
        lg_label = "Все чемпионаты"
    else:
        lg_label = LEAGUE_NAMES.get(league_code, league_code)
    suf = _life_title_suffix(league_code, cl=cl)

    def _fmt(rows: list[dict], role: str) -> str:
        title = f"Сухие матчи · {role}{suf}"
        out = [title, f"Лига: {lg_label}", ""]
        if not rows:
            out.append("Нет данных.")
            return "\n".join(out)
        out.append(f"{'№':>2} {'Игрок':<24} {'Клуб':<18} {'Матч':>5} {'Сух':>5}")
        for i, r in enumerate(rows[:limit], start=1):
            out.append(
                f"{i:>2} {str(r['name'])[:24]:<24} {str(r['team'])[:18]:<18} "
                f"{int(r.get('matches', 0) or 0):>5} "
                f"{int(r.get('clean_sheets', 0) or 0):>5}"
            )
        return "\n".join(out)

    return _fmt(gk_rows, "вратари"), _fmt(df_rows, "защитники")
