#!/usr/bin/env python3
"""
Пересобрать pickle таблиц лиг из match_results.json.

Правила как в main.process_match: счёт в pickle идёт только для национальных лиг
и для ЛЧ в групповой фазе (is_cl_group_phase_record). Нокаут ЛЧ — только журнал.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.chdir(ROOT)

import teams  # noqa: E402
from match_results import (  # noqa: E402
    _norm,
    is_cl_group_phase_record,
    load_records_and_keys,
    record_key,
)


def _add_stat(first_team: str, second_team: str, first_score: int, second_score: int, td: dict) -> None:
    td[first_team].update_stats(first_score, second_score, second_team)
    td[second_team].update_stats(second_score, first_score, first_team)


LEAGUE_ATTR = {
    "rpl": "teams_rpl",
    "eng": "teams_eng",
    "esp": "teams_spain",
    "ger": "teams_germany",
    "ita": "teams_italy",
    "cl": "teams_champ_league",
}

PICKLE_FILES = [
    ("rpl", "rpl_teams.pkl"),
    ("eng", "england_teams.pkl"),
    ("esp", "spain_teams.pkl"),
    ("ger", "germany_teams.pkl"),
    ("ita", "italy_teams.pkl"),
    ("cl", "champ_league_teams.pkl"),
]


def rebuild() -> None:
    teams.reset_all_teams()
    records, _ = load_records_and_keys()
    seen: set = set()
    applied = 0
    skipped_dup = 0
    skipped_no_score = 0
    skipped_knockout_cl = 0
    skipped_unknown_league = 0
    skipped_missing_team = 0

    for r in records:
        lg = str(r.get("league") or "")
        if lg not in LEAGUE_ATTR:
            skipped_unknown_league += 1
            continue
        k = record_key(r.get("home", ""), r.get("away", ""), lg, _rec=r)
        if k in seen:
            skipped_dup += 1
            continue
        seen.add(k)

        hs, aws = r.get("home_score"), r.get("away_score")
        if hs is None or aws is None:
            skipped_no_score += 1
            continue

        if lg == "cl" and not is_cl_group_phase_record(r):
            skipped_knockout_cl += 1
            continue

        h = _norm(str(r.get("home", "")))
        a = _norm(str(r.get("away", "")))
        td = getattr(teams, LEAGUE_ATTR[lg])
        if h not in td or a not in td:
            print(f"  [skip] нет команды в {lg}: {h} — {a}")
            skipped_missing_team += 1
            continue

        _add_stat(h, a, int(hs), int(aws), td)
        applied += 1

    for _code, fname in PICKLE_FILES:
        attr = LEAGUE_ATTR[_code]
        teams.save_teams(os.path.join(teams.PICKLE_DIR, fname), getattr(teams, attr))

    print(
        f"Готово: в pickle применено матчей со счётом: {applied}\n"
        f"  пропуск: дубликат ключа={skipped_dup}, без счёта={skipped_no_score}, "
        f"ЛЧ нокаут={skipped_knockout_cl}, нет лиги={skipped_unknown_league}, "
        f"нет пары в словаре={skipped_missing_team}"
    )


if __name__ == "__main__":
    rebuild()
