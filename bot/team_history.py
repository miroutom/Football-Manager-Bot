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
# Титул ЧМ реже ЛЧ — выше вес; «Лучший игрок ЧМ» идёт в престиж сборной.
WC_TITLE_POINTS = 55.0
WC_BEST_POINTS = 10.0
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
    # Особые кубки: (grade gold|platinum, scope league|cl, season)
    special_cups: list[tuple[str, str, int]] = field(default_factory=list)


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

    special: list[tuple[str, str, int]] = []
    for sn in league_seasons:
        grade = campaign_special_cup(
            team_s, sn, competition="league", league_code=lc or None
        )
        if grade:
            special.append((grade, "league", int(sn)))
    for sn in cl_seasons:
        grade = campaign_special_cup(team_s, sn, competition="cl")
        if grade:
            special.append((grade, "cl", int(sn)))
    special.sort(key=lambda x: (-x[2], 0 if x[0] == "platinum" else 1, x[1]))

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
        special_cups=special,
    )


def prestige_formula_caption() -> str:
    return (
        "Престиж = чемп. лиги×вес лиги + титулы ЛЧ + путь в плей-офф ЛЧ "
        "+ сила состава + личные награды клуба. "
        f"Вес РПЛ={LEAGUE_TITLE_WEIGHT['rpl']:.2f} "
        f"(АПЛ={LEAGUE_TITLE_WEIGHT['eng']:.2f})."
    )


def nation_prestige_formula_caption() -> str:
    return (
        "Престиж сборной = титулы ЧМ + сила заявки + «Лучший игрок ЧМ». "
        f"Титул ЧМ = {WC_TITLE_POINTS:.0f}, лучший игрок = {WC_BEST_POINTS:.0f}."
    )


def cl_stage_short(stage: int) -> str:
    return CL_STAGE_LABEL_RU.get(int(stage), cl_stage_label_ru(stage))


def _all_nation_names() -> list[str]:
    """Канонические имена сборных из конфига ЧМ."""
    try:
        from utils.world_cup import load_wc_config, nations_by_confederation
        from utils.world_cup_format import flatten_nations

        names = [str(n).strip() for n in (load_wc_config().get("nations") or []) if str(n).strip()]
        if names:
            return names
        return [str(n).strip() for n in flatten_nations(nations_by_confederation()) if str(n).strip()]
    except Exception:
        return []


def is_nation_name(name: str) -> bool:
    """True, если название — сборная из пула ЧМ (не клуб)."""
    want = _norm(name)
    if not want:
        return False
    try:
        from utils.wc_callups import resolve_nation_name

        if resolve_nation_name(name):
            return True
    except Exception:
        pass
    return any(_norm(n) == want for n in _all_nation_names())


def get_nation_strength(nation: str) -> float:
    """Средний overall заявки ЧМ; fallback — топ игроков лиги с этой nation."""
    try:
        from utils.wc_callups import club_players_for_nation, squad_for_nation

        roster = squad_for_nation(nation)
        ovrs = [int(p.get("overall") or 0) for p in roster if int(p.get("overall") or 0) > 0]
        if not ovrs:
            players = club_players_for_nation(nation, limit=26)
            ovrs = [int(p.get("overall") or 0) for p in players if int(p.get("overall") or 0) > 0]
        if not ovrs:
            return 70.0
        return sum(ovrs) / len(ovrs)
    except Exception:
        return 70.0


def compute_nation_prestige(nation: str, hist: dict[str, Any] | None = None) -> TeamPrestige:
    hist = hist or load_history()
    try:
        from utils.wc_callups import resolve_nation_name

        nation_s = resolve_nation_name(nation) or (nation or "").strip()
    except Exception:
        nation_s = (nation or "").strip()
    want = _norm(nation_s)

    wc_titles = 0
    for row in hist.get("world_cup") or []:
        if row and len(row) >= 2 and _norm(str(row[1])) == want:
            wc_titles += 1
    wc_title_pts = wc_titles * WC_TITLE_POINTS

    awards_n = 0
    award_pts = 0.0
    for row in hist.get("world_cup_best") or []:
        if not row or len(row) < 3:
            continue
        if _norm(str(row[2])) != want:
            continue
        awards_n += 1
        award_pts += WC_BEST_POINTS

    ovr = float(get_nation_strength(nation_s))
    roster_pts = max(0.0, ovr - 75.0) * 1.6
    score = wc_title_pts + roster_pts + award_pts
    return TeamPrestige(
        team=nation_s,
        league_code="wc",
        score=round(score, 2),
        league_title_pts=round(wc_title_pts, 2),
        cl_title_pts=0.0,
        cl_stage_pts=0.0,
        roster_pts=round(roster_pts, 2),
        award_pts=round(award_pts, 2),
        league_titles=wc_titles,
        cl_titles=0,
        best_cl_stage=0,
        roster_ovr=round(ovr, 1),
        awards=awards_n,
        breakdown={
            "ЧМ титул": round(wc_title_pts, 2),
            "Состав": round(roster_pts, 2),
            "Лучший ЧМ": round(award_pts, 2),
        },
    )


def rank_nations_by_prestige(*, limit: int | None = None) -> list[TeamPrestige]:
    hist = load_history()
    rows = [compute_nation_prestige(t, hist) for t in _all_nation_names()]
    rows.sort(key=lambda r: (-r.score, r.team.casefold()))
    if limit is not None:
        return rows[: max(1, int(limit))]
    return rows


def nation_legends(nation: str, *, limit: int = 8) -> list[ClubLegend]:
    """Лучшие игроки сборной по сумме статы в world_cup.db архивов + текущего сезона."""
    bucket: dict[str, dict[str, Any]] = {}
    seen_paths: set[str] = set()

    def _add(path: str) -> None:
        ap = os.path.abspath(path) if path else ""
        if not ap or ap in seen_paths:
            return
        seen_paths.add(ap)
        _aggregate_legends_from_sqlite(ap, nation, bucket)

    for sn in list_season_archives_with_db():
        _add(season_paths.get_wc_db_path_for_season(int(sn)))
    try:
        cur = season_paths.get_wc_db_path()
        if cur:
            _add(cur)
    except Exception:
        pass

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


def build_nation_dossier(nation: str) -> ClubDossier:
    hist = load_history()
    try:
        from utils.wc_callups import resolve_nation_name

        nation_s = resolve_nation_name(nation) or (nation or "").strip()
    except Exception:
        nation_s = (nation or "").strip()
    want = _norm(nation_s)
    prestige = compute_nation_prestige(nation_s, hist)

    wc_seasons: list[int] = []
    for row in hist.get("world_cup") or []:
        if row and len(row) >= 2 and _norm(str(row[1])) == want:
            wc_seasons.append(int(row[0]))

    awards: list[tuple[str, int, str]] = []
    for row in hist.get("world_cup_best") or []:
        if not row or len(row) < 3:
            continue
        if _norm(str(row[2])) != want:
            continue
        awards.append(("Лучший ЧМ", int(row[0]), str(row[1])))
    awards.sort(key=lambda x: (-x[1], x[0]))

    return ClubDossier(
        team=nation_s,
        league_code="wc",
        league_title="Сборная",
        prestige=prestige,
        league_titles_by_season=sorted(wc_seasons),
        cl_titles_by_season=[],
        cl_stages=[],
        legends=nation_legends(nation_s, limit=8),
        awards=awards,
        special_cups=[],
    )


