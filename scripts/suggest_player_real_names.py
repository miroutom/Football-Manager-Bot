#!/usr/bin/env python3
"""
Предложить разбиение имени/фамилии для игроков сезона.

Не использует реальные составы клубов (в БД игроки могут быть не в тех командах, что в жизни).
Сначала разбирает уже записанные полные имена; затем (опционально) Wikidata по фамилии + стране.

Формат вывода::

  Арсенал
  Хаверц ФРВ 85 Германия -> Кай Хаверц
  Коло Муани ЛФА 84 Франция -> Рандал Коло Муани

  python3 scripts/suggest_player_real_names.py --season 2
  python3 scripts/suggest_player_real_names.py --season 2 --no-lookup
  python3 scripts/suggest_player_real_names.py --season 2 --apply
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.migrate_player_surname import migrate_all_player_surname_columns
from utils.player_name_propose import (
    WikidataNameLookup,
    format_player_line,
    format_proposed_full,
    is_already_split,
    load_manual_hints,
    manual_hint_first,
    names_need_update,
    propose_split_from_fields,
)
from utils.player_names import player_surname

_ALL = (
    (Forward, "forwards"),
    (Midfielder, "midfielders"),
    (Defender, "defenders"),
    (Goalkeeper, "goalkeepers"),
)


def _collect_rows(session, *, team_filter: str, skip_free: bool, limit: int | None):
    out: list[tuple[str, str, Any]] = []
    for Cls, tbl in _ALL:
        for r in session.query(Cls).order_by(Cls.team, Cls.id).all():
            team = (getattr(r, "team", None) or "").strip()
            if not team:
                continue
            if skip_free and team.lower() == "free agent":
                continue
            if team_filter and team.lower() != team_filter.lower():
                continue
            out.append((team, tbl, r))
            if limit is not None and len(out) >= limit:
                return out
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2)
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Записать в БД (по умолчанию только просмотр)",
    )
    ap.add_argument(
        "--no-lookup",
        action="store_true",
        help="Только разбор уже записанных полных имён, без Wikidata",
    )
    ap.add_argument("--team", default="", help="Фильтр по одной команде")
    ap.add_argument("--limit", type=int, default=0, help="Макс. строк (0 = все)")
    ap.add_argument(
        "--hints",
        default=os.path.join(ROOT, "data", "player_first_name_hints.json"),
        help="Ручные подсказки: фамилия|страна или table:id → имя",
    )
    ap.add_argument(
        "--cache",
        default=os.path.join(ROOT, "data", "wikidata_player_name_cache.json"),
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="Показать и строки без изменений (помечены «=»)",
    )
    args = ap.parse_args()

    dry_run = not args.apply
    if dry_run:
        print("Режим просмотра (без записи в БД). Для применения: --apply\n")

    migrate_all_player_surname_columns()

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    path = os.path.join(ROOT, "db", f"season_{args.season}", "league.db")
    if not os.path.isfile(path):
        print(f"Нет {path}")
        sys.exit(1)

    hints = load_manual_hints(args.hints)
    lookup = None if args.no_lookup else WikidataNameLookup(args.cache)

    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    lim = args.limit if args.limit > 0 else None
    rows = _collect_rows(
        session,
        team_filter=args.team.strip(),
        skip_free=True,
        limit=lim,
    )

    by_team: dict[str, list[tuple[str, Any, str, str, str]]] = {}
    stats = {
        "split": 0,
        "lookup": 0,
        "manual": 0,
        "ok_skip": 0,
        "multi": 0,
        "miss": 0,
    }

    try:
        for team, tbl, r in rows:
            first, surname, kind, note = _propose_for_row(
                r, tbl, hints, lookup, no_lookup=args.no_lookup
            )
            if kind == "skip":
                stats["ok_skip"] += 1
                if args.all:
                    sn = player_surname(r)
                    by_team.setdefault(team, []).append(
                        (tbl, r, sn, sn, "=")
                    )
                continue
            if kind == "multi":
                stats["multi"] += 1
            elif kind == "miss":
                stats["miss"] += 1
            elif kind == "split":
                stats["split"] += 1
            elif kind == "lookup":
                stats["lookup"] += 1
            elif kind == "manual":
                stats["manual"] += 1

            line_left = format_player_line(r)
            if kind == "multi":
                cands = note
                right = " | ".join(format_proposed_full(a, b) for a, b in cands)
                right = f"? ({right})"
            elif first:
                right = format_proposed_full(first, surname)
            else:
                right = note or "—"

            by_team.setdefault(team, []).append((tbl, r, line_left, right, kind))

            if args.apply and first and kind in ("split", "lookup", "manual"):
                r.name = first
                r.surname = surname

        if args.apply:
            session.commit()
            print("Изменения записаны в БД.\n")
        if lookup is not None:
            lookup.save_cache()

        for team in sorted(by_team.keys()):
            print(team)
            for _tbl, _r, left, right, kind in by_team[team]:
                mark = ""
                if kind == "=":
                    print(f"  {left}  =")
                    continue
                print(f"  {left} -> {right}")
            print()

        print(
            "Итого: "
            f"разбор {stats['split']}, "
            f"wikidata {stats['lookup']}, "
            f"ручные подсказки {stats['manual']}, "
            f"без изменений {stats['ok_skip']}, "
            f"неоднозначно {stats['multi']}, "
            f"не найдено {stats['miss']}."
        )
        if args.no_lookup:
            print("(Wikidata отключён: --no-lookup)")
    finally:
        session.close()


def _propose_for_row(r, table: str, hints: dict, lookup: WikidataNameLookup | None, *, no_lookup: bool):
    sn = player_surname(r)
    nation = (getattr(r, "nation", None) or "").strip()

    split = propose_split_from_fields(r)
    if split:
        first, surname = split
        if not names_need_update(r, first, surname):
            return "", "", "skip", ""
        return first, surname, "split", ""

    if is_already_split(r):
        return "", "", "skip", ""

    hint_first = manual_hint_first(hints, r, table, sn, nation)
    if hint_first:
        first, surname = hint_first, sn
        if not names_need_update(r, first, surname):
            return "", "", "skip", ""
        return first, surname, "manual", ""

    if no_lookup or lookup is None:
        return "", "", "miss", "нет подсказки (добавь в hints или включи Wikidata)"

    result = lookup.lookup(sn, nation)
    if result is None:
        return "", "", "miss", "не найдено в Wikidata"
    if isinstance(result, list):
        return "", sn, "multi", result

    first, surname = result
    if not names_need_update(r, first, surname):
        return "", "", "skip", ""
    return first, surname, "lookup", ""


if __name__ == "__main__":
    main()
