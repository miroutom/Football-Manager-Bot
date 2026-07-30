# -*- coding: utf-8 -*-
"""
DEBUG: предложение overall по клубу (не применяет в БД).

Сигналы (каждый даёт небольшой вклад в Δ, итог зажат в ±3):
- форма текущего сезона (G+A / сухие vs ожидание для позиции и OVR);
- POTM (все) и MOTM (только с 6-го календарного месяца);
- карьерная продуктивность в клубе;
- травмы (месяцы / периоды);
- win% клуба «когда игрок в заявке» vs средний win% клуба;
- траектория OVR по сезонам (пик → сейчас).

Потолок overall — 94.
Для OVR 90+ (нап/пз): обычно оставить или срезать; плюс — только если
G+A сезона (на темп ~30 матч.) дотягивает до высокой планки.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from html import escape as html_escape
from typing import Any

from utils import season_paths

OVR_CEILING = 94
_MOTM_MIN_MONTH = 6
# С этого OVR советы в основном «оставить / срезать»; плюс — только сверхвысокая стата.
ELITE_OVR = 90
# Планка «полный сезон»: 64 G+A на ~30 матч.; выше 90 — жёстче.
_ELITE_BASE_GA = 64
_ELITE_FULL_SEASON_MATCHES = 30
# Сколько можно отстать от 64 и всё ещё претендовать на +1 при OVR 90:
_ELITE_PLUS_GAP_FWD = 5   # напы/вингеры: ~59 G+A на 30 матч.
_ELITE_PLUS_GAP_MID = 10  # полузащита: ~54 G+A


def _norm(s: str) -> str:
    return (s or "").strip().casefold()


_GK = frozenset({"ВРТ", "ВР", "GK"})
_DEF = frozenset({"ЦЗ", "ЛЦЗ", "ПЦЗ", "ЛЗ", "ПЗ", "ЛФЗ", "ПФЗ"})
_FWD = frozenset({"ФРВ", "ЛФА", "ПФА", "ЦФД", "ЛФД", "ПФД", "СТ"})


@dataclass
class OvrAdviceRow:
    name: str
    position: str
    status: str
    current: int
    suggested: int
    peak: int
    history: list[tuple[int, int]]  # (season, ovr)
    reasons: list[str] = field(default_factory=list)
    signals: dict[str, float] = field(default_factory=dict)
    # context
    season_matches: int = 0
    season_goals: int = 0
    season_assists: int = 0
    season_cs: int = 0
    career_matches: int = 0
    career_ga: int = 0
    career_cs: int = 0
    injury_periods: int = 0
    injury_months: int = 0
    infl_played: int = 0
    infl_win_pct: float = 0.0
    infl_miss: int = 0
    potm: int = 0
    motm: int = 0

    @property
    def delta(self) -> int:
        return int(self.suggested) - int(self.current)


def _expected_ga_per_match(pos: str, ovr: int) -> float:
    """Грубая норма G+A/матч для позиции при данном OVR."""
    pos_u = (pos or "").upper()
    # база для ~85
    if pos_u in _FWD:
        base = 0.85
    elif pos_u in ("ЦАП", "ПП", "CAM"):
        base = 0.70
    elif pos_u in ("ЦП", "ЦОП", "CM", "CDM"):
        base = 0.35
    elif pos_u in _DEF:
        base = 0.12
    else:
        base = 0.40
    # ±0.04 за пункт OVR от 85
    return max(0.05, base + 0.04 * (int(ovr) - 85))


def _expected_cs_rate(ovr: int) -> float:
    return max(0.15, min(0.55, 0.28 + 0.015 * (int(ovr) - 80)))


def _potm_count(name: str, team: str | None = None) -> int:
    """Все POTM из журнала матчей (+ запасной max с поля potm в БД сезона)."""
    from utils.match_potm_log import _load as load_potm_log

    want_n = _norm(name)
    want_t = _norm(team) if team else ""
    n = 0
    for row in load_potm_log():
        if _norm(str(row.get("player") or "")) != want_n:
            continue
        if want_t and _norm(str(row.get("team") or "")) != want_t:
            continue
        n += 1
    return n


def _motm_count_from_month(
    name: str,
    team: str | None = None,
    *,
    min_month: int = _MOTM_MIN_MONTH,
) -> int:
    """MOTM из awards JSON: только месяцы ≥ min_month (ранние ставили наугад)."""
    from utils.month_motm_award import _load as load_motm

    want_n = _norm(name)
    want_t = _norm(team) if team else ""
    n = 0
    for _sk, months in load_motm().items():
        if not isinstance(months, dict):
            continue
        for mo_s, leagues in months.items():
            try:
                mo = int(mo_s)
            except (TypeError, ValueError):
                continue
            if mo < int(min_month):
                continue
            if not isinstance(leagues, dict):
                continue
            for _lc, aw in leagues.items():
                if not isinstance(aw, dict):
                    continue
                if _norm(str(aw.get("player") or "")) != want_n:
                    continue
                if want_t and _norm(str(aw.get("team") or "")) != want_t:
                    continue
                n += 1
    return n


def _dampen_raise_near_ceiling(cur: int, score: float) -> float:
    """У хайрейтингов сложнее расти; у потолка (94) — нельзя выше."""
    if score <= 0:
        return score
    room = OVR_CEILING - int(cur)
    if room <= 0:
        return 0.0
    if cur <= 86:
        return score
    # 87→94: коэффициент от ~0.95 до ~0.25
    span = max(1, OVR_CEILING - 86)
    factor = max(0.25, min(1.0, 0.2 + 0.8 * (room / span)))
    return score * factor


def _is_elite_attack_pos(pos: str) -> bool:
    pos_u = (pos or "").upper()
    return pos_u in _FWD or pos_u in ("ЛФА", "ПФА", "LW", "RW", "ST", "CF")


def _is_elite_mid_pos(pos: str) -> bool:
    pos_u = (pos or "").upper()
    return pos_u in (
        "ЦАП", "ПП", "ЦП", "ЦОП", "CAM", "CM", "CDM", "LM", "RM", "ЛП", "ППА"
    )


def _elite_season_plus(
    pos: str, cur: int, season_ga: int, season_matches: int
) -> tuple[int, str]:
    """
    Плюс для OVR 90+ (нап/пз): G+A сезона vs планка «полный сезон» (~30 матч.).

    База планки — 64 G+A (рекордный сезон); нап может отстать на 5, пз на 10;
    выше 90 планка растёт. Незакрытый сезон: G+A × (30 / сыгранные).
    Возвращает (0|1|2, короткий текст).
    """
    if cur < ELITE_OVR or season_matches < 10:
        return 0, ""
    if not (_is_elite_attack_pos(pos) or _is_elite_mid_pos(pos)):
        return 0, ""

    ga = max(0, int(season_ga))
    sm = max(1, int(season_matches))
    # незакрытый сезон → темп на ~30 матч.
    ga_full = ga * (_ELITE_FULL_SEASON_MATCHES / sm)

    if _is_elite_attack_pos(pos):
        gap0 = _ELITE_PLUS_GAP_FWD
        role = "нап"
    else:
        gap0 = _ELITE_PLUS_GAP_MID
        role = "пз"

    gap = gap0 - 2 * max(0, int(cur) - ELITE_OVR)
    need_plus1 = _ELITE_BASE_GA - gap
    need_plus2 = _ELITE_BASE_GA + max(0, int(cur) - ELITE_OVR)

    pace = f"{ga} G+A в {sm} матч. → на 30 матч. ≈ {ga_full:.0f}"
    if ga_full >= need_plus2 and cur + 2 <= OVR_CEILING:
        return 2, f"+ сезон топ-уровня ({pace}, планка {role} {cur}: {need_plus2:.0f}) → +2"
    if ga_full >= need_plus1 and cur + 1 <= OVR_CEILING:
        return 1, f"+ сильный сезон ({pace}, планка {role} {cur}: {need_plus1:.0f}) → +1"
    return (
        0,
        f"· для плюса при {cur} ({role}) нужно ≈{need_plus1:.0f} G+A на 30 матч.; "
        f"сейчас {pace} — мало",
    )


def _season_player_totals(name: str) -> dict[str, Any]:
    """
    Стата текущего сезона по игроку во всех клубах (лига+ЛЧ).

    Нужно для зимних трансферов: Берарди Интер → Арсенал — не теряем G+A
    на старом клубе.
    """
    want = _norm(name)
    active = int(season_paths.get_active_season())
    out: dict[str, Any] = {
        "matches": 0,
        "goals": 0,
        "assists": 0,
        "clean_sheets": 0,
        "missed_goals": 0,
        "potm": 0,
        "teams": [],
        "by_team": {},
    }
    by_team: dict[str, dict[str, int]] = {}
    base = os.path.join(season_paths.PROJECT_ROOT, "db", f"season_{active}")
    for dbn in ("league.db", "champions_league.db"):
        path = os.path.join(base, dbn)
        if not os.path.isfile(path):
            continue
        conn = sqlite3.connect(path)
        try:
            for tbl in ("forwards", "midfielders", "defenders", "goalkeepers"):
                try:
                    if tbl == "goalkeepers":
                        cur = conn.execute(
                            "SELECT name, team, COALESCE(matches,0), 0, 0, "
                            "COALESCE(clean_sheets,0), COALESCE(missed_goals,0), "
                            "COALESCE(potm,0) FROM {tbl}".format(tbl=tbl)
                        )
                    elif tbl == "defenders":
                        cur = conn.execute(
                            "SELECT name, team, COALESCE(matches,0), "
                            "COALESCE(goals,0), COALESCE(assists,0), "
                            "COALESCE(clean_sheets,0), 0, COALESCE(potm,0) "
                            f"FROM {tbl}"
                        )
                    else:
                        cur = conn.execute(
                            "SELECT name, team, COALESCE(matches,0), "
                            "COALESCE(goals,0), COALESCE(assists,0), 0, 0, "
                            "COALESCE(potm,0) FROM {tbl}".format(tbl=tbl)
                        )
                except sqlite3.OperationalError:
                    continue
                for nm, tm, m, g, a, cs, mg, potm in cur:
                    if _norm(str(nm or "")) != want:
                        continue
                    team = (tm or "").strip() or "?"
                    slot = by_team.setdefault(
                        team,
                        {
                            "matches": 0,
                            "goals": 0,
                            "assists": 0,
                            "clean_sheets": 0,
                            "missed_goals": 0,
                            "potm": 0,
                        },
                    )
                    slot["matches"] += int(m or 0)
                    slot["goals"] += int(g or 0)
                    slot["assists"] += int(a or 0)
                    slot["clean_sheets"] += int(cs or 0)
                    slot["missed_goals"] += int(mg or 0)
                    slot["potm"] += int(potm or 0)
        finally:
            conn.close()
    for team, slot in by_team.items():
        out["matches"] += slot["matches"]
        out["goals"] += slot["goals"]
        out["assists"] += slot["assists"]
        out["clean_sheets"] += slot["clean_sheets"]
        out["missed_goals"] += slot["missed_goals"]
        out["potm"] += slot["potm"]
    out["by_team"] = by_team
    out["teams"] = sorted(by_team.keys(), key=lambda t: t.casefold())
    return out


def _scan_club_players(team: str) -> list[dict[str, Any]]:
    """Текущий сезон: игроки клуба из league+cl (берём max ovr / sum stats)."""
    want = _norm(team)
    active = int(season_paths.get_active_season())
    by: dict[str, dict[str, Any]] = {}
    base = os.path.join(season_paths.PROJECT_ROOT, "db", f"season_{active}")
    for dbn in ("league.db", "champions_league.db"):
        path = os.path.join(base, dbn)
        if not os.path.isfile(path):
            continue
        conn = sqlite3.connect(path)
        try:
            for tbl in ("forwards", "midfielders", "defenders", "goalkeepers"):
                try:
                    if tbl == "goalkeepers":
                        cur = conn.execute(
                            "SELECT name, team, position, COALESCE(overall,0), "
                            "COALESCE(status,''), COALESCE(matches,0), "
                            "0, 0, COALESCE(clean_sheets,0), COALESCE(missed_goals,0), "
                            "COALESCE(potm,0) "
                            f"FROM {tbl}"
                        )
                    elif tbl == "defenders":
                        cur = conn.execute(
                            "SELECT name, team, position, COALESCE(overall,0), "
                            "COALESCE(status,''), COALESCE(matches,0), "
                            "COALESCE(goals,0), COALESCE(assists,0), "
                            "COALESCE(clean_sheets,0), 0, COALESCE(potm,0) "
                            f"FROM {tbl}"
                        )
                    else:
                        cur = conn.execute(
                            "SELECT name, team, position, COALESCE(overall,0), "
                            "COALESCE(status,''), COALESCE(matches,0), "
                            "COALESCE(goals,0), COALESCE(assists,0), 0, 0, "
                            "COALESCE(potm,0) "
                            f"FROM {tbl}"
                        )
                except sqlite3.OperationalError:
                    continue
                for name, tm, pos, ovr, st, m, g, a, cs, mg, potm in cur:
                    if _norm(str(tm or "")) != want:
                        continue
                    nm = (name or "").strip()
                    if not nm:
                        continue
                    key = nm.casefold()
                    slot = by.setdefault(
                        key,
                        {
                            "name": nm,
                            "position": (pos or "").strip().upper(),
                            "overall": 0,
                            "status": (st or "").strip().lower(),
                            "matches": 0,
                            "goals": 0,
                            "assists": 0,
                            "clean_sheets": 0,
                            "missed_goals": 0,
                            "potm": 0,
                        },
                    )
                    slot["matches"] += int(m or 0)
                    slot["goals"] += int(g or 0)
                    slot["assists"] += int(a or 0)
                    slot["clean_sheets"] += int(cs or 0)
                    slot["missed_goals"] += int(mg or 0)
                    slot["potm"] += int(potm or 0)
                    ovri = int(ovr or 0)
                    if ovri >= int(slot["overall"]):
                        slot["overall"] = ovri
                    if st and (not slot["status"] or st == "start"):
                        slot["status"] = (st or "").strip().lower()
                    if pos and not slot["position"]:
                        slot["position"] = (pos or "").strip().upper()
        finally:
            conn.close()
    return list(by.values())


def _ovr_history(team: str, name: str) -> list[tuple[int, int]]:
    want_t, want_n = _norm(team), _norm(name)
    from utils.cumulative_db import list_season_archives_with_db

    seasons = set(list_season_archives_with_db())
    seasons.add(int(season_paths.get_active_season()))
    hist: list[tuple[int, int]] = []
    for sn in sorted(seasons):
        best = 0
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
                            f"SELECT name, team, COALESCE(overall,0) FROM {tbl}"
                        )
                    except sqlite3.OperationalError:
                        continue
                    for nm, tm, ovr in cur:
                        if _norm(str(nm or "")) != want_n:
                            continue
                        if _norm(str(tm or "")) != want_t:
                            continue
                        best = max(best, int(ovr or 0))
            finally:
                conn.close()
        if best > 0:
            hist.append((int(sn), best))
    return hist


def _career_club_stats(team: str, name: str) -> dict[str, int]:
    want_t, want_n = _norm(team), _norm(name)
    from utils.cumulative_db import list_season_archives_with_db

    seasons = set(list_season_archives_with_db())
    seasons.add(int(season_paths.get_active_season()))
    out = {"matches": 0, "goals": 0, "assists": 0, "clean_sheets": 0, "missed_goals": 0}
    for sn in seasons:
        base = os.path.join(season_paths.PROJECT_ROOT, "db", f"season_{int(sn)}")
        for dbn in ("league.db", "champions_league.db"):
            path = os.path.join(base, dbn)
            if not os.path.isfile(path):
                continue
            conn = sqlite3.connect(path)
            try:
                for tbl in ("forwards", "midfielders", "defenders", "goalkeepers"):
                    try:
                        if tbl == "goalkeepers":
                            cur = conn.execute(
                                "SELECT name, team, COALESCE(matches,0), 0, 0, "
                                "COALESCE(clean_sheets,0), COALESCE(missed_goals,0) "
                                f"FROM {tbl}"
                            )
                        elif tbl == "defenders":
                            cur = conn.execute(
                                "SELECT name, team, COALESCE(matches,0), "
                                "COALESCE(goals,0), COALESCE(assists,0), "
                                "COALESCE(clean_sheets,0), 0 FROM {tbl}".format(tbl=tbl)
                            )
                        else:
                            cur = conn.execute(
                                "SELECT name, team, COALESCE(matches,0), "
                                "COALESCE(goals,0), COALESCE(assists,0), 0, 0 "
                                f"FROM {tbl}"
                            )
                    except sqlite3.OperationalError:
                        continue
                    for nm, tm, m, g, a, cs, mg in cur:
                        if _norm(str(nm or "")) != want_n:
                            continue
                        if _norm(str(tm or "")) != want_t:
                            continue
                        out["matches"] += int(m or 0)
                        out["goals"] += int(g or 0)
                        out["assists"] += int(a or 0)
                        out["clean_sheets"] += int(cs or 0)
                        out["missed_goals"] += int(mg or 0)
            finally:
                conn.close()
    return out


def _injury_burden(name: str, team: str | None = None) -> tuple[int, int]:
    from utils.player_discipline import _load, _injury_total_months, _norm as dnorm

    want = dnorm(name)
    want_t = dnorm(team) if team else ""
    n = months = 0
    for inj in (_load().get("injuries") or []):
        if dnorm(str(inj.get("name") or "")) != want:
            continue
        if want_t and dnorm(str(inj.get("team") or "")) not in ("", want_t):
            # считаем все травмы игрока, даже в другом клубе — влияют на OVR
            pass
        n += 1
        months += _injury_total_months(inj)
    return n, months


def _club_fixture_months_this_season(team: str) -> list[int]:
    """Месяцы календарных матчей клуба в активном сезоне (для доступности основы)."""
    from bot.team_history import iter_all_match_records
    from utils.player_discipline import get_calendar_month

    active = int(season_paths.get_active_season())
    want = _norm(team)
    months: list[int] = []
    for m in iter_all_match_records():
        if int(m.get("_season") or 0) != active:
            continue
        if _norm(m.get("home") or "") != want and _norm(m.get("away") or "") != want:
            continue
        day = m.get("day")
        months.append(get_calendar_month(int(day) if day is not None else None))
    return months


def _starter_available_matches(name: str, team: str, fixture_months: list[int]) -> int:
    """Матчи клуба сезона, в которых основа не был в травме."""
    from utils.player_discipline import _injury_blocks_at_month, _load, _norm as dnorm

    if not fixture_months:
        return 0
    active = int(season_paths.get_active_season())
    want = dnorm(name)
    inj_list = [
        inj
        for inj in (_load().get("injuries") or [])
        if dnorm(str(inj.get("name") or "")) == want
    ]
    avail = 0
    for month in fixture_months:
        blocked = any(
            _injury_blocks_at_month(inj, month, current_season=active)
            for inj in inj_list
        )
        if not blocked:
            avail += 1
    return avail


def clamp_ovr_delta_for_team(team: str, current: int, delta: int) -> int:
    """
    Ограничение Δ по лиге и глобальному потолку ``OVR_CEILING`` (94).
    РПЛ: максимум +3; пол 75 (при 75 нельзя вниз, при 76 макс −1, …, при 78+ макс −3).
    Остальные лиги: ±3.
    """
    d = int(delta)
    cur = int(current)
    try:
        from player_stats import national_league_code_for_team

        lc = (national_league_code_for_team(team) or "").lower()
    except Exception:
        lc = ""
    if lc == "rpl":
        lo = max(-3, 75 - cur)
        hi = 3
        d = max(lo, min(hi, d))
    else:
        d = max(-3, min(3, d))
    if d > 0 and cur + d > OVR_CEILING:
        d = max(0, OVR_CEILING - cur)
    return d


def list_club_roster_for_ovr_debug(team: str) -> tuple[str, list[dict[str, Any]]]:
    """
    Все игроки клуба для кнопок DEBUG OVR.
    Возвращает (display_team, roster) — roster: name/position/overall/status, по OVR↓.
    """
    display = (team or "").strip()
    players = _scan_club_players(display)
    if not players:
        players = _scan_club_players(display.title())
        display = display.title()
    players.sort(
        key=lambda p: (
            0 if str(p.get("status") or "") == "start" else (
                1 if str(p.get("status") or "") == "bench" else 2
            ),
            -int(p.get("overall") or 0),
            str(p.get("name") or "").casefold(),
        )
    )
    return display, players


def advise_club_ovr(
    team: str,
    *,
    min_overall: int = 78,
    starters_first: bool = True,
    limit: int = 20,
    only_name: str | None = None,
) -> list[OvrAdviceRow]:
    """DEBUG-советы по OVR для клуба (без записи в БД)."""
    from bot.team_history import club_player_win_influence, iter_all_match_records, match_result_for_team

    display = (team or "").strip()
    # нормализуем МЮ → Мю
    players = _scan_club_players(display)
    if not players:
        # попробовать Title
        players = _scan_club_players(display.title())
        display = display.title()

    want_name = _norm(only_name) if only_name else ""
    if want_name:
        players = [p for p in players if _norm(str(p.get("name") or "")) == want_name]

    # средний win% клуба
    tw = td = tl = 0
    for m in iter_all_match_records():
        if _norm(m.get("home") or "") != _norm(display) and _norm(
            m.get("away") or ""
        ) != _norm(display):
            continue
        res, *_ = match_result_for_team(m, display)
        if res == "W":
            tw += 1
        elif res == "D":
            td += 1
        else:
            tl += 1
    club_n = tw + td + tl
    club_wr = (tw / club_n) if club_n else 0.5

    fixture_months = _club_fixture_months_this_season(display)
    club_season_fixtures = len(fixture_months)

    infl_map = {
        r.player.casefold(): r
        for r in club_player_win_influence(
            display, min_played=1, limit=80, starters_only=False
        )
    }

    rows: list[OvrAdviceRow] = []
    for p in players:
        cur = int(p.get("overall") or 0)
        if not want_name and cur < int(min_overall):
            continue
        name = str(p["name"])
        pos = str(p.get("position") or "")
        status = str(p.get("status") or "")
        hist = _ovr_history(display, name)
        peak = max((o for _, o in hist), default=cur)
        career = _career_club_stats(display, name)
        inj_n, inj_m = _injury_burden(name, display)
        infl = infl_map.get(name.casefold())

        sm_db = int(p.get("matches") or 0)
        sg = int(p.get("goals") or 0)
        sa = int(p.get("assists") or 0)
        scs = int(p.get("clean_sheets") or 0)
        season_all = _season_player_totals(name)
        other_teams = [
            t for t in (season_all.get("teams") or []) if _norm(t) != _norm(display)
        ]
        multi_club = bool(other_teams)
        if multi_club:
            # зимний трансфер и т.п.: G+A/матчи за весь сезон по всем клубам
            sg = int(season_all.get("goals") or 0)
            sa = int(season_all.get("assists") or 0)
            scs = int(season_all.get("clean_sheets") or 0)
            sm_db = int(season_all.get("matches") or 0)
            clubs_lab = " + ".join(season_all.get("teams") or [])
            sm = max(1, sm_db)
            matches_note = (
                f"сезон все клубы ({clubs_lab}): {sm} матч. в БД"
            )
        elif status == "start" and club_season_fixtures > 0:
            # основа: знаменатель = матчи клуба минус травмы (не «дыры» в matches БД)
            sm = _starter_available_matches(name, display, fixture_months)
            sm = max(sm, 1)
            matches_note = f"основа: {sm} из {club_season_fixtures} матч. клуба"
            if sm_db and sm_db != sm:
                matches_note += f" (в БД matches={sm_db})"
        else:
            sm = sm_db
            matches_note = f"по БД matches={sm}"
        reasons: list[str] = []
        score = 0.0  # вклад в Δ до округления
        signals: dict[str, float] = {}
        signals["matches_db"] = float(sm_db)
        signals["matches_eff"] = float(sm)
        if multi_club:
            signals["multi_club"] = 1.0
            reasons.append(
                f"· стата сезона склеена по клубам: "
                + ", ".join(
                    f"{t} {int((season_all['by_team'][t]).get('goals') or 0)}+"
                    f"{int((season_all['by_team'][t]).get('assists') or 0)}"
                    f"/{int((season_all['by_team'][t]).get('matches') or 0)}"
                    for t in (season_all.get("teams") or [])
                )
            )

        # 1) форма текущего сезона
        form = 0.0
        elite = cur >= ELITE_OVR
        season_plus = 0
        if sm >= 3:
            if pos in _GK:
                rate = scs / sm
                exp = _expected_cs_rate(cur)
                form = (rate - exp) / max(0.15, exp)
                signals["form_cs"] = round(rate, 3)
            else:
                ga = sg + sa
                rate = ga / sm
                exp = _expected_ga_per_match(pos, cur)
                form = (rate - exp) / max(0.15, exp)
                signals["form_ga"] = round(rate, 3)

            if elite:
                if form < -0.35:
                    pen = min(2.2, 1.1 + abs(form) * 0.9)
                    score -= pen
                    if pos in _GK:
                        reasons.append(
                            f"− OVR {cur}+ не подтверждён сухими {scs}/{sm} "
                            f"({rate:.0%} vs ~{exp:.0%}; {matches_note}; { -pen:+.1f})"
                        )
                    else:
                        reasons.append(
                            f"− OVR {cur}+ завышен: {sg}+{sa} / {sm} "
                            f"(= {rate:.2f}, норма ~{exp:.2f} для {pos} {cur}; "
                            f"{matches_note}; {-pen:+.1f})"
                        )
                elif form < -0.12:
                    score -= 1.0
                    if pos in _GK:
                        reasons.append(
                            f"− OVR {cur}+ ниже нормы по сухим ({matches_note})"
                        )
                    else:
                        reasons.append(
                            f"− OVR {cur}+ ниже нормы: {sg}+{sa} / {sm} "
                            f"(= {rate:.2f} < ~{exp:.2f}; {matches_note})"
                        )
                else:
                    # на уровне / выше нормы по rate — плюс только от планки «полный сезон»
                    if pos not in _GK:
                        sm_mz = int(sm_db) if int(sm_db) >= 10 else int(sm)
                        season_plus, mz_why = _elite_season_plus(
                            pos, cur, int(sg) + int(sa), sm_mz
                        )
                        signals["elite_ga_proj"] = round(
                            (sg + sa)
                            * (_ELITE_FULL_SEASON_MATCHES / max(sm_mz, 1)),
                            1,
                        )
                        signals["elite_season_plus"] = float(season_plus)
                        if mz_why:
                            if season_plus > 0:
                                score += 0.95 * season_plus
                            reasons.append(mz_why)
                    elif season_plus <= 0:
                        reasons.append(
                            f"· OVR {cur}+ на уровне по сухим — без плюса ({matches_note})"
                        )
            elif pos in _GK:
                if form > 0.25:
                    bump = min(2.0, 0.6 + form * 1.1)
                    bump *= min(1.0, sm / 10.0)
                    score += bump
                    reasons.append(
                        f"+ сухие сейчас {scs}/{sm} ({rate:.0%}) выше нормы ~{exp:.0%} "
                        f"для OVR {cur} ({matches_note}; вклад {bump:+.1f})"
                    )
                elif form < -0.25:
                    score -= min(1.4, 0.5 + abs(form) * 0.9)
                    reasons.append(
                        f"− сухие сейчас {scs}/{sm} ({rate:.0%}) ниже нормы ~{exp:.0%} "
                        f"для OVR {cur} ({matches_note})"
                    )
                else:
                    reasons.append(
                        f"· сухие {scs}/{sm} около нормы для OVR {cur} ({matches_note})"
                    )
            else:
                if form > 0.35:
                    bump = min(2.4, 0.55 + form * 1.05)
                    if sm >= 10:
                        bump += 0.25
                    bump *= min(1.0, sm / 10.0)
                    score += bump
                    reasons.append(
                        f"+ форма сезона {sg}+{sa} в {sm} матч. "
                        f"({rate:.2f} G+A/м vs ожид. ~{exp:.2f} для {pos} {cur}; "
                        f"{matches_note}; вклад {bump:+.1f})"
                    )
                elif form > 0.10:
                    bump = 0.5 * min(1.0, sm / 10.0)
                    score += bump
                    reasons.append(
                        f"+ чуть выше нормы: {sg}+{sa} / {sm} (= {rate:.2f}, "
                        f"ожид. ~{exp:.2f}; {matches_note})"
                    )
                elif form < -0.35:
                    score -= 1.0
                    reasons.append(
                        f"− слабая форма: {sg}+{sa} / {sm} (= {rate:.2f}, "
                        f"ожид. ~{exp:.2f}; {matches_note})"
                    )
                elif form < -0.10:
                    score -= 0.4
                    reasons.append(
                        f"− чуть ниже нормы: {sg}+{sa} / {sm} (= {rate:.2f}; {matches_note})"
                    )
                else:
                    reasons.append(
                        f"· форма ок: {sg}+{sa} в {sm} матч. "
                        f"(= {rate:.2f} ≈ {exp:.2f}; {matches_note})"
                    )
        else:
            reasons.append(
                f"· мало матчей в текущем сезоне ({sm}; {matches_note}) — форма почти не влияет"
            )

        # 1b) POTM (все) + MOTM (с 6-го месяца)
        potm_db = int(p.get("potm") or 0)
        if multi_club:
            potm_db = max(potm_db, int(season_all.get("potm") or 0))
        # лог: по всем клубам, если сезон с трансфером
        potm_log = _potm_count(name, None if multi_club else display)
        potm_n = max(potm_db, potm_log)
        motm_n = _motm_count_from_month(
            name, None if multi_club else display, min_month=_MOTM_MIN_MONTH
        )
        signals["potm"] = float(potm_n)
        signals["motm"] = float(motm_n)
        # 90+: награды только чуть смягчают минус, никогда не поднимают
        award_scale = 1.0
        if elite:
            award_scale = 0.2 if form < -0.12 else 0.0
        elif form < -0.10:
            award_scale = 0.35
        if potm_n > 0:
            potm_bump = min(2.2, 0.45 + potm_n * 0.32) * award_scale
            if potm_bump > 0.05:
                score += potm_bump
                reasons.append(f"+ POTM ×{potm_n} (вклад {potm_bump:+.1f})")
            elif elite:
                reasons.append(f"· POTM ×{potm_n}")
            else:
                reasons.append(f"· POTM ×{potm_n}")
        else:
            reasons.append("· POTM нет")
        if motm_n > 0:
            motm_bump = min(1.6, motm_n * 0.75) * award_scale
            if motm_bump > 0.05:
                score += motm_bump
                reasons.append(
                    f"+ MOTM ×{motm_n} (с {_MOTM_MIN_MONTH}-го мес.; "
                    f"вклад {motm_bump:+.1f})"
                )
            elif elite:
                reasons.append(f"· MOTM ×{motm_n} (с {_MOTM_MIN_MONTH}-го мес.)")
            else:
                reasons.append(f"· MOTM ×{motm_n} (с {_MOTM_MIN_MONTH}-го мес.)")
        else:
            reasons.append(f"· MOTM с {_MOTM_MIN_MONTH}-го мес. нет")

        # скамейка + элитная форма — только ниже 90
        if not elite and status == "bench" and form > 0.5 and sm >= 8:
            score += 0.35
            reasons.append("+ элитная форма со скамейки")

        # 2) карьера в клубе
        cm = int(career.get("matches") or 0)
        if cm >= 10 and pos not in _GK:
            cga = int(career["goals"]) + int(career["assists"])
            crate = cga / cm
            exp_c = _expected_ga_per_match(pos, cur)
            if crate > exp_c * 1.25:
                if elite:
                    reasons.append(
                        f"· карьера сильная ({cga} G+A / {cm}) — у {cur}+ без плюса"
                    )
                else:
                    score += 0.6
                    reasons.append(
                        f"+ карьера в клубе сильная: {cga} G+A / {cm} (= {crate:.2f})"
                    )
            elif crate < exp_c * 0.7:
                score -= 0.5
                reasons.append(
                    f"− карьера скромнее нормы: {cga} G+A / {cm} (= {crate:.2f})"
                )
            signals["career_ga_rate"] = round(crate, 3)
        elif cm >= 10 and pos in _GK:
            crate = int(career["clean_sheets"]) / cm
            exp_c = _expected_cs_rate(cur)
            if crate > exp_c * 1.15:
                if elite:
                    reasons.append(f"· карьера сухих сильная — у {cur}+ без плюса")
                else:
                    score += 0.5
                    reasons.append(f"+ карьера сухих {career['clean_sheets']}/{cm}")
            elif crate < exp_c * 0.75:
                score -= 0.5
                reasons.append(f"− карьера сухих слабая {career['clean_sheets']}/{cm}")

        # 3) травмы
        signals["injury_months"] = float(inj_m)
        if inj_m >= 8:
            score -= 1.2
            reasons.append(f"− много травм: {inj_n} период(ов), {inj_m} мес. суммарно")
        elif inj_m >= 4:
            score -= 0.7
            reasons.append(f"− травмы: {inj_n}×, {inj_m} мес. (давление на OVR)")
        elif inj_m >= 1:
            score -= 0.25
            reasons.append(f"· были травмы: {inj_n}× / {inj_m} мес.")
        else:
            reasons.append("· травм в JSON нет")

        # 4) результаты клуба при нём
        if infl and infl.played >= 20:
            wr = infl.win_pct / 100.0
            signals["infl_wr"] = round(wr, 3)
            diff = wr - club_wr
            if diff > 0.08:
                if elite:
                    reasons.append(
                        f"· win% выше клуба ({infl.win_pct:.0f}%) — у {cur}+ без плюса"
                    )
                else:
                    score += 0.7
                    reasons.append(
                        f"+ при нём клуб чаще побеждает: {infl.win_pct:.0f}% "
                        f"(клуб в среднем {club_wr*100:.0f}%), n={infl.played}"
                    )
            elif diff < -0.08:
                score -= 0.7
                reasons.append(
                    f"− при нём win% ниже клуба: {infl.win_pct:.0f}% "
                    f"vs {club_wr*100:.0f}% (n={infl.played}, травма-проп. {infl.missed_injury})"
                )
            else:
                reasons.append(
                    f"· win% при нём ≈ клуб: {infl.win_pct:.0f}% (n={infl.played})"
                )
            if infl.missed_injury >= 12:
                score -= 0.4
                reasons.append(
                    f"− много матчей клуба без него из‑за травм ({infl.missed_injury})"
                )

        # 5) траектория
        if peak >= cur + 3:
            if elite:
                reasons.append(f"· история OVR: пик {peak}, сейчас {cur}")
            elif score > 0.4:
                score += 0.4
                reasons.append(
                    f"· был пик {peak}, сейчас {cur}: при хорошей форме возможен +1 отскок"
                )
            else:
                score -= 0.3
                reasons.append(
                    f"− OVR уже просел с пика {peak}→{cur}; без формы вверх не тянем"
                )
        elif peak > cur:
            reasons.append(f"· история OVR: пик {peak}, сейчас {cur}")
        if hist:
            chain = " → ".join(str(o) for _, o in hist)
            reasons.append(f"· по сезонам: {chain}")

        # 90+: плюс только от планки полного сезона; остальные плюсы обнуляем
        if elite and score > 0 and season_plus <= 0:
            score = 0.0

        # хайрейтинг ниже 90: положительный score слабее у потолка 94
        score_before_ceil = score
        if not elite:
            score = _dampen_raise_near_ceiling(cur, score)
            if score < score_before_ceil - 0.05:
                reasons.insert(
                    0,
                    f"· у OVR {cur} рост к потолку {OVR_CEILING} ослаблен "
                    f"({score_before_ceil:.1f} → {score:.1f})",
                )

        # итог
        raw_delta = max(-3.0, min(3.0, score))
        # пороги: не дёргать на 0.3
        if raw_delta >= 0.85:
            delta = 1 if raw_delta < 1.7 else (2 if raw_delta < 2.5 else 3)
        elif raw_delta <= -0.85:
            delta = -1 if raw_delta > -1.7 else (-2 if raw_delta > -2.5 else -3)
        else:
            delta = 0
            if elite and form >= -0.12 and sm >= 3 and season_plus <= 0:
                reasons.insert(0, f"· {cur}+ играет на свой уровень → оставляем")
            elif abs(raw_delta) < 0.85 and not any(
                r.startswith(("+", "−")) for r in reasons if r
            ):
                reasons.insert(0, "· сигналов мало / они слабые → оставляем OVR")
            elif delta == 0 and not any(
                "оставляем" in r or "мало" in r for r in reasons[:2]
            ):
                reasons.insert(0, "· плюсы и минусы уравновешены → оставляем OVR")

        delta_raw = int(delta)
        delta = clamp_ovr_delta_for_team(display, cur, delta_raw)
        if delta != delta_raw:
            reasons.insert(
                0,
                f"· лимит: Δ {delta_raw:+d} → {delta:+d} "
                f"(лига / потолок {OVR_CEILING})",
            )

        suggested = max(60, min(OVR_CEILING, cur + delta))
        try:
            from player_stats import national_league_code_for_team

            if (national_league_code_for_team(display) or "").lower() == "rpl":
                suggested = max(75, suggested)
        except Exception:
            pass
        delta = int(suggested) - int(cur)
        signals["score_raw"] = round(score, 2)
        signals["delta"] = float(delta)

        rows.append(
            OvrAdviceRow(
                name=name,
                position=pos,
                status=str(p.get("status") or ""),
                current=cur,
                suggested=suggested,
                peak=peak,
                history=hist,
                reasons=reasons,
                signals=signals,
                season_matches=sm,
                season_goals=sg,
                season_assists=sa,
                season_cs=scs,
                career_matches=cm,
                career_ga=int(career["goals"]) + int(career["assists"]),
                career_cs=int(career["clean_sheets"]),
                injury_periods=inj_n,
                injury_months=inj_m,
                infl_played=int(infl.played) if infl else 0,
                infl_win_pct=float(infl.win_pct) if infl else 0.0,
                infl_miss=int(infl.missed_injury) if infl else 0,
                potm=potm_n,
                motm=motm_n,
            )
        )

    def sort_key(r: OvrAdviceRow) -> tuple:
        st_rank = 0 if r.status == "start" else (1 if r.status == "bench" else 2)
        if not starters_first:
            st_rank = 0
        return (st_rank, -abs(r.delta), -r.current, r.name.casefold())

    rows.sort(key=sort_key)
    if want_name:
        return rows
    return rows[: max(1, int(limit))]


def advise_player_ovr(team: str, name: str) -> OvrAdviceRow | None:
    """DEBUG-совет по одному игроку."""
    rows = advise_club_ovr(team, min_overall=0, limit=1, only_name=name)
    return rows[0] if rows else None


def format_ovr_advice_player_html(team: str, row: OvrAdviceRow) -> str:
    """Короткий HTML-отчёт по одному игроку (для Telegram)."""
    if row.delta > 0:
        tag = f"ПОДНЯТЬ +{row.delta}"
    elif row.delta < 0:
        tag = f"СНИЗИТЬ {row.delta}"
    else:
        tag = "ОСТАВИТЬ"
    lines = [
        f"🔬 <b>DEBUG OVR</b> · {html_escape(team)}",
        "<i>Только просмотр — в БД не пишем.</i>",
        "",
        f"<b>{html_escape(row.name)}</b> · {html_escape(row.position or '—')} · "
        f"{html_escape(row.status or '—')}",
        f"Сейчас <b>{row.current}</b> → <b>{row.suggested}</b>  [{tag}]",
        "",
        f"Сезон: {row.season_matches} матч, {row.season_goals}+{row.season_assists}"
        + (f", CS {row.season_cs}" if row.position in _GK else ""),
        f"Награды: POTM {row.potm} · MOTM (с {_MOTM_MIN_MONTH}м) {row.motm}",
        f"Карьера в клубе: {row.career_matches} матч, G+A {row.career_ga}"
        + (f", CS {row.career_cs}" if row.position in _GK or row.career_cs else ""),
        f"Травмы: {row.injury_periods}× / {row.injury_months} мес",
        f"Влияние: n={row.infl_played}, win {row.infl_win_pct:.0f}%, "
        f"проп.травм {row.infl_miss}",
    ]
    if row.history:
        chain = " → ".join(str(o) for _, o in row.history)
        lines.append(f"OVR по сезонам: {html_escape(chain)} (пик {row.peak})")
    lines.append("")
    lines.append("<b>Почему:</b>")
    for reason in row.reasons:
        lines.append(html_escape(reason))
    return "\n".join(lines)


def format_ovr_advice_report(team: str, rows: list[OvrAdviceRow] | None = None) -> str:
    rows = rows if rows is not None else advise_club_ovr(team)
    chunks = [
        f"── DEBUG OVR · {team} ──",
        "Только тест: в БД ничего не пишем. Δ зажата ±3.",
        "Сигналы: форма сезона · карьера · травмы · win% при игроке · траектория OVR.",
        "",
    ]
    if not rows:
        chunks.append("Нет игроков для разбора.")
        return "\n".join(chunks)

    for r in rows:
        arrow = f"{r.current} → {r.suggested}"
        if r.delta > 0:
            tag = f"ПОДНЯТЬ +{r.delta}"
        elif r.delta < 0:
            tag = f"СНИЗИТЬ {r.delta}"
        else:
            tag = "ОСТАВИТЬ"
        st = r.status or "—"
        chunks.append(
            f"■ {r.name} · {r.position} · {st} · сейчас {r.current}  [{tag}]  {arrow}"
        )
        chunks.append(
            f"  сезон: {r.season_matches} матч, {r.season_goals}+{r.season_assists}"
            + (f", CS {r.season_cs}" if r.position in _GK else "")
            + f" · карьера: {r.career_matches} матч, G+A {r.career_ga}"
            + (f", CS {r.career_cs}" if r.position in _GK or r.career_cs else "")
        )
        chunks.append(
            f"  травмы: {r.injury_periods}× / {r.injury_months} мес · "
            f"влияние: n={r.infl_played}, win {r.infl_win_pct:.0f}%, проп.травм {r.infl_miss}"
        )
        for reason in r.reasons:
            chunks.append(f"  {reason}")
        chunks.append("")
    return "\n".join(chunks).rstrip() + "\n"


def format_ovr_advice_summary_all_clubs(
    *,
    limit_per_club: int = 14,
    changes_only: bool = True,
) -> str:
    """Краткий обзор DEBUG OVR по всем клубам пула (только просмотр)."""
    from utils.transfer_advice import all_league_teams

    chunks = [
        "── DEBUG OVR · все клубы ──",
        "Только тест: в БД ничего не пишем. Ниже игроки с предлагаемым Δ≠0."
        if changes_only
        else "Только тест: в БД ничего не пишем.",
        "",
    ]
    n_clubs = 0
    n_chg = 0
    for team in all_league_teams():
        try:
            rows = advise_club_ovr(team, limit=limit_per_club)
        except Exception as e:
            chunks.append(f"── {team} ── ошибка: {e}")
            chunks.append("")
            continue
        show = [r for r in rows if (not changes_only) or r.delta != 0]
        if not show:
            continue
        n_clubs += 1
        chunks.append(f"── {team} ──")
        for r in show:
            n_chg += 1
            if r.delta > 0:
                tag = f"+{r.delta}"
            elif r.delta < 0:
                tag = str(r.delta)
            else:
                tag = "="
            chunks.append(
                f"  {r.name} · {r.position} · {r.status or '—'} · "
                f"{r.current}→{r.suggested} [{tag}]"
            )
        chunks.append("")
    chunks.append(f"Итого: клубов с правками {n_clubs}, строк {n_chg}.")
    return "\n".join(chunks).rstrip() + "\n"