def nation_prestige_snapshot_for_season(
    nation: str, season: int, hist: dict[str, Any] | None = None
) -> float:
    hist = hist or load_history()
    want = _norm(nation)
    sn = int(season)
    score = 0.0
    for row in hist.get("world_cup") or []:
        if row and len(row) >= 2 and int(row[0]) == sn and _norm(str(row[1])) == want:
            score += WC_TITLE_POINTS
    for row in hist.get("world_cup_best") or []:
        if row and len(row) >= 3 and int(row[0]) == sn and _norm(str(row[2])) == want:
            score += WC_BEST_POINTS
    return round(score, 2)


def nation_career_goals() -> list[ClubCareerGoals]:
    """Голы сборных только в матчах ЧМ (``league=wc``)."""
    pool = _all_nation_names()
    by_norm: dict[str, dict[str, Any]] = {}
    for name in pool:
        by_norm[_norm(name)] = {"team": name, "league_gf": 0, "cl_gf": 0}

    for m in iter_all_match_records():
        lg = str(m.get("league") or "").strip().lower()
        if lg not in ("wc", "world_cup"):
            continue
        hs = int(m.get("home_score") or 0)
        aws = int(m.get("away_score") or 0)
        for team_raw, gf in ((m.get("home"), hs), (m.get("away"), aws)):
            tn = _norm(str(team_raw or ""))
            if not tn:
                continue
            row = by_norm.get(tn)
            if row is None:
                row = {
                    "team": str(team_raw or "").strip(),
                    "league_gf": 0,
                    "cl_gf": 0,
                }
                by_norm[tn] = row
            row["league_gf"] += gf

    out = [
        ClubCareerGoals(
            team=str(v["team"]),
            league_gf=int(v["league_gf"]),
            cl_gf=0,
        )
        for v in by_norm.values()
    ]
    out.sort(key=lambda r: (-r.total_gf, r.team.casefold()))
    return out


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
    for row in hist.get("world_cup") or []:
        if row:
            seasons.add(int(row[0]))
    for sn, _mp in hist.get("cl_knockout_stages") or []:
        seasons.add(int(sn))
    for kind in (*AWARD_POINTS, "world_cup_best"):
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


_NATIONAL_LEAGUE_CODES = frozenset({"rpl", "eng", "esp", "ita", "ger"})
_CL_LEAGUE_CODES = frozenset({"cl", "champions"})


def _match_in_competition(
    m: dict[str, Any],
    *,
    competition: str,
    league_code: str | None = None,
) -> bool:
    """
    competition: ``league`` — нац. лига; ``cl`` — вся ЛЧ (группа/лига + плей-офф).
    """
    lg = str(m.get("league") or "").strip().lower()
    if competition == "cl":
        if lg in _CL_LEAGUE_CODES:
            return True
        # legacy: фаза ЛЧ без кода лиги
        ph = str(m.get("cl_phase") or "").strip().lower()
        return bool(ph)
    # national league
    if lg in _CL_LEAGUE_CODES:
        return False
    want = (league_code or "").strip().lower()
    if want:
        return lg == want
    return lg in _NATIONAL_LEAGUE_CODES


def campaign_wdl(
    team: str,
    season: int,
    *,
    competition: str,
    league_code: str | None = None,
) -> tuple[int, int, int, int]:
    """``(wins, draws, losses, n)`` по кампании сезона (лига или вся ЛЧ)."""
    w = d = l = 0
    for m in club_matches_in_season(team, season):
        if not _match_in_competition(
            m, competition=competition, league_code=league_code
        ):
            continue
        res, _, _, _ = match_result_for_team(m, team)
        if res == "W":
            w += 1
        elif res == "D":
            d += 1
        else:
            l += 1
    return w, d, l, w + d + l


def campaign_special_cup(
    team: str,
    season: int,
    *,
    competition: str,
    league_code: str | None = None,
    min_matches: int | None = None,
) -> str | None:
    """
    Особый кубок чемпионской кампании:
    - ``platinum`` — без ничьих и поражений (все победы);
    - ``gold`` — без поражений (ничьи допустимы).

    Только если есть достаточно матчей. Для ЛЧ учитываются группа/лига + нокаут.
    """
    if min_matches is None:
        min_matches = 6 if competition == "cl" else 8
    w, d, l, n = campaign_wdl(
        team, season, competition=competition, league_code=league_code
    )
    if n < int(min_matches):
        return None
    if l == 0 and d == 0 and w > 0:
        return "platinum"
    if l == 0 and (w + d) > 0:
        return "gold"
    return None


def special_cups_for_champion(
    team: str,
    season: int,
    *,
    competition: str,
    league_code: str | None = None,
) -> str | None:
    """Алиас для истории чемпионов (лига / ЛЧ)."""
    return campaign_special_cup(
        team,
        season,
        competition=competition,
        league_code=league_code,
    )


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


def _match_chrono_key(m: dict[str, Any]) -> tuple[int, int, str]:
    return (int(m.get("_season") or 0), int(m.get("day") or 0), str(m.get("league") or ""))


def club_match_results_chronological(team: str) -> list[str]:
    """Хронология ``W|D|L`` клуба по всем сезонам (лига + ЛЧ)."""
    want = _norm(team)
    rows = [
        m
        for m in iter_all_match_records()
        if _norm(str(m.get("home") or "")) == want
        or _norm(str(m.get("away") or "")) == want
    ]
    rows.sort(key=_match_chrono_key)
    return [match_result_for_team(m, team)[0] for m in rows]


def club_career_streaks_for(team: str) -> dict[str, int]:
    return compute_result_streaks(club_match_results_chronological(team))


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


def find_pvp_kryptonites(*, min_played: int = 3) -> list[dict[str, Any]]:
    """
    Клубные пары, где одна команда не проигрывала другой ``min_played``+ матчей подряд
    (с учётом всей истории встреч).
    """
    from collections import defaultdict

    pair_matches: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for m in iter_all_match_records():
        home = str(m.get("home") or "").strip()
        away = str(m.get("away") or "").strip()
        if not home or not away:
            continue
        if is_nation_name(home) or is_nation_name(away):
            continue
        key = tuple(sorted((home, away), key=lambda x: _norm(x)))
        pair_matches[key].append(m)

    out: list[dict[str, Any]] = []
    for ta, tb in pair_matches:
        h2h = head_to_head(ta, tb)
        played = int(h2h.get("played") or 0)
        if played < int(min_played):
            continue
        wa, wb, dr = int(h2h["wins_a"]), int(h2h["wins_b"]), int(h2h["draws"])
        losses_a = wb
        losses_b = wa
        base = {
            "played": played,
            "draws": dr,
            "matches": list(h2h.get("matches") or []),
            "goals_a": int(h2h.get("goals_a") or 0),
            "goals_b": int(h2h.get("goals_b") or 0),
        }
        if losses_a == 0 and losses_b == 0:
            out.append(
                {
                    **base,
                    "dominant": ta,
                    "victim": tb,
                    "wins": wa,
                    "losses": 0,
                    "all_draws": True,
                }
            )
            continue
        if losses_a == 0:
            out.append(
                {
                    **base,
                    "dominant": ta,
                    "victim": tb,
                    "wins": wa,
                    "losses": 0,
                    "all_draws": False,
                }
            )
        if losses_b == 0:
            out.append(
                {
                    **base,
                    "dominant": tb,
                    "victim": ta,
                    "wins": wb,
                    "losses": 0,
                    "all_draws": False,
                }
            )

    out.sort(
        key=lambda r: (
            -int(r.get("played") or 0),
            -int(r.get("wins") or 0),
            str(r.get("dominant") or ""),
            str(r.get("victim") or ""),
        )
    )
    return out


