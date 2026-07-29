# -*- coding: utf-8 -*-
"""Исправление счёта уже записанного матча (журнал + таблица pickle + логи)."""
from __future__ import annotations

import json
import os
from typing import Any

from utils import season_paths
from utils.utils import PROJECT_ROOT

MATCH_RESULTS_FILE = os.path.join(PROJECT_ROOT, "match_results.json")

_LEAGUE_PICKLE = {
    "rpl": "rpl_teams.pkl",
    "eng": "england_teams.pkl",
    "esp": "spain_teams.pkl",
    "ger": "germany_teams.pkl",
    "ita": "italy_teams.pkl",
    "cl": "champ_league_teams.pkl",
}


def _norm(s: str) -> str:
    return (s or "").strip().title()


def _normalize_cl_phase(raw: Any) -> str:
    if raw is None or str(raw).strip() == "":
        return "knockout"
    p = str(raw).strip().lower()
    if p in ("league", "group", "лига", "группа", "гр", "groups"):
        return "league"
    return "knockout"


def _affects_table(league: str, cl_phase: str | None) -> bool:
    if league != "cl":
        return True
    return _normalize_cl_phase(cl_phase) == "league"


def reverse_add_stat(teams: dict, home: str, away: str, hs: int, aws: int) -> None:
    """Обратное к ``main.add_stat`` / ``Team.update_stats``."""
    th = teams[home]
    ta = teams[away]

    def rev(side, opp: str, s_for: int, s_against: int) -> None:
        side.matches -= 1
        side.scored -= s_for
        side.missed -= s_against
        if s_for > s_against:
            side.wins -= 1
            rp = 3
        elif s_for == s_against:
            side.draws -= 1
            rp = 1
        else:
            side.losses -= 1
            rp = 0
        h = side.head_to_head.get(opp)
        if h:
            h["scored"] -= s_for
            h["missed"] -= s_against
            h["points"] -= rp
            if h["scored"] == 0 and h["missed"] == 0 and h["points"] == 0:
                del side.head_to_head[opp]

    rev(th, away, hs, aws)
    rev(ta, home, aws, hs)


def _teams_dict_for_league(league_code: str) -> dict:
    from main import (
        teams_champ_league,
        teams_eng,
        teams_germany,
        teams_italy,
        teams_rpl,
        teams_spain,
    )

    return {
        "rpl": teams_rpl,
        "eng": teams_eng,
        "esp": teams_spain,
        "ger": teams_germany,
        "ita": teams_italy,
        "cl": teams_champ_league,
    }[league_code]


