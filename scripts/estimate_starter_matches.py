#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Оценка ``matches`` для игроков основы (``status=start``).

Модель (dry-run по умолчанию):
  матчи_игрока ≈ матчи_команды_в_турнире − пропуски_по_травме − пропуски_по_дисквалу

Источники:
  • матчи команды — ``match_results.json`` (активный сезон) или ``db/season_N/match_results.json``;
  • травмы — ``data/player_discipline.json`` (``season``, ``out_from_month``, ``return_month``);
  • дисквалы — ``data/player_discipline.json`` (``matches_left`` — только **остаток**, см. ниже);
  • основа — ``status=start`` в ``league.db`` / ``champions_league.db``.

Ограничения (честно):
  1. **Травма → матчи** — грубо: ``пропуск ≈ месяцы × (матчи_команды / 10)`` (в календаре 10 мес./сезон).
     Пересечение травм с дисквалом не вычитается дважды.
  2. **Дисквалы** — в JSON хранится ``matches_left`` (сколько **осталось** отбыть), а не сколько уже
     пропущено. Для **завершённого** сезона без симуляции по журналу точный пропуск восстановить нельзя.
     Скрипт для дисквалов показывает только активный остаток и предупреждение.
  3. **Лига + ЛЧ** считаются отдельно; в БД ``matches`` — сумма обоих турниров.
  4. Только ``start``; запас/резерв не заполняются «всеми матчами».
  5. Травмы/дисквалы в JSON не архивируются по сезонам — для старых сезонов данные могут быть неполными.

Примеры:
  python scripts/estimate_starter_matches.py --team Ливерпуль
  python scripts/estimate_starter_matches.py --season 2 --team Ливерпуль
  python scripts/estimate_starter_matches.py --all-starters --season 3
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from match_results import _norm, load_records_and_keys_from_path
from player_stats import national_league_code_for_team
from utils import season_paths
from utils.player_discipline import _injuries_for_player, _injury_total_months, _load
from utils.player_transfer import _filter_team


def _norm_team(team: str) -> str:
    t = (team or "").strip()
    if t.casefold() == "цска":
        return "Цска"
    return t

_ALL = (Forward, Midfielder, Defender, Goalkeeper)
_NATIONAL = frozenset({"rpl", "eng", "esp", "ger", "ita"})
_SEASON_MONTHS = 10


def _match_results_path(season_num: int) -> str:
    active = int(season_paths.get_state().get("active_season") or 1)
    if season_num >= active:
        from match_results import MATCH_RESULTS_FILE

        return MATCH_RESULTS_FILE
    return os.path.join(
        season_paths.season_archive_directory(season_num), "match_results.json"
    )


def _season_db_path(season_num: int, *, cl: bool) -> str | None:
    active = int(season_paths.get_state().get("active_season") or 1)
    if season_num == active:
        path = season_paths.get_cl_db_path() if cl else season_paths.get_league_db_path()
        return path if os.path.isfile(path) else None
    fname = season_paths.SEASON_CL_NAME if cl else season_paths.SEASON_LEAGUE_NAME
    path = os.path.join(season_paths.season_archive_directory(season_num), fname)
    return path if os.path.isfile(path) else None


def count_team_tournament_matches(
    team: str, *, league_code: str, season_num: int
) -> int:
    """Сколько матчей команда сыграла в турнире по журналу."""
    path = _match_results_path(season_num)
    records, _ = load_records_and_keys_from_path(path)
    tn = _norm(team)
    lc = (league_code or "").strip().lower()
    n = 0
    for r in records:
        t = (r.get("league") or "").strip().lower()
        if t != lc:
            continue
        h = _norm(r.get("home") or "")
        a = _norm(r.get("away") or "")
        if h == tn or a == tn:
            n += 1
    return n


def _injury_missed_matches(months: int, team_matches: int) -> int:
    if months <= 0 or team_matches <= 0:
        return 0
    return max(0, min(team_matches, round(months * team_matches / _SEASON_MONTHS)))


def _injury_months_in_season(
    st: dict, name: str, team: str, season_num: int
) -> int:
    total = 0
    for inj in _injuries_for_player(st, name, team):
        sn = inj.get("season")
        if sn is None:
            continue
        try:
            if int(sn) != int(season_num):
                continue
        except (TypeError, ValueError):
            continue
        total += _injury_total_months(inj)
    return total


def _active_suspension_left(
    st: dict, name: str, team: str, league_code: str
) -> int:
    nn, tn = (name or "").strip().lower(), _norm(team).lower()
    left = 0
    for row in st.get("suspensions", []):
        if (row.get("name_norm") or "").lower() != nn:
            continue
        if (row.get("team_norm") or "").lower() != tn:
            continue
        lc = (row.get("league_code") or "").strip().lower()
        if lc != (league_code or "").strip().lower():
            continue
        left += int(row.get("matches_left") or 0)
    return left