def aggregate_pvp_kryptonites_by_team(
    rows: list[dict[str, Any]] | None = None, *, min_played: int = 3
) -> list[dict[str, Any]]:
    """Сводка: сколько kryptonite-серий у каждого клуба и против кого."""
    from collections import defaultdict

    rows = rows if rows is not None else find_pvp_kryptonites(min_played=min_played)
    by_team: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for r in rows:
        dom = str(r.get("dominant") or "").strip()
        vic = str(r.get("victim") or "").strip()
        if not dom or not vic:
            continue
        by_team[dom].append((vic, int(r.get("played") or 0)))

    out: list[dict[str, Any]] = []
    for team, pairs in by_team.items():
        pairs.sort(key=lambda x: (-x[1], x[0].lower()))
        opponents = [name for name, _ in pairs]
        out.append(
            {
                "team": team,
                "count": len(opponents),
                "opponents": opponents,
            }
        )
    out.sort(key=lambda x: (-int(x["count"]), str(x["team"]).lower()))
    return out


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
    if is_nation_name(team):
        return [
            (sn, nation_prestige_snapshot_for_season(team, sn)) for sn in list_history_seasons()
        ]
    return [(sn, prestige_snapshot_for_season(team, sn)) for sn in list_history_seasons()]


def compare_clubs(team_a: str, team_b: str) -> dict[str, Any]:
    """Сравнение двух клубов или двух сборных. Смешанные пары запрещены."""
    a_nat = is_nation_name(team_a)
    b_nat = is_nation_name(team_b)
    if a_nat != b_nat:
        raise ValueError(
            "Сравнивать можно только клуб с клубом или сборную со сборной"
        )
    if a_nat:
        pa = compute_nation_prestige(team_a)
        pb = compute_nation_prestige(team_b)
        da = build_nation_dossier(team_a)
        db = build_nation_dossier(team_b)
    else:
        pa = compute_team_prestige(team_a)
        pb = compute_team_prestige(team_b)
        da = build_club_dossier(team_a)
        db = build_club_dossier(team_b)
    h2h = head_to_head(team_a, team_b)
    return {
        "a": pa,
        "b": pb,
        "dossier_a": da,
        "dossier_b": db,
        "h2h": h2h,
        "kind": "nation" if a_nat else "club",
    }


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


@dataclass
class ClubCareerGoals:
    """Сумма забитых голов клуба по всем сезонам из журналов матчей."""

    team: str
    league_gf: int
    cl_gf: int

    @property
    def total_gf(self) -> int:
        return int(self.league_gf) + int(self.cl_gf)


def club_career_goals(*, pool_only: bool = True) -> list[ClubCareerGoals]:
    """
    Голы всех клубов за все сезоны (из журналов ``match_results``).

    - ``league_gf`` — все турниры кроме ``cl``
    - ``cl_gf`` — Лига чемпионов
    - ``total_gf`` — лига + ЛЧ
    """
    pool = _current_pool_club_names()
    by_norm: dict[str, dict[str, Any]] = {}
    for name in pool:
        by_norm[_norm(name)] = {"team": name, "league_gf": 0, "cl_gf": 0}

    for m in iter_all_match_records():
        lg = str(m.get("league") or "").strip().lower()
        is_cl = lg == "cl"
        hs = int(m.get("home_score") or 0)
        aws = int(m.get("away_score") or 0)
        for team_raw, gf in ((m.get("home"), hs), (m.get("away"), aws)):
            tn = _norm(str(team_raw or ""))
            if not tn:
                continue
            if pool_only and tn not in by_norm:
                continue
            row = by_norm.get(tn)
            if row is None:
                row = {
                    "team": str(team_raw or "").strip().title(),
                    "league_gf": 0,
                    "cl_gf": 0,
                }
                by_norm[tn] = row
            if is_cl:
                row["cl_gf"] += gf
            else:
                row["league_gf"] += gf

    out = [
        ClubCareerGoals(
            team=str(v["team"]),
            league_gf=int(v["league_gf"]),
            cl_gf=int(v["cl_gf"]),
        )
        for v in by_norm.values()
    ]
    out.sort(key=lambda r: (-r.total_gf, -r.league_gf, -r.cl_gf, r.team.casefold()))
    return out


def club_career_goals_for(team: str) -> ClubCareerGoals:
    want = _norm(team)
    for row in club_career_goals(pool_only=False):
        if _norm(row.team) == want:
            return row
    display = team.strip().title() if team else "?"
    return ClubCareerGoals(team=display, league_gf=0, cl_gf=0)


@dataclass
class ClubCareerStreaks:
    """Максимальные серии клуба за всю историю (лига + ЛЧ)."""

    team: str
    unbeaten: int
    wins: int
    losses: int


def club_career_streaks(*, pool_only: bool = True) -> list[ClubCareerStreaks]:
    pool = _current_pool_club_names()
    by_norm: dict[str, str] = {_norm(n): n for n in pool}
    team_norms: set[str] = set(by_norm.keys())
    if not pool_only:
        for m in iter_all_match_records():
            for side in (m.get("home"), m.get("away")):
                tn = _norm(str(side or ""))
                if tn:
                    team_norms.add(tn)

    matches_by_team: dict[str, list[dict[str, Any]]] = {tn: [] for tn in team_norms}
    for m in iter_all_match_records():
        for side in (m.get("home"), m.get("away")):
            tn = _norm(str(side or ""))
            if tn in matches_by_team:
                matches_by_team[tn].append(m)

    out: list[ClubCareerStreaks] = []
    for tn, matches in matches_by_team.items():
        matches.sort(key=_match_chrono_key)
        display = by_norm.get(tn)
        if not display and matches:
            for m in matches:
                if _norm(str(m.get("home") or "")) == tn:
                    display = str(m.get("home") or "").strip()
                    break
                if _norm(str(m.get("away") or "")) == tn:
                    display = str(m.get("away") or "").strip()
                    break
        display = display or tn.title()
        s = compute_result_streaks(
            [match_result_for_team(m, display)[0] for m in matches]
        )
        out.append(
            ClubCareerStreaks(
                team=display,
                unbeaten=int(s["unbeaten"]),
                wins=int(s["wins"]),
                losses=int(s["losses"]),
            )
        )
    return out


def rank_clubs_by_streak(
    kind: str,
    *,
    limit: int = 20,
    pool_only: bool = True,
) -> list[ClubCareerStreaks]:
    """``kind``: ``wins`` | ``losses`` | ``unbeaten``."""
    key = str(kind or "wins").strip().lower()
    if key not in {"wins", "losses", "unbeaten"}:
        raise ValueError("kind must be wins, losses or unbeaten")
    rows = club_career_streaks(pool_only=pool_only)
    rows.sort(key=lambda r: (-getattr(r, key), r.team.casefold()))
    return rows[: max(1, int(limit))]


@dataclass
class ClubCareerConceded:
    """Сумма пропущенных голов клуба по всем сезонам из журналов матчей."""

    team: str
    league_ga: int
    cl_ga: int

    @property
    def total_ga(self) -> int:
        return int(self.league_ga) + int(self.cl_ga)


def club_career_conceded(*, pool_only: bool = True) -> list[ClubCareerConceded]:
    """
    Пропущенные мячи клубов за все сезоны.

    Сортировка: меньше total_ga выше (лучше оборона).
    """
    pool = _current_pool_club_names()
    by_norm: dict[str, dict[str, Any]] = {}
    for name in pool:
        by_norm[_norm(name)] = {"team": name, "league_ga": 0, "cl_ga": 0}

    for m in iter_all_match_records():
        lg = str(m.get("league") or "").strip().lower()
        is_cl = lg == "cl"
        hs = int(m.get("home_score") or 0)
        aws = int(m.get("away_score") or 0)
        # home conceded = away scored; away conceded = home scored
        for team_raw, ga in ((m.get("home"), aws), (m.get("away"), hs)):
            tn = _norm(str(team_raw or ""))
            if not tn:
                continue
            if pool_only and tn not in by_norm:
                continue
            row = by_norm.get(tn)
            if row is None:
                row = {
                    "team": str(team_raw or "").strip().title(),
                    "league_ga": 0,
                    "cl_ga": 0,
                }
                by_norm[tn] = row
            if is_cl:
                row["cl_ga"] += ga
            else:
                row["league_ga"] += ga

    out = [
        ClubCareerConceded(
            team=str(v["team"]),
            league_ga=int(v["league_ga"]),
            cl_ga=int(v["cl_ga"]),
        )
        for v in by_norm.values()
    ]
    out.sort(key=lambda r: (r.total_ga, r.league_ga, r.cl_ga, r.team.casefold()))
    return out