def find_journal_match(
    home: str,
    away: str,
    league: str,
    *,
    day: int | None = None,
    cl_phase: str | None = None,
) -> dict[str, Any] | None:
    """Найти запись в ``match_results.json`` (без удаления)."""
    h, a = _norm(home), _norm(away)
    lg = (league or "").strip().lower()
    want_phase = _normalize_cl_phase(cl_phase) if lg == "cl" else None
    if not os.path.isfile(MATCH_RESULTS_FILE):
        return None
    with open(MATCH_RESULTS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    matches = data.get("matches") or []
    hits: list[dict[str, Any]] = []
    for r in matches:
        if not isinstance(r, dict):
            continue
        if _norm(str(r.get("home") or "")) != h:
            continue
        if _norm(str(r.get("away") or "")) != a:
            continue
        if str(r.get("league") or "").strip().lower() != lg:
            continue
        if day is not None and int(r.get("day") or -1) != int(day):
            continue
        if lg == "cl" and want_phase is not None:
            if _normalize_cl_phase(r.get("cl_phase")) != want_phase:
                continue
        hits.append(r)
    if len(hits) == 1:
        return hits[0]
    if not hits:
        return None
    # несколько — берём с максимальным day / последнюю
    hits.sort(key=lambda r: (int(r.get("day") or 0),))
    return hits[-1]


def list_recent_scored_matches(*, limit: int = 20) -> list[dict[str, Any]]:
    """Последние сыгранные матчи из журнала (со счётом), новые сверху."""
    if not os.path.isfile(MATCH_RESULTS_FILE):
        return []
    with open(MATCH_RESULTS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    rows = [
        r
        for r in (data.get("matches") or [])
        if isinstance(r, dict)
        and r.get("home_score") is not None
        and r.get("away_score") is not None
    ]
    return list(reversed(rows[-max(1, int(limit)) :]))


def _patch_side_logs(
    *,
    home: str,
    away: str,
    league: str,
    day: int | None,
    cl_phase: str | None,
    new_hs: int,
    new_as: int,
) -> None:
    """Обновить счёт в potm / player_stats логах для слота матча."""
    h, a = _norm(home), _norm(away)
    lg = (league or "").strip().lower()
    tourn = "cl" if lg == "cl" else "league"
    phase = _normalize_cl_phase(cl_phase) if lg == "cl" else ""

    def _match_row(r: dict) -> bool:
        if _norm(str(r.get("home") or "")) != h:
            return False
        if _norm(str(r.get("away") or "")) != a:
            return False
        rt = str(r.get("tournament") or r.get("league_code") or "").strip().lower()
        if rt not in (tourn, lg, ""):
            # potm: tournament=league/cl; stats log same
            if lg != "cl" and rt not in ("league", lg):
                return False
            if lg == "cl" and rt not in ("cl",):
                return False
        if day is not None and r.get("day") is not None and int(r.get("day")) != int(day):
            return False
        if lg == "cl" and r.get("cl_phase") is not None:
            if _normalize_cl_phase(r.get("cl_phase")) != phase:
                return False
        return True

    for rel in (
        "data/match_potm_log.json",
        "data/match_player_stats_log.json",
    ):
        path = os.path.join(PROJECT_ROOT, rel)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                rows = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(rows, list):
            continue
        changed = False
        for r in rows:
            if isinstance(r, dict) and _match_row(r):
                r["home_score"] = int(new_hs)
                r["away_score"] = int(new_as)
                changed = True
        if changed:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)


def correct_match_score(
    home: str,
    away: str,
    league: str,
    new_home_score: int,
    new_away_score: int,
    *,
    day: int | None = None,
    cl_phase: str | None = None,
    expected_old: tuple[int, int] | None = None,
) -> tuple[bool, str]:
    """
    Исправить счёт в журнале и таблице (pickle + in-memory main.teams_*).

    Не трогает статистику игроков (голы/POTM/жк) — их править отдельно
    или через предложение «стата» после правки в боте.

    Возвращает ``(ok, сообщение)``.
    """
    from main import add_stat, save_result

    h, a = _norm(home), _norm(away)
    lg = (league or "").strip().lower()
    if lg not in _LEAGUE_PICKLE:
        return False, f"Неизвестная лига: {league}"

    if not os.path.isfile(MATCH_RESULTS_FILE):
        return False, "Нет match_results.json"

    with open(MATCH_RESULTS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    matches = data.get("matches") or []

    want_phase = _normalize_cl_phase(cl_phase) if lg == "cl" else None
    idx = None
    rec = None
    for i, r in enumerate(matches):
        if not isinstance(r, dict):
            continue
        if _norm(str(r.get("home") or "")) != h:
            continue
        if _norm(str(r.get("away") or "")) != a:
            continue
        if str(r.get("league") or "").strip().lower() != lg:
            continue
        if day is not None and int(r.get("day") or -1) != int(day):
            continue
        if lg == "cl" and want_phase is not None:
            if _normalize_cl_phase(r.get("cl_phase")) != want_phase:
                continue
        idx, rec = i, r
        # продолжаем — последняя подходящая
    if rec is None or idx is None:
        return False, f"Матч не найден: {h} — {a} ({lg}" + (
            f", day={day}" if day is not None else ""
        ) + ")"

    old_hs, old_as = rec.get("home_score"), rec.get("away_score")
    if old_hs is None or old_as is None:
        return False, "У записи нет счёта"
    old_hs, old_as = int(old_hs), int(old_as)
    new_hs, new_as = int(new_home_score), int(new_away_score)

    if expected_old is not None and (old_hs, old_as) != expected_old:
        return (
            False,
            f"В журнале сейчас {old_hs}:{old_as}, ожидали {expected_old[0]}:{expected_old[1]}",
        )

    if (old_hs, old_as) == (new_hs, new_as):
        return True, f"Счёт уже {new_hs}:{new_as} — менять нечего."

    phase = rec.get("cl_phase")
    touch = _affects_table(lg, phase)
    teams = _teams_dict_for_league(lg)

    if touch:
        if h not in teams or a not in teams:
            return False, f"Команды не в таблице: {h!r}, {a!r}"
        reverse_add_stat(teams, h, a, old_hs, old_as)

    rec["home_score"] = new_hs
    rec["away_score"] = new_as
    matches[idx] = rec
    data["matches"] = matches
    with open(MATCH_RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    if touch:
        add_stat(h, a, new_hs, new_as, teams)
        save_result(lg)

    day_v = int(rec.get("day")) if rec.get("day") is not None else day
    _patch_side_logs(
        home=h,
        away=a,
        league=lg,
        day=day_v,
        cl_phase=phase,
        new_hs=new_hs,
        new_as=new_as,
    )

    note = "" if touch else " (ЛЧ нокаут — таблица pickle не менялась)"
    return (
        True,
        f"✓ Счёт исправлен: {h} {old_hs}:{old_as} → {new_hs}:{new_as} {a}{note}",
    )
