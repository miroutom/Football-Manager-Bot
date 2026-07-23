# -*- coding: utf-8 -*-
"""
История клубов: престиж (с учётом силы лиги и ЛЧ), досье клуба, легенды.

Престиж специально давит «лёгкие» чемпионства (РПЛ) и поднимает глубокие
проходы / титулы ЛЧ и топ-лиги.
"""
from __future__ import annotations

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

# Очки за лучшую стадию ЛЧ в сезоне (победитель учитывается отдельно титулом).
CL_STAGE_POINTS: dict[int, float] = {
    1: 1.0,   # 1/16
    2: 2.5,   # 1/8
    3: 5.5,   # 1/4
    4: 12.0,  # 1/2
    5: 22.0,  # финал
    6: 0.0,   # победитель — только через CL_TITLE_POINTS
}

CL_TITLE_POINTS = 52.0
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
    score: float


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


def _all_club_names() -> set[str]:
    names: set[str] = set()
    for teams in LEAGUE_TEAMS.values():
        names.update(str(t).strip() for t in teams if str(t).strip())
    hist = load_history()
    for rows in (hist.get("league_winners") or {}).values():
        for row in rows or []:
            if row and len(row) >= 2 and str(row[1]).strip():
                names.add(str(row[1]).strip())
    for row in hist.get("champions_league") or []:
        if row and len(row) >= 2 and str(row[1]).strip():
            names.add(str(row[1]).strip())
    for _sn, mp in hist.get("cl_knockout_stages") or []:
        if isinstance(mp, dict):
            names.update(str(t).strip() for t in mp if str(t).strip())
    return names


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
                    f"COALESCE(potm, 0), team FROM {tbl} "
                    f"WHERE team IS NOT NULL AND trim(team) != ''"
                )
            except sqlite3.OperationalError:
                continue
            for name, pos, g, a, m, potm, tm in cur:
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
                    },
                )
                row["goals"] += int(g or 0)
                row["assists"] += int(a or 0)
                row["matches"] += int(m or 0)
                row["potm"] += int(potm or 0)
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