def _club_goal_diff_maps() -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """``(league_gd, cl_gd, total_gd)`` по ``_norm(team)``."""
    league: dict[str, int] = {}
    cl: dict[str, int] = {}
    for m in iter_all_match_records():
        lg = str(m.get("league") or "").strip().lower()
        is_cl = lg == "cl"
        for team in (m.get("home"), m.get("away")):
            tn = _norm(str(team or ""))
            if not tn:
                continue
            _res, _pts, gf, ga = match_result_for_team(m, str(team))
            bucket = cl if is_cl else league
            bucket[tn] = int(bucket.get(tn, 0)) + (gf - ga)
    total = {
        k: int(league.get(k, 0)) + int(cl.get(k, 0))
        for k in set(league) | set(cl)
    }
    return league, cl, total


def _club_sim_records() -> dict[str, dict[str, int]]:
    """Симуляции (оба клуба одного менеджера): wins/draws/losses по клубу."""
    from config.leagues_config import manager_session_label

    out: dict[str, dict[str, int]] = {}
    for m in iter_all_match_records():
        home = str(m.get("home") or "").strip()
        away = str(m.get("away") or "").strip()
        if manager_session_label(home, away) != "Симуляция":
            continue
        for team in (home, away):
            tn = _norm(team)
            slot = out.setdefault(tn, {"w": 0, "d": 0, "l": 0, "played": 0})
            res, _pts, _gf, _ga = match_result_for_team(m, team)
            slot["played"] += 1
            if res == "W":
                slot["w"] += 1
            elif res == "D":
                slot["d"] += 1
            else:
                slot["l"] += 1
    return out


def _club_clean_sheets_total() -> dict[str, int]:
    """Сумма сухих матчей вратарей клуба (лига + ЛЧ, накопительно)."""
    from utils.stats_history_agg import aggregate_life_clean_sheets

    totals: dict[str, int] = {}
    for kwargs in (
        {"league_code": "all", "cl": False},
        {"league_code": None, "cl": True},
    ):
        gk_rows, _df = aggregate_life_clean_sheets(
            kwargs["league_code"],
            cl=bool(kwargs["cl"]),
            merge_by_player=True,
        )
        for r in gk_rows:
            tn = _norm(str(r.get("team") or ""))
            if not tn:
                continue
            totals[tn] = int(totals.get(tn, 0)) + int(r.get("clean_sheets") or 0)
    return totals


def _club_top50_ga_influence() -> dict[str, float]:
    """
    Влияние топ-50 G+A (лига+ЛЧ за всё время): очки ``(51-rank)`` клубу игрока.
    """
    from utils.stats_history_agg import collect_top100_rows

    _scope, rows, _n, err = collect_top100_rows("allcl", limit=50, sort_key=3)
    if err:
        return {}
    out: dict[str, float] = {}
    for i, r in enumerate(rows, start=1):
        tn = _norm(str(r.get("team") or ""))
        if not tn:
            continue
        out[tn] = float(out.get(tn, 0.0)) + float(51 - i)
    return out


