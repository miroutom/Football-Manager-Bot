#!/usr/bin/env python3
"""
Откат одного сыгранного матча на сервере (или локально): удалить строку из
match_results.json и снять статистику в соответствующем pickle — как обратное
к add_stat в main.process_match (нацлиги и групповой этап ЛЧ).

ЛЧ нокаут в pickle не хранится — для такого матча только удаление из журнала.

Запуск из корня репозитория:

  python3 scripts/revert_one_match.py --home "Реал Сосьедад" --away Атлетико --league esp
  python3 scripts/revert_one_match.py --home Рубин --away Динамо --league rpl --day 3
  python3 scripts/revert_one_match.py --home Челси --away "Реал Сосьедад" --league cl --cl-phase knockout --dry-run

Для ЛЧ обязателен --cl-phase league|knockout.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.chdir(ROOT)

from match_results import (  # noqa: E402
    MATCH_RESULTS_FILE,
    _norm,
    is_cl_group_phase_record,
    record_key,
)
from teams import PICKLE_DIR, load_teams, save_teams  # noqa: E402

LEAGUE_PICKLE = {
    "rpl": "rpl_teams.pkl",
    "eng": "england_teams.pkl",
    "esp": "spain_teams.pkl",
    "ger": "germany_teams.pkl",
    "ita": "italy_teams.pkl",
    "cl": "champ_league_teams.pkl",
}


def _reverse_add_stat(teams: dict, home: str, away: str, hs: int, aws: int) -> None:
    """Обратное к main.add_stat(home, away, hs, aws, teams)."""
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


def _build_fake_rec(home: str, away: str, league: str, cl_phase: str | None) -> dict:
    rec = {"home": _norm(home), "away": _norm(away), "league": league}
    if league == "cl":
        rec["cl_phase"] = cl_phase or "knockout"
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description="Откат одного матча: журнал + pickle")
    ap.add_argument("--home", required=True)
    ap.add_argument("--away", required=True)
    ap.add_argument("--league", required=True, choices=list(LEAGUE_PICKLE.keys()))
    ap.add_argument("--day", type=int, default=None, help="если в журнале несколько кандидатов")
    ap.add_argument(
        "--cl-phase",
        choices=("league", "knockout"),
        default=None,
        help="для league=cl обязателен",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lg = args.league
    if lg == "cl" and not args.cl_phase:
        print("Для ЛЧ укажи --cl-phase league или knockout", file=sys.stderr)
        return 2

    h = _norm(args.home)
    a = _norm(args.away)
    fake = _build_fake_rec(h, a, lg, args.cl_phase)
    target_key = record_key(h, a, lg, _rec=fake)

    with open(MATCH_RESULTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    matches = data.get("matches", [])

    def row_key(r: dict):
        return record_key(r.get("home", ""), r.get("away", ""), r.get("league", ""), _rec=r)

    candidates = []
    for i, r in enumerate(matches):
        if row_key(r) != target_key:
            continue
        if args.day is not None and r.get("day") != args.day:
            continue
        candidates.append((i, r))

    if not candidates:
        print(f"В журнале нет записи для ключа {target_key}" + (f", day={args.day}" if args.day else ""))
        return 1
    if len(candidates) > 1:
        print("Несколько записей под фильтр; уточни --day или исправь журнал вручную:", file=sys.stderr)
        for i, r in candidates:
            print(f"  idx={i} {r}", file=sys.stderr)
        return 1

    idx, rec = candidates[0]
    hs, aws = rec.get("home_score"), rec.get("away_score")
    if hs is None or aws is None:
        print("У найденной записи нет счёта — только удаление из JSON (pickle не трогаю).")
        touch_pickle = False
    else:
        hs, aws = int(hs), int(aws)
        touch_pickle = lg != "cl" or is_cl_group_phase_record(rec)

    if args.dry_run:
        print("[dry-run] Удалю запись:", json.dumps(rec, ensure_ascii=False))
        if touch_pickle:
            print("[dry-run] Сниму из pickle add_stat:", h, hs, aws, a)
        elif lg == "cl":
            print("[dry-run] ЛЧ нокаут — pickle не меняется")
        return 0

    new_matches = [r for j, r in enumerate(matches) if j != idx]
    data["matches"] = new_matches
    with open(MATCH_RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Удалено из журнала: {h} — {a} ({lg})")

    if not touch_pickle:
        print("Pickle не трогал (ЛЧ нокаут или запись без счёта).")
        return 0

    pkl_name = LEAGUE_PICKLE[lg]
    pkl_path = os.path.join(PICKLE_DIR, pkl_name)
    teams = load_teams(pkl_path)
    if teams is None:
        print(f"Нет файла {pkl_path}", file=sys.stderr)
        return 3
    if h not in teams or a not in teams:
        print(f"Команды не найдены в pickle: {h!r}, {a!r}", file=sys.stderr)
        return 3

    _reverse_add_stat(teams, h, a, hs, aws)
    save_teams(pkl_path, teams)
    print(f"Снята статистика в {pkl_path} ({h} {hs}:{aws} {a})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
