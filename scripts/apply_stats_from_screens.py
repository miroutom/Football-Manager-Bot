#!/usr/bin/env python3
"""
Запись статы из stats_from_screens_m3_m5.txt в db/season_N (как dry-run, но с add_player_stats).

Сначала обычно восстановите league.db / champions_league.db из снимка (например b4bd9f2).

  python3 scripts/dry_run_stats_from_screens.py          # только проверка имён
  python3 scripts/apply_stats_from_screens.py            # dry-run записи
  python3 scripts/apply_stats_from_screens.py --apply    # запись + rebuild common
"""
from __future__ import annotations

import argparse
import contextlib
import io
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from player_stats import (
    MatchTeamStatBudget,
    add_player_stats,
    find_player_by_name,
    infer_league_code_for_stats,
)
from scripts.dry_run_stats_from_screens import NAME_MAP
from scripts.dry_run_stats_from_screens import (
    HEADER_TEAM_ALIAS,
    _canon_header_team,
    _lookup_player,
    _parse_line,
)
from scripts.stats_screens_load import blocks_with_tournament, DEFAULT_TXT
from utils.transfer_input import resolve_team_name
from utils.utils import session_league


def _resolve_player_for_match(sess, fifa_name: str, home: str, away: str):
    """Как dry-run; если не нашли по hint — ищем среди хозяев/гостей матча."""
    pl, db_name, hinted = _lookup_player(sess, fifa_name)
    if pl:
        return pl, db_name, hinted
    db_name = NAME_MAP.get(fifa_name, fifa_name)
    for side in (home, away):
        pl, _ = find_player_by_name(sess, db_name, side)
        if pl:
            return pl, db_name, side
    pl, _ = find_player_by_name(sess, db_name, None)
    if pl:
        return pl, db_name, hinted
    return None, db_name, hinted


def _apply_discipline(
    raw: str,
    *,
    team: str,
    tournament: str,
    home: str,
    away: str,
    month: int,
) -> tuple[bool, str]:
    from utils.player_discipline import (
        get_calendar_month,
        try_apply_discipline_line,
    )

    st_tourn = "cl" if tournament == "cl" else "league"
    lc = infer_league_code_for_stats(home, away, st_tourn)
    msched = get_calendar_month(month)
    msg, handled = try_apply_discipline_line(
        raw,
        current_team=team,
        tournament=st_tourn,
        league_code=lc,
        schedule_month=msched,
        fixture_home=home,
        fixture_away=away,
    )
    return handled, msg or "—"


