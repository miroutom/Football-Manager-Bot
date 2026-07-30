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
Модель: по темпу сезона оцениваем «играет на N», совет — подвинуть
текущий OVR к N (регрессия при малой выборке, ±3, потолок; у 90+ вверх
только от планки полного сезона).
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
# С этого OVR вверх только от планки полного сезона; вниз — по «играет на N».
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
    # «играет на» — оценка уровня по темпу (до лимитов Δ)
    plays_at: float | None = None
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


# Наклон: сколько G+A/м ≈ +1 OVR (FIFA; чуть положе, чтобы инверсия «темп→OVR» была здравой)
_GA_PER_OVR = 0.06


def _ga_base_for_pos(pos: str) -> float:
    """База G+A/матч при OVR 85."""
    pos_u = (pos or "").upper()
    if pos_u in _FWD:
        return 1.15
    if pos_u in ("ЦАП", "ПП", "CAM", "ЛП", "ППА", "LM", "RM"):
        return 1.00
    if pos_u in ("ЦП", "ЦОП", "CM", "CDM"):
        return 0.55
    if pos_u in _DEF:
        return 0.20
    return 0.60


def _expected_ga_per_match(pos: str, ovr: int) -> float:
    """
    Норма G+A/матч для позиции при данном OVR (FIFA-темп).

    База для ~85; +``_GA_PER_OVR`` за пункт OVR. Ориентир: у атакующих
    «около действия за матч» — норма, не сверхрезультат.
    """
    return max(0.08, _ga_base_for_pos(pos) + _GA_PER_OVR * (int(ovr) - 85))


def _implied_ovr_from_ga_rate(pos: str, rate: float) -> float:
    """Инверсия нормы: какой OVR соответствует темпу G+A/матч."""
    base = _ga_base_for_pos(pos)
    raw = 85.0 + (float(rate) - base) / _GA_PER_OVR
    return max(60.0, min(float(OVR_CEILING + 3), raw))


def _expected_cs_rate(ovr: int) -> float:
    return max(0.15, min(0.55, 0.28 + 0.015 * (int(ovr) - 80)))


