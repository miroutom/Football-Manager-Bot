# -*- coding: utf-8 -*-
"""
Рекомендации по трансферу / удержанию игрока в клубе N.

Вердикты: НО (надо остаться), СО (стоит остаться), СУ (стоит уходить), НУ (надо уходить).
Метки: Т− трофеи, П↓ продуктивность, З+ избыток на позиции, С× не в схему.

Стата и трофеи — только за отрезок в текущем клубе (архивы сезонов + активный сезон).
Трофеи: лига (вес 1.0) + ЛЧ (вес W_CL).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from player_stats import LEAGUE_TEAMS, national_league_code_for_team
from utils import season_paths
from utils.player_names import player_display_name, player_surname
from utils.player_transfer import _filter_team, _norm_cmp
from utils.team_registry import club_trophy_ambition, get_league, teams_in_league
from utils.team_strength import get_teams_sorted_by_strength

_ALL = (Forward, Midfielder, Defender, Goalkeeper)
_GOALKEEPER_POS = frozenset({"ВРТ"})
# Позиции, где высокая продуктивность = «тащит» команду (не ЦЗ/ЛЗ/ПЗ).
_CARRY_POSITIONS = frozenset({"ФРВ", "ЛФА", "ПФА", "ЦАП"})

W_CL = 1.75
MIN_SEASONS_TROPHY_RULE = 2
# Относительный дефицит трофеев (t_deficit / t_exp_player) для метки Т−.
_TROPHY_REL_DEFICIT_BADGE = 0.58
_TROPHY_SENSITIVITY_BADGE = 0.22

VERDICT_NO = "НО"
VERDICT_SO = "СО"
VERDICT_SU = "СУ"
VERDICT_NU = "НУ"

_BADGE_TROPHY = "Т−"
_BADGE_PROD = "П↓"
_BADGE_DEPTH = "З+"
_BADGE_FIT = "С×"

_VERDICT_ORDER = {VERDICT_NU: 0, VERDICT_SU: 1, VERDICT_SO: 2, VERDICT_NO: 3}


@dataclass
class ClubStintStats:
    seasons: int = 0
    matches: int = 0
    goals: int = 0
    assists: int = 0
    ga: int = 0
    clean_sheets: int = 0
    missed_goals: int = 0
    league_trophies: int = 0
    cl_trophies: int = 0
    play_seasons: int = 0
    completed_play_seasons: int = 0
    season_nums: list[int] = field(default_factory=list)
    ovr_first: int | None = None
    ovr_last_completed: int | None = None

    @property
    def trophy_value(self) -> float:
        return float(self.league_trophies) + W_CL * float(self.cl_trophies)

    @property
    def ovr_delta(self) -> int:
        if self.ovr_first is None or self.ovr_last_completed is None:
            return 0
        return int(self.ovr_last_completed) - int(self.ovr_first)


@dataclass
class TransferAdviceRow:
    name: str
    position: str
    overall: int
    verdict: str
    badges: list[str] = field(default_factory=list)
    score: float = 50.0
    depth_rank: int = 1
    person_id: int | None = None
    is_goalkeeper: bool = False

    def label_short(self) -> str:
        parts = [self.verdict, *self.badges]
        return " · ".join(parts)

    def line_text(self) -> str:
        sur = (player_surname(self.name) or self.name).strip()
        badge = (" · " + " ".join(self.badges)) if self.badges else ""
        return f"{self.verdict}{badge}  {sur} {self.position} {self.overall}"


def _norm_team(team: str) -> str:
    t = (team or "").strip()
    if t.casefold() == "цска":
        return "Цска"
    return t


def _is_gk(position: str) -> bool:
    return (position or "").strip().upper() in _GOALKEEPER_POS


def _player_fits_formation(position: str, slots: tuple[Any, ...]) -> bool:
    from bot.squad_pitch import _Pl, _player_fits_slot

    pos = (position or "").strip()
    if not pos:
        return False
    stub = _Pl(name="", position=pos, overall=0, tags=set(), score=0, nation=None)
    for slot in slots:
        if _player_fits_slot(stub, slot):
            return True
    return False


def _league_strength_rank(team: str, league_code: str | None) -> int:
    if not league_code:
        return 99
    reg = teams_in_league(league_code, active_only=False)
    if reg:
        names = [t.name for t in reg]
    else:
        names = LEAGUE_TEAMS.get(league_code) or []
    if not names:
        return 99
    ranked = get_teams_sorted_by_strength(names, "league")
    want = _norm_cmp(_norm_team(team))
    for i, (t, _s) in enumerate(ranked, start=1):
        if _norm_cmp(t) == want:
            return i
    return 99


def _win_prob_league(rank: int) -> float:
    if rank <= 3:
        return 0.32
    if rank <= 5:
        return 0.18
    if rank <= 8:
        return 0.10
    return 0.04


def _win_prob_cl(rank: int) -> float:
    if rank <= 3:
        return 0.12
    if rank <= 8:
        return 0.06
    if rank <= 15:
        return 0.03
    return 0.01


def _cl_strength_rank(team: str) -> int | None:
    from utils.common_db import _team_in_cl_pool

    if not _team_in_cl_pool(team):
        return None
    from champions_league.cl_format import get_cl_participants

    names = list(get_cl_participants())
    if not names:
        return None
    ranked = get_teams_sorted_by_strength(names, "league")
    want = _norm_cmp(_norm_team(team))
    for i, (t, _s) in enumerate(ranked, start=1):
        if _norm_cmp(t) == want:
            return i
    return len(ranked) + 1


def _league_cl_scale(league_code: str | None) -> float:
    lg = get_league((league_code or "").strip().lower())
    if lg is None:
        return 0.65
    return float(lg.cl_scale)


def _player_ambition(
    *,
    ovr: int,
    depth_rank: int,
    skill_norm: float,
    fit: bool,
) -> float:
    """0..1 — насколько этому игроку важны трофеи (роль + скилл + рейтинг)."""
    ovr_n = max(0.0, min(1.0, (int(ovr) - 68) / 22.0))
    if depth_rank <= 1:
        role = 1.0
    elif depth_rank == 2:
        role = 0.58
    elif depth_rank == 3:
        role = 0.28
    else:
        role = 0.08
    skill = max(0.0, min(1.0, (float(skill_norm) + 2.0) / 4.0))
    fit_v = 1.0 if fit else 0.50
    return max(0.05, min(1.0, 0.26 * ovr_n + 0.40 * role + 0.22 * skill + 0.12 * fit_v))


def _trophy_sensitivity(
    *,
    team: str,
    ovr: int,
    depth_rank: int,
    skill_norm: float,
    fit: bool,
) -> tuple[float, float, float]:
    """(club_amb, player_amb, combined) — лига × тир клуба × профиль игрока."""
    club = club_trophy_ambition(team)
    player = _player_ambition(ovr=ovr, depth_rank=depth_rank, skill_norm=skill_norm, fit=fit)
    return club, player, club * player


def _expected_trophies(
    seasons: int,
    *,
    league_rank: int,
    cl_rank: int | None,
    league_code: str | None,
    club_ambition: float,
) -> float:
    if seasons <= 0 or club_ambition <= 0:
        return 0.0
    cl_scale = _league_cl_scale(league_code)
    p_l = _win_prob_league(league_rank)
    p_c = _win_prob_cl(cl_rank) if cl_rank is not None else 0.0
    return seasons * club_ambition * (p_l * 1.0 + p_c * W_CL * cl_scale)


def _seasons_player_at_team(
    team: str, *, person_id: int | None, name: str
) -> list[int]:
    """Номера сезонов, где игрок числился в клубе (league.db)."""
    team_n = _norm_team(team)
    want_name = _norm_cmp(name)
    out: list[int] = []
    active = int(season_paths.get_state().get("active_season") or 1)
    from utils.cumulative_db import list_season_archives_with_db

    season_nums = sorted(set(list_season_archives_with_db()) | {active})
    db_root = os.path.join(season_paths.PROJECT_ROOT, "db")

    for sn in season_nums:
        lp = os.path.join(db_root, f"season_{sn}", season_paths.SEASON_LEAGUE_NAME)
        if not os.path.isfile(lp):
            continue
        eng = create_engine(f"sqlite:///{lp}")
        S = sessionmaker(bind=eng)
        sess = S()
        try:
            found = False
            for Cls in _ALL:
                for r in sess.query(Cls).filter(_filter_team(Cls, team_n)).all():
                    if person_id is not None and getattr(r, "person_id", None) == person_id:
                        found = True
                        break
                    if _norm_cmp(getattr(r, "name", "") or "") == want_name:
                        found = True
                        break
                if found:
                    break
            if found:
                out.append(sn)
        finally:
            sess.close()
            eng.dispose()
    return out


def _row_stats_snapshot(row: Any) -> dict[str, int]:
    m = int(getattr(row, "matches", 0) or 0)
    if _is_gk(getattr(row, "position", "") or ""):
        return {
            "matches": m,
            "clean_sheets": int(getattr(row, "clean_sheets", 0) or 0),
            "missed_goals": int(getattr(row, "missed_goals", 0) or 0),
            "ga": 0,
            "goals": 0,
            "assists": 0,
        }
    g = int(getattr(row, "goals", 0) or 0)
    a = int(getattr(row, "assists", 0) or 0)
    ga = int(getattr(row, "ga", 0) or 0) or (g + a)
    return {
        "matches": m,
        "goals": g,
        "assists": a,
        "ga": ga,
        "clean_sheets": 0,
        "missed_goals": 0,
    }


def _find_row_in_season_db(
    league_path: str, team: str, *, person_id: int | None, name: str
) -> Any | None:
    team_n = _norm_team(team)
    want_name = _norm_cmp(name)
    eng = create_engine(f"sqlite:///{league_path}")
    S = sessionmaker(bind=eng)
    sess = S()
    try:
        best: Any | None = None
        best_key = (-1, -1)
        for Cls in _ALL:
            for r in sess.query(Cls).filter(_filter_team(Cls, team_n)).all():
                if person_id is not None and getattr(r, "person_id", None) == person_id:
                    k = (2, int(getattr(r, "matches", 0) or 0))
                elif _norm_cmp(getattr(r, "name", "") or "") == want_name:
                    k = (1, int(getattr(r, "matches", 0) or 0))
                else:
                    continue
                if k > best_key:
                    best_key = k
                    best = r
        return best
    finally:
        sess.close()
        eng.dispose()


def _collect_club_stint_stats(
    team: str, *, person_id: int | None, name: str, league_code: str | None
) -> ClubStintStats:
    from bot.season_history_store import load_history

    seasons = _seasons_player_at_team(team, person_id=person_id, name=name)
    stint = ClubStintStats(seasons=len(seasons), season_nums=list(seasons))
    db_root = os.path.join(season_paths.PROJECT_ROOT, "db")
    team_n = _norm_team(team)
    active = int(season_paths.get_state().get("active_season") or 1)

    for sn in seasons:
        lp = os.path.join(db_root, f"season_{sn}", season_paths.SEASON_LEAGUE_NAME)
        row = _find_row_in_season_db(
            lp, team_n, person_id=person_id, name=name
        )
        if row is None:
            continue
        snap = _row_stats_snapshot(row)
        m = int(snap["matches"])
        ovr = int(getattr(row, "overall", 0) or 0)
        stint.matches += m
        stint.goals += snap["goals"]
        stint.assists += snap["assists"]
        stint.ga += snap["ga"]
        stint.clean_sheets += snap["clean_sheets"]
        stint.missed_goals += snap["missed_goals"]
        if m > 0:
            stint.play_seasons += 1
            if stint.ovr_first is None and ovr > 0:
                stint.ovr_first = ovr
            completed = (sn < active) or (sn == active and m >= 3)
            if completed and m >= 3:
                stint.completed_play_seasons += 1
                if ovr > 0:
                    stint.ovr_last_completed = ovr

    hist = load_history()
    for sn in seasons:
        if league_code:
            rows = hist.get("league_winners", {}).get(league_code) or []
            if isinstance(rows, list):
                for item in rows:
                    if not item or len(item) < 2:
                        continue
                    if int(item[0]) == sn and _norm_cmp(str(item[1])) == _norm_cmp(team_n):
                        stint.league_trophies += 1
                        break
        cl_rows = hist.get("champions_league") or []
        if isinstance(cl_rows, list):
            for item in cl_rows:
                if not item or len(item) < 2:
                    continue
                if int(item[0]) == sn and _norm_cmp(str(item[1])) == _norm_cmp(team_n):
                    stint.cl_trophies += 1
                    break

    return stint


def _league_expected_rates(session) -> dict[tuple[str, int], float]:
    """(позиция, overall_bucket) → медиана ga/matches или cs/matches."""
    buckets: dict[tuple[str, int, str], list[float]] = {}
    for Cls in _ALL:
        for r in session.query(Cls).all():
            pos = (getattr(r, "position", "") or "").strip().upper()
            ovr = int(getattr(r, "overall", 0) or 0)
            if not pos or ovr <= 0:
                continue
            m = int(getattr(r, "matches", 0) or 0)
            if m <= 0:
                continue
            bucket = (ovr // 3) * 3
            if _is_gk(pos):
                rate = int(getattr(r, "clean_sheets", 0) or 0) / m
                kind = "cs"
            else:
                ga = int(getattr(r, "ga", 0) or 0)
                if ga <= 0:
                    g = int(getattr(r, "goals", 0) or 0)
                    a = int(getattr(r, "assists", 0) or 0)
                    ga = g + a
                rate = ga / m
                kind = "ga"
            buckets.setdefault((pos, bucket, kind), []).append(rate)

    out: dict[tuple[str, int], float] = {}
    for (pos, bucket, kind), vals in buckets.items():
        if vals:
            out[(pos, bucket, kind)] = median(vals)
    return out


def _expected_rate(
    position: str, overall: int, expected: dict[tuple[str, int], float], *, kind: str
) -> float:
    pos = (position or "").strip().upper()
    bucket = (int(overall) // 3) * 3
    for delta in (0, -3, 3, -6, 6):
        v = expected.get((pos, bucket + delta, kind))
        if v is not None and v > 0:
            return v
    return 0.35 if kind == "ga" else 0.25


def _depth_ranks(roster: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    by_pos: dict[str, list[dict[str, Any]]] = {}
    for p in roster:
        pos = (p.get("position") or "").strip().upper()
        by_pos.setdefault(pos, []).append(p)
    ranks: dict[tuple[str, str], int] = {}
    for pos, players in by_pos.items():
        players.sort(
            key=lambda x: (-int(x.get("overall") or 0), (x.get("name") or "").lower())
        )
        for i, pl in enumerate(players, start=1):
            key = (_norm_cmp(pl.get("name") or ""), pos)
            ranks[key] = i
    return ranks


def _expected_league_place(team: str) -> float:
    from utils.team_registry import get_team

    tm = get_team(team)
    if tm is None:
        return 5.0
    tier = max(1, min(5, int(tm.trophy_tier)))
    return {5: 2.0, 4: 4.0, 3: 6.0, 2: 8.0, 1: 10.0}.get(tier, 5.0)


def _load_league_teams_dict(league_code: str, season_num: int) -> dict[str, Any] | None:
    import pickle

    from bot.services import ARCHIVE_PICKLE_BY_LEAGUE

    code = (league_code or "").strip().lower()
    pkl_name = ARCHIVE_PICKLE_BY_LEAGUE.get(code)
    if not pkl_name:
        return None
    active = int(season_paths.get_state().get("active_season") or 1)
    if season_num >= active:
        import teams as teams_mod

        live = {
            "rpl": teams_mod.teams_rpl,
            "eng": teams_mod.teams_eng,
            "esp": teams_mod.teams_spain,
            "ita": teams_mod.teams_italy,
            "ger": teams_mod.teams_germany,
        }
        return live.get(code)
    base = season_paths.season_archive_directory(season_num)
    pkl_path = os.path.join(base, "pickle", pkl_name)
    if not os.path.isfile(pkl_path):
        return None
    with open(pkl_path, "rb") as f:
        return pickle.load(f)


def _team_league_places_during_seasons(
    team: str, league_code: str | None, season_nums: list[int]
) -> list[int]:
    from teams import get_sorted_teams

    if not league_code or not season_nums:
        return []
    want = _norm_cmp(_norm_team(team))
    places: list[int] = []
    for sn in sorted(set(int(x) for x in season_nums)):
        teams_dict = _load_league_teams_dict(league_code, sn)
        if not teams_dict:
            continue
        ranked = get_sorted_teams(teams_dict)
        for i, (name, t) in enumerate(ranked, start=1):
            if _norm_cmp(name) != want:
                continue
            if int(getattr(t, "matches", 0) or 0) <= 0:
                break
            places.append(i)
            break
    return places


def _finish_frustration(places: list[int], expected_place: float) -> float:
    if not places:
        return 0.0
    deficits = [max(0.0, float(p) - float(expected_place)) for p in places]
    avg_def = sum(deficits) / len(deficits)
    return max(0.0, min(1.0, avg_def / 3.0))


def _frustrated_star_pressure(
    *,
    position: str,
    club_amb: float,
    completed_play_seasons: int,
    finish_frust: float,
    depth_rank: int,
    prod_ratio: float,
    ovr_delta: int,
    player_amb: float,
) -> float:
    """
    Давление «уходить» для основы, которая тащит, но клуб стабильно ниже ожиданий.
    Возвращает отрицательную поправку к score (0 или < 0).
    """
    if (position or "").strip().upper() not in _CARRY_POSITIONS:
        return 0.0
    if completed_play_seasons < 2 or depth_rank > 2 or finish_frust < 0.30:
        return 0.0

    carry = 0.0
    if prod_ratio >= 0.82:
        carry += 0.40
    if prod_ratio >= 1.0:
        carry += 0.28
    if ovr_delta >= 3:
        carry += 0.22
    elif ovr_delta >= 1:
        carry += 0.12
    elif ovr_delta < -1:
        carry -= 0.20
    carry = max(0.0, min(1.0, carry))
    if carry < 0.30:
        return 0.0

    tenure = min(1.0, completed_play_seasons / 2.0)
    intensity = club_amb * finish_frust * carry * tenure * max(0.45, player_amb)
    return -40.0 * intensity


def _tenure_trophy_factor(completed_play_seasons: int) -> float:
    """Смягчение трофейного давления для недавних приходов."""
    if completed_play_seasons <= 0:
        return 0.15
    if completed_play_seasons == 1:
        return 0.32
    if completed_play_seasons == 2:
        return 0.78
    return 1.0


def _score_to_verdict(score: float) -> str:
    if score >= 72:
        return VERDICT_NO
    if score >= 55:
        return VERDICT_SO
    if score >= 38:
        return VERDICT_SU
    return VERDICT_NU


def _compute_advice_for_player(
    *,
    team: str,
    player: dict[str, Any],
    depth_rank: int,
    team_median_by_pos: dict[str, float],
    team_median_overall: float,
    league_rank: int,
    cl_rank: int | None,
    league_code: str | None,
    slots: tuple[Any, ...],
    expected_rates: dict[tuple[str, int], float],
    stint: ClubStintStats,
) -> TransferAdviceRow:
    name = str(player.get("name") or "")
    pos = (player.get("position") or "").strip().upper()
    ovr = int(player.get("overall") or 0)
    pid = player.get("person_id")
    is_gk = _is_gk(pos)
    badges: list[str] = []

    fit = _player_fits_formation(pos, slots)
    if not fit:
        badges.append(_BADGE_FIT)

    depth_surplus = (is_gk and depth_rank >= 2) or (not is_gk and depth_rank >= 3)
    if depth_surplus:
        badges.append(_BADGE_DEPTH)

    med = team_median_by_pos.get(pos, float(ovr))
    skill_norm = max(-2.0, min(2.0, (ovr - med) / 5.0))

    club_amb, player_amb, trophy_sens = _trophy_sensitivity(
        team=team,
        ovr=ovr,
        depth_rank=depth_rank,
        skill_norm=skill_norm,
        fit=fit,
    )

    if depth_rank <= 1:
        role_pts = 2.0
    elif depth_rank == 2:
        role_pts = 1.0
    elif depth_rank == 3:
        role_pts = 0.0
    else:
        role_pts = -2.0

    seasons = max(1, stint.seasons) if stint.matches > 0 else max(stint.seasons, 0)
    per_season_rates: list[float] = []
    if stint.seasons > 0 and stint.matches > 0:
        if is_gk:
            per_season_rates.append(stint.clean_sheets / max(stint.matches, 1))
        else:
            per_season_rates.append(stint.ga / max(stint.matches, 1))

    if is_gk:
        actual_rate = (
            per_season_rates[0]
            if per_season_rates
            else (stint.clean_sheets / max(stint.matches, 1))
        )
        exp_rate = _expected_rate(pos, ovr, expected_rates, kind="cs")
        missed_rate = stint.missed_goals / max(stint.matches, 1)
        prod_ratio = actual_rate / exp_rate if exp_rate > 0 else (1.0 if actual_rate > 0 else 0.5)
        prod_norm = max(-2.0, min(2.0, (prod_ratio - 1.0) * 2.0))
        if missed_rate > 1.2:
            prod_norm -= 0.5
    else:
        actual_rate = (
            per_season_rates[0]
            if per_season_rates
            else (stint.ga / max(stint.matches, 1))
        )
        exp_rate = _expected_rate(pos, ovr, expected_rates, kind="ga")
        prod_ratio = actual_rate / exp_rate if exp_rate > 0 else (1.0 if actual_rate > 0 else 0.5)
        prod_norm = max(-2.0, min(2.0, (prod_ratio - 1.0) * 2.0))

    if prod_ratio < 0.6 and stint.matches >= 3:
        prod_gate = 0.45 + 0.40 * player_amb
        if prod_ratio < prod_gate and _BADGE_PROD not in badges:
            badges.append(_BADGE_PROD)

    trophy_seasons = max(stint.completed_play_seasons, 0)
    tenure_tf = _tenure_trophy_factor(stint.completed_play_seasons)
    ovr_delta_live = (
        (ovr - int(stint.ovr_first))
        if stint.ovr_first is not None
        else stint.ovr_delta
    )
    finish_places = _team_league_places_during_seasons(
        team, league_code, stint.season_nums
    )
    finish_frust = _finish_frustration(
        finish_places, _expected_league_place(team)
    )
    frustration_pen = _frustrated_star_pressure(
        position=pos,
        club_amb=club_amb,
        completed_play_seasons=stint.completed_play_seasons,
        finish_frust=finish_frust,
        depth_rank=depth_rank,
        prod_ratio=prod_ratio,
        ovr_delta=ovr_delta_live,
        player_amb=player_amb,
    )
    t_exp_club = _expected_trophies(
        trophy_seasons,
        league_rank=league_rank,
        cl_rank=cl_rank,
        league_code=league_code,
        club_ambition=club_amb,
    )
    t_exp_player = t_exp_club * player_amb * tenure_tf
    t_deficit = t_exp_player - stint.trophy_value
    rel_deficit = (
        t_deficit / max(t_exp_player, 0.12) if t_exp_player > 0.08 else 0.0
    )

    if (
        stint.completed_play_seasons >= MIN_SEASONS_TROPHY_RULE
        and depth_rank <= 3
        and player_amb >= 0.30
        and trophy_sens >= _TROPHY_SENSITIVITY_BADGE
        and rel_deficit > _TROPHY_REL_DEFICIT_BADGE
    ):
        if _BADGE_TROPHY not in badges:
            badges.append(_BADGE_TROPHY)

    trophy_score = 0.0
    if (
        t_exp_player > 0.08
        and rel_deficit > 0
        and trophy_sens >= _TROPHY_SENSITIVITY_BADGE
        and depth_rank <= 3
        and player_amb >= 0.28
    ):
        if depth_rank <= 1:
            trophy_role = 1.0
        elif depth_rank == 2:
            trophy_role = 0.72
        else:
            trophy_role = 0.22
        trophy_role *= max(0.35, min(1.0, player_amb))
        trophy_score = (
            11.0
            * trophy_sens
            * trophy_role
            * tenure_tf
            * max(-1.5, min(1.5, -rel_deficit))
        )

    depth_pen = 0.0
    if depth_rank >= 4:
        depth_pen = -13.0
    elif depth_rank == 3:
        depth_pen = -5.0
    elif depth_rank == 2 and not is_gk:
        depth_pen = -2.5

    usage_pen = 0.0
    if depth_rank <= 2 and stint.completed_play_seasons >= 2 and stint.matches >= 1:
        min_exp = 9.0 * stint.completed_play_seasons * (
            1.0 if depth_rank == 1 else 0.5
        )
        if stint.matches < min_exp:
            usage_pen = -9.0 * (1.0 - stint.matches / max(min_exp, 1.0))

    prod_weight = 0.50 + 0.50 * (1.0 - player_amb * 0.35)
    if (
        pos in _CARRY_POSITIONS
        and finish_frust >= 0.30
        and stint.completed_play_seasons >= 2
        and prod_ratio >= 0.88
        and depth_rank <= 2
    ):
        prod_weight *= 0.28

    score = (
        50.0
        + 12.0 * skill_norm
        + 10.0 * (role_pts / 2.0)
        + 20.0 * (prod_norm / 2.0) * prod_weight
        + trophy_score
        + frustration_pen
        + depth_pen
        + usage_pen
        + (10.0 if fit else -8.0)
    )
    if depth_surplus and not fit:
        score -= 5.0
    if depth_rank >= 4 and not fit:
        score -= 4.0

    stable_core = (
        depth_rank == 1
        and fit
        and abs(float(ovr) - team_median_overall) <= 4.5
        and ovr_delta_live <= 0
        and stint.completed_play_seasons <= 2
        and frustration_pen == 0.0
    )
    if stable_core:
        score += 22.0
        if _BADGE_TROPHY in badges:
            badges = [b for b in badges if b != _BADGE_TROPHY]

    # Глубина 2 без провала по стате — максимум СУ, не НУ только из‑за трофеев.
    if (
        depth_rank == 2
        and _BADGE_DEPTH not in badges
        and _BADGE_PROD not in badges
        and frustration_pen == 0.0
    ):
        score = max(score, 39.0)

    verdict = _score_to_verdict(score)

    hard_no = (
        depth_rank == 1
        and prod_ratio >= 0.95
        and fit
        and ovr >= med
        and frustration_pen == 0.0
        and finish_frust < 0.35
    )

    if hard_no:
        verdict = VERDICT_NO
        score = max(score, 75.0)

    if stint.completed_play_seasons <= 1 and _BADGE_TROPHY in badges:
        badges = [b for b in badges if b != _BADGE_TROPHY]

    badges = badges[:2]

    return TransferAdviceRow(
        name=name,
        position=pos,
        overall=ovr,
        verdict=verdict,
        badges=badges,
        score=round(score, 1),
        depth_rank=depth_rank,
        person_id=int(pid) if pid is not None else None,
        is_goalkeeper=is_gk,
    )


def collect_transfer_advice(team: str) -> tuple[str, list[TransferAdviceRow], str | None]:
    """
    Рекомендации по составу клуба N.
    Возвращает (каноническое_имя_клуба, строки, ошибка).
    """
    from coach_squad_state import resolve_formation_key_for_team
    from team_squad_schemas import get_slots_for_formation_key
    from utils.utils import session_league

    raw = (team or "").strip()
    if len(raw) < 2:
        return "", [], "Укажи название клуба."

    team_n = _norm_team(raw)
    roster: list[dict[str, Any]] = []
    for Cls in _ALL:
        for r in session_league.query(Cls).filter(_filter_team(Cls, team_n)).all():
            nm = player_display_name(r)
            if not nm:
                continue
            roster.append(
                {
                    "name": nm,
                    "position": (r.position or "").strip().upper(),
                    "overall": int(r.overall or 0),
                    "person_id": getattr(r, "person_id", None),
                }
            )

    if not roster:
        from utils.transfer_input import resolve_team_name

        resolved = resolve_team_name(raw, session_league)
        if resolved:
            return collect_transfer_advice(resolved)
        return team_n, [], f"Клуб «{raw}» не найден в нац. лиге."

    canon = team_n
    for Cls in _ALL:
        sample = session_league.query(Cls).filter(_filter_team(Cls, team_n)).first()
        if sample is not None:
            canon = (sample.team or team_n).strip()
            break

    league_code = national_league_code_for_team(canon)
    league_rank = _league_strength_rank(canon, league_code)
    cl_rank = _cl_strength_rank(canon)

    fkey = resolve_formation_key_for_team(canon)
    slots = get_slots_for_formation_key(fkey)

    med_by_pos: dict[str, list[int]] = {}
    for p in roster:
        pos = p["position"]
        med_by_pos.setdefault(pos, []).append(int(p["overall"]))
    team_median_by_pos = {
        pos: median(vals) for pos, vals in med_by_pos.items() if vals
    }
    all_ovrs = [int(p["overall"]) for p in roster if int(p.get("overall") or 0) > 0]
    team_median_overall = float(median(all_ovrs)) if all_ovrs else 80.0

    depth = _depth_ranks(roster)
    expected_rates = _league_expected_rates(session_league)

    rows: list[TransferAdviceRow] = []
    for p in roster:
        key = (_norm_cmp(p["name"]), p["position"])
        dr = depth.get(key, 99)
        stint = _collect_club_stint_stats(
            canon,
            person_id=p.get("person_id"),
            name=p["name"],
            league_code=league_code,
        )
        rows.append(
            _compute_advice_for_player(
                team=canon,
                player=p,
                depth_rank=dr,
                team_median_by_pos=team_median_by_pos,
                team_median_overall=team_median_overall,
                league_rank=league_rank,
                cl_rank=cl_rank,
                league_code=league_code,
                slots=slots,
                expected_rates=expected_rates,
                stint=stint,
            )
        )

    rows.sort(
        key=lambda r: (
            _VERDICT_ORDER.get(r.verdict, 9),
            r.score,
            -r.overall,
            r.name.lower(),
        )
    )
    return canon, rows, None


def format_advice_telegram(
    team: str,
    rows: list[TransferAdviceRow],
    *,
    max_lines: int = 35,
    filter_verdicts: frozenset[str] | None = None,
) -> list[str]:
    """Разбить отчёт на сообщения Telegram (HTML)."""
    from html import escape

    team_e = escape(team)
    header = (
        f"<b>{team_e}</b> · рекомендации\n"
        f"<i>НО СО СУ НУ · Т− П↓ З+ С×</i>\n"
        f"Стата и трофеи — только в этом клубе (ЛЧ ×{W_CL:g}).\n"
    )
    counts = {VERDICT_NO: 0, VERDICT_SO: 0, VERDICT_SU: 0, VERDICT_NU: 0}
    for r in rows:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1

    body_rows = rows
    if filter_verdicts:
        body_rows = [r for r in rows if r.verdict in filter_verdicts]

    lines = [r.line_text() for r in body_rows[:max_lines]]
    if len(body_rows) > max_lines:
        lines.append(f"… ещё {len(body_rows) - max_lines}")

    summary = (
        f"\n<b>Итого:</b> НО {counts[VERDICT_NO]} · СО {counts[VERDICT_SO]} · "
        f"СУ {counts[VERDICT_SU]} · НУ {counts[VERDICT_NU]}"
    )

    text = header + "\n".join(escape(ln) for ln in lines) + summary
    if len(text) <= 4000:
        return [text]

    chunks: list[str] = []
    part_lines: list[str] = []
    for ln in lines:
        part_lines.append(ln)
        chunk_body = header + "\n".join(escape(x) for x in part_lines)
        if len(chunk_body) > 3800:
            part_lines.pop()
            chunks.append(
                header + "\n".join(escape(x) for x in part_lines) + summary
            )
            part_lines = [ln]
    if part_lines:
        chunks.append(header + "\n".join(escape(x) for x in part_lines) + summary)
    return chunks


def all_league_teams() -> list[str]:
    out: list[str] = []
    for code in ("rpl", "eng", "esp", "ger", "ita"):
        reg = teams_in_league(code, active_only=False)
        if reg:
            out.extend(t.name for t in reg)
        else:
            out.extend(LEAGUE_TEAMS.get(code) or [])
    return sorted(set(out), key=lambda x: x.lower())
