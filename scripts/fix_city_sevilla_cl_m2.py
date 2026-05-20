#!/usr/bin/env python3
"""Откат Сити 2:1 Севилья (ЛЧ, м2) и запись 1:2 с правильной статой."""
from __future__ import annotations

import json
import os
import pickle
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from player_stats import apply_match_lineup, revert_match_lineup
from utils import season_paths
from utils.player_discipline import (
    _bump_db_cards,
    _find_yellow_cycle,
    _load as disc_load,
    _save as disc_save,
    try_apply_discipline_line,
)
from player_stats import find_player_by_name, get_session

HOME, AWAY = "Сити", "Севилья"
OLD_HS, OLD_AS = 2, 1
NEW_HS, NEW_AS = 1, 2
DAY = 2
CL_PHASE = "league"


def _reverse_pickle() -> None:
    pkl = os.path.join(season_paths.get_pickle_directory(), "champ_league_teams.pkl")
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import table.team  # noqa: F401

    with open(pkl, "rb") as f:
        teams = pickle.load(f)
    th, ta = teams[HOME], teams[AWAY]

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

    rev(th, AWAY, OLD_HS, OLD_AS)
    rev(ta, HOME, OLD_AS, OLD_HS)
    with open(pkl, "wb") as f:
        pickle.dump(teams, f)
    print(f"Pickle: откат add_stat {HOME} {OLD_HS}:{OLD_AS} {AWAY}")


def _forward_pickle() -> None:
    pkl = os.path.join(season_paths.get_pickle_directory(), "champ_league_teams.pkl")
    import table.team  # noqa: F401

    with open(pkl, "rb") as f:
        teams = pickle.load(f)
    th, ta = teams[HOME], teams[AWAY]

    def add(side, opp: str, s_for: int, s_against: int) -> None:
        side.matches += 1
        side.scored += s_for
        side.missed += s_against
        if s_for > s_against:
            side.wins += 1
            rp = 3
        elif s_for == s_against:
            side.draws += 1
            rp = 1
        else:
            side.losses += 1
            rp = 0
        h = side.head_to_head.setdefault(opp, {"scored": 0, "missed": 0, "points": 0})
        h["scored"] += s_for
        h["missed"] += s_against
        h["points"] += rp

    add(th, AWAY, NEW_HS, NEW_AS)
    add(ta, HOME, NEW_AS, NEW_HS)
    with open(pkl, "wb") as f:
        pickle.dump(teams, f)
    print(f"Pickle: add_stat {HOME} {NEW_HS}:{NEW_AS} {AWAY}")


def _add_journal_row() -> None:
    path = os.path.join(ROOT, "match_results.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("matches", []).append(
        {
            "home": HOME,
            "away": AWAY,
            "league": "cl",
            "home_score": NEW_HS,
            "away_score": NEW_AS,
            "day": DAY,
            "cl_phase": CL_PHASE,
            "entry_type": "play",
        }
    )
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("Журнал: добавлена запись 1:2")


def _remove_journal_row() -> None:
    path = os.path.join(ROOT, "match_results.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    matches = data.get("matches", [])
    out = []
    removed = False
    for r in matches:
        if (
            not removed
            and r.get("home") == HOME
            and r.get("away") == AWAY
            and r.get("league") == "cl"
            and r.get("day") == DAY
            and r.get("home_score") == OLD_HS
            and r.get("away_score") == OLD_AS
        ):
            removed = True
            continue
        out.append(r)
    if not removed:
        raise SystemExit("В журнале не найден матч Сити 2:1 Севилья cl day=2")
    data["matches"] = out
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("Журнал: удалена запись 2:1")


def _revert_sow_yellow() -> None:
    sess = get_session("cl")
    player, _ = find_player_by_name(sess, "Соу", "Севилья")
    if not player:
        raise SystemExit("Соу не найден в CL БД")
    st = disc_load()
    row = _find_yellow_cycle(st, "Соу", "Севилья", "cl", "cl")
    if row:
        c = int(row.get("count") or 0)
        row["count"] = max(0, c - 1)
        print(f"Дисциплина Соу: жк {c} → {row['count']}")
    _bump_db_cards(sess, player, add_yellow=-1)
    sess.commit()
    disc_save(st)
    print("БД CL: Соу жк−1")


def main() -> int:
    mcs_old = (HOME, AWAY, OLD_HS, OLD_AS)
    wrong_rows = [
        ("Рэшфорд", "ЛФА", HOME, 2, 0),
        ("Лукебакио", "ПФА", AWAY, 1, 0),
    ]

    print("=== 1. Откат статистики игроков (CL) ===")
    revert_match_lineup(wrong_rows, "cl", match_for_cs=mcs_old)
    _revert_sow_yellow()

    print("=== 2. Журнал + pickle ===")
    _remove_journal_row()
    _reverse_pickle()
    _add_journal_row()
    _forward_pickle()

    print("=== 3. Новая стата 1:2 ===")
    mcs_new = (HOME, AWAY, NEW_HS, NEW_AS)
    correct_rows = [
        ("Месси", "ПФА", HOME, 1, 0),
        ("Карраско", "ЛФА", AWAY, 1, 0),
        ("Лукебакио", "ПФА", AWAY, 1, 0),
        ("Гонсалвеш", "ЛФА", AWAY, 0, 1),
    ]
    apply_match_lineup(correct_rows, "cl", match_for_cs=mcs_new)

    for name in ("Рамос", "Соу"):
        msg, _ = try_apply_discipline_line(
            f"{name} жк",
            current_team=AWAY,
            tournament="cl",
            league_code="cl",
            schedule_month=DAY,
            fixture_home=HOME,
            fixture_away=AWAY,
            cl_phase=CL_PHASE,
        )
        print(msg or name)

    try:
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
        print("common.db пересобран")
    except Exception as e:
        print(f"common: {e}")

    try:
        from utils.cumulative_db import rebuild_all_time_databases_from_season_archives

        log = rebuild_all_time_databases_from_season_archives()
        print("synced:", log.get("cumulative"), "сезоны:", log.get("seasons"))
    except Exception as e:
        print(f"synced: {e}")

    print("Готово: Сити 1:2 Севилья (ЛЧ, м2)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
