#!/usr/bin/env python3
"""Исправить cl_phase в журнале (месяцы 1–5 → league, 6+ → knockout) и пересобрать таблицу ЛЧ."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from champions_league.cl_format import get_cl_participants
from match_results import (
    cl_phase_from_calendar_day,
    compute_cl_group_standings_from_journal,
    load_records_and_keys,
    _save_v2,
)
from teams import get_pickle_dir, save_teams
from utils.utils import PROJECT_ROOT

STATS_COMPLETED = os.path.join(PROJECT_ROOT, "data", "matches_stats_completed.json")


def _fix_cl_phase_in_records(records: list[dict]) -> int:
    changed = 0
    for r in records:
        t = r.get("league") or r.get("tournament")
        if t != "cl":
            continue
        day = r.get("day")
        expected = cl_phase_from_calendar_day(day)
        if r.get("cl_phase") != expected:
            r["cl_phase"] = expected
            changed += 1
    return changed


def fix_match_results() -> int:
    records, _ = load_records_and_keys()
    changed = _fix_cl_phase_in_records(records)
    if changed:
        _save_v2(records)
    return changed


def fix_stats_completed() -> int:
    if not os.path.isfile(STATS_COMPLETED):
        return 0
    with open(STATS_COMPLETED, encoding="utf-8") as f:
        data = json.load(f)
    items = data if isinstance(data, list) else data.get("matches", [])
    changed = _fix_cl_phase_in_records(items)
    if changed:
        with open(STATS_COMPLETED, "w", encoding="utf-8") as f:
            if isinstance(data, list):
                json.dump(items, f, ensure_ascii=False, indent=2)
            else:
                data["matches"] = items
                json.dump(data, f, ensure_ascii=False, indent=2)
    return changed


def rebuild_cl_pickle() -> None:
    teams = compute_cl_group_standings_from_journal(get_cl_participants())
    path = os.path.join(get_pickle_dir(), "champ_league_teams.pkl")
    save_teams(path, teams)
    print(f"✓ Таблица группы ЛЧ сохранена: {path}")


def report_phases() -> None:
    records, _ = load_records_and_keys()
    from collections import Counter

    cl = [r for r in records if r.get("league") == "cl"]
    by_phase = Counter(r.get("cl_phase") for r in cl)
    by_day: dict[int, Counter] = {}
    for r in cl:
        d = int(r.get("day") or 0)
        by_day.setdefault(d, Counter())[r.get("cl_phase")] += 1
    print(f"CL матчей: {len(cl)}")
    print(f"Фазы: {dict(by_phase)}")
    for d in sorted(by_day):
        print(f"  месяц {d}: {dict(by_day[d])}")


def main() -> None:
    print("До исправления:")
    report_phases()
    n_journal = fix_match_results()
    n_stats = fix_stats_completed()
    print(f"\nИсправлено в match_results.json: {n_journal}")
    print(f"Исправлено в matches_stats_completed.json: {n_stats}")
    rebuild_cl_pickle()
    print("\nПосле исправления:")
    report_phases()


if __name__ == "__main__":
    main()
