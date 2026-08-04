#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Вернуть overall (и опционально nation) из снимка БД, не трогая имена и статистику.

Сопоставление строк — по ``id`` внутри таблицы (как ``restore_stats_from_backup.py``,
но наоборот: из бэкапа берём только рейтинг).

  python3 scripts/restore_overall_from_backup.py --src db/backup_pre_ratings_rollback_9b1cbd5
  python3 scripts/restore_overall_from_backup.py --src db/backup_pre_ratings_rollback_9b1cbd5 --apply
  python3 scripts/restore_overall_from_backup.py --from-git 9b1cbd5 --apply
  python3 scripts/restore_overall_from_backup.py --from-git 9b1cbd5 --full --apply

``--full`` — целиком ``league.db``, ``champions_league.db`` и ``free_agents.db``
(восстанавливает и снятых «убираем» игроков, не только overall).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")

DEFAULT_GIT = "9b1cbd5"  # season_4 до apply_ratings_xlsx


def _season_db_pairs(season: int) -> list[tuple[str, str]]:
    base = os.path.join(ROOT, "db", f"season_{season}")
    return [
        ("league.db", os.path.join(base, "league.db")),
        ("champions_league.db", os.path.join(base, "champions_league.db")),
    ]


def _restore_cols(with_nation: bool) -> tuple[str, ...]:
    return ("overall", "nation") if with_nation else ("overall",)


def _restore_db(
    src_path: str,
    dst_path: str,
    *,
    apply: bool,
    with_nation: bool,
) -> tuple[int, int]:
    cols = _restore_cols(with_nation)
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    rows_touched = 0
    fields_written = 0
    try:
        for table in TABLES:
            dst_cols = {r[1] for r in dst.execute(f"PRAGMA table_info({table})").fetchall()}
            use_cols = [c for c in cols if c in dst_cols]
            if not use_cols:
                continue
            col_list = ",".join(use_cols)
            backup_rows = {
                r[0]: r[1:]
                for r in src.execute(f"SELECT id,{col_list} FROM {table}")
            }
            for row in dst.execute(f"SELECT id,{col_list} FROM {table}"):
                pid = row[0]
                if pid not in backup_rows:
                    continue
                cur_vals = row[1:]
                bak_vals = backup_rows[pid]
                if cur_vals == bak_vals:
                    continue
                rows_touched += 1
                fields_written += sum(1 for a, b in zip(cur_vals, bak_vals) if a != b)
                if apply:
                    sets = ", ".join(f"{c}=?" for c in use_cols)
                    dst.execute(
                        f"UPDATE {table} SET {sets} WHERE id=?",
                        (*bak_vals, pid),
                    )
        if apply:
            dst.commit()
    finally:
        src.close()
        dst.close()
    return fields_written, rows_touched


def _safety_backup(dst_path: str, tag: str) -> str:
    out_dir = os.path.join(os.path.dirname(dst_path), f"backup_pre_overall_restore_{tag}")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, os.path.basename(dst_path))
    shutil.copy2(dst_path, out)
    return out


