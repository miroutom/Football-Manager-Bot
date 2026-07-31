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
- травма: «имя Nм» / «имя Nm» — только **2** или **4** месяца;
  «имя сM Nм» / «имя @M Nm» — с месяца M на 2 или 4 месяца.
  У **полевых** две «жизни»: первая травма — остаётся в клубе; вторая — ``left_team=True``.
  У **вратарей** пять «жизней»: уходит после пятой травмы. Рейтинг не меняется.
- дисквал: в JSON ``unavailable_from_round`` — с какого тура чемпионата бан действует (null = как раньше).
  Нац. лига: туров 1–14; если бан «после» 14-го — ``unavailable_from_round=1`` (перенос на
  следующий сезон; при ``clear_discipline_for_new_season`` активные дисквалы сохраняются,
  цикл жк сгорает — см. ``docs/stats_display_rules.md``).
"""
from __future__ import annotations

import json
import os
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
    "wc": "ЧМ",
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


def is_card_line(text: str) -> bool:
    """Строка жк/кк: «имя жк», «имя кк», «имя 2жк»."""
    t = (text or "").strip()
    return bool(
        _RE_2Y.match(t) or _RE_2Y_GLUE.match(t) or _RE_Y.match(t) or _RE_R.match(t)
    )


def format_calendar_month_label(month: int | None) -> str:
    """«6 месяц» вместо «с6» / «м6»."""
    if month is None:
        return "—"
    try:
        return f"{int(month)} месяц"
    except (TypeError, ValueError):
        return "—"


def injury_overall_penalty(months: int) -> int:
    """
    Штраф к overall при **новой** травме по сроку N месяцев.

    С сезона 3 (после зимнего ТО) отключён: рейтинги не режем из‑за травм.
    Раньше: ≤2м → 0; 3–6м → −2; 7м → −4; ≥8м → −7.
    """
    _ = int(months)
    return 0


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
        max_m = 10
        try:
            from utils.world_cup import is_world_cup_season

            if is_world_cup_season():
                max_m = 11
        except Exception:
            pass
        if 1 <= di <= max_m and di > best:
            best = di
    return best or 1


def get_calendar_month(schedule_day: int | None) -> int:
    """Текущий «месяц» календаря.

    Обычный сезон: дни 1..10. В сезонах ЧМ допускается день 11 (турнир после ЛЧ).
    Если день не передан — ``infer_current_calendar_month()``.
    """
    if schedule_day is not None:
        d = int(schedule_day)
        max_m = 10
        try:
            from utils.world_cup import is_world_cup_season

            if is_world_cup_season():
                max_m = 11
        except Exception:
            pass
        if 1 <= d <= max_m:
            return d
    return infer_current_calendar_month()


def find_fixture_round(
    home: str,
    away: str,
    league_code: str,
    *,
    cl_phase: str | None = None,
    for_team: str | None = None,
) -> int | None:
    """
    Номер тура слота.

    Нац. лиги: по умолчанию следующий тур **хозяев** (подписи кнопок).
    Если задан ``for_team`` — тур **этой** команды для данного матча
    (для дискв.: у хозяев и гостей номера могут отличаться).
    ЛЧ — тур из полного календаря ``schedule.py``.
    """
    lc = (league_code or "").strip().lower()
    if lc in ("rpl", "eng", "esp", "ger", "ita"):
        from utils.calendar_slot_labels import (
            home_display_round,
            team_round_for_fixture,
        )

        if for_team:
            return team_round_for_fixture(for_team, home, away, lc)
        return home_display_round(home, lc)
    if lc != "cl":
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
# Допустимые сроки травмы (месяцы).
_ALLOWED_INJURY_MONTHS = frozenset({2, 4})
_MAX_INJURY_DURATION_MONTHS = max(_ALLOWED_INJURY_MONTHS)
_GK_POSITIONS = frozenset({"ВРТ", "ВР", "GK"})
_FIELD_INJURY_LIVES = 2
_GK_INJURY_LIVES = 5


def _is_field_player(player: Any) -> bool:
    pos = (getattr(player, "position", None) or "").strip().upper()
    return pos not in _GK_POSITIONS


def _injury_life_limit(player: Any) -> int:
    return _FIELD_INJURY_LIVES if _is_field_player(player) else _GK_INJURY_LIVES


def _validate_injury_duration(nmonths: int) -> str | None:
    if int(nmonths) not in _ALLOWED_INJURY_MONTHS:
        return "Травма только на 2 или 4 месяца: <code>имя 2м</code> или <code>имя 4м</code>."
    return None


def _mark_player_left_team_in_dbs(player_name: str, team: str) -> bool:
    """``left_team=True`` в league + ЛЧ для игрока клуба."""
    from player_stats import find_player_by_name, get_session
    from utils.player_transfer import mark_player_left_team

    changed = False
    for tourn in ("league", "cl"):
        sess = get_session(tourn)
        try:
            pl, _ = find_player_by_name(sess, player_name, team)
            if pl is None or bool(getattr(pl, "left_team", False)):
                continue
            mark_player_left_team(pl)
            sess.commit()
            changed = True
        except Exception:
            sess.rollback()
        finally:
            sess.close()
    return changed


def close_stale_carryover_injuries(
    *,
    season_now: int | None = None,
    month: int | None = None,
    last_injured_month: int = _SEASON_MONTHS,
) -> int:
    """
    Закрыть «висящие» травмы прошлого сезона: если период всё ещё активен
    в новом сезоне, обрезать ``return_month`` до конца ``last_injured_month``
    сезона старта (по умолчанию 10-й → выход с 11-го).
    """
    season_now = int(season_now if season_now is not None else _get_active_season_or_default())
    month = int(month if month is not None else get_calendar_month(None))
    return_after = int(last_injured_month) + 1
    fixed = 0
    with _lock:
        st = _load()
        for row in st.get("injuries") or []:
            if not isinstance(row, dict):
                continue
            if _injury_status_label(row, month=month, season_now=season_now) != "активна":
                continue
            try:
                inj_season = int(row.get("season") or season_now)
            except (TypeError, ValueError):
                continue
            if inj_season >= season_now:
                continue
            try:
                ofm = int(row.get("out_from_month") or 1)
            except (TypeError, ValueError):
                ofm = 1
            new_ret = max(ofm + 1, return_after)
            old_ret = int(row.get("return_month") or 0)
            if old_ret <= new_ret:
                continue
            row["return_month"] = new_ret
            row["key"] = _injury_period_key(
                str(row.get("name") or ""),
                str(row.get("team") or ""),
                ofm,
                new_ret,
                inj_season,
            )
            fixed += 1
        if fixed:
            _save(st)
    return fixed


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
    Без ``season`` период **не** блокирует (нужно проставить сезон в JSON).
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
    if inj_season is None:
        return False
    if current_season is None:
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


def _injury_period_key(
    name: str,
    team: str,
    out_from_month: int,
    return_month: int,
    season: int | None = None,
) -> str:
    s = int(season) if season is not None else 0
    return f"{_norm(name)}|{_norm(team)}|{s}|{int(out_from_month)}|{int(return_month)}"


def _injury_period_key_legacy(
    name: str, team: str, out_from_month: int, return_month: int
) -> str:
    """Ключ до введения ``season`` в key (обратная совместимость)."""
    return f"{_norm(name)}|{_norm(team)}|{int(out_from_month)}|{int(return_month)}"


def _injuries_for_player(st: dict, name: str, team: str) -> list[dict]:
    nn, tn = _norm(name), _norm(team)
    return [
        row
        for row in st.get("injuries", [])
        if row.get("name_norm") == nn and row.get("team_norm") == tn
    ]


def _find_injury_period(
    st: dict,
    name: str,
    team: str,
    out_from_month: int,
    return_month: int,
    *,
    season: int | None = None,
) -> dict | None:
    want = _injury_period_key(name, team, out_from_month, return_month, season)
    want_legacy = _injury_period_key_legacy(name, team, out_from_month, return_month)
    for row in st.get("injuries", []):
        if row.get("key") in (want, want_legacy):
            return row
        try:
            ofm = row.get("out_from_month")
            ret = row.get("return_month")
            row_season = row.get("season")
            if (
                row.get("name_norm") == _norm(name)
                and row.get("team_norm") == _norm(team)
                and ofm is not None
                and int(ofm) == int(out_from_month)
                and int(ret) == int(return_month)
                and (
                    season is None
                    or row_season is None
                    or int(row_season) == int(season)
                )
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
    fixture_home: str | None = None,
    fixture_away: str | None = None,
    cl_phase: str | None = None,
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

    rnd = fixture_round
    if fixture_home and fixture_away and lc not in ("cl",):
        rnd = find_fixture_round(
            fixture_home,
            fixture_away,
            lc,
            cl_phase=cl_phase,
            for_team=team,
        )
    elif fixture_home and fixture_away and rnd is None:
        rnd = find_fixture_round(
            fixture_home, fixture_away, lc, cl_phase=cl_phase
        )

    row = _find_susp(st, name, team, lc, scope)
    if row and _suspension_blocks_at_round(row, rnd):
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
    cl_phase: str | None = None,
) -> None:
    """
    После ввода статистики по матчу: −1 матч дискв. у игроков команд home/away в этом турнире.

    Если передан ``susp_snapshot_before_stats`` (снимок до начала ввода строк матча в боте),
    уменьшаем только те ключи, что уже были в снимке — новые дисквалы за этот матч не трогаем.
    Если ``None``, поведение как раньше: все активные дисквалы по матчу −1 (для совместимости).

    Списание только если бан уже действует на этот матч **для команды игрока**
    (``unavailable_from_round``).
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
            team_name = str(row.get("team") or "")
            team_rnd = find_fixture_round(
                home, away, lc, cl_phase=cl_phase, for_team=team_name or None
            )
            if not _suspension_blocks_at_round(row, team_rnd):
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
    player_team: str | None = None,
) -> int | None:
    """Бан со следующего матча **команды игрока** после текущего слота."""
    if not fixture_home or not fixture_away:
        return None
    lc = (league_code or "").strip().lower()
    team = (player_team or "").strip() or None
    rnd = find_fixture_round(
        fixture_home,
        fixture_away,
        league_code,
        cl_phase=cl_phase,
        for_team=team if team and lc in ("rpl", "eng", "esp", "ger", "ita") else None,
    )
    if rnd is None:
        return None
    nxt = max(1, int(rnd) + 1)
    # нац. лига: после 14-го тура следующего матча нет → бан с 1-го тура след. сезона
    if lc in ("rpl", "eng", "esp", "ger", "ita") and nxt > 14:
        return 1
    return nxt


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
        player_team=current_team,
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
        if not (1 <= out_from <= _SEASON_MONTHS and 1 <= nm <= _MAX_INJURY_DURATION_MONTHS):
            return (
                f"Некорректно: старт месяца 1–{_SEASON_MONTHS}, "
                f"срок 2 или 4 мес.",
                True,
            )
        err = _validate_injury_duration(nm)
        if err:
            return (err, True)
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
        if nm < 1 or nm > _MAX_INJURY_DURATION_MONTHS:
            return (
                "Некорректно: травма только на 2 или 4 месяца.",
                True,
            )
        err = _validate_injury_duration(nm)
        if err:
            return (err, True)
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
    if unavailable_from_round is None:
        ufr_note = ""
    elif int(unavailable_from_round) == 1:
        # после 14-го тура нац. лиги — перенос на старт следующего сезона
        ufr_note = " Бан с 1-го тура следующего сезона (перенос)."
    else:
        ufr_note = f" Бан с тура {unavailable_from_round}."
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
        inj = _find_injury_period(
            st, player.name, team, cur, ret, season=season_now
        )
        if inj is None:
            inj = {
                "key": _injury_period_key(
                    player.name, team, cur, ret, season_now
                ),
                "name": player.name,
                "name_norm": _norm(player.name),
                "team": team,
                "team_norm": _norm(team),
                "out_from_month": cur,
                "return_month": ret,
                "type": injury_type,
                "season": season_now,
            }
            st.setdefault("injuries", []).append(inj)
            added = True
        else:
            inj["type"] = injury_type
            inj["season"] = season_now
            inj["key"] = _injury_period_key(
                player.name, team, cur, ret, season_now
            )
            added = False
        periods_count = len(_injuries_for_player(st, player.name, team))
        _save(st)
    leave_note = ""
    life_limit = _injury_life_limit(player)
    if added and periods_count >= life_limit:
        if _mark_player_left_team_in_dbs(player.name, team):
            leave_note = f" Игрок ушёл из клуба ({periods_count}-я травма)."
    rating_note = ""
    if added:
        delta = injury_overall_penalty(nmonths)
        if delta:
            overall_before_penalty = int(getattr(player, "overall", 0) or 0)
            from utils.player_overall_bumps import apply_overall_bumps_for_team

            bump_res = apply_overall_bumps_for_team(team, f"{player.name} {delta:+d}")
            if bump_res.ok:
                rating_note = f" Рейтинг {delta:+d}."
                if overall_before_penalty > 0:
                    with _lock:
                        st2 = _load()
                        row = _find_injury_period(
                            st2, player.name, team, cur, ret, season=season_now
                        )
                        if row is not None:
                            row["overall_before_penalty"] = overall_before_penalty
                            _save(st2)
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
        f"✓ Травма ({tk}): {player.name} — с {format_calendar_month_label(cur)}, "
        f"выход с {format_calendar_month_label(ret)} "
        f"(срок {nmonths} мес.).{carry}{rating_note}{leave_note} {note}",
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

    with _lock:
        st = _load()

    def _team_block(team_label: str, team_norm: str) -> str | None:
        # тур слота для этой команды (не всегда тур хозяев)
        team_rnd = find_fixture_round(
            home, away, lc, cl_phase=cl_phase, for_team=team_label
        )
        if team_rnd is None:
            team_rnd = fixture_round
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
            if not _suspension_blocks_at_round(row, team_rnd):
                continue
            left = int(row.get("matches_left") or 0)
            nm = esc(str(row.get("name", "?")))
            w = "матч" if left == 1 else "матча" if 2 <= left <= 4 else "матчей"
            ufr = row.get("unavailable_from_round")
            ufr_txt = f", с тура <b>{int(ufr)}</b>" if ufr is not None else ""
            rnd_txt = (
                f" (тур слота <b>{team_rnd}</b>)" if team_rnd is not None else ""
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


def list_injury_seasons() -> list[int]:
    """Сезоны, для которых есть хотя бы одна запись травмы (по убыванию)."""
    with _lock:
        st = _load()
    seasons: set[int] = set()
    for inj in st.get("injuries", []) or []:
        sn = inj.get("season")
        if sn is None:
            continue
        try:
            seasons.add(int(sn))
        except (TypeError, ValueError):
            continue
    return sorted(seasons, reverse=True)


def _injury_status_label(
    inj: dict,
    *,
    month: int,
    season_now: int,
) -> str:
    ret = int(inj.get("return_month") or 99)
    ofm = inj.get("out_from_month")
    inj_season = inj.get("season")
    if ofm is None:
        return "?"
    if inj_season is None:
        return "нет сезона"
    if _injury_blocks_at_month(inj, month, current_season=season_now):
        return "активна"
    try:
        sn = int(inj_season)
    except (TypeError, ValueError):
        return "?"
    if sn < season_now and ret <= _SEASON_MONTHS * (season_now - sn) + month:
        return "прошла"
    if sn == season_now and month >= ret:
        return "прошла"
    return "позже"


def _format_injury_rows_table(
    injuries: list[dict],
    *,
    month: int,
    season_now: int,
    title: str,
) -> list[str]:
    """Строки таблицы травм для моноширинного отчёта."""
    chunks: list[str] = [title]
    chunks.append(
        "«начало»/«конец» — месяцы календаря; статус — относительно текущего месяца."
    )
    inj_rows: list[tuple[str, str, str, str, str, str]] = []
    for inj in injuries:
        ret = int(inj.get("return_month") or 99)
        ofm = inj.get("out_from_month")
        name = str(inj.get("name") or "?").strip()
        team = str(inj.get("team") or "?").strip()
        kind = (inj.get("type") or "травма").strip() or "травма"
        st_mark = _injury_status_label(inj, month=month, season_now=season_now)
        start_s = format_calendar_month_label(int(ofm) if ofm is not None else None)
        end_s = format_calendar_month_label(ret if ret != 99 else None)
        inj_rows.append((team, name, kind, st_mark, start_s, end_s))
    if not inj_rows:
        chunks.append("Записей о травмах нет.")
        return chunks
    inj_rows.sort(
        key=lambda r: (r[0].casefold(), r[1].casefold(), r[4], r[5])
    )
    w_team = max(len("Клуб"), max(len(r[0]) for r in inj_rows))
    w_name = max(len("Игрок"), max(len(r[1]) for r in inj_rows))
    head = (
        f"{'Клуб':<{w_team}}  {'Игрок':<{w_name}}  {'Тип':<8}  "
        f"{'Статус':<8}  {'Начало':<10}  {'Конец'}"
    )
    sep = "-" * len(head)
    lines = [head, sep]
    for team, name, kind, st_mark, start_s, end_s in inj_rows:
        lines.append(
            f"{team:<{w_team}}  {name:<{w_name}}  {kind[:8]:<8}  "
            f"{st_mark:<8}  {start_s:<10}  {end_s}"
        )
    chunks.append(f"Периодов: {len(inj_rows)}.")
    chunks.extend(lines)
    return chunks


def format_injuries_season_report_text(
    season: int,
    *,
    schedule_month: int | None = None,
) -> str:
    """Травмы только за указанный сезон старта периода."""
    month = get_calendar_month(schedule_month)
    season_now = _get_active_season_or_default()
    sn = int(season)
    with _lock:
        st = _load()
    injuries = [
        inj
        for inj in (st.get("injuries") or [])
        if inj.get("season") is not None and int(inj.get("season")) == sn
    ]
    chunks: list[str] = [
        f"Месяц календаря: {month} (текущий сезон {season_now}).",
        f"Фильтр: травмы, начавшиеся в сезоне {sn}.",
        "",
    ]
    chunks.extend(
        _format_injury_rows_table(
            injuries,
            month=month,
            season_now=season_now,
            title=f"── ТРАВМЫ · СЕЗОН {sn} ──",
        )
    )
    return "\n".join(chunks)


def format_injury_frequency_report_text(*, limit: int = 25) -> str:
    """Кто чаще всего травмировался: число периодов и суммарные месяцы (все сезоны)."""
    with _lock:
        st = _load()
    career = _career_player_index()
    # name_norm -> agg
    agg: dict[str, dict[str, Any]] = {}
    for inj in st.get("injuries") or []:
        nn = str(inj.get("name_norm") or _norm(str(inj.get("name") or ""))).strip()
        if not nn:
            continue
        name = str(inj.get("name") or nn).strip()
        team = str(inj.get("team") or "?").strip()
        row = agg.get(nn)
        if row is None:
            row = {
                "name": name,
                "teams": {},
                "periods": 0,
                "months": 0,
            }
            agg[nn] = row
        row["periods"] += 1
        row["months"] += _injury_total_months(inj)
        if team:
            row["teams"][team] = int(row["teams"].get(team, 0)) + 1

    ranked: list[tuple[int, int, str, str, int]] = []
    for nn, row in agg.items():
        teams_map: dict[str, int] = row["teams"]
        info = career.get(nn) or {}
        if teams_map:
            top_team = max(teams_map.items(), key=lambda kv: (kv[1], kv[0]))[0]
        else:
            top_team = str(info.get("team") or "?")
        if info.get("name"):
            row["name"] = str(info["name"])
        ovr = int(info.get("overall") or 0)
        ranked.append(
            (
                int(row["periods"]),
                int(row["months"]),
                str(row["name"]),
                top_team,
                ovr,
            )
        )
    ranked.sort(key=lambda r: (-r[0], -r[1], -r[4], r[2].casefold()))
    show = ranked[: max(1, int(limit))]

    chunks: list[str] = [
        "── ЧАЩЕ ВСЕГО ТРАВМИРОВАЛИСЬ ──",
        "Все периоды травм в JSON за все сезоны. "
        "«раз» — число травм; «мес» — сумма длительностей; "
        "OVR — макс. рейтинг по архивам всех сезонов.",
        "",
    ]
    if not show:
        chunks.append("Записей о травмах нет.")
        return "\n".join(chunks)

    w_name = max(len("Игрок"), max(len(r[2]) for r in show))
    w_team = max(len("Клуб"), max(len(r[3]) for r in show))
    head = f"{'#':<3}  {'Игрок':<{w_name}}  {'Клуб':<{w_team}}  OVR  раз  мес"
    sep = "-" * len(head)
    lines = [head, sep]
    for i, (periods, months, name, team, ovr) in enumerate(show, start=1):
        ovr_s = str(ovr) if ovr > 0 else "—"
        lines.append(
            f"{i:<3}  {name:<{w_name}}  {team:<{w_team}}  {ovr_s:<3}  {periods:<3}  {months}"
        )
    chunks.append(f"Игроков в топе: {len(show)} (из {len(ranked)}).")
    chunks.extend(lines)
    return "\n".join(chunks)


def _career_player_index() -> dict[str, dict[str, Any]]:
    """
    Игроки по всем сезонам (архивы league.db + champions_league.db).

    Ключ — ``name_norm``. Матчи суммируются за карьеру; OVR/клуб/позиция —
    из последнего сезона, где игрок встречался.
    """
    import sqlite3

    from utils import season_paths
    from utils.cumulative_db import list_season_archives_with_db

    seasons = set(list_season_archives_with_db())
    try:
        seasons.add(int(season_paths.get_active_season()))
    except Exception:
        pass

    # name_norm -> season -> stats that season
    by_sn: dict[str, dict[int, dict[str, Any]]] = {}
    for sn in sorted(seasons):
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
                            f"SELECT name, team, position, "
                            f"COALESCE(matches, 0), COALESCE(overall, 0) "
                            f"FROM {tbl}"
                        )
                    except sqlite3.OperationalError:
                        continue
                    for name, team, pos, matches, ovr in cur:
                        nm = (name or "").strip()
                        if not nm:
                            continue
                        key = _norm(nm)
                        slot = by_sn.setdefault(key, {}).setdefault(
                            int(sn),
                            {
                                "name": nm,
                                "matches": 0,
                                "overall": 0,
                                "team": (team or "?").strip() or "?",
                                "position": (pos or "").strip().upper(),
                                "teams": {},
                            },
                        )
                        slot["matches"] += int(matches or 0)
                        ovri = int(ovr or 0)
                        if ovri >= int(slot["overall"]):
                            slot["overall"] = ovri
                        tm = (team or "").strip()
                        if tm:
                            slot["teams"][tm] = int(slot["teams"].get(tm, 0)) + int(
                                matches or 0
                            )
                            # клуб сезона — где больше матчей
                            top = max(
                                slot["teams"].items(),
                                key=lambda kv: (kv[1], kv[0]),
                            )[0]
                            slot["team"] = top
                        if pos and not slot["position"]:
                            slot["position"] = (pos or "").strip().upper()
            finally:
                conn.close()

    out: dict[str, dict[str, Any]] = {}
    for key, seasons_map in by_sn.items():
        total_m = sum(int(v["matches"]) for v in seasons_map.values())
        last_sn = max(seasons_map)
        last = seasons_map[last_sn]
        # лучший OVR за карьеру (не обязательно последний)
        best_ovr = max(int(v["overall"]) for v in seasons_map.values())
        out[key] = {
            "name": str(last["name"]),
            "team": str(last["team"]),
            "position": str(last.get("position") or ""),
            "matches": int(total_m),
            "overall": int(best_ovr),
            "last_season": int(last_sn),
        }
    return out


