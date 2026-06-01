#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Игроки с одной фамилией+позицией в season_1, season_2 и league_synced — полное имя в ``name``.

Не разделяем name/surname (surname очищается). Статистика не трогается.

  python3 scripts/apply_cross_season_full_names.py
  python3 scripts/apply_cross_season_full_names.py --apply
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
from scripts.import_player_names_xlsx import (
    XlsxPlayer,
    _canonical_xlsx_team,
    load_names_xlsx,
)
from utils.player_transfer import normalize_player_name_for_db

_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")

_DB_TARGETS = [
    ("season_1/league.db", "s1:league"),
    ("season_1/champions_league.db", "s1:cl"),
    ("season_1/common.db", "s1:common"),
    ("season_2/league.db", "s2:league"),
    ("season_2/champions_league.db", "s2:cl"),
    ("season_2/common.db", "s2:common"),
    ("league_synced.db", "sync:league"),
    ("champions_league_synced.db", "sync:cl"),
    ("common_synced.db", "sync:common"),
]

# Полное имя в одном поле (переопределяет xlsx)
FULL_NAME_OVERRIDES: dict[tuple[str, str], str] = {
    (_norm_cmp("Тонали"), "ЦАП"): "Сандро Тонали",
    (_norm_cmp("Фофана"), "ЦОП"): "Юсуф Фофана",
    (_norm_cmp("Барриос"), "ЦП"): "Вильмар Барриос",
    (_norm_cmp("Гарсия"), "ЦП"): "Саму Гарсия",
    (_norm_cmp("Гарсия"), "ЦЗ"): "Эрик Гарсия",
    (_norm_cmp("Гарсия"), "ЛЗ"): "Фран Гарсия",
    (_norm_cmp("Эрнандез"), "ЛЗ"): "Люка Эрнандез",
}

# Одинаковая фамилия — разные люди; xlsx по одной позиции может ошибиться.
_HOMONYM_ONLY_OVERRIDES = frozenset(
    {_norm_cmp(x) for x in ("Тонали", "Фофана", "Барриос", "Гарсия", "Эрнандез")}
)


def _surname_token(name: str, surname: str | None) -> str:
    sn = (surname or "").strip()
    nm = (name or "").strip()
    if sn and nm and sn.casefold() != nm.casefold():
        return sn
    raw = nm or sn
    parts = raw.split()
    if len(parts) >= 2:
        return parts[-1]
    return raw


def _row_key(name: str, surname: str | None, position: str) -> tuple[str, str]:
    pos = (position or "").strip().upper()
    tok = _surname_token(name, surname)
    return _norm_cmp(tok), pos


def _load_keys(path: str) -> dict[tuple[str, str], list[dict]]:
    out: dict[tuple[str, str], list[dict]] = {}
    if not os.path.isfile(path):
        return out
    conn = sqlite3.connect(path)
    try:
        for table in _TABLES:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if "name" not in cols:
                continue
            has_surname = "surname" in cols
            sel = "name, team, position"
            if has_surname:
                sel = "name, surname, team, position"
            for row in conn.execute(
                f"SELECT id, {sel} FROM {table} WHERE team IS NOT NULL AND TRIM(team) != ''"
            ):
                rid = row[0]
                if has_surname:
                    name, surname, team, pos = row[1], row[2], row[3], row[4]
                else:
                    name, surname, team, pos = row[1], None, row[2], row[3]
                team = (team or "").strip()
                if team.casefold() == "free agent":
                    continue
                k = _row_key(name or "", surname, pos or "")
                out.setdefault(k, []).append(
                    {
                        "id": rid,
                        "table": table,
                        "name": (name or "").strip(),
                        "surname": (surname or "").strip() if surname else "",
                        "team": team,
                    }
                )
    finally:
        conn.close()
    return out


def _load_hints(path: str) -> dict[tuple[str, str], str]:
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out: dict[tuple[str, str], str] = {}
    for k, v in data.items():
        if k.startswith("_") or "|" not in k:
            continue
        left, right = k.split("|", 1)
        fn = (v or "").strip()
        if not fn:
            continue
        out[(_norm_cmp(left), _norm_cmp(right))] = fn
    return out


def _full_name_from_xlsx(
    entries: list[XlsxPlayer], surname_tok: str, position: str, teams: set[str]
) -> str | None:
    st = surname_tok.casefold()
    pos_u = position.upper()
    cands: list[XlsxPlayer] = []
    for e in entries:
        if _norm_cmp(e.surname_label) != _norm_cmp(surname_tok):
            continue
        if (e.position or "").strip().upper() != pos_u:
            continue
        if teams and _norm_cmp(_canonical_xlsx_team(e.team)) not in {
            _norm_cmp(t) for t in teams
        }:
            continue
        cands.append(e)
    if not cands:
        for e in entries:
            if _norm_cmp(e.surname_label) != _norm_cmp(surname_tok):
                continue
            if (e.position or "").strip().upper() != pos_u:
                continue
            cands.append(e)
    if not cands:
        return None
    cands.sort(key=lambda e: int(e.rating or 0), reverse=True)
    e = cands[0]
    fn = (e.first_name or "").strip()
    sn = normalize_player_name_for_db(e.surname_label) or e.surname_label
    if fn:
        return f"{fn} {sn}"
    return sn


def _needs_full_name(name: str, surname: str) -> bool:
    nm = (name or "").strip()
    sn = (surname or "").strip()
    if not nm:
        return False
    if " " in nm and nm.casefold() != sn.casefold():
        return False
    if sn and nm.casefold() == sn.casefold():
        return True
    return " " not in nm


