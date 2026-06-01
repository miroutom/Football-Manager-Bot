# -*- coding: utf-8 -*-
"""
Травмы и дисквалификации: JSON (активные баны, накопление жк к 4) + колонки yellow_cards / red_cards в БД.

Правила:
- 4 жк накопительно (за сезон в лиге/ЛЧ) = 1 матч пропуска **после** того матча, где получена 4-я жк
- 2 жк в одном матче (второе предупреждение) = 1 матч пропуска **после** этого матча +1 red в БД
- прямая КК = 3 матча пропуска **после** этого матча +1 red в БД

Учёт «после матча»: при закрытии ввода статистики матча списание «−1 матч» к отбыванию дисквала
применяется только к банам, которые **уже были** до начала этой сессии ввода; новые баны за текущий
матч в этот же «−1» не попадают (см. ``register_match_played_for_discipline`` + снимок в боте).
- травма: «имя Nм» / «имя Nm» / «имя Nм тип» — срок с текущего месяца календаря;
  «имя сM Nм» / «имя @M Nм» — с месяца M календаря на N месяцев (тип после месяцев опционально).
  В JSON травмы — **список периодов** на игрока (несколько строк: м1→м4, потом м4→м10).
  Поля периода: ``key``, ``out_from_month``, ``return_month``, ``type``.
  **Новый** период (не дубликат с тем же с/до): сразу к overall — 1–2 мес. 0; 3–6 мес. −2;
  7 мес. −4; 8+ мес. −7 (лига + ЛЧ + common + cumulative).
- дисквал: в JSON ``unavailable_from_round`` — с какого тура чемпионата бан действует (null = как раньше).
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_STATE_PATH = _ROOT / "data" / "player_discipline.json"
_MATCH_RESULTS_PATH = _ROOT / "match_results.json"
_lock = threading.Lock()

_YEL4 = 4

# Подписи чемпионатов для текстовых отчётов (без импорта player_stats — циклы).
_LEAGUE_DISPLAY: dict[str, str] = {
    "rpl": "РПЛ",
    "eng": "АПЛ",
    "esp": "Ла Лига",
    "ger": "Бундеслига",
    "ita": "Серия А",
    "cl": "ЛЧ",
}


def _tournament_label(league_code: str, scope: str) -> str:
    if (scope or "").strip().lower() == "cl":
        return "ЛЧ"
    return _LEAGUE_DISPLAY.get((league_code or "").strip().lower(), league_code or "?")
_RE_2Y = re.compile(r"^(.+?)\s+2\s*жк\s*$", re.IGNORECASE | re.UNICODE)
# «имя2жк» без пробела перед цифрой 2
_RE_2Y_GLUE = re.compile(r"^(.+?)2\s*жк\s*$", re.IGNORECASE | re.UNICODE)
_RE_Y = re.compile(r"^(.+?)\s+жк\s*$", re.IGNORECASE | re.UNICODE)
_RE_R = re.compile(r"^(.+?)\s+кк\s*$", re.IGNORECASE | re.UNICODE)
# «имя с3 4м [тип]» — с месяца 3, на 4 месяца
_RE_INJ_FROM = re.compile(
    r"^(.+?)\s+(?:с|@)(\d{1,2})\s+(\d{1,2})\s*(?:[мМ]|[mM])\s*(.*?)\s*$",
    re.IGNORECASE | re.UNICODE,
)
# «имя 4м [тип]» — с текущего месяца календаря
_RE_INJ = re.compile(
    r"^(.+?)\s+(\d+)\s*(?:[мМ]|[mM])\s*(.*?)\s*$",
    re.IGNORECASE | re.UNICODE,
)


def is_injury_line(text: str) -> bool:
    """Строка травмы: «имя Nм» или «имя сM Nм»."""
    t = (text or "").strip()
    return bool(_RE_INJ_FROM.match(t) or _RE_INJ.match(t))


def injury_overall_penalty(months: int) -> int:
    """Штраф к overall при **новой** травме по сроку N месяцев (см. ``_apply_injury``)."""
    m = int(months)
    if m <= 2:
        return 0
    if m < 7:
        return -2
    if m == 7:
        return -4
    return -7


def extract_discipline_player_name(line: str) -> str | None:
    """Фамилия/имя из строки дисциплины (как в try_apply_discipline_line); иначе None."""
    raw = (line or "").strip()
    if not raw:
        return None
    m2 = _RE_2Y.match(raw) or _RE_2Y_GLUE.match(raw)
    if m2:
        return m2.group(1).strip()
    m_inj_f = _RE_INJ_FROM.match(raw)
    if m_inj_f:
        return m_inj_f.group(1).strip()
    m_inj = _RE_INJ.match(raw)
    if m_inj:
        return m_inj.group(1).strip()
    my = _RE_Y.match(raw)
    if my:
        return my.group(1).strip()
    mr = _RE_R.match(raw)
    if mr:
        return mr.group(1).strip()
    return None


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _load() -> dict[str, Any]:
    if not _STATE_PATH.is_file():
        return {"version": 1, "suspensions": [], "yellow_cycle": [], "injuries": []}
    with open(_STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def infer_current_calendar_month() -> int:
    """Текущий «месяц» календаря из ``match_results.json``: ``max(day)`` среди
    сыгранных матчей (``entry_type`` != ``simulation``). Если журнала нет
    или в нём только симуляции — возвращает ``1``.

    Единый источник истины: достаточно записать матч через бота / скрипт —
    «текущий месяц» обновляется автоматически везде, где используется
    ``get_calendar_month``.
    """
    if not _MATCH_RESULTS_PATH.is_file():
        return 1
    try:
        with open(_MATCH_RESULTS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return 1
    matches = []
    if isinstance(raw, dict):
        matches = raw.get("matches") or []
    elif isinstance(raw, list):
        matches = raw
    best = 0
    for m in matches:
        if not isinstance(m, dict):
            continue
        et = (m.get("entry_type") or "play").strip().lower()
        if et == "simulation":
            continue
        d = m.get("day")
        try:
            di = int(d)
        except (TypeError, ValueError):
            continue
        if 1 <= di <= 10 and di > best:
            best = di
    return best or 1


def get_calendar_month(schedule_day: int | None) -> int:
    """Текущий «месяц» календаря.

    Если передан валидный ``schedule_day`` (1..10) — он и возвращается.
    Иначе — ``infer_current_calendar_month()``: ``max(day)`` среди сыгранных
    в ``match_results.json``. Единого «бумажного» файла больше нет.
    """
    if schedule_day is not None and 1 <= int(schedule_day) <= 10:
        return int(schedule_day)
    return infer_current_calendar_month()


def find_fixture_round(
    home: str,
    away: str,
    league_code: str,
    *,
    cl_phase: str | None = None,
) -> int | None:
    """
    Номер тура в официальном расписании лиги/ЛЧ для пары (дом, гости).

    Если пара встречается в нескольких турах (два матча в ЛЧ), предпочитаем
    первый ещё не сыгранный тур; иначе — последний найденный.
    """
    lc = (league_code or "").strip().lower()
    if lc not in ("rpl", "eng", "esp", "ger", "ita", "cl"):
        return None
    from table.schedule import get_schedule

    h, a = _norm(home), _norm(away)
    sch = get_schedule(lc)
    if not sch:
        return None

    candidates: list[int] = []
    for rnd, lines in sorted(sch.items(), key=lambda kv: int(kv[0])):
        try:
            ri = int(rnd)
        except (TypeError, ValueError):
            continue
        for line in lines:
            parts = line.split(";")
            if len(parts) < 2:
                continue
            if _norm(parts[0]) != h or _norm(parts[1]) != a:
                continue
            if lc == "cl" and cl_phase:
                from match_results import cl_phase_from_mixed_schedule_line

                line_lc = line if len(parts) >= 3 else f"{parts[0]};{parts[1]};cl"
                got = cl_phase_from_mixed_schedule_line(line_lc)
                exp = (cl_phase or "").strip().lower()
                if exp in ("league", "group") and got not in ("league", "group"):
                    continue
                if exp == "knockout" and got not in ("knockout", None):
                    if got == "league":
                        continue
            candidates.append(ri)

    if not candidates:
        return None

    try:
        from main import get_teams_by_league
        from match_results import is_match_played

        teams = get_teams_by_league(lc)
        if teams:
            for ri in candidates:
                if not is_match_played(
                    home, away, lc, teams, cl_phase=cl_phase if lc == "cl" else None
                ):
                    return ri
    except Exception:
        pass
    return candidates[-1]


_SEASON_MONTHS = 10


def _injury_total_months(inj: dict) -> int:
    """Полная длительность периода (в месяцах) — для выбора иконки и подписи."""
    ofm = inj.get("out_from_month")
    ret = inj.get("return_month")
    if ofm is None or ret is None:
        return 0
    try:
        return max(0, int(ret) - int(ofm))
    except (TypeError, ValueError):
        return 0


def _injury_blocks_at_month(
    inj: dict,
    month: int,
    *,
    current_season: int | None = None,
) -> bool:
    """Блокирует ли травма игрока в данном месяце ``month`` в сезоне ``current_season``.

    Поддерживает «перенос остатка» в следующие сезоны: если травма создана в сезоне S
    с ``return_month`` > 10, в сезоне S+1 она блокирует месяцы 1..(return_month-10) и т. д.
    Для старых записей без поля ``season`` поведение прежнее (тот же сезон).
    """
    ofm = inj.get("out_from_month")
    if ofm is None:
        return False
    try:
        start = int(ofm)
        ret = int(inj.get("return_month") or 99)
    except (TypeError, ValueError):
        return False
    m = max(1, min(_SEASON_MONTHS, int(month)))
    inj_season = inj.get("season")
    if inj_season is None or current_season is None:
        return start <= m < ret
    try:
        elapsed = int(current_season) - int(inj_season)
    except (TypeError, ValueError):
        elapsed = 0
    if elapsed < 0:
        return False
    global_m = m + _SEASON_MONTHS * elapsed
    return start <= global_m < ret


def _suspension_blocks_at_round(row: dict, fixture_round: int | None) -> bool:
    left = int(row.get("matches_left") or 0)
    if left <= 0:
        return False
    ufr = row.get("unavailable_from_round")
    if ufr is None:
        return True
    if fixture_round is None:
        return True
    try:
        return int(fixture_round) >= int(ufr)
    except (TypeError, ValueError):
        return True


def _susp_key(name: str, team: str, league_code: str, scope: str) -> str:
    return f"{_norm(name)}|{_norm(team)}|{league_code}|{scope}"


def _is_cl_scope(scope: str, league_code: str) -> bool:
    return (scope or "").strip().lower() == "cl" or (league_code or "").strip().lower() == "cl"


def _consolidate_cl_yellow_rows(st: dict, name_norm: str, *, keep_team: str) -> dict | None:
    """Одна запись цикла жк в ЛЧ на игрока; лишние строки (старый клуб) сливаются."""
    ylist = st.setdefault("yellow_cycle", [])
    matches: list[dict] = []
    for row in ylist:
        if row.get("name_norm") != name_norm:
            continue
        if not _is_cl_scope(str(row.get("scope") or ""), str(row.get("league_code") or "")):
            continue
        matches.append(row)
    if not matches:
        return None
    total = sum(int(r.get("count") or 0) for r in matches)
    primary = matches[0]
    for extra in matches[1:]:
        ylist.remove(extra)
    primary["count"] = total
    primary["team"] = keep_team.strip().title()
    primary["team_norm"] = _norm(keep_team)
    primary["league_code"] = "cl"
    primary["scope"] = "cl"
    primary["key"] = _susp_key(primary["name"], primary["team"], "cl", "cl")
    return primary


def _injury_period_key(name: str, team: str, out_from_month: int, return_month: int) -> str:
    return f"{_norm(name)}|{_norm(team)}|{int(out_from_month)}|{int(return_month)}"


def _injuries_for_player(st: dict, name: str, team: str) -> list[dict]:
    nn, tn = _norm(name), _norm(team)
    return [
        row
        for row in st.get("injuries", [])
        if row.get("name_norm") == nn and row.get("team_norm") == tn
    ]


def _find_injury_period(
    st: dict, name: str, team: str, out_from_month: int, return_month: int
) -> dict | None:
    want = _injury_period_key(name, team, out_from_month, return_month)
    for row in st.get("injuries", []):
        if row.get("key") == want:
            return row
        try:
            ofm = row.get("out_from_month")
            ret = row.get("return_month")
            if (
                row.get("name_norm") == _norm(name)
                and row.get("team_norm") == _norm(team)
                and ofm is not None
                and int(ofm) == int(out_from_month)
                and int(ret) == int(return_month)
            ):
                return row
        except (TypeError, ValueError):
            continue
    return None


def _injury_blocking_at_month(
    st: dict,
    name: str,
    team: str,
    month: int,
    *,
    current_season: int | None = None,
) -> dict | None:
    """Период травмы, который закрывает игрока в данном месяце календаря (если есть)."""
    for inj in _injuries_for_player(st, name, team):
        if _injury_blocks_at_month(inj, month, current_season=current_season):
            return inj
    return None


def _get_active_season_or_default() -> int:
    """Безопасное чтение активного сезона (1, если структура сезонов не настроена)."""
    try:
        from utils.season_paths import get_active_season

        return int(get_active_season() or 1)
    except Exception:
        return 1


def get_active_injuries_for_team(
    team: str,
    *,
    schedule_month: int | None = None,
    current_season: int | None = None,
) -> list[dict]:
    """Активные травмы клуба в указанном месяце/сезоне.

    Возвращает список dict-периодов из ``data/player_discipline.json``,
    которые блокируют игроков команды ``team`` в данный момент. Для каждого
    добавлены поля ``total_months`` (полная длительность периода) и
    ``carryover`` (``True``, если период начался в прошлом сезоне).
    """
    month = get_calendar_month(schedule_month)
    season = int(current_season) if current_season is not None else _get_active_season_or_default()
    tn = _norm(team)
    out: list[dict] = []
    with _lock:
        st = _load()
    for inj in st.get("injuries", []):
        if inj.get("team_norm") != tn:
            continue
        if not _injury_blocks_at_month(inj, month, current_season=season):
            continue
        row = dict(inj)
        row["total_months"] = _injury_total_months(inj)
        inj_season = inj.get("season")
        row["carryover"] = (
            inj_season is not None
            and int(inj_season) < season
        )
        out.append(row)
    return out


def _find_susp(st: dict, name: str, team: str, league_code: str, scope: str) -> dict | None:
    if _is_cl_scope(scope, league_code):
        nn = _norm(name)
        found: dict | None = None
        for row in st.get("suspensions", []):
            if row.get("name_norm") != nn:
                continue
            if not _is_cl_scope(str(row.get("scope") or ""), str(row.get("league_code") or "")):
                continue
            if int(row.get("matches_left") or 0) <= 0:
                continue
            found = row
            break
        if found is not None:
            found["team"] = team.strip().title()
            found["team_norm"] = _norm(team)
            found["key"] = _susp_key(name, team, "cl", "cl")
        return found
    k = _susp_key(name, team, league_code, scope)
    for row in st.get("suspensions", []):
        if row.get("key") == k:
            return row
    return None


def _find_yellow_cycle(st: dict, name: str, team: str, league_code: str, scope: str) -> dict | None:
    if _is_cl_scope(scope, league_code):
        row = _consolidate_cl_yellow_rows(st, _norm(name), keep_team=team)
        if row is not None:
            return row
        return None
    k = _susp_key(name, team, league_code, scope)
    for row in st.get("yellow_cycle", []):
        if row.get("key") == k:
            return row
    return None


def snapshot_suspensions_for_fixture(
    home: str,
    away: str,
    league_code: str,
    tournament: str,
) -> dict[str, int]:
    """
    Снимок активных дисквалов (key → matches_left) по командам матча и турниру.

    Нужен боту перед вводом статистики: после матча отбывание −1 матч только для ключей из снимка,
    чтобы новые баны за этот же матч не уменьшались сразу на 1.
    """
    scope = "cl" if tournament == "cl" else "league"
    lc = "cl" if scope == "cl" else league_code
    th, ta = _norm(home), _norm(away)
    out: dict[str, int] = {}
    with _lock:
        st = _load()
        for row in st.get("suspensions", []):
            if row.get("league_code") != lc or row.get("scope") != scope:
                continue
            rt = row.get("team_norm")
            if rt not in (th, ta):
                continue
            key = row.get("key")
            if not key:
                continue
            left = int(row.get("matches_left") or 0)
            if left > 0:
                out[str(key)] = left
    return out


def check_player_eligible(
    name: str,
    team: str,
    *,
    league_code: str,
    tournament: str,
    schedule_month: int,
    fixture_round: int | None = None,
) -> tuple[bool, str | None]:
    """
    Можно ли вписать матчевую стату (голы и т.д.). Возвращает (ok, сообщение при запрете).
    """
    scope = "cl" if tournament == "cl" else "league"
    lc = "cl" if scope == "cl" else league_code
    with _lock:
        st = _load()
    month = max(1, min(10, int(schedule_month)))

    season_now = _get_active_season_or_default()
    inj = _injury_blocking_at_month(st, name, team, month, current_season=season_now)
    if inj:
        ret = int(inj.get("return_month") or 99)
        ofm = int(inj.get("out_from_month") or month)
        kind = (inj.get("type") or "травма").strip() or "травма"
        return (
            False,
            f"🚫 {name} — травма с {ofm} мес., выход с {ret} ({kind})",
        )

    row = _find_susp(st, name, team, lc, scope)
    if row and _suspension_blocks_at_round(row, fixture_round):
        m = int(row["matches_left"])
        w = "матч" if m == 1 else "матча" if 2 <= m <= 4 else "матчей"
        ufr = row.get("unavailable_from_round")
        extra = f", с тура {ufr}" if ufr is not None else ""
        return (False, f"🚫 {name} — {m} {w} дисквалификации (турнир: {lc}{extra})")

    return (True, None)


def register_match_played_for_discipline(
    home: str,
    away: str,
    league_code: str,
    tournament: str,
    *,
    susp_snapshot_before_stats: dict[str, int] | None = None,
) -> None:
    """
    После ввода статистики по матчу: −1 матч дискв. у игроков команд home/away в этом турнире.

    Если передан ``susp_snapshot_before_stats`` (снимок до начала ввода строк матча в боте),
    уменьшаем только те ключи, что уже были в снимке — новые дисквалы за этот матч не трогаем.
    Если ``None``, поведение как раньше: все активные дисквалы по матчу −1 (для совместимости).
    """
    scope = "cl" if tournament == "cl" else "league"
    lc = "cl" if scope == "cl" else league_code
    th, ta = _norm(home), _norm(away)
    with _lock:
        st = _load()
        changed = False
        for row in st.get("suspensions", []):
            if row.get("league_code") != lc or row.get("scope") != scope:
                continue
            rt = row.get("team_norm")
            if rt not in (th, ta):
                continue
            key = row.get("key")
            if not key:
                continue
            left = int(row.get("matches_left") or 0)
            if left <= 0:
                continue
            if susp_snapshot_before_stats is not None and str(key) not in susp_snapshot_before_stats:
                continue
            row["matches_left"] = left - 1
            changed = True
        if changed:
            _save(st)


def _upsert_susp(
    st: dict,
    name: str,
    team: str,
    league_code: str,
    scope: str,
    add: int,
    *,
    unavailable_from_round: int | None = None,
) -> None:
    k = _susp_key(name, team, league_code, scope)
    row = _find_susp(st, name, team, league_code, scope)
    if row is None:
        entry: dict[str, Any] = {
            "key": k,
            "name": name.strip().title(),
            "name_norm": _norm(name),
            "team": team.strip().title(),
            "team_norm": _norm(team),
            "league_code": league_code,
            "scope": scope,
            "matches_left": add,
        }
        if unavailable_from_round is not None:
            entry["unavailable_from_round"] = int(unavailable_from_round)
        st.setdefault("suspensions", []).append(entry)
    else:
        row["matches_left"] = int(row.get("matches_left") or 0) + add
        if unavailable_from_round is not None:
            old = row.get("unavailable_from_round")
            ufr = int(unavailable_from_round)
            if old is None:
                row["unavailable_from_round"] = ufr
            else:
                try:
                    row["unavailable_from_round"] = min(int(old), ufr)
                except (TypeError, ValueError):
                    row["unavailable_from_round"] = ufr


def _inc_yellow_cycle(
    st: dict,
    name: str,
    team: str,
    league_code: str,
    scope: str,
    *,
    unavailable_from_round: int | None = None,
) -> str | None:
    """
    +1 к циклу жк. При достижении 4 — бан 1 матч, цикл 0. Возвращает сообщение при бане.
    """
    k = _susp_key(name, team, league_code, scope)
    ylist = st.setdefault("yellow_cycle", [])
    row = _find_yellow_cycle(st, name, team, league_code, scope)
    if row is None:
        row = {
            "key": k,
            "name": name.strip().title(),
            "name_norm": _norm(name),
            "team": team.strip().title(),
            "team_norm": _norm(team),
            "league_code": league_code,
            "scope": scope,
            "count": 0,
        }
        ylist.append(row)
    c = int(row.get("count") or 0) + 1
    if c >= _YEL4:
        _upsert_susp(
            st,
            name,
            team,
            league_code,
            scope,
            1,
            unavailable_from_round=unavailable_from_round,
        )
        row["count"] = 0
        return (
            f"⚠ 4-я жёлтая: {name} — 1 матч дисквалификации (и отсечка жк сброшена)."
        )
    row["count"] = c
    return f"Накопительно жк: {c}/{_YEL4} (к 4 — 1 матч дискв.)."


def _bump_db_cards(
    session, player: Any, *, add_yellow: int = 0, add_red: int = 0
) -> None:
    y = int(getattr(player, "yellow_cards", 0) or 0) + add_yellow
    r = int(getattr(player, "red_cards", 0) or 0) + add_red
    if hasattr(player, "yellow_cards"):
        player.yellow_cards = y
    if hasattr(player, "red_cards"):
        player.red_cards = r


def _ban_from_round_after_card(
    *,
    fixture_home: str | None,
    fixture_away: str | None,
    league_code: str,
    cl_phase: str | None,
) -> int | None:
    if not fixture_home or not fixture_away:
        return None
    rnd = find_fixture_round(
        fixture_home, fixture_away, league_code, cl_phase=cl_phase
    )
    if rnd is None:
        return None
    return int(rnd) + 1


def try_apply_discipline_line(
    line: str,
    *,
    current_team: str,
    tournament: str,
    league_code: str,
    schedule_month: int,
    fixture_home: str | None = None,
    fixture_away: str | None = None,
    cl_phase: str | None = None,
) -> tuple[str | None, bool]:
    """
    Разбор строки дисциплины/травмы. (сообщение, обработано_ли).
    Если обработано — обновлены JSON/БД и common.
    """
    raw = (line or "").strip()
    if not raw:
        return (None, False)
    lc = league_code
    ban_from = _ban_from_round_after_card(
        fixture_home=fixture_home,
        fixture_away=fixture_away,
        league_code=lc,
        cl_phase=cl_phase,
    )
    # порядок: 2жк, травма (с M), травма (Nм), жк, кк
    m2 = _RE_2Y.match(raw) or _RE_2Y_GLUE.match(raw)
    if m2:
        name = m2.group(1).strip()
        return _apply_red_card(
            name,
            current_team,
            tournament,
            league_code,
            schedule_month,
            matches=1,
            add_yellow=0,
            add_red=1,
            kind_label="2-я жёлтая (кк)",
            unavailable_from_round=ban_from,
        )
    m3f = _RE_INJ_FROM.match(raw)
    if m3f:
        from player_stats import find_player_by_name, get_session

        name = m3f.group(1).strip()
        out_from = int(m3f.group(2))
        nm = int(m3f.group(3))
        raw_type = (m3f.group(4) or "").strip()
        if not (1 <= out_from <= 10 and 1 <= nm <= 10):
            return ("Некорректно: месяцы 1–10.", True)
        injury_type = raw_type if raw_type else "травма"
        if len(injury_type) > 80:
            injury_type = injury_type[:80].rstrip()
        return _apply_injury(
            name,
            current_team,
            tournament,
            schedule_month,
            nm,
            injury_type,
            find_player_by_name,
            get_session,
            out_from_month=out_from,
        )
    m3 = _RE_INJ.match(raw)
    if m3:
        from player_stats import find_player_by_name, get_session

        name, nm = m3.group(1).strip(), int(m3.group(2))
        raw_type = (m3.group(3) or "").strip()
        if nm < 1 or nm > 10:
            return ("Некорректно: число месяцев 1–10.", True)
        injury_type = raw_type if raw_type else "травма"
        if len(injury_type) > 80:
            injury_type = injury_type[:80].rstrip()
        return _apply_injury(
            name,
            current_team,
            tournament,
            schedule_month,
            nm,
            injury_type,
            find_player_by_name,
            get_session,
        )
    if _RE_Y.match(raw):
        my = _RE_Y.match(raw)
        name = my.group(1).strip()
        return _apply_yellow(
            name,
            current_team,
            tournament,
            league_code,
            unavailable_from_round=ban_from,
        )
    if _RE_R.match(raw) and not m2:
        mr = _RE_R.match(raw)
        name = mr.group(1).strip()
        return _apply_red_card(
            name,
            current_team,
            tournament,
            league_code,
            schedule_month,
            matches=3,
            add_yellow=0,
            add_red=1,
            kind_label="прямая кк",
            unavailable_from_round=ban_from,
        )
    return (None, False)


def _apply_yellow(
    name: str,
    current_team: str,
    tournament: str,
    league_code: str,
    *,
    unavailable_from_round: int | None = None,
) -> tuple[str | None, bool]:
    from utils.player_names import resolve_player_query_in_team
    from utils.utils import get_session
    from utils.common_db import rebuild_common_database

    t = "cl" if tournament == "cl" or (league_code or "") == "cl" else "league"
    sess = get_session(t)
    team = current_team.strip().title()
    player, err = resolve_player_query_in_team(sess, team, name)
    if err:
        return (f"✗ {err}", True)
    if not player:
        return (f"✗ Не найден в БД: {name.strip()} ({team})", True)
    scope = "cl" if t == "cl" else "league"
    lc = "cl" if scope == "cl" else league_code
    with _lock:
        st = _load()
        msg_c = _inc_yellow_cycle(
            st,
            player.name,
            team,
            lc,
            scope,
            unavailable_from_round=unavailable_from_round,
        )
        _bump_db_cards(sess, player, add_yellow=1)
        sess.commit()
        _save(st)
    try:
        rebuild_common_database()
    except Exception:
        pass
    return (f"✓ Жк: {player.name}. {msg_c} В БД жк+1.", True)


def _apply_red_card(
    name: str,
    current_team: str,
    tournament: str,
    league_code: str,
    schedule_month: int,
    *,
    matches: int,
    add_yellow: int,
    add_red: int,
    kind_label: str,
    unavailable_from_round: int | None = None,
) -> tuple[str | None, bool]:
    from utils.player_names import resolve_player_query_in_team
    from utils.utils import get_session
    from utils.common_db import rebuild_common_database

    t = "cl" if tournament == "cl" or league_code == "cl" else "league"
    sess = get_session(t)
    team = current_team.strip().title()
    player, err = resolve_player_query_in_team(sess, team, name)
    if err:
        return (f"✗ {err}", True)
    if not player:
        return (f"✗ Не найден в БД: {name.strip()} ({team})", True)
    scope = "cl" if t == "cl" else "league"
    lc = "cl" if scope == "cl" else league_code
    with _lock:
        st = _load()
        _upsert_susp(
            st,
            player.name,
            team,
            lc,
            scope,
            matches,
            unavailable_from_round=unavailable_from_round,
        )
        _bump_db_cards(sess, player, add_yellow=add_yellow, add_red=add_red)
        sess.commit()
        _save(st)
    try:
        rebuild_common_database()
    except Exception:
        pass
    ufr_note = (
        f" Бан с тура {unavailable_from_round}."
        if unavailable_from_round is not None
        else ""
    )
    return (
        f"✓ {kind_label}: {player.name} — +{matches} к дискв., кк в БД +1.{ufr_note}",
        True,
    )


def _apply_injury(
    name: str,
    current_team: str,
    tournament: str,
    month: int,
    nmonths: int,
    injury_type: str,
    find_pl,
    get_sess,
    *,
    out_from_month: int | None = None,
) -> tuple[str | None, bool]:
    t = "cl" if tournament == "cl" else "league"
    sess = get_sess(t)
    team = current_team.strip().title()
    nmt = name.title()
    player, _ = find_pl(sess, nmt, team)
    if not player:
        return (f"✗ Не найден: {nmt} ({team})", True)
    cur = max(1, min(10, int(out_from_month if out_from_month is not None else month)))
    ret = cur + int(nmonths)
    season_now = _get_active_season_or_default()
    with _lock:
        st = _load()
        inj = _find_injury_period(st, player.name, team, cur, ret)
        if inj is None:
            st.setdefault("injuries", []).append(
                {
                    "key": _injury_period_key(player.name, team, cur, ret),
                    "name": player.name,
                    "name_norm": _norm(player.name),
                    "team": team,
                    "team_norm": _norm(team),
                    "out_from_month": cur,
                    "return_month": ret,
                    "type": injury_type,
                    "season": season_now,
                }
            )
            added = True
        else:
            inj["type"] = injury_type
            if not inj.get("key"):
                inj["key"] = _injury_period_key(player.name, team, cur, ret)
            inj.setdefault("season", season_now)
            added = False
        _save(st)
    rating_note = ""
    if added:
        delta = injury_overall_penalty(nmonths)
        if delta:
            from utils.player_overall_bumps import apply_overall_bumps_for_team

            bump_res = apply_overall_bumps_for_team(team, f"{player.name} {delta:+d}")
            if bump_res.ok:
                rating_note = f" Рейтинг <b>{delta:+d}</b>."
            elif bump_res.errors:
                rating_note = f" (рейтинг: {bump_res.errors[0]})"
    tk = injury_type.strip() or "травма"
    note = (
        f"Добавлен период (всего у игрока: {len(_injuries_for_player(st, player.name, team))})."
        if added
        else "Период уже был — обновлён только тип."
    )
    carry = ""
    if ret > _SEASON_MONTHS:
        in_this = max(0, _SEASON_MONTHS + 1 - cur)
        in_next = (ret - cur) - in_this
        carry = (
            f" Переход на следующий сезон: ~{in_this} мес. в этом, ~{in_next} мес. в следующем."
        )
    return (
        f"✓ Травма ({tk}): {player.name} — с <b>{cur}</b> мес., выход с <b>{ret}</b> "
        f"(срок {nmonths} мес.).{carry}{rating_note} {note}",
        True,
    )


def format_discipline_pre_match_notice_html(
    home: str,
    away: str,
    *,
    league_code: str,
    schedule_day: int | None = None,
    cl_phase: str | None = None,
    fixture_round: int | None = None,
) -> str:
    """
    Краткий блок для экрана выбора матча: активные травмы и дисквалы по обеим командам
    (фильтр дисквала по турниру слота: лига или ЛЧ).
    """
    import html as html_module

    esc = html_module.escape
    month = get_calendar_month(schedule_day)
    season_now = _get_active_season_or_default()
    scope = "cl" if league_code == "cl" else "league"
    lc = "cl" if scope == "cl" else league_code
    if fixture_round is None:
        fixture_round = find_fixture_round(home, away, lc, cl_phase=cl_phase)

    with _lock:
        st = _load()

    def _team_block(team_label: str, team_norm: str) -> str | None:
        lines: list[str] = []
        for inj in st.get("injuries", []):
            if inj.get("team_norm") != team_norm:
                continue
            if not _injury_blocks_at_month(inj, month, current_season=season_now):
                continue
            ret = int(inj.get("return_month") or 99)
            ofm = inj.get("out_from_month")
            nm = esc(str(inj.get("name", "?")))
            tk = esc((inj.get("type") or "травма").strip() or "травма")
            if ofm is not None:
                lines.append(
                    f"• {nm} — <b>{tk}</b>: с <b>{int(ofm)}</b>-го мес., выход с <b>{ret}</b>-го "
                    f"(слот <b>{month}</b>-й)"
                )
            else:
                lines.append(
                    f"• {nm} — <b>{tk}</b>: выход с <b>{ret}</b>-го мес. "
                    f"(⚠ задайте <code>out_from_month</code> в JSON)"
                )
        for row in st.get("suspensions", []):
            if row.get("team_norm") != team_norm:
                continue
            if row.get("scope") != scope or row.get("league_code") != lc:
                continue
            if not _suspension_blocks_at_round(row, fixture_round):
                continue
            left = int(row.get("matches_left") or 0)
            nm = esc(str(row.get("name", "?")))
            w = "матч" if left == 1 else "матча" if 2 <= left <= 4 else "матчей"
            ufr = row.get("unavailable_from_round")
            ufr_txt = f", с тура <b>{int(ufr)}</b>" if ufr is not None else ""
            rnd_txt = (
                f" (тур слота <b>{fixture_round}</b>)" if fixture_round is not None else ""
            )
            lines.append(
                f"• {nm} — дискв. <b>{left}</b> {w}{ufr_txt}{rnd_txt} ({esc(lc)})"
            )
        if not lines:
            return None
        return f"<b>{esc(team_label)}</b>\n" + "\n".join(lines)

    th_n, ta_n = _norm(home), _norm(away)
    chunks: list[str] = []
    hb = _team_block(home, th_n)
    if hb:
        chunks.append(hb)
    ab = _team_block(away, ta_n)
    if ab:
        chunks.append(ab)
    if not chunks:
        return ""
    return (
        "<b>⚠ Травмы и дисквалы</b> (по данным дисциплины)\n\n"
        + "\n\n".join(chunks)
    )


def format_active_injuries_report_text(*, schedule_month: int | None = None) -> str:
    """
    Моноширинный отчёт: травмы, активные дисквалы (после жк/кк), накопление жк к 4-й.

    Дисквалы: ``matches_left`` — сколько ещё **закрытых** матчей команды в этом турнире
    до снятия (см. ``register_match_played_for_discipline``).
    """
    month = get_calendar_month(schedule_month)
    season_now = _get_active_season_or_default()
    with _lock:
        st = _load()

    chunks: list[str] = [f"Месяц календаря: {month} (сезон {season_now}).", ""]

    # --- травмы ---
    inj_rows: list[tuple[str, str, str, str, int, str]] = []
    for inj in st.get("injuries", []):
        ret = int(inj.get("return_month") or 99)
        ofm = inj.get("out_from_month")
        ofm_s = str(int(ofm)) if ofm is not None else "?"
        name = str(inj.get("name") or "?").strip()
        team = str(inj.get("team") or "?").strip()
        kind = (inj.get("type") or "травма").strip() or "травма"
        if ofm is None:
            st_mark = "?"
        elif _injury_blocks_at_month(inj, month, current_season=season_now):
            st_mark = "активна"
        elif (
            inj.get("season") is not None
            and int(inj.get("season")) < season_now
            and ret <= _SEASON_MONTHS * (season_now - int(inj.get("season"))) + month
        ):
            st_mark = "прошла"
        elif (inj.get("season") in (None, season_now)) and month >= ret:
            st_mark = "прошла"
        else:
            st_mark = "позже"
        inj_rows.append((team, name, kind, ofm_s, ret, st_mark))
    chunks.append("── ТРАВМЫ (все периоды в JSON) ──")
    chunks.append(
        "Несколько строк на одного игрока — норма (туры вразнобой). "
        "«с»/«до» — месяцы; статус — для текущего месяца календаря."
    )
    if not inj_rows:
        chunks.append("Записей о травмах нет.")
    else:
        inj_rows.sort(key=lambda r: (r[0].casefold(), r[1].casefold(), r[3], r[4]))
        w_team = max(len("Клуб"), max(len(r[0]) for r in inj_rows))
        w_name = max(len("Игрок"), max(len(r[1]) for r in inj_rows))
        head = (
            f"{'Клуб':<{w_team}}  {'Игрок':<{w_name}}  {'Тип':<10}  "
            f"с   до   статус"
        )
        sep = "-" * len(head)
        lines = [head, sep]
        for team, name, kind, ofm_s, ret, st_mark in inj_rows:
            lines.append(
                f"{team:<{w_team}}  {name:<{w_name}}  {kind[:10]:<10}  "
                f"{ofm_s:<3} м{ret:<3} {st_mark}"
            )
        chunks.append(f"Периодов: {len(inj_rows)}.")
        chunks.extend(lines)

    chunks.append("")
    chunks.append("── ДИСКВАЛЫ (после жк/кк в матче) ──")
    chunks.append(
        "Осталось матчей — сколько закрытых матчей команды в этом турнире до снятия дисквала."
    )
    susp_rows: list[tuple[str, str, str, int, str]] = []
    for row in st.get("suspensions", []):
        left = int(row.get("matches_left") or 0)
        if left <= 0:
            continue
        team = str(row.get("team") or "?").strip()
        name = str(row.get("name") or "?").strip()
        lab = _tournament_label(str(row.get("league_code") or ""), str(row.get("scope") or ""))
        ufr = row.get("unavailable_from_round")
        ufr_s = str(int(ufr)) if ufr is not None else "?"
        susp_rows.append((team, name, lab, left, ufr_s))
    if not susp_rows:
        chunks.append("Активных дисквалов нет.")
    else:
        susp_rows.sort(key=lambda r: (r[2].casefold(), r[0].casefold(), r[1].casefold()))
        w_team = max(len("Клуб"), max(len(r[0]) for r in susp_rows))
        w_name = max(len("Игрок"), max(len(r[1]) for r in susp_rows))
        w_tour = max(len("Турнир"), max(len(r[2]) for r in susp_rows))
        head = (
            f"{'Клуб':<{w_team}}  {'Игрок':<{w_name}}  {'Турнир':<{w_tour}}  "
            f"с тура  ост."
        )
        sep = "-" * len(head)
        lines = [head, sep]
        for team, name, lab, left, ufr_s in susp_rows:
            wn = "матч" if left == 1 else "матча" if 2 <= left <= 4 else "матчей"
            lines.append(
                f"{team:<{w_team}}  {name:<{w_name}}  {lab:<{w_tour}}  "
                f"{ufr_s:<5} {left} {wn}"
            )
        chunks.append(f"Игроков: {len(susp_rows)}.")
        chunks.extend(lines)

    chunks.append("")
    chunks.append("── НАКОПЛЕНИЕ ЖК (к 4-й в сезоне лиги / ЛЧ) ──")
    chunks.append("При 4-й жёлтой в цикле — 1 матч дисквала, счётчик жк обнуляется.")
    yel_rows: list[tuple[str, str, str, int]] = []
    for row in st.get("yellow_cycle", []):
        cnt = int(row.get("count") or 0)
        if cnt <= 0:
            continue
        team = str(row.get("team") or "?").strip()
        name = str(row.get("name") or "?").strip()
        lab = _tournament_label(str(row.get("league_code") or ""), str(row.get("scope") or ""))
        yel_rows.append((team, name, lab, cnt))
    if not yel_rows:
        chunks.append("Нет записей с ненулевым счётчиком жк.")
    else:
        yel_rows.sort(key=lambda r: (r[2].casefold(), r[0].casefold(), r[1].casefold()))
        w_team = max(len("Клуб"), max(len(r[0]) for r in yel_rows))
        w_name = max(len("Игрок"), max(len(r[1]) for r in yel_rows))
        w_tour = max(len("Турнир"), max(len(r[2]) for r in yel_rows))
        head = f"{'Клуб':<{w_team}}  {'Игрок':<{w_name}}  {'Турнир':<{w_tour}}  жк"
        sep = "-" * len(head)
        lines = [head, sep]
        for team, name, lab, cnt in yel_rows:
            lines.append(f"{team:<{w_team}}  {name:<{w_name}}  {lab:<{w_tour}}  {cnt}/{_YEL4}")
        chunks.append(f"Игроков: {len(yel_rows)}.")
        chunks.extend(lines)

    return "\n".join(chunks)


def migrate_cl_discipline_team(player: str, new_team: str) -> None:
    """После трансфера: записи ЛЧ в JSON привязать к новому клубу (цикл жк / дисквал ЛЧ)."""
    nn = _norm(player)
    nt = new_team.strip().title()
    if not nn or not nt:
        return
    with _lock:
        st = _load()
        for bucket in ("suspensions", "yellow_cycle"):
            for row in st.get(bucket, []):
                if row.get("name_norm") != nn:
                    continue
                if not _is_cl_scope(
                    str(row.get("scope") or ""),
                    str(row.get("league_code") or ""),
                ):
                    continue
                row["team"] = nt
                row["team_norm"] = _norm(nt)
                row["key"] = _susp_key(
                    row.get("name") or player,
                    nt,
                    "cl",
                    "cl",
                )
        _consolidate_cl_yellow_rows(st, nn, keep_team=nt)
        _save(st)


def reset_yellow_accumulation_for_player(
    name: str,
    *,
    league_codes: list[str] | None = None,
    include_cl: bool = True,
) -> int:
    """
    Обнулить накопление жк к 4-й (``yellow_cycle.count``), не трогая ``yellow_cards`` в SQLite.

    ``league_codes`` — только эти нац. лиги (rpl, eng, …); ``None`` — все циклы игрока.
    ``include_cl`` — сбрасывать ли цикл в ЛЧ (scope/league_code cl).
    """
    name_norm = _norm(name)
    if not name_norm:
        return 0
    codes = (
        {c.strip().lower() for c in league_codes if c}
        if league_codes is not None
        else None
    )
    n = 0
    with _lock:
        st = _load()
        for row in st.get("yellow_cycle", []):
            if row.get("name_norm") != name_norm:
                continue
            lc = (row.get("league_code") or "").strip().lower()
            scope = (row.get("scope") or "league").strip().lower()
            is_cl = scope == "cl" or lc == "cl"
            if codes is not None:
                if is_cl:
                    if not include_cl:
                        continue
                elif lc not in codes:
                    continue
            elif is_cl and not include_cl:
                continue
            if int(row.get("count") or 0) != 0:
                row["count"] = 0
                n += 1
        if n:
            _save(st)
    return n


def clear_discipline_for_new_season() -> dict[str, int]:
    """
    Начало нового сезона: обнулить циклы жк к 4-й; активные дисквалы и травмы оставить.

    ``yellow_cards`` / ``red_cards`` в SQLite не трогаются (см. ``finalize_season``).
    """
    with _lock:
        st = _load()
        ycleared = len(st.get("yellow_cycle", []))
        st["yellow_cycle"] = []
        susp = [
            r
            for r in st.get("suspensions", [])
            if int(r.get("matches_left") or 0) > 0
        ]
        kept_s = len(susp)
        st["suspensions"] = susp
        inj = len(st.get("injuries", []))
        _save(st)
    return {"yellow_cycle_cleared": ycleared, "suspensions_kept": kept_s, "injuries_kept": inj}


def clear_discipline_state() -> None:
    """Полный сброс JSON (ручной сброс; не использовать при ``finalize_season``)."""
    with _lock:
        if _STATE_PATH.is_file():
            _STATE_PATH.unlink()


def line_looks_discipline(s: str) -> bool:
    t = (s or "").strip()
    if _RE_INJ_FROM.match(t) or _RE_INJ.match(t):
        return True
    if t.endswith("2жк"):
        return True
    if t.endswith("жк") or t.endswith("кк"):
        return True
    return False
