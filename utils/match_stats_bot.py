# -*- coding: utf-8 -*-
"""Ввод статистики матча в боте: состав, «кто играл», строка «голы пасы жк травма»."""
from __future__ import annotations

import contextlib
import io
import re
from dataclasses import dataclass, field

from utils.match_ratings import build_roster_template, player_row_key

_PAGE = 10

_RE_INJ_TOKEN = re.compile(r"^(\d+)\s*[мm]$", re.IGNORECASE | re.UNICODE)
_RE_2Y_TOKEN = re.compile(r"^2\s*жк$", re.IGNORECASE | re.UNICODE)
_RE_Y_TOKEN = re.compile(r"^жк$", re.IGNORECASE | re.UNICODE)
_RE_R_TOKEN = re.compile(r"^кк$", re.IGNORECASE | re.UNICODE)
_RE_CS = re.compile(r"^cs$", re.IGNORECASE)


@dataclass
class MatchRosterPlayer:
    idx: int
    name: str
    position: str
    team: str
    side_label: str  # «хоз» / «гост»


@dataclass
class ParsedPlayerStatLine:
    goals: int = 0
    assists: int = 0
    clean_sheet: bool = False
    yellow: bool = False
    second_yellow: bool = False
    red_direct: bool = False
    injury_months: int | None = None
    parse_errors: list[str] = field(default_factory=list)


def load_match_roster(
    home: str,
    away: str,
    tournament: str,
) -> list[MatchRosterPlayer]:
    """Игроки обеих команд из БД турнира (start/bench/reserve)."""
    out: list[MatchRosterPlayer] = []
    idx = 0
    for team, side in ((home, "хоз"), (away, "гост")):
        try:
            _tpl, key_map, canon = build_roster_template(team, tournament)
        except Exception:
            key_map = {}
            canon = team
        seen: set[str] = set()
        for pk, (nm, pos, _ovr) in key_map.items():
            if pk in seen:
                continue
            seen.add(pk)
            out.append(
                MatchRosterPlayer(
                    idx=idx,
                    name=nm,
                    position=pos,
                    team=canon,
                    side_label=side,
                )
            )
            idx += 1
    return out


def parse_player_stat_line(text: str) -> ParsedPlayerStatLine:
    """
    Разбор строки без имени: ``1 0 жк 3м`` → 1 гол, 0 пас, жк, травма 3 мес.
    Первые 0–2 числа — голы и передачи; остальное — дисциплина / cs.
    """
    raw = (text or "").strip()
    out = ParsedPlayerStatLine()
    if not raw:
        out.parse_errors.append("Пустая строка.")
        return out

    tokens = raw.split()
    nums: list[int] = []
    rest: list[str] = []
    for tok in tokens:
        if len(nums) < 2 and re.fullmatch(r"\d+", tok):
            nums.append(int(tok))
        else:
            rest.append(tok)

    if len(nums) >= 1:
        out.goals = nums[0]
    if len(nums) >= 2:
        out.assists = nums[1]

    i = 0
    while i < len(rest):
        tok = rest[i]
        if _RE_CS.match(tok):
            out.clean_sheet = True
            i += 1
            continue
        if _RE_2Y_TOKEN.match(tok):
            out.second_yellow = True
            i += 1
            continue
        if _RE_Y_TOKEN.match(tok):
            out.yellow = True
            i += 1
            continue
        if _RE_R_TOKEN.match(tok):
            out.red_direct = True
            i += 1
            continue
        m_inj = _RE_INJ_TOKEN.match(tok)
        if m_inj:
            nm = int(m_inj.group(1))
            if nm < 1 or nm > 10:
                out.parse_errors.append("Срок травмы: число месяцев 1–10.")
            else:
                out.injury_months = nm
            i += 1
            continue
        out.parse_errors.append(f"Неизвестный фрагмент: «{tok}»")
        i += 1

    if out.second_yellow and out.yellow:
        out.parse_errors.append("Укажи либо «жк», либо «2жк», не оба.")
    if out.second_yellow and out.red_direct:
        out.parse_errors.append("«2жк» и «кк» в одной строке не сочетаются.")
    return out


