# -*- coding: utf-8 -*-
"""Ввод статистики матча в боте: состав, «кто играл», строка «голы пасы жк травма»."""
from __future__ import annotations

import contextlib
import io
import re
from dataclasses import dataclass, field
from typing import Any

from utils.player_names import player_display_name, player_surname
from utils.player_transfer import _norm_cmp
from coach_squad_state import resolve_formation_key_for_team
from team_squad_schemas import SquadSlot, get_slots_for_formation_key


def player_row_key(name: str, pos: str) -> str:
    """Как в utils.match_ratings.player_row_key — локально, без импорта match_ratings."""

    return f"{_norm_cmp(name)}|{_norm_cmp(pos)}"


_PAGE = 10

# Порядок по схеме: атака слева направо → полузащита → защита → вратарь
_FWD_SLOT_IDS = frozenset({"LW", "RW", "ST", "CF", "STL", "STR"})
_MID_SLOT_IDS = frozenset(
    {
        "CDM",
        "LCM",
        "RCM",
        "CAM",
        "CCM",
        "LM",
        "RM",
        "LDM",
        "RDM",
    }
)
_DEF_SLOT_IDS = frozenset({"LB", "RB", "LCB", "RCB", "CB", "LWB", "RWB"})
_RU_FWD_POS = frozenset({"ЛФА", "ПФА", "ФРВ", "ЦФД", "ЛФД", "ПФД"})
_RU_DEF_POS = frozenset({"ЛЗ", "ПЗ", "ЦЗ", "ЛЦЗ", "ПЦЗ", "ЛФЗ", "ПФЗ"})

_RE_INJ_TOKEN = re.compile(r"^(\d+)\s*[мm]$", re.IGNORECASE | re.UNICODE)
_RE_2Y_TOKEN = re.compile(r"^2\s*жк$", re.IGNORECASE | re.UNICODE)
_RE_Y_TOKEN = re.compile(r"^жк$", re.IGNORECASE | re.UNICODE)
_RE_R_TOKEN = re.compile(r"^кк$", re.IGNORECASE | re.UNICODE)
_RE_CS = re.compile(r"^cs$", re.IGNORECASE)


def _slot_line_group(slot: SquadSlot) -> int:
    """0 — атака … 3 — вратарь (внутри линии — по x слева направо)."""
    sid = (slot.slot_id or "").strip().upper()
    if sid == "GK":
        return 3
    if sid in _FWD_SLOT_IDS:
        return 0
    if sid in _DEF_SLOT_IDS:
        return 2
    if sid in _MID_SLOT_IDS:
        return 1
    ap = slot.allowed_positions
    if ap <= frozenset({"ВРТ"}):
        return 3
    if ap & _RU_FWD_POS:
        return 0
    if ap & _RU_DEF_POS:
        return 2
    return 1


def sort_slots_for_pitch_list(slots: tuple[SquadSlot, ...]) -> list[SquadSlot]:
    return sorted(slots, key=lambda s: (_slot_line_group(s), s.x))


def order_players_by_slots(
    rows: list[tuple[str, str, int]],
    sorted_slots: list[SquadSlot],
) -> list[tuple[str, str, int]]:
    """Жадно сопоставить игроков слотам активной схемы (сильнее OVR раньше)."""
    remaining = list(rows)
    out: list[tuple[str, str, int]] = []
    for slot in sorted_slots:
        allowed = slot.allowed_positions
        cand_i: list[int] = []
        for i, (_nm, pos, _ovr) in enumerate(remaining):
            pst = (pos or "").strip()
            if pst in allowed:
                cand_i.append(i)
        if not cand_i:
            continue
        pick = max(
            cand_i,
            key=lambda i: (remaining[i][2], remaining[i][0].lower()),
        )
        out.append(remaining.pop(pick))
    remaining.sort(key=lambda r: (-r[2], r[0].lower()))
    out.extend(remaining)
    return out


@dataclass
class MatchRosterPlayer:
    idx: int
    name: str
    position: str
    team: str
    side_label: str  # «хоз» / «гост»
    squad_status: str = ""  # start | bench | reserve


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


