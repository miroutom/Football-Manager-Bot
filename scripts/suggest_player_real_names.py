#!/usr/bin/env python3
"""
Предложить разбиение имени/фамилии для игроков сезона (или всех архивов).

Не использует реальные составы клубов. Имя: ru.wikipedia (``/wiki/Фамилия`` → «Фамилия, Имя»),
затем Wikidata по фамилии + стране. Составные фамилии: пробел, ``_``, ``-``.

После ``--apply`` для всех сезонов пересобери накопительные БД::

  python3 -c "from utils.cumulative_db import rebuild_all_time_databases_from_season_archives; print(rebuild_all_time_databases_from_season_archives())"

Формат вывода::

  === Сезон 1 ===
  Арсенал
  Хаверц ФРВ 85 Германия -> Кай Хаверц

  python3 scripts/suggest_player_real_names.py --season 2
  python3 scripts/suggest_player_real_names.py --all-seasons
  python3 scripts/suggest_player_real_names.py --all-seasons --apply
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
from utils.cumulative_db import list_season_archives_with_db
from utils.migrate_player_surname import (
    migrate_all_player_surname_columns,
    prepare_season_archive_schema,
)
from utils.player_name_propose import (
    PlayerFirstNameLookup,
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


def _propose_for_row(
    r, table: str, hints: dict, lookup: PlayerFirstNameLookup | None, *, no_lookup: bool
):
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
        return "", "", "miss", "нет подсказки (добавь в hints или убери --no-lookup)"

    result = lookup.lookup(sn, nation)
    if result is None:
        return "", "", "miss", "не найдено (Wikipedia / Wikidata)"
    if isinstance(result, list):
        return "", sn, "multi", result

    first, surname = result
    if not names_need_update(r, first, surname):
        return "", "", "skip", ""
    return first, surname, "lookup", ""


def _run_season(
    season_num: int,
    *,
    apply: bool,
    no_lookup: bool,
    team_filter: str,
    limit: int | None,
    hints: dict,
    lookup: PlayerFirstNameLookup | None,
    show_unchanged: bool,
) -> dict[str, int]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    path = os.path.join(ROOT, "db", f"season_{season_num}", "league.db")
    if not os.path.isfile(path):
        print(f"Пропуск сезона {season_num}: нет {path}\n")
        return {}

    prepare_season_archive_schema(season_num)

    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    stats = {
        "split": 0,
        "lookup": 0,
        "manual": 0,
        "ok_skip": 0,
        "multi": 0,
        "miss": 0,
    }
    by_team: dict[str, list[tuple]] = {}

    try:
        rows = _collect_rows(
            session,
            team_filter=team_filter,
            skip_free=True,
            limit=limit,
        )
        for team, tbl, r in rows:
            first, surname, kind, note = _propose_for_row(
                r, tbl, hints, lookup, no_lookup=no_lookup
            )
            if kind == "skip":
                stats["ok_skip"] += 1
                if show_unchanged:
                    by_team.setdefault(team, []).append(
                        (format_player_line(r), "=", kind)
                    )
                continue
            stats[kind] = stats.get(kind, 0) + 1

            line_left = format_player_line(r)
            if kind == "multi":
                cands = note
                right = " | ".join(format_proposed_full(a, b) for a, b in cands)
                right = f"? ({right})"
            elif first:
                right = format_proposed_full(first, surname)
            else:
                right = note or "—"

            by_team.setdefault(team, []).append((line_left, right, kind))

            if apply and first and kind in ("split", "lookup", "manual"):
                r.name = first
                r.surname = surname

        if apply:
            session.commit()
    finally:
        session.close()
        engine.dispose()

    print(f"=== Сезон {season_num} ===")
    if apply:
        print("(записано в db/season_{}/league.db)\n".format(season_num))
    for team in sorted(by_team.keys()):
        print(team)
        for left, right, kind in by_team[team]:
            if kind == "=":
                print(f"  {left}  =")
            else:
                print(f"  {left} -> {right}")
        print()

    print(
        f"Сезон {season_num}: разбор {stats.get('split', 0)}, "
        f"wikidata {stats.get('lookup', 0)}, "
        f"ручные {stats.get('manual', 0)}, "
        f"без изменений {stats.get('ok_skip', 0)}, "
        f"неоднозначно {stats.get('multi', 0)}, "
        f"не найдено {stats.get('miss', 0)}."
    )
    print()
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=0, help="Один сезон (0 = не задан)")
    ap.add_argument(
        "--all-seasons",
        action="store_true",
        help="Все папки db/season_N/ с league.db (1, 2, …)",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Записать в БД (по умолчанию только просмотр)",
    )
    ap.add_argument(
        "--no-lookup",
        action="store_true",
        help="Только разбор полных имён + hints, без Wikipedia/Wikidata",
    )
    ap.add_argument("--team", default="", help="Фильтр по одной команде")
    ap.add_argument("--limit", type=int, default=0, help="Макс. строк на сезон (0 = все)")
    ap.add_argument(
        "--hints",
        default=os.path.join(ROOT, "data", "player_first_name_hints.json"),
    )
    ap.add_argument(
        "--cache",
        default=os.path.join(ROOT, "data", "wikidata_player_name_cache.json"),
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="Показать строки без изменений (=)",
    )
    args = ap.parse_args()

    if args.all_seasons:
        seasons = list_season_archives_with_db()
    elif args.season > 0:
        seasons = [args.season]
    else:
        seasons = [2]

    if not seasons:
        print("Нет архивов season_N с league.db")
        sys.exit(1)

    if not args.apply:
        print("Режим просмотра. Для записи: --apply\n")

    migrate_all_player_surname_columns()

    hints = load_manual_hints(args.hints)
    lookup = None if args.no_lookup else PlayerFirstNameLookup(args.cache)
    lim = args.limit if args.limit > 0 else None
    team = args.team.strip()

    for sn in seasons:
        _run_season(
            sn,
            apply=args.apply,
            no_lookup=args.no_lookup,
            team_filter=team,
            limit=lim,
            hints=hints,
            lookup=lookup,
            show_unchanged=args.all,
        )

    if lookup is not None:
        lookup.save_cache()

    if args.apply and len(seasons) > 0:
        print(
            "Дальше пересобери *_synced.db:\n"
            "  python3 -c \"from utils.cumulative_db import "
            "rebuild_all_time_databases_from_season_archives; "
            "print(rebuild_all_time_databases_from_season_archives())\""
        )
    if args.no_lookup:
        print("(Поиск имён отключён: --no-lookup)")


if __name__ == "__main__":
    main()