def format_never_injured_report_text(
    *,
    limit: int = 50,
    min_matches: int = 1,
) -> str:
    """
    Игроки за все сезоны (архивы), у которых нет ни одной записи травмы в JSON.

    Сортировка: больше карьерных матчей выше.
    """
    with _lock:
        st = _load()
    injured: set[str] = set()
    for inj in st.get("injuries") or []:
        nn = str(inj.get("name_norm") or _norm(str(inj.get("name") or ""))).strip()
        if nn:
            injured.add(nn)

    career = _career_player_index()
    ranked = [
        row
        for key, row in career.items()
        if key not in injured and int(row.get("matches") or 0) >= int(min_matches)
    ]
    ranked.sort(
        key=lambda r: (
            -int(r["matches"]),
            -int(r.get("overall") or 0),
            str(r["name"]).casefold(),
        )
    )
    show = ranked[: max(1, int(limit))]

    chunks: list[str] = [
        "── НИ РАЗУ НЕ ТРАВМИРОВАЛИСЬ ──",
        "Нет записей в JSON травм за все сезоны. "
        "Матчи и OVR — сумма/макс по архивам всех сезонов (лига+ЛЧ). "
        f"Мин. матчей: {min_matches}.",
        "",
    ]
    if not show:
        chunks.append("Таких игроков нет (или все уже имели травму).")
        return "\n".join(chunks)

    w_name = max(len("Игрок"), max(len(str(r["name"])) for r in show))
    w_team = max(len("Клуб"), max(len(str(r["team"])) for r in show))
    w_pos = max(len("Поз"), max(len(str(r["position"]) or "—") for r in show))
    head = (
        f"{'#':<3}  {'Игрок':<{w_name}}  {'Клуб':<{w_team}}  "
        f"{'Поз':<{w_pos}}  OVR  матч"
    )
    sep = "-" * len(head)
    lines = [head, sep]
    for i, r in enumerate(show, start=1):
        ovr = int(r.get("overall") or 0)
        ovr_s = str(ovr) if ovr > 0 else "—"
        lines.append(
            f"{i:<3}  {r['name']:<{w_name}}  {r['team']:<{w_team}}  "
            f"{(r['position'] or '—'):<{w_pos}}  {ovr_s:<3}  {r['matches']}"
        )
    chunks.append(
        f"В топе: {len(show)} (всего без травм с матчами: {len(ranked)}; "
        f"с травмой в JSON: {len(injured)})."
    )
    chunks.extend(lines)
    return "\n".join(chunks)


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
    chunks.extend(
        _format_injury_rows_table(
            list(st.get("injuries") or []),
            month=month,
            season_now=season_now,
            title="── ТРАВМЫ (все периоды в JSON) ──",
        )
    )

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

    У перенесённых дисквалов ``unavailable_from_round`` сбрасывается на 1 (или оставляется
    1…14), чтобы бан «с 15-го» прошлого сезона действовал с 1-го тура нового.
    ``yellow_cards`` / ``red_cards`` в SQLite не трогаются (см. ``finalize_season``).
    """
    with _lock:
        st = _load()
        ycleared = len(st.get("yellow_cycle", []))
        st["yellow_cycle"] = []
        susp = []
        for r in st.get("suspensions", []):
            if int(r.get("matches_left") or 0) <= 0:
                continue
            ufr = r.get("unavailable_from_round")
            if ufr is not None:
                try:
                    u = int(ufr)
                except (TypeError, ValueError):
                    u = 1
                # прошлый сезон / «после 14» → с первого тура нового
                if u < 1 or u > 14:
                    r["unavailable_from_round"] = 1
            susp.append(r)
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