@dataclass
class PlayerMatchAcc:
    """Накопленная стата игрока за текущую сессию матча (для показа и дозаписи)."""

    goals: int = 0
    assists: int = 0
    yellow_count: int = 0
    second_yellow_token: bool = False
    red_direct: bool = False
    injury_months: int | None = None
    clean_sheet: bool = False

    def has_content(self) -> bool:
        return bool(
            self.goals
            or self.assists
            or self.yellow_count
            or self.second_yellow_token
            or self.red_direct
            or self.injury_months is not None
            or self.clean_sheet
        )

    def to_dict(self) -> dict:
        return {
            "goals": self.goals,
            "assists": self.assists,
            "yellow_count": self.yellow_count,
            "second_yellow_token": self.second_yellow_token,
            "red_direct": self.red_direct,
            "injury_months": self.injury_months,
            "clean_sheet": self.clean_sheet,
        }

    @classmethod
    def from_dict(cls, raw: dict | None) -> PlayerMatchAcc:
        if not raw:
            return cls()
        return cls(
            goals=int(raw.get("goals") or 0),
            assists=int(raw.get("assists") or 0),
            yellow_count=int(raw.get("yellow_count") or 0),
            second_yellow_token=bool(raw.get("second_yellow_token")),
            red_direct=bool(raw.get("red_direct")),
            injury_months=raw.get("injury_months"),
            clean_sheet=bool(raw.get("clean_sheet")),
        )


def validate_stat_delta(acc: PlayerMatchAcc, parsed: ParsedPlayerStatLine) -> list[str]:
    """Нельзя убавить гол/пас ниже нуля в текущей сессии матча."""
    errs: list[str] = []
    if acc.goals + parsed.goals < 0:
        errs.append(
            f"Голов в матче уже {acc.goals} — убавить на {abs(parsed.goals)} нельзя."
        )
    if acc.assists + parsed.assists < 0:
        errs.append(
            f"Передач в матче уже {acc.assists} — убавить на {abs(parsed.assists)} нельзя."
        )
    return errs


def merge_player_acc(acc: PlayerMatchAcc, parsed: ParsedPlayerStatLine) -> None:
    acc.goals += parsed.goals
    acc.assists += parsed.assists
    if parsed.clean_sheet:
        acc.clean_sheet = True
    if parsed.yellow:
        acc.yellow_count += 1
    if parsed.second_yellow:
        acc.second_yellow_token = True
    if parsed.red_direct:
        acc.red_direct = True
    if parsed.injury_months is not None:
        acc.injury_months = parsed.injury_months


def format_player_acc(acc: PlayerMatchAcc | dict | None) -> str:
    if acc is None:
        return ""
    if isinstance(acc, dict):
        acc = PlayerMatchAcc.from_dict(acc)
    if not acc.has_content():
        return ""
    parts: list[str] = [f"{acc.goals}+{acc.assists}"]
    if acc.red_direct:
        parts.append("кк")
    elif acc.second_yellow_token or acc.yellow_count >= 2:
        parts.append("2жк")
    elif acc.yellow_count >= 1:
        parts.append("жк")
    if acc.injury_months is not None:
        parts.append(f"{acc.injury_months}м")
    if acc.clean_sheet:
        parts.append("cs")
    return " ".join(parts)


def get_player_acc(data: dict, idx: int) -> PlayerMatchAcc:
    raw = (data.get("stats_player_acc") or {}).get(str(idx))
    return PlayerMatchAcc.from_dict(raw)


def set_player_acc(data: dict, idx: int, acc: PlayerMatchAcc) -> dict:
    bag = dict(data.get("stats_player_acc") or {})
    if acc.has_content():
        bag[str(idx)] = acc.to_dict()
    else:
        bag.pop(str(idx), None)
    return bag