def apply_played_appearances(
    players: list[MatchRosterPlayer],
    played_idxs: set[int],
    *,
    tournament: str,
) -> list[str]:
    """+1 матч в БД каждому отмеченному игроку (без голов/пасов)."""
    from player_stats import add_player_stats

    logs: list[str] = []
    for p in players:
        if p.idx not in played_idxs:
            continue
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = add_player_stats(
                p.name,
                p.position,
                p.team,
                0,
                0,
                clean_sheet=False,
                tournament=tournament,
                auto_find=True,
                match_for_cs=None,
                skip_discipline_check=True,
                increment_matches=True,
            )
        line = buf.getvalue().strip()
        if ok:
            logs.append(line or f"✓ {p.name} · матч")
        else:
            logs.append(line or f"✗ {p.name}")
    return logs


def apply_player_stat_line(
    player: MatchRosterPlayer,
    parsed: ParsedPlayerStatLine,
    *,
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
    tournament: str,
    league_code: str | None,
    schedule_day: int | None,
) -> list[str]:
    """Голы/пасы/сухой матч + дисциплина для уже выбранного игрока."""
    from player_stats import add_player_stats, get_position_type
    from utils.player_discipline import get_calendar_month, try_apply_discipline_line

    logs: list[str] = []
    if parsed.parse_errors:
        return list(parsed.parse_errors)

    match_for_cs = (home_team, away_team, home_score, away_score)
    clean_sheet = parsed.clean_sheet
    if not clean_sheet and get_position_type(player.position) in ("defender", "goalkeeper"):
        if player.team.lower() == home_team.lower() and away_score == 0:
            clean_sheet = True
        elif player.team.lower() == away_team.lower() and home_score == 0:
            clean_sheet = True

    if parsed.goals or parsed.assists or clean_sheet:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = add_player_stats(
                player.name,
                player.position,
                player.team,
                parsed.goals,
                parsed.assists,
                clean_sheet=clean_sheet,
                tournament=tournament,
                auto_find=True,
                match_for_cs=match_for_cs,
                skip_discipline_check=True,
                increment_matches=False,
            )
        line = buf.getvalue().strip()
        logs.append(line or ("✓" if ok else "✗ запись голов/пасов"))

    st_tourn = "cl" if (tournament or "") == "cl" else "league"
    lc = league_code or ""
    msched = get_calendar_month(schedule_day)

    if parsed.yellow:
        msg, _ = try_apply_discipline_line(
            f"{player.name} жк",
            current_team=player.team,
            tournament=st_tourn,
            league_code=lc,
            schedule_month=msched,
        )
        if msg:
            logs.append(msg)
    if parsed.second_yellow:
        msg, _ = try_apply_discipline_line(
            f"{player.name} 2жк",
            current_team=player.team,
            tournament=st_tourn,
            league_code=lc,
            schedule_month=msched,
        )
        if msg:
            logs.append(msg)
    if parsed.red_direct:
        msg, _ = try_apply_discipline_line(
            f"{player.name} кк",
            current_team=player.team,
            tournament=st_tourn,
            league_code=lc,
            schedule_month=msched,
        )
        if msg:
            logs.append(msg)
    if parsed.injury_months is not None:
        msg, _ = try_apply_discipline_line(
            f"{player.name} {parsed.injury_months}м",
            current_team=player.team,
            tournament=st_tourn,
            league_code=lc,
            schedule_month=msched,
        )
        if msg:
            logs.append(msg)

    if not logs:
        logs.append("Ничего не записано (все нули и без дисциплины?).")
    return logs


def player_by_idx(players: list[MatchRosterPlayer], idx: int) -> MatchRosterPlayer | None:
    for p in players:
        if p.idx == idx:
            return p
    return None


def serialize_roster(players: list[MatchRosterPlayer]) -> list[dict]:
    return [
        {
            "idx": p.idx,
            "name": p.name,
            "position": p.position,
            "team": p.team,
            "side_label": p.side_label,
        }
        for p in players
    ]


def deserialize_roster(raw: list) -> list[MatchRosterPlayer]:
    out: list[MatchRosterPlayer] = []
    for d in raw or []:
        out.append(
            MatchRosterPlayer(
                idx=int(d["idx"]),
                name=str(d["name"]),
                position=str(d["position"]),
                team=str(d["team"]),
                side_label=str(d.get("side_label") or ""),
            )
        )
    return out


def roster_pk(player: MatchRosterPlayer) -> str:
    return player_row_key(player.name, player.position)
