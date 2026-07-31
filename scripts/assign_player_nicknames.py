#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Интерактивно задать nickname игрокам со сложными фамилиями.

Никнейм привязывается к ``person_id`` → ``data/player_nicknames.json``.
Один человек с разными id в лиге и ЛЧ показывается один раз; ник пишется на все id.

Показываются игроки с:
  · дефисом / апострофом в имени;
  · составным именем (≥3 слова);
  · частицами (ван, де, ди, фон, …);
  · длинной фамилией (≥10 букв в последнем сегменте).

Пример строки::

  [3/41] Коло Муани Арсенал ПФА 86
           pid=128 · дефис|составное

Запуск из корня::

  python3 scripts/assign_player_nicknames.py
  python3 scripts/assign_player_nicknames.py --redo
  python3 scripts/assign_player_nicknames.py --list-only
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _norm_key(name: str, team: str) -> tuple[str, str]:
    from utils.player_transfer import _norm_cmp

    return _norm_cmp(name), _norm_cmp(team)


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
        get_nickname_for_player,
        is_complex_player_name,
    )
    import utils.player_nicknames as pn

    prev = pn._LONG_SURNAME_CHARS
    pn._LONG_SURNAME_CHARS = int(min_len)

    classes = (Forward, Midfielder, Defender, Goalkeeper)
    paths = [
        ("league", season_paths.get_league_db_path()),
        ("cl", season_paths.get_cl_db_path()),
    ]
    # ключ: (name, team) → один кандидат, несколько person_id
    by_player: dict[tuple[str, str], dict] = {}
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
                            if pid is None:
                                no_pid.append(
                                    {
                                        "person_id": None,
                                        "name": name,
                                        "team": team,
                                        "position": pos,
                                        "overall": ovr,
                                        "db": db_label,
                                        "reasons": reasons,
                                    }
                                )
                                continue
                            key = _norm_key(name, team)
                            cur = by_player.get(key)
                            if cur is None:
                                by_player[key] = {
                                    "person_id": int(pid),
                                    "person_ids": {int(pid)},
                                    "name": name,
                                    "team": team,
                                    "position": pos,
                                    "overall": ovr,
                                    "db": db_label,
                                    "reasons": reasons,
                                }
                                continue
                            cur["person_ids"].add(int(pid))
                            # канон — минимальный person_id
                            cur["person_id"] = min(cur["person_ids"])
                            if ovr > int(cur.get("overall") or 0):
                                cur["overall"] = ovr
                                cur["position"] = pos
                                cur["name"] = name
                                cur["team"] = team
            finally:
                eng.dispose()
    finally:
        pn._LONG_SURNAME_CHARS = prev

    rows: list[dict] = []
    for cur in by_player.values():
        pids = sorted(cur["person_ids"])
        cur["person_ids"] = pids
        cur["person_id"] = pids[0]
        rows.append(cur)

    if not include_named:
        rows = [
            r
            for r in rows
            if not get_nickname_for_player(
                person_id=r["person_id"], name=r["name"], team=r["team"]
            )
        ]
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
    from utils.player_nicknames import get_nickname_for_player

    pids = row.get("person_ids") or [row.get("person_id")]
    uniq = sorted({int(p) for p in pids if p is not None})
    nick = get_nickname_for_player(
        person_id=row.get("person_id"), name=row["name"], team=row["team"]
    )
    nick_s = f"  (nick={nick})" if nick else ""
    reasons = "|".join(row.get("reasons") or [])
    head = f"{row['name']} {row['team']} {row['position']} {row['overall']}"
    if len(uniq) > 1:
        extra = f"⚠ pids={','.join(map(str, uniq))} (нужен unify_person_ids)"
    else:
        extra = f"pid={uniq[0] if uniq else '—'}"
    return (
        f"[{idx}/{total}] {head}{nick_s}\n"
        f"         {extra} · {reasons}"
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
    ap.add_argument(
        "--sync-siblings",
        action="store_true",
        help="скопировать уже заданные ники на все person_id-дубли (лига/ЛЧ)",
    )
    args = ap.parse_args()

    if args.sync_siblings:
        return _sync_siblings()

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

    from utils.player_nicknames import get_nickname_for_player, nicknames_path, set_nickname

    start = max(1, int(args.start)) - 1
    total = len(rows)
    print(f"Файл: {nicknames_path()}")
    print("Enter — пропуск · q — выход · nickname — сохранить на все id игрока\n")

    i = start
    while i < total:
        r = rows[i]
        print(_format_line(r, idx=i + 1, total=total))
        existing = get_nickname_for_player(
            person_id=r["person_id"], name=r["name"], team=r["team"]
        )
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
            saved = set_nickname(
                int(r["person_id"]),
                s,
                also_person_ids=list(r.get("person_ids") or []),
                name=r["name"],
                team=r["team"],
            )
            pids = r.get("person_ids") or [r["person_id"]]
            print(f"  ✓ {pids} → «{saved}»")
        except ValueError as e:
            print(f"  ✗ {e}")
            continue
        i += 1

    print("Готово.")
    return 0


def _sync_siblings() -> int:
    """Проставить уже сохранённые ники на все связанные person_id."""
    from utils.player_nicknames import (
        get_nickname,
        load_nicknames,
        set_nickname,
        sibling_person_ids,
    )
    from utils.player_transfer import _norm_cmp

    # собрать name/team по pid из БД
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from data.defender import Defender
    from data.forward import Forward
    from data.goalkeeper import Goalkeeper
    from data.midfielder import Midfielder
    from utils import season_paths
    from utils.person_registry import row_person_id

    pid_meta: dict[int, tuple[str, str]] = {}
    classes = (Forward, Midfielder, Defender, Goalkeeper)
    for path in (season_paths.get_league_db_path(), season_paths.get_cl_db_path()):
        if not path or not os.path.isfile(path):
            continue
        eng = create_engine(f"sqlite:///{path}")
        Session = sessionmaker(bind=eng)
        try:
            with Session() as session:
                for Cls in classes:
                    for r in session.query(Cls).all():
                        pid = row_person_id(r)
                        if pid is None:
                            continue
                        name = (getattr(r, "name", None) or "").strip()
                        team = (getattr(r, "team", None) or "").strip()
                        if name:
                            pid_meta[int(pid)] = (name, team)
        finally:
            eng.dispose()

    mp = load_nicknames().get("by_person_id") or {}
    synced = 0
    seen_names: set[tuple[str, str]] = set()
    for pid_s, nick in list(mp.items()):
        nick_s = str(nick).strip()
        if not nick_s:
            continue
        try:
            pid = int(pid_s)
        except (TypeError, ValueError):
            continue
        meta = pid_meta.get(pid)
        if not meta:
            continue
        name, team = meta
        key = (_norm_cmp(name), _norm_cmp(team))
        if key in seen_names:
            continue
        seen_names.add(key)
        sibs = sibling_person_ids(name=name, team=team, person_id=pid)
        before = {p for p in sibs if get_nickname(p)}
        set_nickname(pid, nick_s, also_person_ids=sibs, name=name, team=team)
        after = {p for p in sibs if get_nickname(p) == nick_s}
        if after - before:
            synced += 1
            print(f"  {name} ({team}): {sorted(sibs)} → «{nick_s}»")
    print(f"Синхронизировано групп: {synced}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