def load_match_roster(
    home: str,
    away: str,
    tournament: str,
) -> list[MatchRosterPlayer]:
    """Игроки обеих команд: старт → бенч → резерв, в каждом блоке — порядок по схеме клуба."""
    from utils.match_ratings import _resolve_team_name_for_session, _roster_buckets_for_canonical
    from utils.utils import get_session

    out: list[MatchRosterPlayer] = []
    idx = 0
    sess = get_session(tournament)
    for raw_team, side in ((home, "хоз"), (away, "гост")):
        try:
            canon = _resolve_team_name_for_session(raw_team.strip(), sess)
            buckets = _roster_buckets_for_canonical(sess, canon)
            form_key = resolve_formation_key_for_team(canon)
            slot_tpl = get_slots_for_formation_key(form_key)
            sorted_slots = sort_slots_for_pitch_list(slot_tpl)
        except Exception:
            canon = (raw_team or "").strip()
            buckets = {"start": [], "bench": [], "reserve": []}
            sorted_slots = []
        sec_order = ("start", "bench", "reserve")
        for sec in sec_order:
            rows = list(buckets.get(sec) or [])
            if sorted_slots:
                ordered = order_players_by_slots(rows, sorted_slots)
            else:
                ordered = sorted(rows, key=lambda r: (-r[2], r[0].lower()))
            for nm, pos, ovr in ordered:
                out.append(
                    MatchRosterPlayer(
                        idx=idx,
                        name=nm,
                        position=pos,
                        team=canon,
                        side_label=side,
                        squad_status=sec,
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
        if len(nums) < 2 and re.fullmatch(r"-?\d+", tok):
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
                player_display_name(p),
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
            logs.append(line or f"✓ {player_display_name(p)} · матч")
        else:
            logs.append(line or f"✗ {player_display_name(p)}")
    return logs


def apply_player_stat_line(
    player: MatchRosterPlayer,
    parsed: ParsedPlayerStatLine,
    *,
    session_acc: PlayerMatchAcc | None = None,
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
    tournament: str,
    league_code: str | None,
    schedule_day: int | None,
    match_team_budget=None,
) -> list[str]:
    """Голы/пасы/сухой матч + дисциплина для уже выбранного игрока."""
    from player_stats import add_player_stats, get_position_type
    from utils.player_discipline import get_calendar_month, try_apply_discipline_line

    logs: list[str] = []
    if parsed.parse_errors:
        return list(parsed.parse_errors)

    acc = session_acc or PlayerMatchAcc()
    delta_errs = validate_stat_delta(acc, parsed)
    if delta_errs:
        return delta_errs

    match_for_cs = (home_team, away_team, home_score, away_score)
    clean_sheet = parsed.clean_sheet
    if not clean_sheet and get_position_type(player.position) in ("defender", "goalkeeper"):
        if player.team.lower() == home_team.lower() and away_score == 0:
            clean_sheet = True
        elif player.team.lower() == away_team.lower() and home_score == 0:
            clean_sheet = True

    team_g0 = team_a0 = 0
    if match_team_budget is not None:
        team_g0 = match_team_budget.goals_used(player.team)
        team_a0 = match_team_budget.assists_used(player.team)

    if parsed.goals != 0 or parsed.assists != 0 or clean_sheet:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = add_player_stats(
                player_display_name(player),
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
                team_goals_already=team_g0,
                team_assists_already=team_a0,
            )
        line = buf.getvalue().strip()
        logs.append(line or ("✓" if ok else "✗ запись голов/пасов"))
        if ok and match_team_budget is not None:
            match_team_budget.add(player.team, parsed.goals, parsed.assists)

    st_tourn = "cl" if (tournament or "") == "cl" else "league"
    lc = league_code or ""
    msched = get_calendar_month(schedule_day)

    if parsed.yellow:
        msg, _ = try_apply_discipline_line(
            f"{player_display_name(player)} жк",
            current_team=player.team,
            tournament=st_tourn,
            league_code=lc,
            schedule_month=msched,
            fixture_home=home_team,
            fixture_away=away_team,
        )
        if msg:
            logs.append(msg)
    if parsed.second_yellow:
        msg, _ = try_apply_discipline_line(
            f"{player_display_name(player)} 2жк",
            current_team=player.team,
            tournament=st_tourn,
            league_code=lc,
            schedule_month=msched,
            fixture_home=home_team,
            fixture_away=away_team,
        )
        if msg:
            logs.append(msg)
    if parsed.red_direct:
        msg, _ = try_apply_discipline_line(
            f"{player_display_name(player)} кк",
            current_team=player.team,
            tournament=st_tourn,
            league_code=lc,
            schedule_month=msched,
            fixture_home=home_team,
            fixture_away=away_team,
        )
        if msg:
            logs.append(msg)
    if parsed.injury_months is not None:
        msg, _ = try_apply_discipline_line(
            f"{player_display_name(player)} {parsed.injury_months}м",
            current_team=player.team,
            tournament=st_tourn,
            league_code=lc,
            schedule_month=msched,
            fixture_home=home_team,
            fixture_away=away_team,
        )
        if msg:
            logs.append(msg)

    if not logs and not (
        parsed.goals != 0
        or parsed.assists != 0
        or parsed.clean_sheet
        or parsed.yellow
        or parsed.second_yellow
        or parsed.red_direct
        or parsed.injury_months is not None
    ):
        logs.append("Пустая строка — без изменений.")
    elif not logs:
        logs.append("✓ записано")
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
            "name": player_display_name(p),
            "position": p.position,
            "team": p.team,
            "side_label": p.side_label,
            "squad_status": getattr(p, "squad_status", "") or "",
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
                squad_status=str(d.get("squad_status") or ""),
            )
        )
    return out


