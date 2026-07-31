#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Интерактивно задать nickname игрокам со сложными фамилиями.

Никнейм привязывается к ``person_id`` → ``data/player_nicknames.json``.

Показываются игроки с:
  · дефисом / апострофом в имени;
  · составным именем (≥3 слова);
  · частицами (ван, де, ди, фон, …);
  · длинной фамилией (≥10 букв в последнем сегменте).

Пример строки::

  [3/41] pid=128 · Коло Муани · Арсенал · ПФА · 86 · дефис|составное
  nickname (Enter=пропуск, q=выход): муани

Запуск из корня::

  python3 scripts/assign_player_nicknames.py
  python3 scripts/assign_player_nicknames.py --redo          # снова показать уже с ником
  python3 scripts/assign_player_nicknames.py --list-only     # только список, без ввода
  python3 scripts/assign_player_nicknames.py --min-len 8     # порог длины фамилии
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _collect_candidates(
    *, min_len: int, include_named: bool
) -> tuple[list[dict], list[dict]]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from data.defender import Defender
    from data.forward import Forward
    from data.goalkeeper import Goalkeeper
    from data.midfielder import Midfielder
    from utils import season_paths
    from utils.person_registry import row_person_id
    from utils.player_nicknames import (
        complex_name_reasons,
        get_nickname,
        is_complex_player_name,
    )
    import utils.player_nicknames as pn

    # временно подкрутить порог длины
    prev = pn._LONG_SURNAME_CHARS
    pn._LONG_SURNAME_CHARS = int(min_len)

    classes = (Forward, Midfielder, Defender, Goalkeeper)
    paths = [
        ("league", season_paths.get_league_db_path()),
        ("cl", season_paths.get_cl_db_path()),
    ]
    best: dict[int, dict] = {}
    no_pid: list[dict] = []

    try:
        for db_label, path in paths:
            if not os.path.isfile(path):
                continue
            eng = create_engine(f"sqlite:///{path}")
            Session = sessionmaker(bind=eng)
            try:
                with Session() as session:
                    for Cls in classes:
                        for r in session.query(Cls).all():
                            if getattr(r, "left_team", False):
                                continue
                            name = (getattr(r, "name", None) or "").strip()
                            if not name or not is_complex_player_name(name):
                                continue
                            team = (getattr(r, "team", None) or "").strip() or "—"
                            pos = (getattr(r, "position", None) or "").strip() or "—"
                            ovr = int(getattr(r, "overall", 0) or 0)
                            reasons = complex_name_reasons(name)
                            pid = row_person_id(r)
                            row = {
                                "person_id": pid,
                                "name": name,
                                "team": team,
                                "position": pos,
                                "overall": ovr,
                                "db": db_label,
                                "reasons": reasons,
                            }
                            if pid is None:
                                no_pid.append(row)
                                continue
                            prev_row = best.get(pid)
                            if prev_row is None or ovr > int(prev_row.get("overall") or 0):
                                best[pid] = row
            finally:
                eng.dispose()
    finally:
        pn._LONG_SURNAME_CHARS = prev

    rows = list(best.values())
    if not include_named:
        rows = [r for r in rows if not get_nickname(r["person_id"])]
    rows.sort(
        key=lambda r: (
            str(r["name"]).casefold(),
            str(r["team"]).casefold(),
            int(r["person_id"] or 0),
        )
    )
    no_pid.sort(key=lambda r: str(r["name"]).casefold())
    return rows, no_pid


def _format_line(row: dict, *, idx: int, total: int) -> str:
    """Основная строка как при заполнении статы: Имя Клуб Поз OVR."""
    pid = row.get("person_id")
    nick = ""
    if pid:
        from utils.player_nicknames import get_nickname

        n = get_nickname(pid)
        if n:
            nick = f"  (nick={n})"
    reasons = "|".join(row.get("reasons") or [])
    head = f"{row['name']} {row['team']} {row['position']} {row['overall']}"
    return (
        f"[{idx}/{total}] {head}{nick}\n"
        f"         pid={pid if pid is not None else '—'} · {reasons}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Nickname для сложных фамилий → person_id")
    ap.add_argument("--list-only", action="store_true", help="только вывести список")
    ap.add_argument(
        "--redo",
        action="store_true",
        help="показывать и тех, у кого nickname уже есть",
    )
    ap.add_argument(
        "--min-len",
        type=int,
        default=10,
        help="порог длины фамилии (по умолчанию 10)",
    )
    ap.add_argument(
        "--start",
        type=int,
        default=1,
        help="начать с N-го кандидата (1-based)",
    )
    args = ap.parse_args()

    rows, no_pid = _collect_candidates(min_len=args.min_len, include_named=args.redo)
    print(
        f"Кандидатов: {len(rows)}"
        + (f" · без person_id (пропуск): {len(no_pid)}" if no_pid else "")
    )
    if no_pid:
        print("⚠ Без person_id (нужен backfill) — не предлагаются для ввода:")
        for r in no_pid[:15]:
            print(f"  · {r['name']} · {r['team']} · {r['position']} · {r['db']}")
        if len(no_pid) > 15:
            print(f"  … ещё {len(no_pid) - 15}")
        print()

    if not rows:
        print("Некого назначать (или все уже с nickname — уберите фильтр через --redo).")
        return 0

    if args.list_only:
        for i, r in enumerate(rows, 1):
            print(_format_line(r, idx=i, total=len(rows)))
        from utils.player_nicknames import nicknames_path

        print(f"\nФайл: {nicknames_path()}")
        return 0

    from utils.player_nicknames import get_nickname, nicknames_path, set_nickname

    start = max(1, int(args.start)) - 1
    total = len(rows)
    print(f"Файл: {nicknames_path()}")
    print("Enter — пропуск · q — выход · nickname — сохранить\n")

    i = start
    while i < total:
        r = rows[i]
        print(_format_line(r, idx=i + 1, total=total))
        existing = get_nickname(r["person_id"])
        prompt = "nickname"
        if existing:
            prompt += f" [сейчас: {existing}]"
        prompt += ": "
        try:
            raw = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print("\nСтоп.")
            break
        s = (raw or "").strip()
        if s.casefold() in ("q", "quit", "exit", "й"):
            print("Выход.")
            break
        if not s:
            i += 1
            continue
        try:
            saved = set_nickname(int(r["person_id"]), s)
            print(f"  ✓ pid={r['person_id']} → «{saved}»")
        except ValueError as e:
            print(f"  ✗ {e}")
            continue
        i += 1

    print("Готово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
