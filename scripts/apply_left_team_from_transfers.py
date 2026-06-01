#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проставить ``left_team=True`` по журналу ``data/transfers.json``.

Для каждой записи (кроме из «свободный агент») помечает строки игрока
в ``from_team`` (имя + позиция) — ``team`` и стата не меняются, из заявки скрываются.

БД: активный сезон (league/cl/common) + ``*_synced.db``.

  python3 scripts/apply_left_team_from_transfers.py --dry-run
  python3 scripts/apply_left_team_from_transfers.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import sqlite3

from player_stats import _norm_cmp
from utils import season_paths
from utils.migrate_player_left_team import migrate_all_player_left_team_columns
from utils.transfer_input import _team_name_as_in_db, normalize_position

_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")
_TRANSFERS_PATH = os.path.join(ROOT, "data", "transfers.json")
_FA_MARKERS = ("(свободный агент)", "свободный агент", "free agent")


def _is_free_agent_team(team: str) -> bool:
    t = (team or "").strip().lower()
    return any(m in t for m in _FA_MARKERS) or t in ("fa", "free agent")


def _load_transfers() -> list[dict]:
    with open(_TRANSFERS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get("transfers") or [])


def _resolve_team_in_db(conn: sqlite3.Connection, from_team: str) -> str:
    """Точное имя клуба в этой БД (casefold)."""
    raw = _team_name_as_in_db((from_team or "").strip())
    want = _norm_cmp(raw)
    teams: set[str] = set()
    for table in _TABLES:
        try:
            for (tm,) in conn.execute(
                f"SELECT DISTINCT team FROM {table} WHERE team IS NOT NULL"
            ):
                if tm:
                    teams.add(str(tm).strip())
        except sqlite3.OperationalError:
            pass
    for tm in teams:
        if _norm_cmp(tm) == want:
            return tm
    return raw


def _team_matches(db_team: str, resolved_from: str) -> bool:
    return _norm_cmp(db_team) == _norm_cmp(resolved_from)


def _mark_left_in_db(
    db_path: str,
    from_team: str,
    player: str,
    position: str,
    *,
    dry_run: bool,
) -> list[str]:
    want_n = _norm_cmp(player)
    want_pos = _norm_cmp(position) if position else ""
    touched: list[str] = []
    conn = sqlite3.connect(db_path)
    try:
        resolved_team = _resolve_team_in_db(conn, from_team)
        for table in _TABLES:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if "left_team" not in cols or "name" not in cols:
                continue
            has_m = "matches" in cols
            sel = "id, name, team, position, left_team"
            if has_m:
                sel += ", matches"
            for row in conn.execute(f"SELECT {sel} FROM {table}"):
                rid, name, team, pos = row[0], row[1], row[2], row[3]
                left = bool(row[4])
                matches = int(row[5] or 0) if has_m and len(row) > 5 else 0
                if left:
                    continue
                if not _team_matches(team or "", resolved_team):
                    continue
                if _norm_cmp(name or "") != want_n:
                    continue
                pos_u = (pos or "").strip().upper()
                if want_pos and _norm_cmp(pos_u) != want_pos:
                    continue
                line = (
                    f"  {table} id={rid} {name} {pos_u} @ {team} m={matches}"
                )
                touched.append(line)
                if not dry_run:
                    upd = f"UPDATE {table} SET left_team = 1"
                    if "status" in cols:
                        upd += ", status = NULL"
                    upd += " WHERE id = ?"
                    conn.execute(upd, (rid,))
        if not dry_run and touched:
            conn.commit()
    finally:
        conn.close()
    return touched


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.apply:
        args.dry_run = False
    else:
        args.dry_run = True

    migrate_all_player_left_team_columns()

    transfers = _load_transfers()
    skipped_fa = 0
    seen: set[tuple[str, str, str, str]] = set()
    total_lines = 0

    db_paths = season_paths.iter_player_roster_db_paths(include_synced=True)

    print(f"Журнал: {_TRANSFERS_PATH} ({len(transfers)} записей)")
    print(f"БД: {', '.join(l for l, _ in db_paths)}")
    print(f"Режим: {'dry-run' if args.dry_run else 'APPLY'}\n")

    for tr in transfers:
        player = (tr.get("player") or "").strip()
        from_team = (tr.get("from_team") or "").strip()
        to_team = (tr.get("to_team") or "").strip()
        pos = normalize_position(tr.get("position") or "")
        if not player or not from_team:
            continue
        if _is_free_agent_team(from_team):
            skipped_fa += 1
            continue
        key = (_norm_cmp(player), _norm_cmp(from_team), _norm_cmp(to_team), _norm_cmp(pos))
        if key in seen:
            continue
        seen.add(key)

        any_row = False
        print(f"— {player}: {from_team} ({pos}) → {to_team}")
        for label, path in db_paths:
            lines = _mark_left_in_db(
                path, from_team, player, pos, dry_run=args.dry_run
            )
            if lines:
                print(f"  [{label}]")
                for ln in lines:
                    print(ln)
                any_row = True
                total_lines += len(lines)
        if not any_row:
            print("  (строк в from_team не найдено)")

    print(f"\nИтого: пометок {total_lines}, пропущено из СА: {skipped_fa}")
    if args.dry_run:
        print("Применить: python3 scripts/apply_left_team_from_transfers.py --apply")
    else:
        try:
            from utils.common_db import rebuild_common_database

            rebuild_common_database()
            print("common.db пересобран.")
        except Exception as e:
            print(f"common.db не пересобран ({e!s}); league/cl/synced уже обновлены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