def _norm01(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


@dataclass
class ClubAttackRating:
    team: str
    score: float
    league_gf: int
    cl_gf: int
    top50_pts: float
    breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class ClubDefenseRating:
    team: str
    score: float
    league_ga: int
    cl_ga: int
    clean_sheets: int
    goal_diff: int
    sim_losses: int
    sim_played: int
    breakdown: dict[str, float] = field(default_factory=dict)


def rank_clubs_by_attack(*, pool_only: bool = True) -> list[ClubAttackRating]:
    """
    Рейтинг нападения пула.

    Веса (после нормализации 0..1 внутри пула): лиговые голы 40%, голы ЛЧ 35%,
    влияние топ-50 G+A 25%.
    """
    goals = { _norm(r.team): r for r in club_career_goals(pool_only=pool_only) }
    top50 = _club_top50_ga_influence()
    teams = list(goals.values())
    if not teams:
        return []

    lg_vals = [r.league_gf for r in teams]
    cl_vals = [r.cl_gf for r in teams]
    t50_vals = [float(top50.get(_norm(r.team), 0.0)) for r in teams]
    lg_lo, lg_hi = min(lg_vals), max(lg_vals)
    cl_lo, cl_hi = min(cl_vals), max(cl_vals)
    t_lo, t_hi = min(t50_vals), max(t50_vals)

    out: list[ClubAttackRating] = []
    for r in teams:
        tn = _norm(r.team)
        t50 = float(top50.get(tn, 0.0))
        p_lg = _norm01(float(r.league_gf), float(lg_lo), float(lg_hi))
        p_cl = _norm01(float(r.cl_gf), float(cl_lo), float(cl_hi))
        p_t50 = _norm01(t50, float(t_lo), float(t_hi))
        score = 100.0 * (0.40 * p_lg + 0.35 * p_cl + 0.25 * p_t50)
        out.append(
            ClubAttackRating(
                team=r.team,
                score=round(score, 2),
                league_gf=r.league_gf,
                cl_gf=r.cl_gf,
                top50_pts=round(t50, 1),
                breakdown={
                    "Лига голы": round(40.0 * p_lg, 2),
                    "ЛЧ голы": round(35.0 * p_cl, 2),
                    "Топ-50 G+A": round(25.0 * p_t50, 2),
                },
            )
        )
    out.sort(key=lambda x: (-x.score, -x.league_gf - x.cl_gf, x.team.casefold()))
    return out


def rank_clubs_by_defense(*, pool_only: bool = True) -> list[ClubDefenseRating]:
    """
    Рейтинг защиты пула.

    Веса: меньше пропущенных в лиге 25%, в ЛЧ 20%, сухие вратарей 25%,
    разница мячей 15%, меньше поражений в симуляциях 15%.
    """
    conceded = { _norm(r.team): r for r in club_career_conceded(pool_only=pool_only) }
    _lg_gd, _cl_gd, total_gd = _club_goal_diff_maps()
    cs_map = _club_clean_sheets_total()
    sims = _club_sim_records()
    teams = list(conceded.values())
    if not teams:
        return []

    def _sim_loss_rate(tn: str) -> float:
        s = sims.get(tn) or {}
        played = int(s.get("played") or 0)
        if played <= 0:
            return 0.5  # нейтрально, если симов нет
        return float(s.get("l") or 0) / float(played)

    lg_ga = [r.league_ga for r in teams]
    cl_ga = [r.cl_ga for r in teams]
    cs_vals = [int(cs_map.get(_norm(r.team), 0)) for r in teams]
    gd_vals = [int(total_gd.get(_norm(r.team), 0)) for r in teams]
    sim_rates = [_sim_loss_rate(_norm(r.team)) for r in teams]

    # для пропущенных и sim_rate — меньше лучше → инвертируем после norm01
    lg_lo, lg_hi = min(lg_ga), max(lg_ga)
    cl_lo, cl_hi = min(cl_ga), max(cl_ga)
    cs_lo, cs_hi = min(cs_vals), max(cs_vals)
    gd_lo, gd_hi = min(gd_vals), max(gd_vals)
    sr_lo, sr_hi = min(sim_rates), max(sim_rates)

    out: list[ClubDefenseRating] = []
    for r in teams:
        tn = _norm(r.team)
        cs = int(cs_map.get(tn, 0))
        gd = int(total_gd.get(tn, 0))
        s = sims.get(tn) or {}
        sim_l = int(s.get("l") or 0)
        sim_n = int(s.get("played") or 0)
        sr = _sim_loss_rate(tn)

        p_lg = 1.0 - _norm01(float(r.league_ga), float(lg_lo), float(lg_hi))
        p_cl = 1.0 - _norm01(float(r.cl_ga), float(cl_lo), float(cl_hi))
        p_cs = _norm01(float(cs), float(cs_lo), float(cs_hi))
        p_gd = _norm01(float(gd), float(gd_lo), float(gd_hi))
        p_sim = 1.0 - _norm01(sr, float(sr_lo), float(sr_hi))

        score = 100.0 * (
            0.25 * p_lg + 0.20 * p_cl + 0.25 * p_cs + 0.15 * p_gd + 0.15 * p_sim
        )
        out.append(
            ClubDefenseRating(
                team=r.team,
                score=round(score, 2),
                league_ga=r.league_ga,
                cl_ga=r.cl_ga,
                clean_sheets=cs,
                goal_diff=gd,
                sim_losses=sim_l,
                sim_played=sim_n,
                breakdown={
                    "Лига −пр.": round(25.0 * p_lg, 2),
                    "ЛЧ −пр.": round(20.0 * p_cl, 2),
                    "Сухие": round(25.0 * p_cs, 2),
                    "Разн.": round(15.0 * p_gd, 2),
                    "Сим −пор.": round(15.0 * p_sim, 2),
                },
            )
        )
    out.sort(
        key=lambda x: (
            -x.score,
            x.league_ga + x.cl_ga,
            -x.clean_sheets,
            x.team.casefold(),
        )
    )
    return out


def attack_rating_caption() -> str:
    return (
        "Атака = норм. голы лиги (40%) + голы ЛЧ (35%) + "
        "влияние топ-50 G+A лига+ЛЧ (25%)."
    )


def defense_rating_caption() -> str:
    return (
        "Защита = меньше пр. в лиге (25%) и ЛЧ (20%) + сухие вратарей (25%) + "
        "разница мячей (15%) + меньше поражений в симуляциях (15%)."
    )


@dataclass
class PlayerWinInfluence:
    """Оценка влияния игрока на результаты клуба."""

    player: str
    team: str
    position: str
    played: int
    wins: int
    draws: int
    losses: int
    missed_injury: int = 0
    status: str = ""
    mode: str = "heuristic"  # heuristic | lineup
    score: float = 0.0
    goals: int = 0
    assists: int = 0
    clean_sheets: int = 0
    missed_goals: int = 0  # пропущенные у вратаря (карьера в клубе)

    @property
    def win_pct(self) -> float:
        if self.played <= 0:
            return 0.0
        return 100.0 * self.wins / self.played


_DEF_POS = frozenset({"ЦЗ", "ЛЦЗ", "ПЦЗ", "ЛЗ", "ПЗ", "ЛФЗ", "ПФЗ", "CB", "LB", "RB"})
_GK_POS = frozenset({"ВРТ", "ВР", "GK"})


def _club_player_career_stats(team: str) -> dict[str, dict[str, Any]]:
    """Сумма статы игрока в клубе по архивам (лига+ЛЧ, все сезоны)."""
    from utils.cumulative_db import list_season_archives_with_db

    want = _norm(team)
    seasons = set(list_season_archives_with_db())
    try:
        seasons.add(int(season_paths.get_active_season()))
    except Exception:
        pass
    out: dict[str, dict[str, Any]] = {}
    for sn in sorted(seasons):
        base = os.path.join(season_paths.PROJECT_ROOT, "db", f"season_{int(sn)}")
        for dbn in ("league.db", "champions_league.db"):
            path = os.path.join(base, dbn)
            if not os.path.isfile(path):
                continue
            conn = sqlite3.connect(path)
            try:
                specs = (
                    ("forwards", False),
                    ("midfielders", False),
                    ("defenders", True),
                    ("goalkeepers", True),
                )
                for tbl, is_def_gk in specs:
                    try:
                        if tbl == "goalkeepers":
                            cur = conn.execute(
                                "SELECT name, team, position, COALESCE(matches,0), "
                                "0, 0, COALESCE(clean_sheets,0), COALESCE(missed_goals,0) "
                                f"FROM {tbl}"
                            )
                        elif tbl == "defenders":
                            cur = conn.execute(
                                "SELECT name, team, position, COALESCE(matches,0), "
                                "COALESCE(goals,0), COALESCE(assists,0), "
                                "COALESCE(clean_sheets,0), 0 "
                                f"FROM {tbl}"
                            )
                        else:
                            cur = conn.execute(
                                "SELECT name, team, position, COALESCE(matches,0), "
                                "COALESCE(goals,0), COALESCE(assists,0), 0, 0 "
                                f"FROM {tbl}"
                            )
                    except sqlite3.OperationalError:
                        continue
                    for name, tm, pos, m, g, a, cs, mg in cur:
                        if _norm(str(tm or "")) != want:
                            continue
                        nm = (name or "").strip()
                        if not nm:
                            continue
                        key = nm.casefold()
                        slot = out.setdefault(
                            key,
                            {
                                "name": nm,
                                "position": (pos or "").strip().upper(),
                                "matches": 0,
                                "goals": 0,
                                "assists": 0,
                                "clean_sheets": 0,
                                "missed_goals": 0,
                            },
                        )
                        slot["matches"] += int(m or 0)
                        slot["goals"] += int(g or 0)
                        slot["assists"] += int(a or 0)
                        slot["clean_sheets"] += int(cs or 0)
                        slot["missed_goals"] += int(mg or 0)
                        if pos and not slot["position"]:
                            slot["position"] = (pos or "").strip().upper()
            finally:
                conn.close()
    return out


def _influence_stats_raw(pos: str, st: dict[str, Any]) -> float:
    """Сырой вклад статы (чем выше — лучше). Масштаб примерно 0..~3."""
    pos_u = (pos or "").strip().upper()
    db_m = max(1, int(st.get("matches") or 0))
    if pos_u in _GK_POS:
        cs = float(st.get("clean_sheets") or 0)
        mg = float(st.get("missed_goals") or 0)
        # сухари полезны; пропущенные на матч — штраф
        return (cs / db_m) * 2.0 - (mg / db_m) * 0.35
    if pos_u in _DEF_POS:
        cs = float(st.get("clean_sheets") or 0)
        ga = float(st.get("goals") or 0) + float(st.get("assists") or 0)
        return (cs / db_m) * 1.6 + (ga / db_m) * 0.4
    ga = float(st.get("goals") or 0) + float(st.get("assists") or 0)
    return (ga / db_m) * 1.2


def _score_influence_rows(
    rows: list[PlayerWinInfluence],
    *,
    team_win_rate: float,
) -> None:
    """
    Балл влияния (in-place ``score``).

    Win% сжимается к среднему клуба при малой выборке; сильно весим объём
    матчей и доступность (меньше травм); стата — небольшой бонус (≤ ~8%).
    """
    if not rows:
        return
    prior = 20.0
    twr = max(0.0, min(1.0, float(team_win_rate)))
    max_played = max(int(r.played) for r in rows) or 1

    raw_stats = [_influence_stats_raw(r.position, {
        "matches": max(r.played, 1),
        "goals": r.goals,
        "assists": r.assists,
        "clean_sheets": r.clean_sheets,
        "missed_goals": r.missed_goals,
    }) for r in rows]
    # для норм статы используем карьерные матчи из БД если есть — уже в raw
    s_lo, s_hi = min(raw_stats), max(raw_stats)
    s_span = (s_hi - s_lo) if s_hi > s_lo else 1.0

    for r, raw_s in zip(rows, raw_stats):
        n = float(r.played)
        adj_wr = (float(r.wins) + prior * twr) / (n + prior)
        # объём: 21 матч << 67
        volume = n / (n + 28.0)
        volume *= min(1.0, n / max(25.0, 0.45 * max_played))
        avail_den = n + float(r.missed_injury)
        durability = n / avail_den if avail_den > 0 else 0.0
        stats_n = (raw_s - s_lo) / s_span  # 0..1

        score = 100.0 * (
            0.50 * adj_wr
            + 0.28 * volume
            + 0.14 * durability
            + 0.08 * max(0.0, stats_n)
        )
        r.score = round(score, 2)


def _roster_by_season_for_club(team: str) -> dict[int, dict[str, dict[str, str]]]:
    """
    ``{season: {name_norm: {name, position, status}}}`` по архивам + активный сезон.
    Игрок «в клубе» в сезоне, если есть в league.db или champions_league.db.
    """
    from utils.cumulative_db import list_season_archives_with_db

    want = _norm(team)
    seasons = set(list_season_archives_with_db())
    try:
        seasons.add(int(season_paths.get_active_season()))
    except Exception:
        pass
    out: dict[int, dict[str, dict[str, str]]] = {}
    for sn in sorted(seasons):
        bucket: dict[str, dict[str, str]] = {}
        base = os.path.join(season_paths.PROJECT_ROOT, "db", f"season_{int(sn)}")
        for dbn in ("league.db", "champions_league.db"):
            path = os.path.join(base, dbn)
            if not os.path.isfile(path):
                continue
            conn = sqlite3.connect(path)
            try:
                for tbl in ("forwards", "midfielders", "defenders", "goalkeepers"):
                    try:
                        cur = conn.execute(
                            f"SELECT name, position, COALESCE(status, ''), team "
                            f"FROM {tbl} WHERE team IS NOT NULL AND trim(team) != ''"
                        )
                    except sqlite3.OperationalError:
                        continue
                    for name, pos, status, tm in cur:
                        if _norm(str(tm or "")) != want:
                            continue
                        nm = (name or "").strip()
                        if not nm:
                            continue
                        key = nm.casefold()
                        st = (status or "").strip().lower()
                        prev = bucket.get(key)
                        if prev is None:
                            bucket[key] = {
                                "name": nm,
                                "position": (pos or "").strip().upper(),
                                "status": st,
                            }
                        else:
                            # start важнее bench/reserve
                            if st == "start" or (
                                st and prev.get("status") not in ("start",)
                            ):
                                if st == "start" or not prev.get("status"):
                                    prev["status"] = st
                            if pos and not prev.get("position"):
                                prev["position"] = (pos or "").strip().upper()
            finally:
                conn.close()
        if bucket:
            out[int(sn)] = bucket
    return out


def _injuries_for_player_name(name: str) -> list[dict[str, Any]]:
    from utils.player_discipline import _load, _norm as disc_norm

    want = disc_norm(name)
    rows = []
    for inj in (_load().get("injuries") or []):
        nn = str(inj.get("name_norm") or disc_norm(str(inj.get("name") or ""))).strip()
        if nn == want:
            rows.append(inj)
    return rows


def club_player_win_influence(
    team: str,
    *,
    min_played: int = 10,
    limit: int = 25,
    starters_only: bool = False,
) -> list[PlayerWinInfluence]:
    """
    «Эффект Родри» — влияние игрока на результаты клуба:

    - **основа (start)**: матчи клуба сезона минус окна травм (или явный
      лог состава, если есть);
    - **скамейка и резерв** (одинаково): эвристика «все матчи клуба» не
      применяется — берём ``matches`` из БД (карьера в клубе); Win%% без
      лога ≈ средний клуба; явный лог состава по-прежнему учитывается;
    - фильтр выдачи — ``min_played`` (обычно 10+).

    Балл: сжатый Win%% + объём + доступность + чуть статы.
    """
    from utils.player_discipline import (
        _injury_blocks_at_month,
        get_calendar_month,
    )

    display_team = (team or "").strip()
    want = _norm(display_team)
    if not want:
        return []

    roster_by_sn = _roster_by_season_for_club(display_team)
    if not roster_by_sn:
        return []

    career_stats = _club_player_career_stats(display_team)

    # кандидаты: name_norm -> meta
    candidates: dict[str, dict[str, Any]] = {}
    for sn, bucket in roster_by_sn.items():
        for key, meta in bucket.items():
            slot = candidates.setdefault(
                key,
                {
                    "name": meta["name"],
                    "position": meta.get("position") or "",
                    "statuses": set(),
                    "seasons": set(),
                },
            )
            slot["seasons"].add(int(sn))
            st = (meta.get("status") or "").strip().lower()
            if st:
                slot["statuses"].add(st)
            if meta.get("position") and not slot["position"]:
                slot["position"] = meta["position"]

    if starters_only:
        candidates = {
            k: v
            for k, v in candidates.items()
            if "start" in (v.get("statuses") or set())
        }

    # явные присутствия из lineup-лога: (season, home, away, day) -> {name_norm}
    explicit: dict[tuple, set[str]] = {}
    try:
        from utils.match_lineup_log import _load as load_lineups

        for row in load_lineups():
            home = str(row.get("home") or "")
            away = str(row.get("away") or "")
            if _norm(home) != want and _norm(away) != want:
                continue
            key = (
                int(row.get("season") or 0),
                _norm(home),
                _norm(away),
                int(row["day"]) if row.get("day") is not None else -1,
            )
            names = explicit.setdefault(key, set())
            for pl in row.get("players") or []:
                if _norm(str(pl.get("team") or "")) != want:
                    continue
                names.add(str(pl.get("player") or "").strip().casefold())
    except Exception:
        explicit = {}

    # injuries cache
    inj_cache: dict[str, list[dict[str, Any]]] = {}

    def _best_status(statuses: set[str]) -> str:
        if "start" in statuses:
            return "start"
        if "bench" in statuses:
            return "bench"
        if "reserve" in statuses:
            return "reserve"
        return ""

    agg: dict[str, dict[str, Any]] = {
        k: {
            "player": v["name"],
            "position": v.get("position") or "",
            "status": _best_status(v.get("statuses") or set()),
            "w": 0,
            "d": 0,
            "l": 0,
            "n": 0,
            "missed": 0,
            "mode": "heuristic",
            "ever_start": "start" in (v.get("statuses") or set()),
        }
        for k, v in candidates.items()
    }

    team_w = team_d = team_l = 0
    for m in iter_all_match_records():
        home = str(m.get("home") or "")
        away = str(m.get("away") or "")
        if _norm(home) != want and _norm(away) != want:
            continue
        sn = int(m.get("_season") or 0)
        roster = roster_by_sn.get(sn) or {}
        if not roster:
            continue
        day = m.get("day")
        month = get_calendar_month(int(day) if day is not None else None)
        res, _pts, _gf, _ga = match_result_for_team(m, display_team)
        if res == "W":
            team_w += 1
        elif res == "L":
            team_l += 1
        else:
            team_d += 1
        ex_key = (sn, _norm(home), _norm(away), int(day) if day is not None else -1)
        ex_names = explicit.get(ex_key)

        for key, meta in roster.items():
            if key not in agg:
                continue
            season_st = (meta.get("status") or "").strip().lower()
            if starters_only and season_st != "start":
                continue
            slot = agg[key]
            # явный состав на матч — для всех статусов
            if ex_names is not None:
                if key not in ex_names:
                    continue
                slot["lineup_n"] = int(slot.get("lineup_n") or 0) + 1
            else:
                # без лога: «матчи клуба − травмы» только для основы сезона
                if season_st != "start":
                    continue
                inj_list = inj_cache.get(key)
                if inj_list is None:
                    inj_list = _injuries_for_player_name(str(meta.get("name") or ""))
                    inj_cache[key] = inj_list
                blocked = any(
                    _injury_blocks_at_month(inj, month, current_season=sn)
                    for inj in inj_list
                )
                if blocked:
                    slot["missed"] += 1
                    continue

            slot["n"] += 1
            if res == "W":
                slot["w"] += 1
            elif res == "L":
                slot["l"] += 1
            else:
                slot["d"] += 1

    team_n = team_w + team_d + team_l
    team_wr = (team_w / team_n) if team_n else 0.5

    def _apply_db_matches_non_starter(slot: dict[str, Any], db_m: int) -> None:
        """Скамейка и резерв одинаково: объём = matches из БД; Win%% из лога или ≈ клуб."""
        db_m = max(0, int(db_m))
        lineup_n = int(slot.get("lineup_n") or 0)
        counted = int(slot.get("n") or 0)
        if db_m <= 0 and lineup_n <= 0 and counted <= 0:
            slot["n"] = 0
            return
        if lineup_n > 0 and counted > 0:
            tw0 = int(slot["w"])
            td0 = int(slot["d"])
            tl0 = int(slot["l"])
            tot = tw0 + td0 + tl0
            n_use = db_m if db_m > 0 else tot
            if tot > 0 and n_use != tot:
                slot["w"] = int(round(n_use * tw0 / tot))
                slot["d"] = int(round(n_use * td0 / tot))
                slot["l"] = max(0, n_use - slot["w"] - slot["d"])
            slot["n"] = n_use
            slot["mode"] = "lineup+db" if db_m > 0 else "lineup"
            return
        n_use = db_m
        slot["n"] = n_use
        if team_n > 0 and n_use > 0:
            slot["w"] = int(round(n_use * team_w / team_n))
            slot["d"] = int(round(n_use * team_d / team_n))
            slot["l"] = max(0, n_use - slot["w"] - slot["d"])
        else:
            slot["w"] = slot["d"] = slot["l"] = 0
        slot["missed"] = 0
        slot["mode"] = "db"

    out: list[PlayerWinInfluence] = []
    for key, slot in agg.items():
        st = career_stats.get(key) or {}
        db_m = int(st.get("matches") or 0)
        if not bool(slot.get("ever_start")):
            # никогда не был start → скамейка или резерв: только БД (+ лог)
            _apply_db_matches_non_starter(slot, db_m)

        n = int(slot["n"])
        if n < int(min_played):
            continue
        lineup_n = int(slot.get("lineup_n") or 0)
        mode = str(slot.get("mode") or "heuristic")
        if mode == "heuristic" and lineup_n >= max(1, n // 2):
            mode = "lineup"
        pos = str(slot["position"] or st.get("position") or "")
        out.append(
            PlayerWinInfluence(
                player=str(slot["player"]),
                team=display_team,
                position=pos,
                played=n,
                wins=int(slot["w"]),
                draws=int(slot["d"]),
                losses=int(slot["l"]),
                missed_injury=int(slot["missed"]),
                status=str(slot.get("status") or ""),
                mode=mode,
                goals=int(st.get("goals") or 0),
                assists=int(st.get("assists") or 0),
                clean_sheets=int(st.get("clean_sheets") or 0),
                missed_goals=int(st.get("missed_goals") or 0),
            )
        )
    _score_influence_rows(out, team_win_rate=team_wr)
    out.sort(
        key=lambda r: (-r.score, -r.played, -r.wins, r.player.casefold())
    )
    return out[: max(1, int(limit))]


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


_PLAYER_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")


@dataclass
class TitledPlayer:
    """Игрок с командными и личными титулами за карьеру."""

    name: str
    team: str
    position: str
    overall: int
    league_titles: int
    cl_titles: int
    individual_awards: int
    person_id: int | None = None

    @property
    def total_titles(self) -> int:
        return (
            int(self.league_titles)
            + int(self.cl_titles)
            + int(self.individual_awards)
        )


def _titled_merge_key(person_id: Any, name: str, position: str) -> tuple:
    pos = (position or "").strip().upper()
    if person_id is not None:
        try:
            return ("p", int(person_id), pos)
        except (TypeError, ValueError):
            pass
    return ("n", (name or "").strip().casefold(), pos)


def _wc_best_counts_by_player() -> dict[str, int]:
    hist = load_history()
    out: dict[str, int] = {}
    for row in hist.get("world_cup_best") or []:
        if not row or len(row) < 2:
            continue
        p = str(row[1]).strip()
        if p:
            k = p.casefold()
            out[k] = out.get(k, 0) + 1
    return out


def _history_winners_by_season(rows: list[Any] | None) -> dict[int, str]:
    out: dict[int, str] = {}
    for row in rows or []:
        if not row or len(row) < 2:
            continue
        try:
            sn = int(row[0])
        except (TypeError, ValueError):
            continue
        team = str(row[1] or "").strip()
        if team:
            out[sn] = team
    return out


def _bucket_ensure_player(
    bucket: dict[tuple, dict[str, Any]],
    key: tuple,
    *,
    name: str,
    team: str,
    position: str,
    overall: int,
    person_id: Any,
) -> dict[str, Any]:
    row = bucket.get(key)
    if row is None:
        row = {
            "name": name,
            "team": team,
            "position": position,
            "overall": int(overall or 0),
            "person_id": int(person_id) if person_id is not None else None,
            "league_titles": 0,
            "cl_titles": 0,
            "individual_awards": 0,
            "league_titles_by_club": {},
            "cl_titles_by_club": {},
        }
        bucket[key] = row
        return row
    if int(overall or 0) > int(row.get("overall") or 0):
        row["overall"] = int(overall or 0)
    if name:
        row["name"] = name
    if team:
        row["team"] = team
    if position:
        row["position"] = position
    if person_id is not None:
        row["person_id"] = int(person_id)
    row.setdefault("league_titles_by_club", {})
    row.setdefault("cl_titles_by_club", {})
    return row


def _inc_club_title_counter(row: dict[str, Any], field: str, club: str) -> None:
    by_club: dict[str, int] = row.setdefault(field, {})
    ck = _norm(club)
    by_club[ck] = int(by_club.get(ck, 0)) + 1


def _club_title_count(row: dict[str, Any], field: str, club: str) -> int:
    by_club = row.get(field) or {}
    return int(by_club.get(_norm(club), 0))


def _award_titles_to_winner_squad(
    bucket: dict[tuple, dict[str, Any]],
    season_num: int,
    winner: str,
    *,
    cl: bool,
) -> None:
    """+1 титул каждому игроку заявки чемпиона (по ``season_history`` + архив сезона)."""
    from utils.player_trophies import (
        iter_squad_rows_in_db,
        season_tournament_db_path,
        teams_matching_winner,
    )

    path = season_tournament_db_path(int(season_num), cl=cl)
    if not path:
        return
    field = "cl_titles" if cl else "league_titles"
    club_field = "cl_titles_by_club" if cl else "league_titles_by_club"
    for team_label in teams_matching_winner(path, winner):
        for name, pos, pid, team, ovr in iter_squad_rows_in_db(path, team_label):
            key = _titled_merge_key(pid, name, pos)
            row = _bucket_ensure_player(
                bucket,
                key,
                name=name,
                team=team,
                position=pos,
                overall=ovr,
                person_id=pid,
            )
            row[field] = int(row.get(field) or 0) + 1
            _inc_club_title_counter(row, club_field, team_label)


def _scan_synced_golden_awards(db_path: str) -> dict[tuple, dict[str, Any]]:
    """Золотые награды и метаданные из common_synced."""
    if not db_path or not os.path.isfile(db_path):
        return {}
    out: dict[tuple, dict[str, Any]] = {}
    conn = sqlite3.connect(db_path)
    try:
        for tbl in _PLAYER_TABLES:
            is_gk = tbl == "goalkeepers"
            cols = (
                "name, team, position, overall, person_id, "
                "COALESCE(golden_balls,0), COALESCE(golden_boots,0), "
                "COALESCE(golden_boys,0)"
            )
            if is_gk:
                cols += ", COALESCE(golden_gloves,0)"
            try:
                cur = conn.execute(f"SELECT {cols} FROM {tbl}")
            except sqlite3.OperationalError:
                continue
            for row in cur:
                if is_gk:
                    name, team, pos, ovr, pid, gb, gbo, gby, gg = row
                else:
                    name, team, pos, ovr, pid, gb, gbo, gby = row
                    gg = 0
                awards = int(gb or 0) + int(gbo or 0) + int(gby or 0) + int(gg or 0)
                key = _titled_merge_key(pid, str(name or ""), str(pos or ""))
                prev = out.get(key)
                if prev is None:
                    out[key] = {
                        "name": str(name or "").strip(),
                        "team": str(team or "").strip().title(),
                        "position": str(pos or "").strip().upper(),
                        "overall": int(ovr or 0),
                        "person_id": int(pid) if pid is not None else None,
                        "golden_awards": awards,
                    }
                else:
                    prev["golden_awards"] = int(prev.get("golden_awards") or 0) + awards
                    if int(ovr or 0) > int(prev.get("overall") or 0):
                        prev["overall"] = int(ovr or 0)
                    if str(name or "").strip():
                        prev["name"] = str(name).strip()
                    if str(team or "").strip():
                        prev["team"] = str(team).strip().title()
    finally:
        conn.close()
    return out


def _build_titled_players_bucket() -> dict[tuple, dict[str, Any]]:
    """
    Командные титулы — победители из ``season_history.json`` × заявка сезона.
    Личные награды — ``common_synced`` + лучший игрок ЧМ из истории.
    """
    from utils import season_paths

    hist = load_history()
    bucket: dict[tuple, dict[str, Any]] = {}

    for _code, rows in (hist.get("league_winners") or {}).items():
        for sn, winner in _history_winners_by_season(rows).items():
            _award_titles_to_winner_squad(bucket, sn, winner, cl=False)

    for sn, winner in _history_winners_by_season(
        hist.get("champions_league")
    ).items():
        _award_titles_to_winner_squad(bucket, sn, winner, cl=True)

    meta = _scan_synced_golden_awards(season_paths.get_cumulative_common_db_path())
    wc_best = _wc_best_counts_by_player()

    for key, m in meta.items():
        name = str(m.get("name") or "").strip()
        if not name:
            continue
        ga = int(m.get("golden_awards") or 0) + int(wc_best.get(name.casefold(), 0))
        if key in bucket:
            row = bucket[key]
            row["individual_awards"] = ga
            if int(m.get("overall") or 0) > int(row.get("overall") or 0):
                row["overall"] = int(m.get("overall") or 0)
            if m.get("person_id") is not None:
                row["person_id"] = m.get("person_id")
        elif ga > 0:
            bucket[key] = {
                "name": name,
                "team": str(m.get("team") or "").strip().title() or "—",
                "position": str(m.get("position") or "").strip().upper() or "—",
                "overall": int(m.get("overall") or 0),
                "person_id": m.get("person_id"),
                "league_titles": 0,
                "cl_titles": 0,
                "individual_awards": ga,
            }

    # wc_best для игроков, уже попавших в bucket только с командными титулами
    for row in bucket.values():
        if int(row.get("individual_awards") or 0) > 0:
            continue
        name = str(row.get("name") or "").strip()
        extra = int(wc_best.get(name.casefold(), 0))
        if extra:
            row["individual_awards"] = extra

    rows = list(bucket.values())
    rows = [r for r in rows if _row_has_any_title(r)]
    if rows:
        from utils.stats_history_agg import _apply_active_season_club_labels

        _apply_active_season_club_labels(rows)
    return { _titled_merge_key(r.get("person_id"), r["name"], r["position"]): r for r in rows }


def _row_has_any_title(row: dict[str, Any]) -> bool:
    return (
        int(row.get("league_titles") or 0)
        + int(row.get("cl_titles") or 0)
        + int(row.get("individual_awards") or 0)
    ) > 0


def _titled_players_from_bucket(
    bucket: dict[tuple, dict[str, Any]],
    *,
    min_total: int = 1,
    team: str | None = None,
    at_club: bool = False,
) -> list[TitledPlayer]:
    want = _norm(team) if team else None
    out: list[TitledPlayer] = []
    for b in bucket.values():
        if at_club and want:
            lt = _club_title_count(b, "league_titles_by_club", want)
            ct = _club_title_count(b, "cl_titles_by_club", want)
            ia = int(b.get("individual_awards") or 0)
            team_titles = lt + ct
            if team_titles < int(min_total):
                continue
            tp = TitledPlayer(
                name=str(b.get("name") or ""),
                team=str(b.get("team") or "—"),
                position=str(b.get("position") or "—"),
                overall=int(b.get("overall") or 0),
                league_titles=lt,
                cl_titles=ct,
                individual_awards=ia,
                person_id=b.get("person_id"),
            )
        else:
            tp = TitledPlayer(
                name=str(b.get("name") or ""),
                team=str(b.get("team") or "—"),
                position=str(b.get("position") or "—"),
                overall=int(b.get("overall") or 0),
                league_titles=int(b.get("league_titles") or 0),
                cl_titles=int(b.get("cl_titles") or 0),
                individual_awards=int(b.get("individual_awards") or 0),
                person_id=b.get("person_id"),
            )
            if tp.total_titles < int(min_total):
                continue
        out.append(tp)
    out.sort(
        key=lambda x: (
            -x.total_titles,
            -x.league_titles,
            -x.cl_titles,
            -x.individual_awards,
            x.name.casefold(),
        )
    )
    return out


_titled_players_cache: dict[tuple, dict[str, Any]] | None = None


def _titled_players_bucket_cached() -> dict[tuple, dict[str, Any]]:
    global _titled_players_cache
    if _titled_players_cache is None:
        _titled_players_cache = _build_titled_players_bucket()
    return _titled_players_cache


def clear_titled_players_cache() -> None:
    """Сброс кэша (тесты / после финализации сезона)."""
    global _titled_players_cache
    _titled_players_cache = None


def titled_players_global(*, min_total: int = 3) -> list[TitledPlayer]:
    """Все игроки с ``min_total``+ титулов (лига + ЛЧ + личные награды)."""
    return _titled_players_from_bucket(
        _titled_players_bucket_cached(),
        min_total=min_total,
    )


def titled_players_for_team(team: str, *, min_total: int = 1) -> list[TitledPlayer]:
    """Игроки с ``min_total``+ **командных** титулов, выигранных в этом клубе."""
    return _titled_players_from_bucket(
        _titled_players_bucket_cached(),
        min_total=min_total,
        team=team,
        at_club=True,
    )