def _materialize_git_snapshot(commit: str, season: int, dest_dir: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    for fn in ("league.db", "champions_league.db"):
        rel = f"db/season_{season}/{fn}"
        out = os.path.join(dest_dir, fn)
        proc = subprocess.run(
            ["git", "show", f"{commit}:{rel}"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise SystemExit(f"В git {commit} нет {rel}")
        with open(out, "wb") as f:
            f.write(proc.stdout)
    manifest = {
        "source": "git",
        "commit": commit,
        "season": season,
        "files": {"league": "league.db", "cl": "champions_league.db"},
    }
    import json

    with open(os.path.join(dest_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return dest_dir


def _publish() -> None:
    from utils.common_db import rebuild_common_database

    rebuild_common_database()
    print("  · common.db пересобран")

    from utils import season_paths
    from utils.cumulative_db import rebuild_all_time_databases_from_season_archives

    if not season_paths.is_legacy_mode():
        log = rebuild_all_time_databases_from_season_archives()
        seasons = log.get("seasons") or []
        print(f"  · *_synced пересобраны из архивов season {seasons}")

    script = os.path.join(ROOT, "tools", "transfer_window_app", "export_rosters.py")
    subprocess.run([sys.executable, script], check=True, cwd=ROOT)
    print("  · rosters.json экспортирован")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", help="Папка с league.db (+ champions_league.db)")
    ap.add_argument(
        "--from-git",
        metavar="COMMIT",
        help=f"Взять season_N/league+cl из git (по умолчанию {DEFAULT_GIT})",
    )
    ap.add_argument("--season", type=int, default=0, help="Сезон (0 = активный)")
    ap.add_argument("--with-nation", action="store_true", help="Также вернуть nation из бэкапа")
    ap.add_argument(
        "--full",
        action="store_true",
        help="Целиком league+cl (+ free_agents из git), не только overall",
    )
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    from utils import season_paths

    season = args.season or season_paths.get_active_season()
    temp_dir: str | None = None
    src_root = args.src
    git_commit = args.from_git

    if args.from_git:
        commit = args.from_git
        temp_dir = tempfile.mkdtemp(prefix="restore_ovr_git_")
        src_root = _materialize_git_snapshot(commit, season, temp_dir)
        print(f"Снимок из git {commit} → {src_root}")
    elif not src_root:
        src_root = os.path.join(ROOT, "db", f"backup_pre_ratings_rollback_{DEFAULT_GIT}")
        if not os.path.isdir(src_root):
            print(
                "Укажите --src или --from-git. "
                f"Нет папки по умолчанию: {src_root}",
                file=sys.stderr,
            )
            return 1

    src_root = os.path.abspath(src_root)
    if not os.path.isdir(src_root):
        print(f"Нет папки: {src_root}", file=sys.stderr)
        return 1

    tag = datetime.now().strftime("%Y%m%d_%H%M%S")

    if args.full:
        if not args.apply:
            print("(--full) dry-run: будут перезаписаны league.db, champions_league.db", end="")
            if git_commit:
                print(", free_agents.db", end="")
            print()
            print("Повторите с --full --apply")
            return 0
        for rel_src, dst_path in _season_db_pairs(season):
            sp = os.path.join(src_root, rel_src)
            if not os.path.isfile(sp) or not os.path.isfile(dst_path):
                continue
            snap = _safety_backup(dst_path, tag)
            print(f"снимок: {snap}")
            shutil.copy2(sp, dst_path)
            print(f"[APPLY full] {dst_path}")
        if git_commit:
            fa_dst = os.path.join(ROOT, "db", "free_agents.db")
            if os.path.isfile(fa_dst):
                snap = _safety_backup(fa_dst, tag)
                print(f"снимок: {snap}")
            proc = subprocess.run(
                ["git", "show", f"{git_commit}:db/free_agents.db"],
                cwd=ROOT,
                capture_output=True,
                check=False,
            )
            if proc.returncode == 0:
                with open(fa_dst, "wb") as f:
                    f.write(proc.stdout)
                print(f"[APPLY full] {fa_dst}")
        print("\nПубликация:")
        _publish()
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
        print("Готово.")
        return 0

    total_rows = 0
    total_fields = 0

    for rel_src, dst_path in _season_db_pairs(season):
        sp = os.path.join(src_root, rel_src)
        if not os.path.isfile(sp):
            print(f"SKIP (нет в источнике): {rel_src}")
            continue
        if not os.path.isfile(dst_path):
            print(f"SKIP (нет цели): {dst_path}")
            continue
        if args.apply:
            snap = _safety_backup(dst_path, tag)
            print(f"снимок: {snap}")
        fields, rows = _restore_db(
            sp, dst_path, apply=args.apply, with_nation=args.with_nation
        )
        mode = "APPLY" if args.apply else "dry-run"
        print(f"[{mode}] season_{season}/{rel_src}: строк={rows}, полей={fields}")
        total_rows += rows
        total_fields += fields

    print(f"Итого: строк={total_rows}, полей={total_fields}")
    if not args.apply:
        print("Повторите с --apply для записи.")
        return 0

    if total_rows:
        print("\nПубликация:")
        _publish()
    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)
    print("Готово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