def roster_pk(player: MatchRosterPlayer) -> str:
    return player_row_key(player_surname(player), player.position)


def parse_roster_name_lines(text: str) -> list[str]:
    """Строки «кто сыграл» — по одному игроку, можно несколько в одном сообщении."""
    out: list[str] = []
    for line in (text or "").replace("\r", "").split("\n"):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def resolve_player_in_team(session, raw_name: str, team: str) -> tuple[Any | None, str]:
    """
    Найти игрока в клубе: точное имя, иначе единственное совпадение по фрагменту/фамилии.
    Возвращает (row SQLAlchemy, ошибка).
    """
    from player_stats import Forward, Goalkeeper, Defender, Midfielder, find_player_by_name

    team_t = (team or "").strip().title()
    name_try = (raw_name or "").strip().title()
    if not name_try:
        return None, "Пустая строка."

    pl, _ = find_player_by_name(session, name_try, team_t)
    if pl:
        return pl, ""

    q = _norm_cmp(raw_name)
    team_n = _norm_cmp(team_t)
    found: list[Any] = []
    seen: set[str] = set()
    for Cls in (Forward, Midfielder, Defender, Goalkeeper):
        for p in session.query(Cls).all():
            if _norm_cmp(p.team) != team_n:
                continue
            pn = _norm_cmp(player_surname(p))
            if pn in seen:
                continue
            parts = pn.split()
            hit = (
                pn == q
                or q in pn
                or any(p.startswith(q) or q == p for p in parts)
            )
            if hit:
                seen.add(pn)
                found.append(p)
    if len(found) == 1:
        return found[0], ""
    if len(found) > 1:
        if len({_norm_cmp(player_surname(p)) for p in found}) == 1:
            pick = max(
                found,
                key=lambda p: (
                    int(getattr(p, "matches", 0) or 0),
                    int(getattr(p, "overall", 0) or 0),
                    int(getattr(p, "id", 0) or 0),
                ),
            )
            return pick, ""
        names = ", ".join(
            sorted({f"{player_display_name(p)} {p.position}" for p in found})[:6]
        )
        extra = "…" if len(found) > 6 else ""
        return None, f"Неоднозначно «{raw_name}»: {names}{extra}"
    return None, f"Не найден в БД «{raw_name}» ({team_t})"