def _roster_starters(team: str, season_num: int) -> list[dict]:
    team_n = _norm_team(team)
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for cl in (False, True):
        lp = _season_db_path(season_num, cl=cl)
        if not lp:
            continue
        eng = create_engine(f"sqlite:///{lp}")
        Session = sessionmaker(bind=eng)
        try:
            with Session() as sess:
                for Cls in _ALL:
                    for r in sess.query(Cls).filter(_filter_team(Cls, team_n)):
                        if (r.status or "").strip().lower() != "start":
                            continue
                        key = (r.name, r.position)
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append(
                            {
                                "name": r.name,
                                "position": r.position,
                                "overall": int(r.overall or 0),
                                "db_matches": int(getattr(r, "matches", 0) or 0),
                                "in_cl_db": cl,
                            }
                        )
        finally:
            eng.dispose()
    by_name: dict[str, dict] = {}
    for p in out:
        cur = by_name.get(p["name"])
        if cur is None:
            by_name[p["name"]] = dict(p)
        else:
            cur["db_matches"] = max(cur["db_matches"], p["db_matches"])
            cur["in_cl_db"] = cur["in_cl_db"] or p["in_cl_db"]
    return list(by_name.values())


def estimate_for_player(
    *,
    name: str,
    team: str,
    season_num: int,
    league_code: str,
    in_cl: bool,
) -> dict:
    st = _load()
    team_lg = count_team_tournament_matches(team, league_code=league_code, season_num=season_num)
    team_cl = 0
    if in_cl:
        team_cl = count_team_tournament_matches(team, league_code="cl", season_num=season_num)

    inj_m = _injury_months_in_season(st, name, team, season_num)
    miss_lg = _injury_missed_matches(inj_m, team_lg)
    miss_cl = _injury_missed_matches(inj_m, team_cl) if team_cl else 0

    susp_lg_left = _active_suspension_left(st, name, team, league_code)
    susp_cl_left = _active_suspension_left(st, name, team, "cl") if in_cl else 0

    est_lg = max(0, team_lg - miss_lg)
    est_cl = max(0, team_cl - miss_cl)
    est_total = est_lg + est_cl

    return {
        "team_lg": team_lg,
        "team_cl": team_cl,
        "injury_months": inj_m,
        "miss_lg_inj": miss_lg,
        "miss_cl_inj": miss_cl,
        "susp_lg_left": susp_lg_left,
        "susp_cl_left": susp_cl_left,
        "est_lg": est_lg,
        "est_cl": est_cl,
        "est_total": est_total,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Оценка matches для основы (dry-run)")
    ap.add_argument("--season", type=int, default=None, help="Номер сезона (по умолчанию — активный)")
    ap.add_argument("--team", type=str, default=None, help="Один клуб")
    ap.add_argument("--all-starters", action="store_true", help="Все клубы нац. лиг")
    args = ap.parse_args()

    sn = args.season or int(season_paths.get_state().get("active_season") or 1)

    if args.all_starters:
        from utils.team_registry import teams_in_league

        teams: list[str] = []
        for code in _NATIONAL:
            teams.extend(t.name for t in teams_in_league(code, active_only=True))
        teams = sorted(set(teams))
    elif args.team:
        teams = [args.team.strip()]
    else:
        ap.error("Укажите --team или --all-starters")

    print(f"Сезон {sn} · оценка matches для status=start (dry-run)\n")
    print(
        "Игрок          Клуб           лг_команда  лч_команда  "
        "травм_мес  оценка  в_БД  Δ   примечание"
    )
    print("-" * 95)

    for team in teams:
        lc = national_league_code_for_team(team)
        if not lc or lc not in _NATIONAL:
            continue
        for p in _roster_starters(team, sn):
            est = estimate_for_player(
                name=p["name"],
                team=team,
                season_num=sn,
                league_code=lc,
                in_cl=p.get("in_cl_db", False),
            )
            db_m = p["db_matches"]
            delta = est["est_total"] - db_m
            note_parts: list[str] = []
            if est["injury_months"]:
                note_parts.append(f"травма {est['injury_months']} мес.")
            if est["susp_lg_left"] or est["susp_cl_left"]:
                note_parts.append(
                    f"дисквал остаток лг={est['susp_lg_left']} лч={est['susp_cl_left']} (не вычтен)"
                )
            if est["team_lg"] == 0 and est["team_cl"] == 0:
                note_parts.append("нет матчей в журнале")
            note = "; ".join(note_parts) or "—"

            print(
                f"{p['name']:<14} {team:<14} "
                f"{est['team_lg']:>10}  {est['team_cl']:>10}  "
                f"{est['injury_months']:>9}  {est['est_total']:>6}  {db_m:>4}  {delta:+3}   {note}"
            )

    print(
        "\nДисквалы: ``matches_left`` — остаток, не история пропусков. "
        "Для точного backfill нужна симуляция по журналу или поле matches_banned при выдаче бана."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
