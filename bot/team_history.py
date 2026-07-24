# -*- coding: utf-8 -*-
"""
История клубов: престиж (с учётом силы лиги и ЛЧ), досье клуба, легенды.

Престиж специально давит «лёгкие» чемпионства (РПЛ) и поднимает глубокие
проходы / титулы ЛЧ и топ-лиги.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from bot.season_history_store import load_history
from player_stats import LEAGUE_NAMES, LEAGUE_TEAMS, national_league_code_for_team
from utils import season_paths
from utils.cl_knockout_results import CL_STAGE_LABEL_RU, cl_stage_label_ru
from utils.cumulative_db import list_season_archives_with_db
from utils.team_strength import get_team_strength

# Вес чемпионства нац. лиги (РПЛ сильно слабее топ-5 Европы).
LEAGUE_TITLE_WEIGHT: dict[str, float] = {
    "eng": 1.00,
    "esp": 0.98,
    "ita": 0.95,
    "ger": 0.92,
    "rpl": 0.18,
}

# Очки за лучшую стадию ЛЧ в сезоне (путь). Титул даёт ещё CL_TITLE_POINTS сверху.
CL_STAGE_POINTS: dict[int, float] = {
    1: 3.0,   # 1/16
    2: 8.0,   # 1/8
    3: 16.0,  # 1/4
    4: 28.0,  # 1/2
    5: 40.0,  # финал
    6: 48.0,  # победитель — путь до трофея (титул отдельно)
}

CL_TITLE_POINTS = 40.0
LEAGUE_TITLE_BASE = 20.0
AWARD_POINTS = {
    "golden_ball": 12.0,
    "golden_boot": 7.0,
    "golden_glove": 6.0,
    "golden_boy": 4.0,
}


@dataclass
class TeamPrestige:
    team: str
    league_code: str
    score: float
    league_title_pts: float = 0.0
    cl_title_pts: float = 0.0
    cl_stage_pts: float = 0.0
    roster_pts: float = 0.0
    award_pts: float = 0.0
    league_titles: int = 0
    cl_titles: int = 0
    best_cl_stage: int = 0
    roster_ovr: float = 70.0
    awards: int = 0
    breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class ClubLegend:
    name: str
    position: str
    goals: int
    assists: int
    matches: int
    potm: int
    overall: int
    score: float


def format_season_list(seasons: list[int]) -> str:
    """[2, 5] → «2 сезон, 5 сезон»."""
    if not seasons:
        return "—"
    return ", ".join(f"{int(sn)} сезон" for sn in seasons)


def format_season_tag(sn: int) -> str:
    return f"{int(sn)} сезон"


@dataclass
class ClubDossier:
    team: str
    league_code: str
    league_title: str
    prestige: TeamPrestige
    league_titles_by_season: list[int]
    cl_titles_by_season: list[int]
    cl_stages: list[tuple[int, int]]  # (season, stage)
    legends: list[ClubLegend]
    awards: list[tuple[str, int, str]]  # (kind_label, season, player)


def _norm(s: str) -> str:
    return (s or "").strip().casefold()


def _current_pool_club_names() -> set[str]:
    """Актуальный пул сезона: 8 клубов × 5 лиг = 40."""
    from config.leagues_config import ALL_LEAGUES

    names: set[str] = set()
    for code, cfg in ALL_LEAGUES.items():
        if code == "cl":
            continue
        for t in cfg.get("teams") or []:
            s = str(t).strip()
            if s:
                # В конфиге часто lower; в БД/истории — Title.
                names.add(s.title() if s == s.lower() else s)
    return names


def _all_club_names() -> set[str]:
    """Для рейтинга силы — только текущие 40 клубов пула."""
    names = _current_pool_club_names()
    if names:
        return names
    # fallback: расширенный список из LEAGUE_TEAMS
    out: set[str] = set()
    for teams in LEAGUE_TEAMS.values():
        out.update(str(t).strip() for t in teams if str(t).strip())
    return out


def _award_counts_by_team(hist: dict[str, Any]) -> dict[str, tuple[int, float]]:
    out: dict[str, list[float]] = {}
    for kind, pts in AWARD_POINTS.items():
        for row in hist.get(kind) or []:
            if not row or len(row) < 3:
                continue
            team = str(row[2]).strip()
            if not team:
                continue
            bucket = out.setdefault(_norm(team), [0.0, 0.0])
            bucket[0] += 1
            bucket[1] += pts
    return {k: (int(v[0]), float(v[1])) for k, v in out.items()}


def compute_team_prestige(team: str, hist: dict[str, Any] | None = None) -> TeamPrestige:
    hist = hist or load_history()
    team_s = (team or "").strip()
    lc = national_league_code_for_team(team_s) or ""
    want = _norm(team_s)

    league_titles = 0
    league_pts = 0.0
    for code, rows in (hist.get("league_winners") or {}).items():
        w = float(LEAGUE_TITLE_WEIGHT.get(str(code), 0.7))
        for row in rows or []:
            if not row or len(row) < 2:
                continue
            if _norm(str(row[1])) != want:
                continue
            league_titles += 1
            league_pts += LEAGUE_TITLE_BASE * w

    cl_titles = 0
    for row in hist.get("champions_league") or []:
        if row and len(row) >= 2 and _norm(str(row[1])) == want:
            cl_titles += 1
    cl_title_pts = cl_titles * CL_TITLE_POINTS

    best_stage = 0
    stage_pts = 0.0
    for _sn, mp in hist.get("cl_knockout_stages") or []:
        if not isinstance(mp, dict):
            continue
        for t, st in mp.items():
            if _norm(str(t)) != want:
                continue
            si = int(st or 0)
            best_stage = max(best_stage, si)
            stage_pts += float(CL_STAGE_POINTS.get(si, 0.0))

    ovr = float(get_team_strength(team_s, "league"))
    roster_pts = max(0.0, ovr - 75.0) * 1.6

    awards_map = _award_counts_by_team(hist)
    awards_n, award_pts = awards_map.get(want, (0, 0.0))

    score = league_pts + cl_title_pts + stage_pts + roster_pts + award_pts
    return TeamPrestige(
        team=team_s,
        league_code=lc,
        score=round(score, 2),
        league_title_pts=round(league_pts, 2),
        cl_title_pts=round(cl_title_pts, 2),
        cl_stage_pts=round(stage_pts, 2),
        roster_pts=round(roster_pts, 2),
        award_pts=round(award_pts, 2),
        league_titles=league_titles,
        cl_titles=cl_titles,
        best_cl_stage=best_stage,
        roster_ovr=round(ovr, 1),
        awards=awards_n,
        breakdown={
            "Лига": round(league_pts, 2),
            "ЛЧ титул": round(cl_title_pts, 2),
            "ЛЧ путь": round(stage_pts, 2),
            "Состав": round(roster_pts, 2),
            "Награды": round(award_pts, 2),
        },
    )


def rank_teams_by_prestige(*, limit: int | None = None) -> list[TeamPrestige]:
    """``limit=None`` — полный список клубов; иначе топ-N."""
    hist = load_history()
    rows = [compute_team_prestige(t, hist) for t in sorted(_all_club_names(), key=_norm)]
    rows.sort(key=lambda r: (-r.score, r.team.casefold()))
    if limit is not None:
        return rows[: max(1, int(limit))]
    return rows


def _aggregate_legends_from_sqlite(db_path: str, team: str, bucket: dict[str, dict[str, Any]]) -> None:
    if not db_path or not os.path.isfile(db_path):
        return
    want = _norm(team)
    conn = sqlite3.connect(db_path)
    try:
        for tbl in ("forwards", "midfielders", "defenders", "goalkeepers"):
            try:
                # SQLite lower() не трогает кириллицу — фильтруем в Python.
                cur = conn.execute(
                    f"SELECT name, position, goals, assists, matches, "
                    f"COALESCE(potm, 0), COALESCE(overall, 0), team FROM {tbl} "
                    f"WHERE team IS NOT NULL AND trim(team) != ''"
                )
            except sqlite3.OperationalError:
                continue
            for name, pos, g, a, m, potm, ovr, tm in cur:
                if _norm(str(tm or "")) != want:
                    continue
                nm = (name or "").strip()
                if not nm:
                    continue
                key = nm.casefold()
                row = bucket.setdefault(
                    key,
                    {
                        "name": nm,
                        "position": (pos or "").strip().upper(),
                        "goals": 0,
                        "assists": 0,
                        "matches": 0,
                        "potm": 0,
                        "overall": 0,
                    },
                )
                row["goals"] += int(g or 0)
                row["assists"] += int(a or 0)
                row["matches"] += int(m or 0)
                row["potm"] += int(potm or 0)
                ov = int(ovr or 0)
                if ov > int(row["overall"] or 0):
                    row["overall"] = ov
                if (pos or "").strip() and not row["position"]:
                    row["position"] = str(pos).strip().upper()
    finally:
        conn.close()


def club_legends(team: str, *, limit: int = 8) -> list[ClubLegend]:
    """Лучшие игроки клуба по сумме статы в архивах сезонов + текущем сезоне."""
    bucket: dict[str, dict[str, Any]] = {}
    seen_paths: set[str] = set()

    def _add_pair(league_db: str, cl_db: str) -> None:
        for p in (league_db, cl_db):
            ap = os.path.abspath(p) if p else ""
            if not ap or ap in seen_paths:
                continue
            seen_paths.add(ap)
            _aggregate_legends_from_sqlite(ap, team, bucket)

    for sn in list_season_archives_with_db():
        root = season_paths.season_archive_directory(int(sn))
        _add_pair(
            os.path.join(root, season_paths.SEASON_LEAGUE_NAME),
            os.path.join(root, season_paths.SEASON_CL_NAME),
        )
    try:
        from utils.utils import CHAMPIONS_LEAGUE_DB_PATH, LEAGUE_DB_PATH

        _add_pair(LEAGUE_DB_PATH, CHAMPIONS_LEAGUE_DB_PATH)
    except Exception:
        sp = season_paths.get_active_season_directory()
        _add_pair(
            os.path.join(sp, season_paths.SEASON_LEAGUE_NAME),
            os.path.join(sp, season_paths.SEASON_CL_NAME),
        )

    legends: list[ClubLegend] = []
    for row in bucket.values():
        g = int(row["goals"])
        a = int(row["assists"])
        m = int(row["matches"])
        potm = int(row["potm"])
        if g + a + m + potm <= 0:
            continue
        score = g * 3.0 + a * 2.0 + potm * 4.0 + m * 0.15
        legends.append(
            ClubLegend(
                name=str(row["name"]),
                position=str(row["position"] or "?"),
                goals=g,
                assists=a,
                matches=m,
                potm=potm,
                overall=int(row.get("overall") or 0),
                score=score,
            )
        )
    legends.sort(key=lambda x: (-x.score, -x.goals, x.name.casefold()))
    return legends[: max(1, int(limit))]


def build_club_dossier(team: str) -> ClubDossier:
    hist = load_history()
    team_s = (team or "").strip()
    want = _norm(team_s)
    lc = national_league_code_for_team(team_s) or ""
    prestige = compute_team_prestige(team_s, hist)

    league_seasons: list[int] = []
    if lc:
        for row in (hist.get("league_winners") or {}).get(lc) or []:
            if row and len(row) >= 2 and _norm(str(row[1])) == want:
                league_seasons.append(int(row[0]))

    cl_seasons: list[int] = []
    for row in hist.get("champions_league") or []:
        if row and len(row) >= 2 and _norm(str(row[1])) == want:
            cl_seasons.append(int(row[0]))

    stages: list[tuple[int, int]] = []
    for sn, mp in hist.get("cl_knockout_stages") or []:
        if not isinstance(mp, dict):
            continue
        for t, st in mp.items():
            if _norm(str(t)) == want:
                stages.append((int(sn), int(st or 0)))
    stages.sort(key=lambda x: x[0])

    award_kind_label = {
        "golden_ball": "ЗМ",
        "golden_boot": "Бутса",
        "golden_glove": "Перчатка",
        "golden_boy": "Golden Boy",
    }
    awards: list[tuple[str, int, str]] = []
    for kind, lab in award_kind_label.items():
        for row in hist.get(kind) or []:
            if not row or len(row) < 3:
                continue
            if _norm(str(row[2])) != want:
                continue
            awards.append((lab, int(row[0]), str(row[1])))
    awards.sort(key=lambda x: (-x[1], x[0]))

    return ClubDossier(
        team=team_s,
        league_code=lc,
        league_title=LEAGUE_NAMES.get(lc, lc or "—"),
        prestige=prestige,
        league_titles_by_season=sorted(league_seasons),
        cl_titles_by_season=sorted(cl_seasons),
        cl_stages=stages,
        legends=club_legends(team_s, limit=8),
        awards=awards,
    )


def prestige_formula_caption() -> str:
    return (
        "Престиж = чемп. лиги×вес лиги + титулы ЛЧ + путь в плей-офф ЛЧ "
        "+ сила состава + личные награды клуба. "
        f"Вес РПЛ={LEAGUE_TITLE_WEIGHT['rpl']:.2f} "
        f"(АПЛ={LEAGUE_TITLE_WEIGHT['eng']:.2f})."
    )


def cl_stage_short(stage: int) -> str:
    return CL_STAGE_LABEL_RU.get(int(stage), cl_stage_label_ru(stage))


# ─── Доп. аналитика: H2H, матчи сезона, менеджеры, динамика ─────────

def list_history_seasons() -> list[int]:
    """Сезоны, по которым есть история / журналы."""
    hist = load_history()
    seasons: set[int] = set()
    for rows in (hist.get("league_winners") or {}).values():
        for row in rows or []:
            if row:
                seasons.add(int(row[0]))
    for row in hist.get("champions_league") or []:
        if row:
            seasons.add(int(row[0]))
    for sn, _mp in hist.get("cl_knockout_stages") or []:
        seasons.add(int(sn))
    for kind in AWARD_POINTS:
        for row in hist.get(kind) or []:
            if row:
                seasons.add(int(row[0]))
    for sn in list_season_archives_with_db():
        seasons.add(int(sn))
    try:
        seasons.add(int(season_paths.get_active_season()))
    except Exception:
        pass
    return sorted(seasons) if seasons else [1]


def _match_journal_paths() -> list[tuple[int | None, str]]:
    """(season|None, path) — None = текущий match_results.json в корне."""
    out: list[tuple[int | None, str]] = []
    root_jr = os.path.join(season_paths.PROJECT_ROOT, "match_results.json")
    if os.path.isfile(root_jr):
        try:
            active = int(season_paths.get_active_season())
        except Exception:
            active = None
        out.append((active, root_jr))
    for sn in list_season_archives_with_db():
        p = os.path.join(season_paths.season_archive_directory(int(sn)), "match_results.json")
        if os.path.isfile(p):
            # не дублируем active, если тот же файл
            ap = os.path.abspath(p)
            if any(os.path.abspath(x[1]) == ap for x in out):
                continue
            out.append((int(sn), p))
    return out


def _load_matches_from_path(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, list):
        return [m for m in raw if isinstance(m, dict)]
    if isinstance(raw, dict):
        rows = raw.get("matches") or []
        return [m for m in rows if isinstance(m, dict)]
    return []


def iter_all_match_records() -> list[dict[str, Any]]:
    """Все матчи из журналов с полем ``_season`` (только записи со счётом)."""
    seen: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for sn, path in _match_journal_paths():
        for m in _load_matches_from_path(path):
            home = str(m.get("home") or "").strip()
            away = str(m.get("away") or "").strip()
            if not home or not away:
                continue
            hs, aws = m.get("home_score"), m.get("away_score")
            if hs is None or aws is None:
                continue
            try:
                hs_i, aws_i = int(hs), int(aws)
            except (TypeError, ValueError):
                continue
            key = (
                sn,
                home.casefold(),
                away.casefold(),
                m.get("league"),
                m.get("day"),
                hs_i,
                aws_i,
                m.get("cl_phase"),
            )
            if key in seen:
                continue
            seen.add(key)
            row = dict(m)
            row["home_score"] = hs_i
            row["away_score"] = aws_i
            row["_season"] = sn
            out.append(row)
    return out


def _penalties_pair(m: dict[str, Any]) -> tuple[int, int] | None:
    """Голы в серии пенальти ``(home, away)`` или ``None``."""
    pen = m.get("penalties_by_team")
    if not isinstance(pen, dict) or not pen:
        return None
    home = str(m.get("home") or "").strip()
    away = str(m.get("away") or "").strip()

    def _get(team: str) -> int | None:
        if not team:
            return None
        if team in pen:
            try:
                return int(pen[team])
            except (TypeError, ValueError):
                return None
        want = _norm(team)
        for k, v in pen.items():
            if _norm(str(k)) == want:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    return None
        return None

    ph, pa = _get(home), _get(away)
    if ph is None or pa is None:
        return None
    return ph, pa


def match_result_for_team(m: dict[str, Any], team: str) -> tuple[str, int, int, int]:
    """
    ``(W|D|L, points, gf, ga)`` с точки зрения клуба.
    При ничьей по счёту и ``penalties_by_team`` — победа/поражение по серии.
    """
    want = _norm(team)
    home = _norm(str(m.get("home") or ""))
    away = _norm(str(m.get("away") or ""))
    hs = int(m.get("home_score") or 0)
    aws = int(m.get("away_score") or 0)
    if home == want:
        gf, ga = hs, aws
        side_home = True
    elif away == want:
        gf, ga = aws, hs
        side_home = False
    else:
        return "D", 0, 0, 0
    if gf > ga:
        return "W", 3, gf, ga
    if gf < ga:
        return "L", 0, gf, ga
    pens = _penalties_pair(m)
    if pens is not None:
        ph, pa = pens
        mine, theirs = (ph, pa) if side_home else (pa, ph)
        if mine > theirs:
            return "W", 3, gf, ga
        if mine < theirs:
            return "L", 0, gf, ga
    return "D", 1, gf, ga


def compute_result_streaks(results: list[str]) -> dict[str, int]:
    """
    Самые длинные серии по хронологической последовательности ``W|D|L``.

    - ``unbeaten`` — без поражений (W и D)
    - ``wins`` — только победы
    - ``losses`` — только поражения
    """
    best_u = best_w = best_l = 0
    cur_u = cur_w = cur_l = 0
    for r in results:
        if r == "W":
            cur_w += 1
            cur_u += 1
            cur_l = 0
        elif r == "D":
            cur_w = 0
            cur_u += 1
            cur_l = 0
        else:
            cur_w = 0
            cur_u = 0
            cur_l += 1
        best_w = max(best_w, cur_w)
        best_u = max(best_u, cur_u)
        best_l = max(best_l, cur_l)
    return {"unbeaten": best_u, "wins": best_w, "losses": best_l}

def format_match_score_with_pens(m: dict[str, Any]) -> str:
    """``Ливерпуль 2:2 Аталанта (пен. 5:3)``."""
    home = str(m.get("home") or "")
    away = str(m.get("away") or "")
    hs = m.get("home_score")
    aws = m.get("away_score")
    line = f"{home} {hs}:{aws} {away}"
    pens = _penalties_pair(m)
    if pens is not None:
        ph, pa = pens
        line += f" (пен. {ph}:{pa})"
    return line


def head_to_head(team_a: str, team_b: str) -> dict[str, Any]:
    a, b = team_a.strip(), team_b.strip()
    an, bn = _norm(a), _norm(b)
    matches: list[dict[str, Any]] = []
    wa = wb = draws = gf_a = ga_a = 0
    for m in iter_all_match_records():
        h, aw = _norm(str(m.get("home") or "")), _norm(str(m.get("away") or ""))
        if {h, aw} != {an, bn}:
            continue
        matches.append(m)
        res, _pts, gf, ga = match_result_for_team(m, a)
        gf_a += gf
        ga_a += ga
        if res == "W":
            wa += 1
        elif res == "L":
            wb += 1
        else:
            draws += 1
    matches.sort(
        key=lambda m: (m.get("_season") or 0, m.get("day") or 0, str(m.get("league") or ""))
    )
    return {
        "team_a": a,
        "team_b": b,
        "played": len(matches),
        "wins_a": wa,
        "wins_b": wb,
        "draws": draws,
        "goals_a": gf_a,
        "goals_b": ga_a,
        "matches": matches,
    }


def club_matches_in_season(team: str, season: int) -> list[dict[str, Any]]:
    want = _norm(team)
    rows = [
        m
        for m in iter_all_match_records()
        if m.get("_season") == int(season)
        and (
            _norm(str(m.get("home") or "")) == want
            or _norm(str(m.get("away") or "")) == want
        )
    ]
    # хронология сезона: месяц, затем турнир (чтобы лига/ЛЧ одного месяца шли рядом)
    rows.sort(key=lambda m: (int(m.get("day") or 0), str(m.get("league") or "")))
    return rows

def prestige_snapshot_for_season(team: str, season: int, hist: dict[str, Any] | None = None) -> float:
    """Престиж только за вклад сезона N (без текущего OVR состава)."""
    hist = hist or load_history()
    want = _norm(team)
    sn = int(season)
    score = 0.0
    for code, rows in (hist.get("league_winners") or {}).items():
        w = float(LEAGUE_TITLE_WEIGHT.get(str(code), 0.7))
        for row in rows or []:
            if row and len(row) >= 2 and int(row[0]) == sn and _norm(str(row[1])) == want:
                score += LEAGUE_TITLE_BASE * w
    for row in hist.get("champions_league") or []:
        if row and len(row) >= 2 and int(row[0]) == sn and _norm(str(row[1])) == want:
            score += CL_TITLE_POINTS
    for s2, mp in hist.get("cl_knockout_stages") or []:
        if int(s2) != sn or not isinstance(mp, dict):
            continue
        for t, st in mp.items():
            if _norm(str(t)) == want:
                score += float(CL_STAGE_POINTS.get(int(st or 0), 0.0))
    for kind, pts in AWARD_POINTS.items():
        for row in hist.get(kind) or []:
            if row and len(row) >= 3 and int(row[0]) == sn and _norm(str(row[2])) == want:
                score += float(pts)
    return round(score, 2)


def prestige_dynamics(team: str) -> list[tuple[int, float]]:
    return [(sn, prestige_snapshot_for_season(team, sn)) for sn in list_history_seasons()]


def compare_clubs(team_a: str, team_b: str) -> dict[str, Any]:
    pa = compute_team_prestige(team_a)
    pb = compute_team_prestige(team_b)
    da = build_club_dossier(team_a)
    db = build_club_dossier(team_b)
    h2h = head_to_head(team_a, team_b)
    return {"a": pa, "b": pb, "dossier_a": da, "dossier_b": db, "h2h": h2h}


def manager_side_stats(side: str) -> dict[str, Any]:
    from config.leagues_config import MANAGER_TEAMS

    key = (side or "").strip().lower()
    clubs = [str(t).strip().title() for t in (MANAGER_TEAMS.get(key) or [])]
    hist = load_history()
    prestiges = [compute_team_prestige(t, hist) for t in clubs]
    total = sum(p.score for p in prestiges)
    league_titles = sum(p.league_titles for p in prestiges)
    cl_titles = sum(p.cl_titles for p in prestiges)
    awards = sum(p.awards for p in prestiges)
    ranked = sorted(prestiges, key=lambda p: (-p.score, p.team.casefold()))
    return {
        "side": key,
        "label": "Roman" if key == "roman" else "Lika" if key == "lika" else key,
        "clubs": clubs,
        "prestige_total": round(total, 1),
        "league_titles": league_titles,
        "cl_titles": cl_titles,
        "awards": awards,
        "top_clubs": ranked,  # все клубы менеджера, по убыванию престижа
        "avg_prestige": round(total / max(1, len(prestiges)), 1),
    }


def hall_of_fame_global(*, limit: int = 20) -> list[ClubLegend]:
    """Топ игроков по всем клубам текущего пула (лига+ЛЧ в архивах)."""
    best: dict[str, ClubLegend] = {}
    for team in sorted(_current_pool_club_names(), key=_norm):
        for leg in club_legends(team, limit=12):
            # ключ: имя — берём лучший score (игрок мог сменить клуб)
            k = leg.name.casefold()
            prev = best.get(k)
            if prev is None or leg.score > prev.score:
                # помечаем клуб в position field? keep as is; store team in name suffix no
                best[k] = ClubLegend(
                    name=f"{leg.name}",
                    position=leg.position,
                    goals=leg.goals,
                    assists=leg.assists,
                    matches=leg.matches,
                    potm=leg.potm,
                    overall=leg.overall,
                    score=leg.score,
                )
                # monkey: attach team via expanding - use a simple approach
                setattr(best[k], "club", team)
    rows = list(best.values())
    rows.sort(key=lambda x: (-x.score, -x.goals, x.name.casefold()))
    return rows[: max(1, int(limit))]


def season_cover_data(season: int) -> dict[str, Any]:
    hist = load_history()
    sn = int(season)
    leagues: dict[str, str | None] = {}
    for code in ("rpl", "eng", "esp", "ita", "ger"):
        winner = None
        for row in (hist.get("league_winners") or {}).get(code) or []:
            if row and int(row[0]) == sn:
                winner = str(row[1])
        leagues[code] = winner
    cl = None
    for row in hist.get("champions_league") or []:
        if row and int(row[0]) == sn:
            cl = str(row[1])
    awards: dict[str, tuple[str, str] | None] = {}
    labels = {
        "golden_ball": "ЗМ",
        "golden_boot": "Бутса",
        "golden_glove": "Перчатка",
        "golden_boy": "Golden Boy",
    }
    for kind, lab in labels.items():
        hit = None
        for row in hist.get(kind) or []:
            if row and len(row) >= 3 and int(row[0]) == sn:
                hit = (str(row[1]), str(row[2]))
        awards[lab] = hit
    return {"season": sn, "leagues": leagues, "cl": cl, "awards": awards}


def league_winners_heatmap() -> dict[str, Any]:
    """seasons × league codes → winner team."""
    hist = load_history()
    seasons = list_history_seasons()
    codes = ["rpl", "eng", "esp", "ita", "ger"]
    grid: dict[tuple[int, str], str | None] = {}
    for sn in seasons:
        for code in codes:
            w = None
            for row in (hist.get("league_winners") or {}).get(code) or []:
                if row and int(row[0]) == sn:
                    w = str(row[1])
            grid[(sn, code)] = w
    return {"seasons": seasons, "codes": codes, "grid": grid}