def apply_roster_names_for_team(
    names: list[str],
    team: str,
    *,
    tournament: str,
) -> tuple[list[str], list[str], list[str]]:
    """
  Засчитать +1 матч каждому из списка имён.
  Возвращает (session_keys, ok_lines, err_lines).
    """
    from player_stats import _stats_session_key, add_player_stats
    from utils.utils import get_session

    sess = get_session(tournament)
    keys: list[str] = []
    ok: list[str] = []
    err: list[str] = []
    for raw in names:
        pl, emsg = resolve_player_in_team(sess, raw, team)
        if not pl:
            err.append(emsg or raw)
            continue
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            success = add_player_stats(
                player_display_name(pl),
                pl.position,
                pl.team,
                0,
                0,
                clean_sheet=False,
                tournament=tournament,
                auto_find=True,
                increment_matches=True,
                skip_discipline_check=True,
            )
        line = buf.getvalue().strip() or (
            f"✓ {player_display_name(pl)}" if success else f"✗ {player_display_name(pl)}"
        )
        if success:
            keys.append(_stats_session_key(player_surname(pl), pl.team))
            ok.append(line)
        else:
            err.append(line or player_display_name(pl))
    return keys, ok, err


def _played_side_filter(side: str) -> str:
    return (side or "all").strip().lower()


def filter_roster_by_side(
    players: list[MatchRosterPlayer], side: str
) -> list[MatchRosterPlayer]:
    s = _played_side_filter(side)
    if s in ("home", "h", "хоз"):
        return [p for p in players if p.side_label == "хоз"]
    if s in ("away", "a", "гост"):
        return [p for p in players if p.side_label == "гост"]
    return list(players)


def build_stats_played_keyboard(
    players: list[MatchRosterPlayer],
    played_idxs: set[int],
    *,
    page: int = 0,
    side: str = "all",
) -> tuple[InlineKeyboardMarkup, int, int]:
    """Клавиатура отметки сыгравших; возвращает (kb, page, total_pages)."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    visible = filter_roster_by_side(players, side)
    ps = _PAGE
    n = len(visible)
    total_pages = max(1, (n + ps - 1) // ps)
    page = max(0, min(int(page), total_pages - 1))
    chunk = visible[page * ps : page * ps + ps]
    rows: list[list[InlineKeyboardButton]] = []
    for p in chunk:
        mark = "✅ " if p.idx in played_idxs else ""
        sec = ""
        if p.squad_status == "bench":
            sec = "·б "
        elif p.squad_status == "reserve":
            sec = "·р "
        label = f"{mark}{player_display_name(p)} {sec}{p.position}"
        if len(label) > 58:
            label = label[:55] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"stats:pl:t:{p.idx}",
                )
            ]
        )
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text=f"« {page}/{total_pages}",
                    callback_data=f"stats:pl:pg:{page - 1}",
                )
            )
        if page < total_pages - 1:
            nav.append(
                InlineKeyboardButton(
                    text=f"{page + 2}/{total_pages} »",
                    callback_data=f"stats:pl:pg:{page + 1}",
                )
            )
        if nav:
            rows.append(nav)
    side_tag = _played_side_filter(side)
    rows.append(
        [
            InlineKeyboardButton(
                text="Все" + (" ✓" if side_tag == "all" else ""),
                callback_data="stats:pl:side:all",
            ),
            InlineKeyboardButton(
                text="Хозяева" + (" ✓" if side_tag in ("home", "h", "хоз") else ""),
                callback_data="stats:pl:side:home",
            ),
            InlineKeyboardButton(
                text="Гости" + (" ✓" if side_tag in ("away", "a", "гост") else ""),
                callback_data="stats:pl:side:away",
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="✓ Далее — ввод статы",
                callback_data="stats:pl:done",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows), page, total_pages


def stats_played_pick_intro(
    *,
    home: str,
    away: str,
    hs: int,
    aws: int,
    played_count: int,
    page: int,
    total_pages: int,
) -> str:
    return (
        f"<b>Кто сыграл?</b> {home} ({hs}:{aws}) {away}\n"
        f"Отмечено: <b>{played_count}</b>. Нажми на игрока — переключить ✅.\n"
        f"Стр. {page + 1}/{total_pages}. Затем «Далее» — каждому +1 матч, потом строки статы."
    )