def apply_all(*, do_apply: bool, txt_path: Path) -> tuple[int, int, int]:
    ok, fail, skip_blocks = 0, 0, 0
    logs: list[str] = []

    for label, home, away, hs, aws, month, tournament, stat_lines in blocks_with_tournament(
        txt_path
    ):
        home_c = _canon_header_team(home)
        away_c = _canon_header_team(away)
        rh = resolve_team_name(home_c, session_league) or home_c
        ra = resolve_team_name(away_c, session_league) or away_c
        match_for_cs = (rh, ra, int(hs), int(aws))

        if not stat_lines:
            logs.append(f"## {label} · {rh} {hs}:{aws} {ra} — нет строк, пропуск")
            skip_blocks += 1
            continue

        logs.append(f"## {label} · {rh} {hs}:{aws} {ra} → {tournament}, day={month}")
        sess_tourn = tournament
        from player_stats import get_session

        sess = get_session(sess_tourn)
        lc = infer_league_code_for_stats(rh, ra, sess_tourn)
        match_for_cs = (rh, ra, int(hs), int(aws))
        team_budget = MatchTeamStatBudget()

        for raw in stat_lines:
            fifa_name, g, a, cs, disc = _parse_line(raw)
            pl, db_name, hinted = _resolve_player_for_match(sess, fifa_name, rh, ra)
            if not pl:
                rt = resolve_team_name(hinted, session_league) or hinted or "?"
                logs.append(f"  ✗ НЕ НАЙДЕН {db_name} @ {rt} ← {raw}")
                fail += 1
                continue

            team = (pl.team or "").strip().title()
            if hinted:
                ht = resolve_team_name(hinted, session_league) or hinted
                if team.lower() != ht.lower():
                    logs.append(
                        f"  · {db_name}: в БД клуб {team}, в матче {ht} ← {raw}"
                    )

            if not do_apply:
                g_add = max(0, int(g))
                a_add = max(0, int(a))
                if g_add or a_add:
                    from player_stats import _validate_goals_vs_team_score

                    ok_v, err_v = _validate_goals_vs_team_score(
                        team,
                        g_add,
                        a_add,
                        match_for_cs,
                        team_goals_already=team_budget.goals_used(team),
                        team_assists_already=team_budget.assists_used(team),
                    )
                    if not ok_v:
                        logs.append(f"  ✗ {pl.name} ({team}): {err_v} ← {raw}")
                        fail += 1
                        continue
                    team_budget.add(team, g_add, a_add)
                logs.append(f"  · {raw} → {pl.name} ({team})")
                ok += 1
                continue

            if disc:
                handled, dmsg = _apply_discipline(
                    raw,
                    team=team,
                    tournament=sess_tourn,
                    home=rh,
                    away=ra,
                    month=month,
                )
                if handled:
                    logs.append(f"  ✓ {dmsg}")
                    ok += 1
                else:
                    logs.append(f"  ✗ дисциплина: {raw}")
                    fail += 1
                continue

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                success = add_player_stats(
                    pl.name,
                    pl.position,
                    team,
                    g,
                    a,
                    clean_sheet=cs,
                    tournament=sess_tourn,
                    auto_find=True,
                    match_for_cs=match_for_cs,
                    discipline_league_code=lc,
                    schedule_day=month,
                    increment_matches=True,
                    skip_discipline_check=True,
                    team_goals_already=team_budget.goals_used(team),
                    team_assists_already=team_budget.assists_used(team),
                )
            line = buf.getvalue().strip() or ("✓" if success else "✗")
            logs.append(f"  {line} ← {raw}")
            if success:
                team_budget.add(team, g, a)
                ok += 1
            else:
                fail += 1

        logs.append("")

    text = "\n".join(logs)
    print(text)
    print(
        f"\n--- {'ЗАПИСАНО' if do_apply else 'DRY-RUN'}: "
        f"{ok} OK, {fail} ошибок, {skip_blocks} матчей без строк ---"
    )
    return ok, fail, skip_blocks


def restore_from_backup(backup_dir: Path, season_dir: Path) -> None:
    for name in ("league.db", "champions_league.db"):
        src = backup_dir / name
        dst = season_dir / name
        if not src.is_file():
            raise FileNotFoundError(src)
        shutil.copy2(src, dst)
        print(f"Восстановлено: {dst} ← {src}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Записать в БД и пересобрать common.db",
    )
    parser.add_argument(
        "--txt",
        type=Path,
        default=DEFAULT_TXT,
        help="Файл со строчной статой (по умолчанию stats_from_screens_m3_m5.txt)",
    )
    parser.add_argument(
        "--restore-b4bd9f2",
        action="store_true",
        help="Сначала скопировать db/backup_view_b4bd9f2_20260526 → db/season_2",
    )
    parser.add_argument(
        "--no-rebuild-common",
        action="store_true",
        help="Не вызывать rebuild_common_database после --apply",
    )
    args = parser.parse_args()

    from utils import season_paths

    season_dir = Path(season_paths.get_season_directory_abs())
    if args.restore_b4bd9f2:
        backup = ROOT / "db" / "backup_view_b4bd9f2_20260526"
        if not backup.is_dir():
            raise SystemExit(f"Нет папки снимка: {backup}")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pre = ROOT / "db" / f"backup_pre_restore_{stamp}"
        pre.mkdir(parents=True, exist_ok=True)
        for name in ("league.db", "champions_league.db", "common.db"):
            p = season_dir / name
            if p.is_file():
                shutil.copy2(p, pre / name)
        print(f"Бэкап текущих БД: {pre}")
        restore_from_backup(backup, season_dir)
        from utils.utils import reinit_db_connections

        reinit_db_connections()

    ok, fail, _skip = apply_all(do_apply=args.apply, txt_path=args.txt)
    if args.apply and not args.no_rebuild_common:
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
        print("✓ common.db пересобран (league + champions_league).")

    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
