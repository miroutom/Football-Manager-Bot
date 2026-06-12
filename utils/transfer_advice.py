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
from utils.team_strength import get_team_strength, get_teams_sorted_by_strength

_ALL = (Forward, Midfielder, Defender, Goalkeeper)
_GOALKEEPER_POS = frozenset({"ВРТ"})

W_CL = 1.75
TOP_PLAYER_OVR = 87
TOP_CLUB_RANK = 5
MIN_SEASONS_TROPHY_RULE = 2

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

    @property
    def trophy_value(self) -> float:
        return float(self.league_trophies) + W_CL * float(self.cl_trophies)


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


def _expected_trophies(
    seasons: int, *, league_rank: int, cl_rank: int | None
) -> float:
    if seasons <= 0:
        return 0.0
    p_l = _win_prob_league(league_rank)
    p_c = _win_prob_cl(cl_rank) if cl_rank is not None else 0.0
    return seasons * (p_l * 1.0 + p_c * W_CL)


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
    stint = ClubStintStats(seasons=len(seasons))
    db_root = os.path.join(season_paths.PROJECT_ROOT, "db")
    team_n = _norm_team(team)

    for sn in seasons:
        lp = os.path.join(db_root, f"season_{sn}", season_paths.SEASON_LEAGUE_NAME)
        row = _find_row_in_season_db(
            lp, team_n, person_id=person_id, name=name
        )
        if row is None:
            continue
        snap = _row_stats_snapshot(row)
        stint.matches += snap["matches"]
        stint.goals += snap["goals"]
        stint.assists += snap["assists"]
        stint.ga += snap["ga"]
        stint.clean_sheets += snap["clean_sheets"]
        stint.missed_goals += snap["missed_goals"]

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
    league_rank: int,
    cl_rank: int | None,
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
        if _BADGE_PROD not in badges:
            badges.append(_BADGE_PROD)

    t_exp = _expected_trophies(stint.seasons, league_rank=league_rank, cl_rank=cl_rank)
    t_deficit = t_exp - stint.trophy_value
    if t_deficit > 0.45 and stint.seasons >= 1:
        if _BADGE_TROPHY not in badges:
            badges.append(_BADGE_TROPHY)

    score = (
        50.0
        + 12.0 * skill_norm
        + 10.0 * (role_pts / 2.0)
        + 18.0 * (prod_norm / 2.0)
        + 15.0 * max(-1.5, min(1.5, -t_deficit / max(t_exp, 0.5)))
        + (10.0 if fit else -6.0)
    )

    verdict = _score_to_verdict(score)

    hard_nu = (
        ovr >= TOP_PLAYER_OVR
        and league_rank <= TOP_CLUB_RANK
        and stint.seasons >= MIN_SEASONS_TROPHY_RULE
        and stint.trophy_value < 0.5
        and t_deficit > 0.8
    )
    hard_nu_depth = depth_rank >= 4 and not fit and _BADGE_PROD in badges
    hard_no = depth_rank == 1 and prod_ratio >= 0.95 and fit and ovr >= med

    if hard_nu or hard_nu_depth:
        verdict = VERDICT_NU
        score = min(score, 30.0)
    elif hard_no:
        verdict = VERDICT_NO
        score = max(score, 75.0)

    if stint.seasons <= 1 and verdict == VERDICT_NU and _BADGE_TROPHY in badges:
        verdict = VERDICT_SU
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
                league_rank=league_rank,
                cl_rank=cl_rank,
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
    for _code, names in LEAGUE_TEAMS.items():
        out.extend(names)
    return sorted(set(out), key=lambda x: x.lower())