def _full_name_from_rows(rows: list[dict]) -> str | None:
    for r in rows:
        nm = r["name"]
        sn = r["surname"]
        if nm and " " in nm and nm.casefold() != (sn or "").casefold():
            return nm
    for r in rows:
        nm = r["name"]
        if nm and " " in nm:
            return nm
    return None


def _resolve_full_name(
    key: tuple[str, str],
    *,
    rows_s1: list[dict],
    rows_s2: list[dict],
    rows_sync: list[dict],
    xlsx_entries: list[XlsxPlayer],
    hints: dict[tuple[str, str], str],
) -> str | None:
    if key in FULL_NAME_OVERRIDES:
        return FULL_NAME_OVERRIDES[key]
    st, pos = key
    if st in _HOMONYM_ONLY_OVERRIDES:
        return None
    all_rows = rows_s1 + rows_s2 + rows_sync
    teams = {r["team"] for r in all_rows}
    hit = _full_name_from_rows(all_rows)
    if hit:
        return hit
    for r in all_rows:
        sur = _surname_token(r["name"], r["surname"] or None)
        h = hints.get((_norm_cmp(sur), _norm_cmp(r["team"])))
        if h:
            return f"{h} {sur}"
    xlsx_hit = _full_name_from_xlsx(xlsx_entries, st, pos, teams)
    if xlsx_hit:
        return xlsx_hit
    return None


def _cross_season_keys() -> tuple[set[tuple[str, str]], dict]:
    s1 = _load_keys(os.path.join(ROOT, "db", "season_1", "league.db"))
    s2 = _load_keys(os.path.join(ROOT, "db", "season_2", "league.db"))
    sync = _load_keys(os.path.join(ROOT, "db", "league_synced.db"))
    keys = set(s1) & set(s2) & set(sync)
    meta = {k: {"s1": s1[k], "s2": s2[k], "sync": sync[k]} for k in keys}
    return keys, meta


def _apply_to_db(
    path: str,
    label: str,
    keys: set[tuple[str, str]],
    full_names: dict[tuple[str, str], str],
    *,
    apply: bool,
) -> list[str]:
    log: list[str] = []
    if not os.path.isfile(path):
        return log
    conn = sqlite3.connect(path)
    n = 0
    try:
        for table in _TABLES:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if "name" not in cols:
                continue
            has_surname = "surname" in cols
            sel = "id, name, team, position"
            if has_surname:
                sel = "id, name, surname, team, position"
            for row in conn.execute(f"SELECT {sel} FROM {table}"):
                if has_surname:
                    rid, name, surname, team, pos = row
                else:
                    rid, name, surname, team, pos = row[0], row[1], None, row[2], row[3]
                k = _row_key(name or "", surname, pos or "")
                if k not in keys:
                    continue
                if not _needs_full_name(name or "", surname or ""):
                    continue
                full = full_names[k]
                cur = (name or "").strip()
                if cur == full:
                    continue
                log.append(
                    f"{'APPLY' if apply else 'rename'} {label} {table} "
                    f"id={rid} {cur!r} → {full!r} ({team} {pos})"
                )
                if apply:
                    if has_surname:
                        conn.execute(
                            f"UPDATE {table} SET name = ?, surname = NULL WHERE id = ?",
                            (full, rid),
                        )
                    else:
                        conn.execute(
                            f"UPDATE {table} SET name = ? WHERE id = ?",
                            (full, rid),
                        )
                    n += 1
        if apply:
            conn.commit()
    finally:
        conn.close()
    if apply and n:
        log.append(f"  [{label}] записано: {n}")
    return log


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--xlsx", default=os.path.join(ROOT, "db", "names.xlsx"))
    ap.add_argument(
        "--hints",
        default=os.path.join(ROOT, "data", "player_first_name_hints.json"),
    )
    args = ap.parse_args()

    keys, meta = _cross_season_keys()
    hints = _load_hints(args.hints)
    xlsx_entries = load_names_xlsx(args.xlsx)

    full_names: dict[tuple[str, str], str] = {}
    skipped: list[str] = []
    for k in sorted(keys):
        fn = _resolve_full_name(
            k,
            rows_s1=meta[k]["s1"],
            rows_s2=meta[k]["s2"],
            rows_sync=meta[k]["sync"],
            xlsx_entries=xlsx_entries,
            hints=hints,
        )
        if not fn:
            skipped.append(f"{k[1]} / {k[0]}")
            continue
        full_names[k] = fn

    print(f"Ключей (фамилия+поз) в s1+s2+league_synced: {len(keys)}")
    print(f"С полным именем для записи: {len(full_names)}, без имени: {len(skipped)}")

    for k, fn in sorted(full_names.items(), key=lambda x: x[1]):
        if k in FULL_NAME_OVERRIDES or k[0] in (
            _norm_cmp("тонали"),
            _norm_cmp("фофана"),
            _norm_cmp("барриос"),
            _norm_cmp("гарсия"),
            _norm_cmp("эрнандез"),
        ):
            print(f"  {k[1]:<4} {fn}")

    all_log: list[str] = []
    for rel, label in _DB_TARGETS:
        path = os.path.join(ROOT, "db", rel)
        all_log.extend(_apply_to_db(path, label, set(full_names), full_names, apply=args.apply))

    shown = 0
    for line in all_log:
        if "→" in line or "записано" in line:
            print(line)
            shown += 1
            if shown >= 80 and not args.apply:
                print("…")
                break
    if shown >= 80:
        print(f"(показано первые ~80 строк, всего событий {len(all_log)})")

    if skipped[:20]:
        print("\nБез полного имени (первые 20):")
        for s in skipped[:20]:
            print(" ", s)

    if not args.apply:
        print("\nПовторите с --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
