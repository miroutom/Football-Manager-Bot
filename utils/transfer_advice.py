# -*- coding: utf-8 -*-
"""
Рекомендации по трансферу / удержанию игрока в клубе N.

Вердикты: НО (надо остаться), СО (стоит остаться), СУ (стоит уходить), НУ (надо уходить).
Метки: Т− трофеи, П↓ продуктивность, З+ избыток на позиции, С× не в схему.

Стата и трофеи — только за отрезок в текущем клубе (архивы сезонов + активный сезон):
национальная лига и ЛЧ (``league.db`` + ``champions_league.db``).
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
_DEF_POS = frozenset({"ЦЗ", "ЛЗ", "ПЗ", "ЛЦЗ", "ПЦЗ"})
_WIDE_DEF_POS = frozenset({"ЛЗ", "ПЗ"})
_CENTER_DEF_POS = frozenset({"ЦЗ", "ЛЦЗ", "ПЦЗ"})
_MID_POS = frozenset({"ЦП", "ЦОП", "ЛП", "ПП", "ЦАП", "ЛЦП", "ПЦП"})

W_CL = 1.75
MIN_SEASONS_TROPHY_RULE = 2
# Относительный дефицит трофеев (t_deficit / t_exp_player) для метки Т−.
_TROPHY_REL_DEFICIT_BADGE = 0.58
_TROPHY_SENSITIVITY_BADGE = 0.22

# Пороги score → вердикт (чем выше score, тем сильнее «остаться»).
SCORE_VERDICT_NO = 72.0
SCORE_VERDICT_SO = 55.0
SCORE_VERDICT_SU = 38.0

VERDICT_NO = "НО"
VERDICT_SO = "СО"
VERDICT_SU = "СУ"
VERDICT_NU = "НУ"

_BADGE_TROPHY = "Т−"
_BADGE_PROD = "П↓"
_BADGE_DEPTH = "З+"
_BADGE_FIT = "С×"

# Человекочитаемые причины для экрана (до 3 на игрока).
REASON_OUTGREW = "П+"
REASON_UNDERCLUB = "П−"
REASON_CARRY_FAIL = "Т×"
REASON_NEW = "Н"
REASON_LEVEL = "≈"
REASON_USAGE = "⏱"
REASON_GROWTH = "↑"
REASON_DECLINE = "↓"
REASON_INJURY = "Тр"

REASON_LEGEND: dict[str, str] = {
    REASON_OUTGREW: "перерос клуб",
    REASON_UNDERCLUB: "не дорос до клуба",
    _BADGE_TROPHY: "нет трофеев",
    REASON_CARRY_FAIL: "тащит — нет титулов",
    _BADGE_DEPTH: "избыток на позиции",
    _BADGE_FIT: "не в схему",
    _BADGE_PROD: "слабая стата",
    REASON_NEW: "недавно в клубе",
    REASON_LEVEL: "на уровне команды",
    REASON_USAGE: "мало игр для роли",
    REASON_GROWTH: "вырос в клубе",
    REASON_DECLINE: "упал рейтинг",
    REASON_INJURY: "частые травмы",
}

ADVICE_REASON_LEGEND_HTML = (
    "<i>П+ перерос · П− не дорос · Т− трофеи · Т× тащит без титулов\n"
    "З+ запас · С× схема · П↓ стата · Н новичок · ≈ уровень · ⏱ мало игр · Тр травмы</i>\n"
)

VERDICT_RULES_HTML = (
    "<i>Score: НО ≥72 · СО ≥55 · СУ ≥38 · НУ &lt;38\n"
    "Роль, продуктивность, трофеи, травмы; ± вклад в результаты — отдельная метрика.</i>"
)

_VERDICT_SECTION = {
    VERDICT_NU: "📕 НУ",
    VERDICT_SU: "📙 СУ",
    VERDICT_SO: "📗 СО",
    VERDICT_NO: "📘 НО",
}


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
    ovr_peak: int | None = None
    ovr_peak_hist: int | None = None
    injury_periods: int = 0
    injury_months: int = 0
    injury_months_by_season: dict[int, int] = field(default_factory=dict)
    per_season_matches: dict[int, int] = field(default_factory=dict)
    per_season_ga: dict[int, int] = field(default_factory=dict)
    per_season_ovr: dict[int, int] = field(default_factory=dict)
    per_season_yellow: dict[int, int] = field(default_factory=dict)
    per_season_red: dict[int, int] = field(default_factory=dict)
    per_season_clean_sheets: dict[int, int] = field(default_factory=dict)
    per_season_missed_goals: dict[int, int] = field(default_factory=dict)
    yellow_cards: int = 0
    red_cards: int = 0
    missed_goals: int = 0
    trophy_events: list[tuple[int, str, float]] = field(default_factory=list)
    last_season_num: int | None = None
    last_season_matches: int = 0
    last_season_ga: int = 0
    last_season_ovr: int | None = None

    @property
    def trophy_value(self) -> float:
        return float(self.league_trophies) + W_CL * float(self.cl_trophies)

    @property
    def ovr_delta(self) -> int:
        if self.ovr_first is None or self.ovr_last_completed is None:
            return 0
        return int(self.ovr_last_completed) - int(self.ovr_first)


@dataclass(frozen=True)
class TeamSeasonDefense:
    """Командная оборона за сезон: сухие — у вратарей, пропущенные — из таблицы лиги."""

    gk_cs: int = 0
    gk_matches: int = 0
    table_matches: int = 0
    conceded: int = 0


@dataclass
class TransferAdviceRow:
    name: str
    position: str
    overall: int
    verdict: str
    badges: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)
    score: float = 50.0
    depth_rank: int = 1
    person_id: int | None = None
    is_goalkeeper: bool = False

    def label_short(self) -> str:
        parts = [self.verdict, *(self.reasons or self.badges)]
        return " · ".join(parts)

    def compact_line(self) -> str:
        """Строка без вердикта (для группировки по секциям)."""
        sur = (player_surname(self.name) or self.name).strip()
        tags = self.reasons or self.badges
        tag_s = " · ".join(tags) if tags else "—"
        return f"{sur} {self.overall} {self.position} · {tag_s}"

    def line_text(self) -> str:
        sur = (player_surname(self.name) or self.name).strip()
        tags = self.reasons or self.badges
        badge = (" · " + " ".join(tags)) if tags else ""
        return f"{self.verdict}{badge}  {sur} {self.position} {self.overall}"


_VERDICT_ORDER = {VERDICT_NU: 0, VERDICT_SU: 1, VERDICT_SO: 2, VERDICT_NO: 3}

# Коды вкладок дашборда → вердикты
_VIEW_KEY_TO_VERDICT: dict[str, str] = {
    "nu": VERDICT_NU,
    "su": VERDICT_SU,
    "so": VERDICT_SO,
    "no": VERDICT_NO,
}


def normalize_advice_view(view: str) -> str:
    """``nu``/``no``/… → ``НУ``/``НО``/…; ``summary``/``all``/``sell`` без изменений."""
    v = (view or "summary").strip().lower()
    return _VIEW_KEY_TO_VERDICT.get(v, v)


def _sort_rows_by_overall(rows: list[TransferAdviceRow]) -> list[TransferAdviceRow]:
    return sorted(
        rows,
        key=lambda r: (-int(r.overall or 0), (r.name or "").lower()),
    )


def _norm_team(team: str) -> str:
    t = (team or "").strip()
    if t.casefold() == "цска":
        return "Цска"
    return t


def _is_gk(position: str) -> bool:
    return (position or "").strip().upper() in _GOALKEEPER_POS


def _is_lineup_starter(status: str | None) -> bool:
    """Игрок в стартовом составе (поле ``status`` в league.db)."""
    return (status or "").strip().lower() == "start"


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


def _season_db_path_for_stint(season_num: int, *, cl: bool) -> str | None:
    """Путь к league.db или champions_league.db сезона (архив или активный)."""
    active = int(season_paths.get_state().get("active_season") or 1)
    if season_num == active:
        path = season_paths.get_cl_db_path() if cl else season_paths.get_league_db_path()
        return path if os.path.isfile(path) else None
    fname = season_paths.SEASON_CL_NAME if cl else season_paths.SEASON_LEAGUE_NAME
    path = os.path.join(season_paths.season_archive_directory(season_num), fname)
    return path if os.path.isfile(path) else None


def _player_in_season_db(
    league_path: str, team: str, *, person_id: int | None, name: str
) -> bool:
    team_n = _norm_team(team)
    want_name = _norm_cmp(name)
    eng = create_engine(f"sqlite:///{league_path}")
    S = sessionmaker(bind=eng)
    sess = S()
    try:
        for Cls in _ALL:
            for r in sess.query(Cls).filter(_filter_team(Cls, team_n)).all():
                if person_id is not None and getattr(r, "person_id", None) == person_id:
                    return True
                if _norm_cmp(getattr(r, "name", "") or "") == want_name:
                    return True
        return False
    finally:
        sess.close()
        eng.dispose()


def _seasons_player_at_team(
    team: str, *, person_id: int | None, name: str
) -> list[int]:
    """Номера сезонов, где игрок числился в клубе (league.db + champions_league.db)."""
    team_n = _norm_team(team)
    out: list[int] = []
    active = int(season_paths.get_state().get("active_season") or 1)
    from utils.cumulative_db import list_season_archives_with_db

    season_nums = sorted(set(list_season_archives_with_db()) | {active})

    for sn in season_nums:
        found = False
        for cl in (False, True):
            lp = _season_db_path_for_stint(sn, cl=cl)
            if lp and _player_in_season_db(
                lp, team_n, person_id=person_id, name=name
            ):
                found = True
                break
        if found:
            out.append(sn)
    return out


def _row_stats_snapshot(row: Any) -> dict[str, int]:
    m = int(getattr(row, "matches", 0) or 0)
    yc = int(getattr(row, "yellow_cards", 0) or 0)
    rc = int(getattr(row, "red_cards", 0) or 0)
    pos = (getattr(row, "position", "") or "").strip().upper()
    cs = int(getattr(row, "clean_sheets", 0) or 0)
    mg = int(getattr(row, "missed_goals", 0) or 0)
    if _is_gk(pos):
        return {
            "matches": m,
            "clean_sheets": cs,
            "missed_goals": mg,
            "ga": 0,
            "goals": 0,
            "assists": 0,
            "yellow_cards": yc,
            "red_cards": rc,
        }
    g = int(getattr(row, "goals", 0) or 0)
    a = int(getattr(row, "assists", 0) or 0)
    ga = int(getattr(row, "ga", 0) or 0) or (g + a)
    return {
        "matches": m,
        "goals": g,
        "assists": a,
        "ga": ga,
        "clean_sheets": cs,
        "missed_goals": 0,
        "yellow_cards": yc,
        "red_cards": rc,
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


def _collect_injuries_for_stint(
    team: str,
    *,
    name: str,
    season_nums: list[int],
) -> tuple[int, int, dict[int, int], dict[int, int], int]:
    """Травмы в клубе за сезоны стажа: периодов, месяцев, штраф/мес. по сезону, пик до штрафа."""
    from utils.player_discipline import _load, _injury_total_months, injury_overall_penalty

    team_cmp = _norm_cmp(_norm_team(team))
    want_name = _norm_cmp(name)
    seasons_set = {int(s) for s in season_nums}
    periods = 0
    total_months = 0
    pen_by_season: dict[int, int] = {}
    months_by_season: dict[int, int] = {}
    peak_before_penalty = 0

    for inj in _load().get("injuries", []):
        if _norm_cmp(str(inj.get("team_norm") or inj.get("team") or "")) != team_cmp:
            continue
        if _norm_cmp(str(inj.get("name_norm") or inj.get("name") or "")) != want_name:
            continue
        sn = inj.get("season")
        if sn is None:
            continue
        try:
            sn_i = int(sn)
        except (TypeError, ValueError):
            continue
        if sn_i not in seasons_set:
            continue
        months = _injury_total_months(inj)
        if months <= 0:
            continue
        periods += 1
        total_months += months
        months_by_season[sn_i] = months_by_season.get(sn_i, 0) + months
        pen = abs(int(injury_overall_penalty(months)))
        if pen > 0:
            pen_by_season[sn_i] = pen_by_season.get(sn_i, 0) + pen
        ob = inj.get("overall_before_penalty")
        if ob is not None:
            try:
                peak_before_penalty = max(peak_before_penalty, int(ob))
            except (TypeError, ValueError):
                pass

    return periods, total_months, pen_by_season, months_by_season, peak_before_penalty


def _injury_stint_score_penalty(periods: int, months: int) -> float:
    """Минимальный штраф к score за травмы в клубе."""
    if periods <= 0:
        return 0.0
    return -min(2.5, 0.7 * periods + 0.04 * months)


def _collect_club_stint_stats(
    team: str, *, person_id: int | None, name: str, league_code: str | None
) -> ClubStintStats:
    from bot.season_history_store import load_history

    seasons = _seasons_player_at_team(team, person_id=person_id, name=name)
    stint = ClubStintStats(seasons=len(seasons), season_nums=list(seasons))
    team_n = _norm_team(team)
    active = int(season_paths.get_state().get("active_season") or 1)
    per_season_ovr: dict[int, int] = {}

    for sn in seasons:
        season_m = 0
        season_ga = 0
        season_cs = 0
        season_mg = 0
        season_yellow = 0
        season_red = 0
        season_missed = 0
        ovr_best = 0
        for cl in (False, True):
            lp = _season_db_path_for_stint(sn, cl=cl)
            if not lp:
                continue
            row = _find_row_in_season_db(
                lp, team_n, person_id=person_id, name=name
            )
            if row is None:
                continue
            snap = _row_stats_snapshot(row)
            season_m += int(snap["matches"])
            season_ga += int(snap["ga"])
            season_cs += int(snap["clean_sheets"])
            season_mg += int(snap["missed_goals"])
            season_yellow += int(snap["yellow_cards"])
            season_red += int(snap["red_cards"])
            season_missed += int(snap["missed_goals"])
            stint.goals += snap["goals"]
            stint.assists += snap["assists"]
            ovr = int(getattr(row, "overall", 0) or 0)
            if ovr > 0:
                ovr_best = max(ovr_best, ovr)

        if ovr_best > 0:
            per_season_ovr[sn] = ovr_best

        stint.per_season_matches[sn] = season_m
        stint.per_season_ga[sn] = season_ga
        stint.per_season_yellow[sn] = season_yellow
        stint.per_season_red[sn] = season_red
        stint.per_season_clean_sheets[sn] = season_cs
        stint.per_season_missed_goals[sn] = season_missed
        if ovr_best > 0:
            stint.per_season_ovr[sn] = ovr_best

        stint.matches += season_m
        stint.ga += season_ga
        stint.clean_sheets += season_cs
        stint.missed_goals += season_mg
        stint.yellow_cards += season_yellow
        stint.red_cards += season_red
        stint.missed_goals += season_missed
        if season_m > 0:
            stint.play_seasons += 1
            if stint.ovr_first is None and ovr_best > 0:
                stint.ovr_first = ovr_best
            archived = sn < active
            min_completed_m = 1 if archived else 3
            season_done = archived or season_m >= 3
            if season_done and season_m >= min_completed_m:
                stint.completed_play_seasons += 1
                if ovr_best > 0:
                    stint.ovr_last_completed = ovr_best
                if stint.last_season_num is None or sn >= int(stint.last_season_num):
                    stint.last_season_num = sn
                    stint.last_season_matches = season_m
                    stint.last_season_ga = season_ga
                    stint.last_season_ovr = ovr_best

    hist = load_history()
    stint.trophy_events = []
    for sn in seasons:
        if league_code:
            rows = hist.get("league_winners", {}).get(league_code) or []
            if isinstance(rows, list):
                for item in rows:
                    if not item or len(item) < 2:
                        continue
                    if int(item[0]) == sn and _norm_cmp(str(item[1])) == _norm_cmp(team_n):
                        stint.league_trophies += 1
                        stint.trophy_events.append((sn, "league", 1.0))
                        break
        cl_rows = hist.get("champions_league") or []
        if isinstance(cl_rows, list):
            for item in cl_rows:
                if not item or len(item) < 2:
                    continue
                if int(item[0]) == sn and _norm_cmp(str(item[1])) == _norm_cmp(team_n):
                    stint.cl_trophies += 1
                    stint.trophy_events.append((sn, "cl", W_CL))
                    break

    inj_periods, inj_months, inj_pen_by_season, inj_months_by_season, inj_peak = (
        _collect_injuries_for_stint(team_n, name=name, season_nums=seasons)
    )
    stint.injury_periods = inj_periods
    stint.injury_months = inj_months
    stint.injury_months_by_season = inj_months_by_season

    est_peaks: list[int] = []
    for sn, so in per_season_ovr.items():
        est = int(so) + int(inj_pen_by_season.get(int(sn), 0))
        est_peaks.append(est)
    if inj_peak > 0:
        est_peaks.append(inj_peak)
    stint.ovr_peak = max(est_peaks) if est_peaks else None
    stint.ovr_peak_hist = stint.ovr_peak

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
                buckets.setdefault((pos, bucket, "cs"), []).append(rate)
                mg = int(getattr(r, "missed_goals", 0) or 0) / m
                buckets.setdefault((pos, bucket, "mg"), []).append(mg)
            elif pos in _DEF_POS:
                cs = int(getattr(r, "clean_sheets", 0) or 0)
                rate = cs / m
                buckets.setdefault((pos, bucket, "cs"), []).append(rate)
                ga = int(getattr(r, "ga", 0) or 0)
                if ga <= 0:
                    g = int(getattr(r, "goals", 0) or 0)
                    a = int(getattr(r, "assists", 0) or 0)
                    ga = g + a
                buckets.setdefault((pos, bucket, "ga"), []).append(ga / m)
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
    return 0.35 if kind == "ga" else (1.05 if kind == "mg" else 0.25)


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
    from utils.team_registry import get_team, teams_in_league

    tm = get_team(team)
    if tm is None:
        return 5.0
    tier = max(1, min(5, int(tm.trophy_tier)))
    baseline = {5: 2.0, 4: 4.0, 3: 6.0, 2: 8.0, 1: 10.0}.get(tier, 5.0)
    n = max(1, len(teams_in_league(tm.league_code)))
    scaled = baseline * (n / 10.0)
    return float(max(1, min(n, round(scaled))))


def _trophies_critical_for_team(team: str) -> bool:
    """Трофеи важны для вердикта (топ-клубы / высокий trophy_tier)."""
    from utils.team_registry import get_team

    tm = get_team(team)
    if tm is None:
        return False
    return int(tm.trophy_tier) >= 4 or club_trophy_ambition(team) >= 0.42


def _finish_place_delta(places: list[int], expected_place: float) -> float:
    """>0 — команда выше ожиданий (место лучше), <0 — ниже."""
    if not places:
        return 0.0
    avg = sum(places) / len(places)
    return float(expected_place) - float(avg)


def _cap_verdict_at_most(current: str, ceiling: str) -> str:
    """Не выше ceiling по «остаться» (НО > СО > СУ > НУ)."""
    if _VERDICT_ORDER[current] > _VERDICT_ORDER[ceiling]:
        return ceiling
    return current


def _cap_verdict_at_least(current: str, floor: str) -> str:
    """Не ниже floor — сильнее к продаже."""
    if _VERDICT_ORDER[current] < _VERDICT_ORDER[floor]:
        return floor
    return current


_VERDICT_LEAVE_MARKERS = frozenset(
    {REASON_CARRY_FAIL, REASON_OUTGREW, _BADGE_TROPHY}
)
_VERDICT_SELL_MARKERS = frozenset(
    {REASON_UNDERCLUB, _BADGE_PROD, REASON_DECLINE, _BADGE_DEPTH, REASON_USAGE}
)


def _apply_verdict_modifiers(
    verdict: str,
    score: float,
    *,
    raw_reasons: list[str],
    completed_play_seasons: int,
    place_delta: float,
    trophies_critical: bool,
    depth_rank: int,
) -> tuple[str, float]:
    """Согласовать вердикт со score, причинами и контекстом клуба."""
    v = verdict
    s = score

    if any(c in _VERDICT_LEAVE_MARKERS for c in raw_reasons):
        v = _cap_verdict_at_most(v, VERDICT_SO)
        s = min(s, SCORE_VERDICT_NO - 0.1)

    if REASON_OUTGREW in raw_reasons and REASON_NEW in raw_reasons:
        v = _cap_verdict_at_most(v, VERDICT_SO)
        s = min(s, SCORE_VERDICT_NO - 0.1)

    if completed_play_seasons <= 1:
        v = _cap_verdict_at_most(v, VERDICT_SO)
        s = min(s, SCORE_VERDICT_NO - 0.1)

    if any(c in _VERDICT_SELL_MARKERS for c in raw_reasons):
        if depth_rank >= 3:
            v = _cap_verdict_at_least(v, VERDICT_NU)
        else:
            v = _cap_verdict_at_least(v, VERDICT_SU)

    if trophies_critical and place_delta <= -1.5 and depth_rank <= 2:
        v = _cap_verdict_at_most(v, VERDICT_SO)
        s = min(s, SCORE_VERDICT_NO - 0.1)

    if not trophies_critical and place_delta >= 1.0:
        v = _cap_verdict_at_most(v, VERDICT_SO)
        s = min(s, SCORE_VERDICT_NO - 0.1)

    return v, s


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


def _team_gk_season_stats(team: str, season_num: int) -> tuple[int, int]:
    """Сумма clean_sheets и matches вратарей клуба (лига + ЛЧ)."""
    from player_stats import _team_name_as_in_db

    team_n = _norm_team(team)
    db_team = _team_name_as_in_db(team_n)
    gk_cs = 0
    gk_matches = 0
    for cl in (False, True):
        lp = _season_db_path_for_stint(season_num, cl=cl)
        if not lp:
            continue
        eng = create_engine(f"sqlite:///{lp}")
        Session = sessionmaker(bind=eng)
        try:
            with Session() as sess:
                for row in sess.query(Goalkeeper).filter(_filter_team(Goalkeeper, db_team)):
                    gk_cs += int(getattr(row, "clean_sheets", 0) or 0)
                    gk_matches += int(getattr(row, "matches", 0) or 0)
        finally:
            eng.dispose()
    return gk_cs, gk_matches


def _team_table_conceded_stats(
    team: str, league_code: str | None, season_num: int
) -> tuple[int, int]:
    """(matches, conceded) из таблицы национальной лиги."""
    from player_stats import _find_team_in_standings, _team_name_as_in_db

    teams_dict = _load_league_teams_dict(league_code or "", season_num)
    if not teams_dict:
        return 0, 0
    st = _find_team_in_standings(teams_dict, _team_name_as_in_db(_norm_team(team)))
    if st is None:
        return 0, 0
    table_matches = int(getattr(st, "matches", 0) or 0)
    conceded = int(getattr(st, "missed", 0) or 0)
    return table_matches, conceded


def _team_season_defense_stats(
    team: str, league_code: str | None, season_num: int
) -> TeamSeasonDefense:
    gk_cs, gk_matches = _team_gk_season_stats(team, season_num)
    table_matches, conceded = _team_table_conceded_stats(team, league_code, season_num)
    return TeamSeasonDefense(
        gk_cs=gk_cs,
        gk_matches=gk_matches,
        table_matches=table_matches,
        conceded=conceded,
    )


def _build_team_season_defense_cache(
    team: str, league_code: str | None, season_nums: list[int]
) -> dict[int, TeamSeasonDefense]:
    cache: dict[int, TeamSeasonDefense] = {}
    for sn in sorted(set(int(x) for x in season_nums)):
        cache[sn] = _team_season_defense_stats(team, league_code, sn)
    return cache


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
    ovr_drop_peak: int,
    player_amb: float,
    trophy_earned: float,
) -> float:
    """
    Давление «уходить» для основы, которая тащит, но клуб стабильно ниже ожиданий.
    Возвращает отрицательную поправку к score (0 или < 0).
    """
    if (position or "").strip().upper() not in _CARRY_POSITIONS:
        return 0.0
    if completed_play_seasons < 2 or depth_rank > 2 or finish_frust < 0.30:
        return 0.0
    if trophy_earned < _EARNED_TROPHY_MIN:
        return 0.0

    carry = 0.0
    if prod_ratio >= 0.82:
        carry += 0.40
    if prod_ratio >= 1.0:
        carry += 0.28
    if ovr_drop_peak <= -2:
        carry -= 0.38
    elif ovr_drop_peak <= -1:
        carry -= 0.20
    elif ovr_drop_peak >= 3:
        carry += 0.22
    elif ovr_drop_peak >= 1:
        carry += 0.12
    carry = max(0.0, min(1.0, carry))
    if carry < 0.30:
        return 0.0

    tenure = min(1.0, completed_play_seasons / 2.0)
    intensity = club_amb * finish_frust * carry * tenure * max(0.45, player_amb) * trophy_earned
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


def _prod_ratio(
    *,
    position: str,
    overall: int,
    ga: int,
    matches: int,
    expected_rates: dict[tuple[str, int], float],
    is_gk: bool,
) -> float:
    m = max(int(matches), 1)
    if is_gk:
        actual = float(ga) / m
        exp = _expected_rate(position, overall, expected_rates, kind="cs")
    else:
        actual = float(ga) / m
        exp = _expected_rate(position, overall, expected_rates, kind="ga")
    if exp <= 0:
        return 1.0 if actual > 0 else 0.5
    return actual / exp


def _trophy_earned_factor(
    *,
    prod_ratio: float,
    prod_ratio_last: float | None,
    ovr_drop_peak: int,
    ovr: int,
    depth_rank: int,
) -> float:
    """
    0..1 — заслужил ли игрок претензии по трофеям (вклад в результаты клуба).
    Падение с пика и слабая стата для рейтинга снижают вес трофейного давления.
    """
    career = min(1.0, max(0.0, float(prod_ratio) / 1.08))
    last_v = prod_ratio_last if prod_ratio_last is not None else prod_ratio
    factor = min(career, min(1.0, max(0.0, float(last_v) / 1.05)))

    if ovr_drop_peak <= -2:
        factor *= 0.22
    elif ovr_drop_peak <= -1:
        factor *= 0.42

    if ovr >= 85 and last_v < 1.30:
        factor *= 0.38
    elif ovr >= 82 and last_v < 1.15:
        factor *= 0.50

    if depth_rank >= 3:
        factor *= 0.28
    return max(0.0, min(1.0, factor))


def _depth_role_mult(depth_rank: int) -> float:
    if depth_rank <= 1:
        return 1.0
    if depth_rank == 2:
        return 0.82
    return 0.55


def _injury_pm_impact(depth_rank: int, injury_months: int, *, scale: float = 1.0) -> float:
    if injury_months <= 0:
        return 0.0
    w = 0.38 if depth_rank <= 1 else 0.2
    return -injury_months * w * scale


def _team_recent_trophy_count(
    team: str, league_code: str | None, *, lookback_seasons: int = 2
) -> int:
    """Число титулов (лига + ЛЧ) за последние завершённые сезоны."""
    from bot.season_history_store import load_history

    active = int(season_paths.get_state().get("active_season") or 1)
    hist = load_history()
    team_cmp = _norm_cmp(_norm_team(team))
    count = 0
    for sn in range(max(1, active - lookback_seasons), active):
        if league_code:
            for item in hist.get("league_winners", {}).get(league_code) or []:
                if item and len(item) >= 2 and int(item[0]) == sn:
                    if _norm_cmp(str(item[1])) == team_cmp:
                        count += 1
                        break
        for item in hist.get("champions_league") or []:
            if item and len(item) >= 2 and int(item[0]) == sn:
                if _norm_cmp(str(item[1])) == team_cmp:
                    count += 1
                    break
    return count


def _team_is_apex_destination(
    team: str,
    league_code: str | None,
    league_rank: int,
    cl_rank: int | None,
) -> bool:
    """Практически некуда «перерастать» — элита с трофеями."""
    from utils.team_registry import get_team

    tm = get_team(team)
    tier = max(1, min(5, int(tm.trophy_tier))) if tm else 3
    recent = _team_recent_trophy_count(team, league_code, lookback_seasons=2)

    if tier >= 5 and league_rank <= 1 and recent >= 2:
        return True
    if tier >= 4 and league_rank <= 2 and recent >= 2:
        return True
    if league_rank <= 1 and (cl_rank or 99) <= 4 and recent >= 3:
        return True
    return False


def _discipline_pm_impact(
    position: str, *, yellow: int, red: int, matches: int
) -> float:
    if yellow <= 0 and red <= 0:
        return 0.0
    pos = (position or "").strip().upper()
    pen = yellow * 0.28 + red * 1.15
    if pos in _DEF_POS:
        pen *= 1.4
        if matches > 0 and yellow / matches > 0.25:
            pen += (yellow / matches - 0.25) * matches * 0.55
    elif pos in _CARRY_POSITIONS:
        pen *= 0.75
    return -pen


def _outfield_pm_season(
    *,
    position: str,
    overall: int,
    ga: int,
    matches: int,
    yellow: int,
    red: int,
    injury_months: int,
    depth_rank: int,
    expected_rates: dict[tuple[str, int], float],
) -> float:
    """Нападающие и полузащита: избыток голов+передач, карточки, травмы."""
    if matches <= 0:
        return 0.0
    pos = (position or "").strip().upper()
    exp = _expected_rate(pos, overall, expected_rates, kind="ga") * matches
    w = 1.0 if pos in _CARRY_POSITIONS else 0.82
    prod = (ga - exp) * w
    cards = _discipline_pm_impact(pos, yellow=yellow, red=red, matches=matches)
    inj = _injury_pm_impact(depth_rank, injury_months)
    return (prod + cards + inj) * _depth_role_mult(depth_rank)


def _defender_ga_pm(
    *,
    position: str,
    overall: int,
    ga: int,
    matches: int,
    expected_rates: dict[tuple[str, int], float],
) -> float:
    """Г+А: у крайних — небольшой вес, ноль может дать минус; у центральных — только плюс."""
    if matches <= 0:
        return 0.0
    pos = (position or "").strip().upper()
    exp_ga = _expected_rate(pos, overall, expected_rates, kind="ga") * matches
    if pos in _WIDE_DEF_POS:
        ga_pm = (ga - exp_ga) * 0.35
        if ga <= 0 and matches >= 5:
            ga_pm -= 0.6
        return ga_pm
    if pos in _CENTER_DEF_POS:
        return max(0.0, ga - exp_ga) * 0.25
    exp_ga_small = max(0.08, exp_ga * 0.5)
    return (ga - exp_ga_small) * 0.3


def _defender_rating_progress_pm(
    stint: ClubStintStats, *, current_ovr: int | None = None
) -> float:
    """
    Динамика рейтинга за стаж: падение — сильный минус, стагнация — лёгкий минус.

    Учитываются рейтинги на границах сезонов (в т.ч. без матчей в новом сезоне —
    overall в БД сезона N задаётся после окончания сезона N−1).
    """
    if stint.matches < 3:
        return 0.0

    pm = 0.0
    chain: list[tuple[int, int, int]] = []
    for sn in sorted(int(x) for x in stint.season_nums):
        ovr = int(stint.per_season_ovr.get(sn, 0) or 0)
        if ovr <= 0:
            continue
        m = int(stint.per_season_matches.get(sn, 0) or 0)
        chain.append((sn, ovr, m))

    prev_ovr: int | None = None
    for _sn, ovr, m in chain:
        weight = min(1.0, m / 10.0) if m >= 3 else 0.45
        if prev_ovr is not None:
            delta = ovr - prev_ovr
            if delta < 0:
                pm -= (abs(delta) * 3.5 + 2.0) * weight
            elif delta == 0:
                pm -= 2.5 * weight
            else:
                pm += min(delta * 0.55, 2.2) * weight
        prev_ovr = ovr

    peak = int(stint.ovr_peak or stint.ovr_first or 0)
    live = int(current_ovr or 0)
    if peak > 0 and live > 0 and live < peak:
        pm -= (peak - live) * 3.5 + 2.0

    first = stint.ovr_first
    if first is not None and stint.matches >= 8:
        comp = max(1, int(stint.completed_play_seasons or 1))
        anchor = live if live > 0 else int(stint.ovr_last_completed or first)
        total_delta = int(anchor) - int(first)
        if total_delta < 0:
            pm -= abs(total_delta) * 2.8 * comp + 2.0
        elif total_delta == 0 and peak <= int(first):
            pm -= 3.5 * comp
        elif total_delta == 1:
            pm += 0.6 * comp
        elif total_delta > 1:
            pm += total_delta * 0.45 * comp

    return pm


def _defender_pm_season(
    *,
    position: str,
    overall: int,
    ga: int,
    matches: int,
    yellow: int,
    red: int,
    injury_months: int,
    depth_rank: int,
    expected_rates: dict[tuple[str, int], float],
    team_defense: TeamSeasonDefense | None = None,
) -> float:
    """Защитники: сухие вратарей команды, пропущенные из таблицы, Г+А по роли."""
    if matches <= 0:
        return 0.0
    pos = (position or "").strip().upper()
    td = team_defense or TeamSeasonDefense()

    cs_pm = 0.0
    if td.gk_cs > 0 and (td.gk_matches > 0 or td.table_matches > 0):
        denom = max(td.gk_matches, td.table_matches, 1)
        participation = min(1.0, matches / denom)
        attributed_cs = td.gk_cs * participation
        cs_rate = _expected_rate(pos, overall, expected_rates, kind="cs")
        if cs_rate <= 0:
            cs_rate = 0.28 + max(0, (overall - 78)) * 0.006
        exp_cs = cs_rate * matches
        cs_pm = (attributed_cs - exp_cs) * 1.35

    conceded_pm = 0.0
    if td.table_matches > 0:
        team_conceded_rate = td.conceded / td.table_matches
        exp_conceded_rate = 1.15
        league_factor = min(matches, td.table_matches)
        conceded_pm = (exp_conceded_rate - team_conceded_rate) * league_factor * 0.9

    ga_pm = _defender_ga_pm(
        position=pos,
        overall=overall,
        ga=ga,
        matches=matches,
        expected_rates=expected_rates,
    )
    cards = _discipline_pm_impact(pos, yellow=yellow, red=red, matches=matches)
    inj = _injury_pm_impact(depth_rank, injury_months, scale=1.15)

    raw = cs_pm + conceded_pm + ga_pm + cards + inj
    return raw * _depth_role_mult(depth_rank)


def _goalkeeper_pm_season(
    *,
    position: str,
    overall: int,
    clean_sheets: int,
    missed_goals: int,
    matches: int,
    yellow: int,
    red: int,
    injury_months: int,
    depth_rank: int,
    expected_rates: dict[tuple[str, int], float],
) -> float:
    """Вратари: сухие матчи, мало пропущенных, травмы."""
    if matches <= 0:
        return 0.0
    pos = (position or "").strip().upper()
    cs_rate = _expected_rate(pos, overall, expected_rates, kind="cs")
    if cs_rate <= 0:
        cs_rate = 0.32
    exp_cs = cs_rate * matches
    cs_pm = (clean_sheets - exp_cs) * 1.4

    mg_rate = _expected_rate(pos, overall, expected_rates, kind="mg")
    if mg_rate <= 0:
        mg_rate = 1.05
    exp_mg = mg_rate * matches
    mg_pm = (exp_mg - missed_goals) * 0.65

    cards = _discipline_pm_impact(pos, yellow=yellow, red=red, matches=matches) * 0.5
    inj = _injury_pm_impact(depth_rank, injury_months, scale=1.2)

    raw = cs_pm + mg_pm + cards + inj
    return raw * _depth_role_mult(depth_rank)


def _season_pm_by_role(
    *,
    position: str,
    is_gk: bool,
    overall: int,
    ga: int,
    clean_sheets: int,
    missed_goals: int,
    matches: int,
    yellow: int,
    red: int,
    injury_months: int,
    depth_rank: int,
    expected_rates: dict[tuple[str, int], float],
    team_defense: TeamSeasonDefense | None = None,
) -> float:
    pos = (position or "").strip().upper()
    if is_gk:
        return _goalkeeper_pm_season(
            position=pos,
            overall=overall,
            clean_sheets=clean_sheets,
            missed_goals=missed_goals,
            matches=matches,
            yellow=yellow,
            red=red,
            injury_months=injury_months,
            depth_rank=depth_rank,
            expected_rates=expected_rates,
        )
    if pos in _DEF_POS:
        return _defender_pm_season(
            position=pos,
            overall=overall,
            ga=ga,
            matches=matches,
            yellow=yellow,
            red=red,
            injury_months=injury_months,
            depth_rank=depth_rank,
            expected_rates=expected_rates,
            team_defense=team_defense,
        )
    return _outfield_pm_season(
        position=pos,
        overall=overall,
        ga=ga,
        matches=matches,
        yellow=yellow,
        red=red,
        injury_months=injury_months,
        depth_rank=depth_rank,
        expected_rates=expected_rates,
    )


def _result_impact_pm(
    stint: ClubStintStats,
    *,
    position: str,
    depth_rank: int,
    expected_rates: dict[tuple[str, int], float],
    is_gk: bool,
    team_season_defense: dict[int, TeamSeasonDefense] | None = None,
    current_ovr: int | None = None,
) -> float:
    """
    Вклад в результаты клуба за стаж (±).

    Формула зависит от роли: нападающие — Г+А; защитники — сухие вратарей
    команды и пропущенные из таблицы; вратари — сухие, пропущенные, травмы.
    """
    total = 0.0
    pos = (position or "").strip().upper()
    defense_cache = team_season_defense or {}

    for sn in stint.season_nums:
        m = int(stint.per_season_matches.get(sn, 0) or 0)
        if m <= 0:
            continue
        ovr_s = int(stint.per_season_ovr.get(sn, 0) or 0) or 80
        total += _season_pm_by_role(
            position=pos,
            is_gk=is_gk,
            overall=ovr_s,
            ga=int(stint.per_season_ga.get(sn, 0) or 0),
            clean_sheets=int(stint.per_season_clean_sheets.get(sn, 0) or 0),
            missed_goals=int(stint.per_season_missed_goals.get(sn, 0) or 0),
            matches=m,
            yellow=int(stint.per_season_yellow.get(sn, 0) or 0),
            red=int(stint.per_season_red.get(sn, 0) or 0),
            injury_months=int(stint.injury_months_by_season.get(sn, 0) or 0),
            depth_rank=depth_rank,
            expected_rates=expected_rates,
            team_defense=defense_cache.get(int(sn)),
        )

    if pos in _DEF_POS:
        total += _defender_rating_progress_pm(stint, current_ovr=current_ovr)

    return round(total, 1)


def _result_pm_hint(
    pm: float, *, position: str, is_gk: bool
) -> tuple[str, str]:
    """
    Короткая оценка ± вклада для карточки: (ярлык, пояснение).

    Пороги зависят от роли — у защитников и вратарей типичный размах меньше.
    """
    pos = (position or "").strip().upper()
    is_def = pos in _DEF_POS
    if is_gk or is_def:
        bands: list[tuple[float, str, str]] = [
            (8.0, "заметный плюс", "стабильно выше ожиданий для роли"),
            (2.0, "положительный", "скорее помогает, чем мешает"),
            (-5.0, "в норме", "без яркого перекоса"),
            (-12.0, "ниже ожиданий", "результат слабее, чем ждут от игрока"),
            (-999.0, "слабый вклад", "заметно тянет оценку вниз"),
        ]
    else:
        bands = [
            (25.0, "выдающийся", "один из лучших по вкладу в составе"),
            (12.0, "заметный плюс", "стабильно выше ожиданий для роли"),
            (-3.0, "в норме", "без яркого перекоса"),
            (-15.0, "ниже ожиданий", "результат слабее, чем ждут от игрока"),
            (-999.0, "слабый вклад", "заметно тянет оценку вниз"),
        ]
    for threshold, label, explain in bands:
        if pm >= threshold:
            return label, explain
    return "слабый вклад", "заметно тянет оценку вниз"


def _format_result_pm(pm: float) -> str:
    if pm >= 0:
        return f"+{pm:.1f}"
    return f"{pm:.1f}"


_EARNED_TROPHY_MIN = 0.32


def _reason_codes_raw(
    *,
    badges: list[str],
    frustration_pen: float,
    skill_norm: float,
    ovr: int,
    team_median_overall: float,
    depth_rank: int,
    prod_ratio: float,
    ovr_delta_live: int,
    completed_play_seasons: int,
    stable_core: bool,
    usage_pen: float,
    matches: int,
    in_start: bool = False,
    injury_periods: int = 0,
    injury_months: int = 0,
    team_is_apex: bool = False,
    finish_frust: float = 0.0,
    trophies_critical: bool = True,
) -> list[str]:
    """Сырые коды причин (до фильтра под вердикт)."""
    raw: list[str] = []

    if frustration_pen < 0:
        raw.append(REASON_CARRY_FAIL)
    if _BADGE_TROPHY in badges:
        raw.append(_BADGE_TROPHY)

    outgrown = (
        not team_is_apex
        and depth_rank <= 2
        and completed_play_seasons >= 2
        and (
            skill_norm >= 0.85
            or float(ovr) >= team_median_overall + 4.0
        )
        and frustration_pen == 0.0
        and finish_frust < 0.45
        and prod_ratio >= 0.92
    )
    if outgrown:
        raw.append(REASON_OUTGREW)

    underclub = (
        skill_norm <= -0.55
        or float(ovr) < team_median_overall - 4.5
        or (prod_ratio < 0.52 and matches >= 5 and depth_rank >= 2)
    )
    if underclub:
        raw.append(REASON_UNDERCLUB)

    for b in badges:
        if b == _BADGE_DEPTH and in_start:
            continue
        if b in (_BADGE_DEPTH, _BADGE_FIT, _BADGE_PROD) and b not in raw:
            raw.append(b)

    if usage_pen < 0:
        raw.append(REASON_USAGE)
    if completed_play_seasons <= 1:
        raw.append(REASON_NEW)
    if stable_core:
        raw.append(REASON_LEVEL)
    if ovr_delta_live >= 3:
        raw.append(REASON_GROWTH)
    elif ovr_delta_live <= -2:
        raw.append(REASON_DECLINE)
    if injury_periods >= 2 or injury_months >= 8:
        raw.append(REASON_INJURY)

    seen: set[str] = set()
    out: list[str] = []
    for code in raw:
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _filter_reasons_for_verdict(
    raw: list[str],
    *,
    verdict: str,
    stable_core: bool,
    ovr_delta_live: int,
) -> list[str]:
    out = list(raw)
    if verdict == VERDICT_NO:
        leave_codes = {
            REASON_CARRY_FAIL,
            REASON_OUTGREW,
            _BADGE_TROPHY,
            REASON_UNDERCLUB,
            _BADGE_PROD,
            REASON_DECLINE,
            REASON_USAGE,
        }
        out = [c for c in out if c not in leave_codes]
        if not out:
            if stable_core:
                out = [REASON_LEVEL]
            elif ovr_delta_live >= 2:
                out = [REASON_GROWTH]
            elif REASON_NEW in raw:
                out = [REASON_NEW]
    return out[:3]


def _build_reasons(
    *,
    badges: list[str],
    frustration_pen: float,
    skill_norm: float,
    ovr: int,
    team_median_overall: float,
    depth_rank: int,
    prod_ratio: float,
    ovr_delta_live: int,
    completed_play_seasons: int,
    stable_core: bool,
    usage_pen: float,
    matches: int,
    in_start: bool = False,
    injury_periods: int = 0,
    injury_months: int = 0,
    team_is_apex: bool = False,
    finish_frust: float = 0.0,
    verdict: str | None = None,
    trophies_critical: bool = True,
) -> list[str]:
    """До 3 причин для отображения (порядок = важность)."""
    raw = _reason_codes_raw(
        badges=badges,
        frustration_pen=frustration_pen,
        skill_norm=skill_norm,
        ovr=ovr,
        team_median_overall=team_median_overall,
        depth_rank=depth_rank,
        prod_ratio=prod_ratio,
        ovr_delta_live=ovr_delta_live,
        completed_play_seasons=completed_play_seasons,
        stable_core=stable_core,
        usage_pen=usage_pen,
        matches=matches,
        in_start=in_start,
        injury_periods=injury_periods,
        injury_months=injury_months,
        team_is_apex=team_is_apex,
        finish_frust=finish_frust,
        trophies_critical=trophies_critical,
    )
    return _filter_reasons_for_verdict(
        raw,
        verdict=verdict or VERDICT_SO,
        stable_core=stable_core,
        ovr_delta_live=ovr_delta_live,
    )


def _result_pm_score_term(
    result_pm: float, *, position: str, is_gk: bool, matches: int
) -> float:
    """Часть score от ± вклада в результаты (отдельно от строки в карточке)."""
    if matches < 3:
        return 0.0
    pos = (position or "").strip().upper()
    if is_gk or pos in _DEF_POS:
        scale = 0.55
        cap = 18.0
    else:
        scale = 0.32
        cap = 22.0
    return max(-cap, min(cap, float(result_pm) * scale))


def _score_to_verdict(score: float) -> str:
    if score >= SCORE_VERDICT_NO:
        return VERDICT_NO
    if score >= SCORE_VERDICT_SO:
        return VERDICT_SO
    if score >= SCORE_VERDICT_SU:
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
    team_is_apex: bool = False,
    team_season_defense: dict[int, TeamSeasonDefense] | None = None,
) -> TransferAdviceRow:
    name = str(player.get("name") or "")
    pos = (player.get("position") or "").strip().upper()
    ovr = int(player.get("overall") or 0)
    pid = player.get("person_id")
    is_gk = _is_gk(pos)
    badges: list[str] = []
    in_start = _is_lineup_starter(player.get("status"))

    fit = _player_fits_formation(pos, slots)
    if not fit:
        badges.append(_BADGE_FIT)

    depth_surplus = (is_gk and depth_rank >= 2) or (not is_gk and depth_rank >= 3)
    if depth_surplus and not in_start:
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
    ovr_peak_display = max(
        int(stint.ovr_peak_hist or 0),
        int(stint.ovr_first or 0),
    )
    if int(ovr) > ovr_peak_display:
        ovr_peak_display = int(ovr)
    ovr_peak = max(ovr_peak_display, int(ovr))
    ovr_drop_peak = int(ovr) - int(ovr_peak)

    prod_ratio_last: float | None = None
    if int(stint.last_season_matches or 0) >= 3:
        prod_ratio_last = _prod_ratio(
            position=pos,
            overall=int(stint.last_season_ovr or ovr),
            ga=int(stint.last_season_ga),
            matches=int(stint.last_season_matches),
            expected_rates=expected_rates,
            is_gk=is_gk,
        )

    trophy_earned = _trophy_earned_factor(
        prod_ratio=prod_ratio,
        prod_ratio_last=prod_ratio_last,
        ovr_drop_peak=ovr_drop_peak,
        ovr=ovr,
        depth_rank=depth_rank,
    )
    result_pm = _result_impact_pm(
        stint,
        position=pos,
        depth_rank=depth_rank,
        expected_rates=expected_rates,
        is_gk=is_gk,
        team_season_defense=team_season_defense,
        current_ovr=ovr,
    )
    result_pm_label, result_pm_explain = _result_pm_hint(
        float(result_pm), position=pos, is_gk=is_gk
    )

    expected_place = _expected_league_place(team)
    trophies_critical = _trophies_critical_for_team(team)
    finish_places = _team_league_places_during_seasons(
        team, league_code, stint.season_nums
    )
    finish_frust = _finish_frustration(finish_places, expected_place)
    place_delta = _finish_place_delta(finish_places, expected_place)
    frustration_pen = _frustrated_star_pressure(
        position=pos,
        club_amb=club_amb,
        completed_play_seasons=stint.completed_play_seasons,
        finish_frust=finish_frust,
        depth_rank=depth_rank,
        prod_ratio=prod_ratio,
        ovr_drop_peak=ovr_drop_peak,
        player_amb=player_amb,
        trophy_earned=trophy_earned,
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
        trophies_critical
        and stint.completed_play_seasons >= MIN_SEASONS_TROPHY_RULE
        and depth_rank <= 3
        and player_amb >= 0.30
        and trophy_sens >= _TROPHY_SENSITIVITY_BADGE
        and rel_deficit > _TROPHY_REL_DEFICIT_BADGE
        and trophy_earned >= _EARNED_TROPHY_MIN
    ):
        if _BADGE_TROPHY not in badges:
            badges.append(_BADGE_TROPHY)

    trophy_score = 0.0
    if (
        trophies_critical
        and t_exp_player > 0.08
        and rel_deficit > 0
        and trophy_sens >= _TROPHY_SENSITIVITY_BADGE
        and depth_rank <= 3
        and player_amb >= 0.28
        and trophy_earned >= _EARNED_TROPHY_MIN
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
            * trophy_earned
            * max(-1.5, min(1.5, -rel_deficit))
        )

    depth_pen = 0.0
    if not in_start:
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
        + _injury_stint_score_penalty(stint.injury_periods, stint.injury_months)
        + _result_pm_score_term(
            float(result_pm), position=pos, is_gk=is_gk, matches=stint.matches
        )
    )
    if ovr_drop_peak <= -2:
        score -= min(14.0, abs(int(ovr_drop_peak)) * 4.0)
    if (
        depth_rank == 1
        and not is_gk
        and pos not in _DEF_POS
        and ovr_drop_peak <= -2
        and float(result_pm) < 22.0
    ):
        score -= 22.0
    if depth_surplus and not fit and not in_start:
        score -= 5.0
    if depth_rank >= 4 and not fit:
        score -= 4.0

    stable_core = (
        depth_rank == 1
        and fit
        and abs(float(ovr) - team_median_overall) <= 4.5
        and ovr_delta_live <= 0
        and ovr_drop_peak > -2
        and stint.completed_play_seasons <= 2
        and frustration_pen == 0.0
        and (prod_ratio_last is None or prod_ratio_last >= 1.0)
    )
    if stable_core:
        score += 14.0
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

    if frustration_pen < 0:
        score = min(score, SCORE_VERDICT_NO - 0.1)
    if (
        trophies_critical
        and finish_frust >= 0.50
        and depth_rank <= 1
        and _BADGE_TROPHY in badges
        and stint.completed_play_seasons >= MIN_SEASONS_TROPHY_RULE
    ):
        score = min(score, SCORE_VERDICT_NO - 0.1)

    verdict = _score_to_verdict(score)

    hard_no = (
        depth_rank == 1
        and prod_ratio >= 0.95
        and fit
        and ovr >= med
        and frustration_pen == 0.0
        and finish_frust < 0.35
        and ovr_drop_peak > -2
        and ovr_delta_live > -2
        and stint.completed_play_seasons >= 2
        and (
            is_gk
            or pos in _DEF_POS
            or float(result_pm) >= 22.0
        )
    )

    if hard_no:
        verdict = VERDICT_NO
        score = max(score, 75.0)

    if stint.completed_play_seasons <= 1 and _BADGE_TROPHY in badges:
        badges = [b for b in badges if b != _BADGE_TROPHY]

    badges = badges[:2]

    raw_reasons = _reason_codes_raw(
        badges=badges,
        frustration_pen=frustration_pen,
        skill_norm=skill_norm,
        ovr=ovr,
        team_median_overall=team_median_overall,
        depth_rank=depth_rank,
        prod_ratio=prod_ratio,
        ovr_delta_live=ovr_delta_live,
        completed_play_seasons=stint.completed_play_seasons,
        stable_core=stable_core,
        usage_pen=usage_pen,
        matches=stint.matches,
        in_start=in_start,
        injury_periods=stint.injury_periods,
        injury_months=stint.injury_months,
        team_is_apex=team_is_apex,
        finish_frust=finish_frust,
        trophies_critical=trophies_critical,
    )
    verdict, score = _apply_verdict_modifiers(
        verdict,
        score,
        raw_reasons=raw_reasons,
        completed_play_seasons=stint.completed_play_seasons,
        place_delta=place_delta,
        trophies_critical=trophies_critical,
        depth_rank=depth_rank,
    )
    reasons = _filter_reasons_for_verdict(
        raw_reasons,
        verdict=verdict,
        stable_core=stable_core,
        ovr_delta_live=ovr_delta_live,
    )
    detail = {
        "seasons_completed": stint.completed_play_seasons,
        "play_seasons": stint.play_seasons,
        "tenure_seasons": stint.seasons,
        "matches": stint.matches,
        "goals": stint.goals,
        "assists": stint.assists,
        "ga": stint.ga,
        "ovr_first": stint.ovr_first,
        "ovr_peak": ovr_peak_display,
        "ovr_drop_peak": ovr_drop_peak,
        "injury_periods": stint.injury_periods,
        "injury_months": stint.injury_months,
        "trophy_earned": round(trophy_earned, 2),
        "result_pm": result_pm,
        "result_pm_label": result_pm_label,
        "result_pm_explain": result_pm_explain,
        "prod_ratio": round(prod_ratio, 2),
        "prod_ratio_last": round(prod_ratio_last, 2) if prod_ratio_last is not None else None,
        "finish_places": finish_places,
        "expected_place": round(expected_place, 1),
        "place_delta": round(place_delta, 1),
        "trophies_critical": trophies_critical,
        "league_trophies": stint.league_trophies,
        "cl_trophies": stint.cl_trophies,
        "depth_rank": depth_rank,
        "status": player.get("status"),
        "in_start": in_start,
        "fit": fit,
    }

    return TransferAdviceRow(
        name=name,
        position=pos,
        overall=ovr,
        verdict=verdict,
        badges=badges,
        reasons=reasons,
        detail=detail,
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
                    "status": (getattr(r, "status", None) or "").strip().lower() or None,
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
    team_is_apex = _team_is_apex_destination(
        canon, league_code, league_rank, cl_rank
    )
    active = int(season_paths.get_state().get("active_season") or 1)
    team_season_defense = _build_team_season_defense_cache(
        canon, league_code, list(range(1, active + 1))
    )

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
                team_is_apex=team_is_apex,
                team_season_defense=team_season_defense,
            )
        )

    rows.sort(
        key=lambda r: (
            -int(r.overall or 0),
            _VERDICT_ORDER.get(r.verdict, 9),
            -float(r.score or 0),
            (r.name or "").lower(),
        )
    )
    return canon, rows, None


def _rows_for_view(
    rows: list[TransferAdviceRow], view: str
) -> list[TransferAdviceRow]:
    if view == "sell":
        return _sort_rows_by_overall(
            [r for r in rows if r.verdict in (VERDICT_SU, VERDICT_NU)]
        )
    verdict = normalize_advice_view(view)
    if verdict in _VERDICT_ORDER:
        return _sort_rows_by_overall(
            [r for r in rows if r.verdict == verdict]
        )
    return _sort_rows_by_overall(list(rows))


def _summary_names(rows: list[TransferAdviceRow], limit: int = 3) -> str:
    if not rows:
        return "—"
    names = [(player_surname(r.name) or r.name).strip() for r in rows]
    if len(names) <= limit:
        return ", ".join(names)
    extra = len(names) - limit
    return ", ".join(names[:limit]) + f" +{extra}"


def flat_advice_rows(rows: list[TransferAdviceRow], view: str) -> list[TransferAdviceRow]:
    if view == "all":
        out: list[TransferAdviceRow] = []
        for v in (VERDICT_NU, VERDICT_SU, VERDICT_SO, VERDICT_NO):
            out.extend(
                _sort_rows_by_overall(r for r in rows if r.verdict == v)
            )
        return out
    return _rows_for_view(rows, view)


def paginate_advice_view(
    rows: list[TransferAdviceRow],
    view: str,
    page: int,
    page_size: int,
) -> tuple[list[TransferAdviceRow], int, int]:
    """Страница списка для view; возвращает (chunk, page, total_pages)."""
    body = flat_advice_rows(rows, view)
    total_pages = max(1, (len(body) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    chunk = body[page * page_size : page * page_size + page_size]
    return chunk, page, total_pages


def format_player_advice_card_html(
    team: str,
    row: TransferAdviceRow,
) -> str:
    """Карточка игрока для дашборда (HTML)."""
    from html import escape

    d = row.detail or {}
    sur = escape((player_surname(row.name) or row.name).strip())
    team_e = escape(team)
    verdict_e = escape(row.verdict)
    reasons = row.reasons or row.badges
    reason_lines: list[str] = []
    for code in reasons:
        hint = REASON_LEGEND.get(code, code)
        reason_lines.append(f"· <b>{escape(code)}</b> — {escape(hint)}")
    if not reason_lines:
        reason_lines.append("· нет отдельных меток")

    ovr_first = d.get("ovr_first")
    ovr_peak = d.get("ovr_peak")
    ovr_line = f"{ovr_first or '—'} → {ovr_peak or '—'} → {row.overall}"
    drop = int(d.get("ovr_drop_peak") or 0)
    if drop < 0:
        ovr_line += f" ({drop:+d} с пика)"

    places = d.get("finish_places") or []
    places_s = ", ".join(str(x) for x in places) if places else "—"
    exp_pl = d.get("expected_place")
    places_line = f"{places_s}"
    if exp_pl is not None and places:
        places_line += f" (ожид. ~{exp_pl:g})"

    status = d.get("status") or "—"
    if d.get("in_start"):
        status = "start"

    prod_c = d.get("prod_ratio")
    prod_l = d.get("prod_ratio_last")
    prod_line = f"карьера в клубе ×{prod_c}" if prod_c is not None else "—"
    if prod_l is not None:
        prod_line += f", последний сезон ×{prod_l}"

    trophy_line = (
        f"лига {d.get('league_trophies', 0)}, ЛЧ {d.get('cl_trophies', 0)}"
    )
    result_pm = d.get("result_pm")
    result_lines: list[str] = []
    if result_pm is not None and int(d.get("matches", 0) or 0) > 0:
        pm_label = d.get("result_pm_label") or ""
        pm_explain = d.get("result_pm_explain") or ""
        head = (
            f"Вклад в результаты: <b>{escape(_format_result_pm(float(result_pm)))}</b>"
        )
        if pm_label:
            head += f" · <i>{escape(str(pm_label))}</i>"
        result_lines.append(head)
        if pm_explain:
            result_lines.append(escape(str(pm_explain)))

    lines = [
        f"<b>{sur}</b> · {escape(row.position)} · {row.overall}",
        f"<b>{team_e}</b> · <b>{verdict_e}</b> · score {row.score}",
        f"<i>вердикт по score (НО ≥{SCORE_VERDICT_NO:g}, СО ≥{SCORE_VERDICT_SO:g}, "
        f"СУ ≥{SCORE_VERDICT_SU:g})</i>",
        "",
        "<b>Причины</b>",
        *reason_lines,
        "",
        "<b>В клубе</b>",
        f"Сезонов {d.get('play_seasons', d.get('seasons_completed', 0))}, "
        f"матчей {d.get('matches', 0)}, "
        f"Г {d.get('goals', 0)} А {d.get('assists', 0)}",
        f"Рейтинг: {escape(ovr_line)}",
        f"Статус: <code>{escape(str(status))}</code>, глубина {d.get('depth_rank', '?')}",
    ]
    inj_p = int(d.get("injury_periods") or 0)
    if inj_p > 0:
        lines.append(
            f"Травмы в клубе: {inj_p} пер., {int(d.get('injury_months') or 0)} мес."
        )
    lines.extend([
        f"Продуктивность: {escape(prod_line)}",
    ])
    lines.extend(result_lines)
    lines.extend([
        f"Места команды: {escape(places_line)}",
        f"Трофеи: {escape(trophy_line)}",
    ])
    return "\n".join(lines)


def format_team_advice_html(
    team: str,
    rows: list[TransferAdviceRow],
    *,
    view: str = "summary",
    page: int = 0,
    page_size: int = 10,
    quota: str | None = None,
) -> tuple[str, int]:
    """
    HTML для Telegram.

    view: summary (сводка) | all (секции) | nu/su/so/no/sell (одна группа).
    Возвращает (текст, число_страниц).
    """
    from html import escape

    team_e = escape(team)
    q_part = f" · <code>{escape(quota)}</code>" if quota else ""
    counts = {v: sum(1 for r in rows if r.verdict == v) for v in _VERDICT_ORDER}

    if view == "summary":
        lines = [f"<b>{team_e}</b>{q_part}", ""]
        for v in (VERDICT_NU, VERDICT_SU, VERDICT_SO, VERDICT_NO):
            grp = _sort_rows_by_overall(r for r in rows if r.verdict == v)
            if not grp:
                continue
            lines.append(
                f"{_VERDICT_SECTION[v]} <b>{counts[v]}</b> — "
                f"{escape(_summary_names(grp))}"
            )
        lines.append("")
        lines.append(ADVICE_REASON_LEGEND_HTML.rstrip())
        lines.append(VERDICT_RULES_HTML.rstrip())
        lines.append("<i>Выбери группу кнопками ниже</i>")
        return "\n".join(lines), 1

    if view == "all":
        flat: list[tuple[str, TransferAdviceRow]] = []
        for v in (VERDICT_NU, VERDICT_SU, VERDICT_SO, VERDICT_NO):
            for r in _sort_rows_by_overall(r for r in rows if r.verdict == v):
                flat.append((v, r))
        total_pages = max(1, (len(flat) + page_size - 1) // page_size)
        page = max(0, min(page, total_pages - 1))
        chunk_slice = flat[page * page_size : page * page_size + page_size]
        lines = [f"<b>{team_e}</b>{q_part}", "<i>Все игроки по группам</i>", ""]
        prev_v: str | None = None
        for v, r in chunk_slice:
            if v != prev_v:
                lines.append(f"{_VERDICT_SECTION[v]}")
                prev_v = v
            lines.append(escape(r.compact_line()))
        if len(flat) > page_size:
            lines.append(f"\n<i>стр. {page + 1}/{total_pages}</i>")
        if page == 0:
            lines.append("\n" + ADVICE_REASON_LEGEND_HTML.rstrip())
            lines.append(VERDICT_RULES_HTML.rstrip())
        lines.append("<i>Нажми на игрока ниже — карточка с деталями</i>")
        return "\n".join(lines), total_pages

    body_rows = _rows_for_view(rows, view)
    total_pages = max(1, (len(body_rows) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    chunk = body_rows[page * page_size : page * page_size + page_size]

    verdict = normalize_advice_view(view)
    if verdict in _VERDICT_ORDER:
        title = _VERDICT_SECTION.get(verdict, verdict)
        header = f"<b>{team_e}</b>{q_part}\n{title} <b>{len(body_rows)}</b>\n"
    elif view == "sell":
        header = (
            f"<b>{team_e}</b>{q_part}\n"
            f"📉 <b>СУ+НУ {len(body_rows)}</b>\n"
        )
    else:
        header = f"<b>{team_e}</b>{q_part}\n"

    if not chunk:
        return header + "\nНет игроков в этой группе.", 1

    lines = [header.rstrip(), ""]
    lines.extend(escape(r.compact_line()) for r in chunk)
    if len(body_rows) > page_size:
        lines.append(f"\n<i>стр. {page + 1}/{total_pages}</i>")
    if page == 0:
        lines.append("\n" + ADVICE_REASON_LEGEND_HTML.rstrip())
        lines.append(VERDICT_RULES_HTML.rstrip())
    lines.append("<i>Нажми на игрока ниже — карточка с деталями</i>")
    return "\n".join(lines), total_pages


def format_advice_telegram(
    team: str,
    rows: list[TransferAdviceRow],
    *,
    max_lines: int = 35,
    filter_verdicts: frozenset[str] | None = None,
) -> list[str]:
    """Разбить отчёт на сообщения Telegram (HTML), группами по вердикту."""
    view = "sell" if filter_verdicts == frozenset({VERDICT_SU, VERDICT_NU}) else "all"
    if filter_verdicts and len(filter_verdicts) == 1:
        view = next(iter(filter_verdicts))
    text, _pages = format_team_advice_html(
        team, rows, view=view, page=0, page_size=max_lines
    )
    counts = {VERDICT_NO: 0, VERDICT_SO: 0, VERDICT_SU: 0, VERDICT_NU: 0}
    for r in rows:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    summary = (
        f"\n<b>Итого:</b> НО {counts[VERDICT_NO]} · СО {counts[VERDICT_SO]} · "
        f"СУ {counts[VERDICT_SU]} · НУ {counts[VERDICT_NU]}"
    )
    if len(text + summary) <= 4000:
        return [text + summary]
    return [text, summary]


def all_league_teams() -> list[str]:
    out: list[str] = []
    for code in ("rpl", "eng", "esp", "ger", "ita"):
        reg = teams_in_league(code, active_only=False)
        if reg:
            out.extend(t.name for t in reg)
        else:
            out.extend(LEAGUE_TEAMS.get(code) or [])
    return sorted(set(out), key=lambda x: x.lower())