def _implied_ovr_from_cs_rate(rate: float) -> float:
    """Инверсия нормы сухих → OVR."""
    raw = 80.0 + (float(rate) - 0.28) / 0.015
    return max(60.0, min(float(OVR_CEILING + 3), raw))


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
        return 2, f"· планка роста +2 ({pace}, нужно ≥{need_plus2:.0f} для {role} {cur})"
    if ga_full >= need_plus1 and cur + 1 <= OVR_CEILING:
        return 1, f"· планка роста +1 ({pace}, нужно ≥{need_plus1:.0f} для {role} {cur})"
    return (
        0,
        f"· для роста с {cur} ({role}) нужно ≈{need_plus1:.0f} G+A на 30 матч.; "
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

        elite = cur >= ELITE_OVR
        season_plus = 0
        plays_at = float(cur)
        rate = 0.0
        form = 0.0  # (rate-exp)/exp — только для мягких порогов наград

        # 1) Темп сезона → «играет на N»
        if sm >= 3:
            if pos in _GK:
                rate = scs / sm
                raw_imp = _implied_ovr_from_cs_rate(rate)
                exp_cur = _expected_cs_rate(cur)
                form = (rate - exp_cur) / max(0.15, exp_cur)
                signals["form_cs"] = round(rate, 3)
                reasons.append(
                    f"· сухие {scs}/{sm} ({rate:.0%}) → сырой уровень ~{raw_imp:.0f} "
                    f"(норма для {cur}: ~{exp_cur:.0%}; {matches_note})"
                )
            else:
                ga = sg + sa
                rate = ga / sm
                raw_imp = _implied_ovr_from_ga_rate(pos, rate)
                exp_cur = _expected_ga_per_match(pos, cur)
                form = (rate - exp_cur) / max(0.15, exp_cur)
                signals["form_ga"] = round(rate, 3)
                reasons.append(
                    f"· {sg}+{sa} в {sm} матч. (= {rate:.2f} G+A/м) → "
                    f"сырой уровень ~{raw_imp:.0f} "
                    f"(норма для {pos} {cur}: ~{exp_cur:.2f}; {matches_note})"
                )
            # регрессия к текущему при малой выборке (полная уверенность с ~12 матч.)
            conf = min(1.0, sm / 12.0)
            plays_at = conf * raw_imp + (1.0 - conf) * float(cur)
            signals["implied_raw"] = round(raw_imp, 2)
            signals["form_conf"] = round(conf, 2)
            if conf < 0.99:
                reasons.append(
                    f"· вес сезона {conf:.0%} (мало матчей) → тянем к текущему {cur} "
                    f"→ ~{plays_at:.0f}"
                )
        else:
            reasons.append(
                f"· мало матчей в текущем сезоне ({sm}; {matches_note}) — "
                f"ориентир ≈ текущий {cur}"
            )

        # 1b) POTM / MOTM — лёгкий сдвиг «играет на»
        potm_db = int(p.get("potm") or 0)
        if multi_club:
            potm_db = max(potm_db, int(season_all.get("potm") or 0))
        potm_log = _potm_count(name, None if multi_club else display)
        potm_n = max(potm_db, potm_log)
        motm_n = _motm_count_from_month(
            name, None if multi_club else display, min_month=_MOTM_MIN_MONTH
        )
        signals["potm"] = float(potm_n)
        signals["motm"] = float(motm_n)
        award_shift = 0.0
        if not elite or form < -0.12:
            # у 90+ награды не поднимают «уровень», только чуть смягчают просадку
            if potm_n > 0:
                award_shift += min(1.2, 0.25 + potm_n * 0.18)
            if motm_n > 0:
                award_shift += min(0.8, motm_n * 0.35)
            if elite:
                award_shift *= 0.35
        if award_shift > 0.05:
            plays_at += award_shift
            reasons.append(
                f"· награды: POTM ×{potm_n}, MOTM ×{motm_n} "
                f"(с {_MOTM_MIN_MONTH}м) → уровень {award_shift:+.1f}"
            )
        else:
            reasons.append(
                f"· POTM ×{potm_n} · MOTM ×{motm_n} (с {_MOTM_MIN_MONTH}м)"
                + (" — у 90+ не поднимают уровень" if elite and (potm_n or motm_n) else "")
            )

        if not elite and status == "bench" and sm >= 8 and plays_at >= cur + 1.5:
            plays_at += 0.3
            reasons.append("· сильный темп со скамейки → чуть выше")

        # 2) карьера в клубе — мягкий якорь
        cm = int(career.get("matches") or 0)
        if cm >= 15:
            if pos not in _GK:
                cga = int(career["goals"]) + int(career["assists"])
                crate = cga / cm
                career_imp = _implied_ovr_from_ga_rate(pos, crate)
                signals["career_ga_rate"] = round(crate, 3)
            else:
                crate = int(career["clean_sheets"]) / cm
                career_imp = _implied_ovr_from_cs_rate(crate)
            # 20% якорь к карьерному уровню
            before = plays_at
            plays_at = 0.8 * plays_at + 0.2 * career_imp
            reasons.append(
                f"· карьера в клубе ({cm} матч.) ≈ уровень {career_imp:.0f} "
                f"→ подмешиваем ({before:.0f} → {plays_at:.0f})"
            )

        # 3) травмы
        signals["injury_months"] = float(inj_m)
        if inj_m >= 8:
            plays_at -= 1.2
            reasons.append(f"· много травм: {inj_n}× / {inj_m} мес. → уровень −1.2")
        elif inj_m >= 4:
            plays_at -= 0.7
            reasons.append(f"· травмы: {inj_n}× / {inj_m} мес. → уровень −0.7")
        elif inj_m >= 1:
            plays_at -= 0.25
            reasons.append(f"· были травмы: {inj_n}× / {inj_m} мес.")
        else:
            reasons.append("· травм в JSON нет")

        # 4) win% при нём
        if infl and infl.played >= 20:
            wr = infl.win_pct / 100.0
            signals["infl_wr"] = round(wr, 3)
            diff = wr - club_wr
            if diff > 0.08 and not elite:
                plays_at += 0.5
                reasons.append(
                    f"· при нём win% выше клуба: {infl.win_pct:.0f}% "
                    f"vs {club_wr*100:.0f}% (n={infl.played}) → +0.5"
                )
            elif diff < -0.08:
                plays_at -= 0.5
                reasons.append(
                    f"· при нём win% ниже клуба: {infl.win_pct:.0f}% "
                    f"vs {club_wr*100:.0f}% (n={infl.played}) → −0.5"
                )
            else:
                reasons.append(
                    f"· win% при нём ≈ клуб: {infl.win_pct:.0f}% (n={infl.played})"
                )
            if infl.missed_injury >= 12:
                plays_at -= 0.4
                reasons.append(
                    f"· много матчей клуба без него из‑за травм ({infl.missed_injury})"
                )

        # 5) траектория (информация + лёгкий якорь к пику ниже 90)
        if hist:
            chain = " → ".join(str(o) for _, o in hist)
            reasons.append(f"· по сезонам: {chain}")
        if peak > cur:
            reasons.append(f"· история OVR: пик {peak}, сейчас {cur}")
            if not elite and peak >= cur + 3 and plays_at > cur:
                plays_at += 0.3
                reasons.append("· был заметный пик — при хорошем темпе чуть легче отскок")

        # оценка «играет на» до лимитов роста 90+
        plays_at_shown = plays_at
        signals["plays_at"] = round(plays_at_shown, 2)
        target_level = plays_at

        # 90+: вверх только на величину планки полного сезона; вниз — по темпу
        if elite and pos not in _GK and sm >= 3:
            sm_mz = int(sm_db) if int(sm_db) >= 10 else int(sm)
            season_plus, mz_why = _elite_season_plus(
                pos, cur, int(sg) + int(sa), sm_mz
            )
            signals["elite_ga_proj"] = round(
                (sg + sa) * (_ELITE_FULL_SEASON_MATCHES / max(sm_mz, 1)), 1
            )
            signals["elite_season_plus"] = float(season_plus)
            if mz_why:
                reasons.append(mz_why)
            if target_level > cur + 0.35:
                if season_plus > 0:
                    cap = float(cur + season_plus)
                    if target_level > cap:
                        reasons.append(
                            f"· по темпу ~{plays_at_shown:.0f}, но с {cur}+ рост ограничен "
                            f"планкой → цель не выше {cur + season_plus}"
                        )
                        target_level = cap
                else:
                    reasons.append(
                        f"· по темпу ~{plays_at_shown:.0f}, но с {cur}+ рост только от "
                        f"планки полного сезона → потолок роста = {cur}"
                    )
                    target_level = min(target_level, float(cur))

        signals["target_level"] = round(target_level, 2)

        # совет: двигаем текущий к целевому уровню, ±3 / потолок / РПЛ
        target = int(round(target_level))
        target = max(60, min(OVR_CEILING, target))
        # у хайрейтинга ниже 90 рост к потолку осторожнее
        if not elite and target > cur:
            room = OVR_CEILING - cur
            if cur >= 87 and room <= 4:
                target = min(target, cur + max(1, min(2, room)))
        delta_raw = target - cur
        delta = clamp_ovr_delta_for_team(display, cur, delta_raw)
        if delta != delta_raw:
            reasons.insert(
                0,
                f"· лимит: цель {target} (Δ {delta_raw:+d}) → {cur + delta} "
                f"(±3 / лига / потолок {OVR_CEILING})",
            )

        suggested = cur + delta
        try:
            from player_stats import national_league_code_for_team

            if (national_league_code_for_team(display) or "").lower() == "rpl":
                suggested = max(75, suggested)
        except Exception:
            pass
        delta = int(suggested) - int(cur)
        signals["delta"] = float(delta)

        if abs(plays_at_shown - cur) < 0.45 and delta == 0:
            reasons.insert(
                0, f"· играет на ~{plays_at_shown:.0f} ≈ сейчас {cur} → оставляем"
            )
        elif delta == 0 and abs(plays_at_shown - cur) >= 0.45:
            reasons.insert(
                0,
                f"· играет на ~{plays_at_shown:.0f}, сейчас {cur} — совет без сдвига "
                f"(лимиты / правила 90+)",
            )
        else:
            reasons.insert(
                0,
                f"· играет на ~{plays_at_shown:.0f} → совет {suggested} "
                f"(сейчас {cur}, {delta:+d})",
            )

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
                plays_at=round(plays_at_shown, 1),
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
    plays = (
        f"~{row.plays_at:.0f}"
        if row.plays_at is not None
        else "—"
    )
    lines = [
        f"🔬 <b>DEBUG OVR</b> · {html_escape(team)}",
        "<i>Только просмотр — в БД не пишем.</i>",
        "",
        f"<b>{html_escape(row.name)}</b> · {html_escape(row.position or '—')} · "
        f"{html_escape(row.status or '—')}",
        f"Сейчас <b>{row.current}</b> · играет на <b>{plays}</b> → "
        f"совет <b>{row.suggested}</b>  [{tag}]",
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
        "Только тест: в БД ничего не пишем. Модель: играет на N → совет (±3).",
        "Сигналы: темп сезона · карьера · травмы · win% · траектория OVR.",
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
            f"■ {r.name} · {r.position} · {st} · сейчас {r.current} · "
            f"играет на ~{r.plays_at:.0f}  [{tag}]  → {r.suggested}"
            if r.plays_at is not None
            else f"■ {r.name} · {r.position} · {st} · сейчас {r.current}  [{tag}]  {arrow}"
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
