#!/usr/bin/env python3
"""
Импорт имён из ``db/names.xlsx`` (блоки по командам).

Сезон 2: сопоставление по клубу + позиция + рейтинг + нация (+ подпись в БД).
Сезон 1: фамилия + нация (позиция/рейтинг/клуб из xlsx — только для уточнения).

  python3 scripts/import_player_names_xlsx.py --season 2
  python3 scripts/import_player_names_xlsx.py --season 2 --apply
  python3 scripts/import_player_names_xlsx.py --season 1
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.migrate_player_surname import prepare_season_archive_schema
from utils.player_names import is_empty_first_name_value
from utils.player_transfer import _norm_cmp, normalize_player_name_for_db

_ALL = (
    (Forward, "forwards"),
    (Midfielder, "midfielders"),
    (Defender, "defenders"),
    (Goalkeeper, "goalkeepers"),
)


@dataclass
class XlsxPlayer:
    team: str
    surname_label: str  # колонка surname в xlsx → целевая фамилия
    position: str
    rating: int
    nation: str
    first_name: str  # колонка name


def _first_name_from_cell(raw: str) -> str:
    s = normalize_player_name_for_db(raw or "")
    if is_empty_first_name_value(s):
        return ""
    return s


# Синонимы национальности (xlsx ↔ БД)
_NATION_CANON: dict[str, str] = {
    "босния и герцеговина": "босния",
    "босния и герц": "босния",
    "юж. корея": "южная корея",
    "южная корея": "южная корея",
    "кот-д'ивуар": "кот д ивуар",
    "кот-д ивуар": "кот д ивуар",
    "др конго": "др конго",
    "конго": "др конго",
    "оаэ": "оаэ",
    "сауд. аравия": "саудовская аравия",
    "саудовская аравия": "саудовская аравия",
    "англия": "англия",
    "англ": "англия",
}


def _norm_nat(s: str) -> str:
    n = (s or "").strip().casefold()
    return _NATION_CANON.get(n, n)


def _db_listing_label(row) -> str:
    """Как в list_team_roster — для поиска строки до импорта."""
    fn = (getattr(row, "name", None) or "").strip()
    sn = (getattr(row, "surname", None) or "").strip()
    if fn and sn and _norm_cmp(fn) != _norm_cmp(sn):
        if _norm_cmp(sn) in _norm_cmp(fn) and len(fn.split()) > len(sn.split()):
            return fn
        return sn or fn
    return sn or fn


def _label_matches_db(xlsx_surname: str, row) -> bool:
    """Совпадение подписи в xlsx с тем, что сейчас в БД."""
    want = _norm_cmp(xlsx_surname)
    if not want:
        return True
    labels = {
        _norm_cmp(_db_listing_label(row)),
        _norm_cmp(getattr(row, "name", None) or ""),
        _norm_cmp(getattr(row, "surname", None) or ""),
    }
    fn = (getattr(row, "name", None) or "").strip()
    sn = (getattr(row, "surname", None) or "").strip()
    if fn and sn:
        labels.add(_norm_cmp(f"{fn} {sn}"))
    return want in labels


def load_names_xlsx(path: str) -> list[XlsxPlayer]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    out: list[XlsxPlayer] = []
    team = ""
    try:
        for row in ws.iter_rows(values_only=True):
            if not row or all(c is None or str(c).strip() == "" for c in row):
                continue
            c0 = row[0]
            c1 = row[1] if len(row) > 1 else None
            if c0 is None:
                continue
            s0 = str(c0).strip()
            if c1 is None or str(c1).strip() == "":
                if s0.lower() != "surname":
                    team = s0
                continue
            if str(c1).strip().lower() == "position":
                continue
            pos = str(c1).strip().upper()
            try:
                rating = int(row[2]) if row[2] is not None else 0
            except (TypeError, ValueError):
                rating = 0
            nation = str(row[3]).strip() if len(row) > 3 and row[3] is not None else ""
            first_raw = row[4] if len(row) > 4 else ""
            first = _first_name_from_cell(str(first_raw) if first_raw is not None else "")
            sn = normalize_player_name_for_db(s0) or s0
            if not sn or not team:
                continue
            out.append(
                XlsxPlayer(
                    team=team,
                    surname_label=sn,
                    position=pos,
                    rating=rating,
                    nation=nation,
                    first_name=first,
                )
            )
    finally:
        wb.close()
    return out


def _iter_rows(session, team: str | None, *, include_left: bool):
    for Cls, tbl in _ALL:
        for r in session.query(Cls).all():
            if not include_left and bool(getattr(r, "left_team", False)):
                continue
            t = (getattr(r, "team", None) or "").strip()
            if not t or t.casefold() == "free agent":
                continue
            if team is not None and _norm_cmp(t) != _norm_cmp(team):
                continue
            yield tbl, r


def _match_row(entry: XlsxPlayer, row, *, require_team: bool) -> bool:
    if require_team and _norm_cmp(row.team or "") != _norm_cmp(entry.team):
        return False
    if (getattr(row, "position", None) or "").strip().upper() != entry.position:
        return False
    if int(getattr(row, "overall", 0) or 0) != entry.rating:
        return False
    if _norm_nat(getattr(row, "nation", None) or "") != _norm_nat(entry.nation):
        return False
    return True


def _candidates_surname_nation(session, entry: XlsxPlayer) -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    for tbl, r in _iter_rows(session, None, include_left=False):
        if _norm_nat(getattr(r, "nation", None) or "") != _norm_nat(entry.nation):
            continue
        if not _label_matches_db(entry.surname_label, r):
            continue
        out.append((tbl, r))
    return out


def _pick_one(
    cands: list[tuple[str, object]], entry: XlsxPlayer, *, prefer_team: bool
) -> tuple[tuple[str, object] | None, str | None]:
    if not cands:
        return None, "не найден"
    if len(cands) == 1:
        return cands[0], None

    def _filt(rows: list[tuple[str, object]], pred) -> list[tuple[str, object]]:
        x = [c for c in rows if pred(c[1])]
        return x if x else rows

    pool = list(cands)
    pool = _filt(
        pool,
        lambda r: (getattr(r, "position", None) or "").strip().upper() == entry.position,
    )
    pool = _filt(pool, lambda r: int(getattr(r, "overall", 0) or 0) == entry.rating)
    if prefer_team:
        pool = _filt(
            pool, lambda r: _norm_cmp(r.team or "") == _norm_cmp(entry.team)
        )
    if len(pool) == 1:
        return pool[0], None
    clubs = sorted({(c[1].team or "").strip() for c in pool if (c[1].team or "").strip()})
    extra = f" ({', '.join(clubs[:4])}{'…' if len(clubs) > 4 else ''})" if clubs else ""
    return None, f"неоднозначно: {len(pool)}{extra}"


def find_db_row(session, entry: XlsxPlayer, *, require_team: bool):
    if not require_team:
        cands = _candidates_surname_nation(session, entry)
        return _pick_one(cands, entry, prefer_team=True)

    strict: list[tuple[str, object]] = []
    loose: list[tuple[str, object]] = []
    for tbl, r in _iter_rows(session, entry.team, include_left=False):
        if not _match_row(entry, r, require_team=True):
            continue
        loose.append((tbl, r))
        if _label_matches_db(entry.surname_label, r):
            strict.append((tbl, r))
    if len(strict) == 1:
        return strict[0], None
    if len(strict) > 1:
        return _pick_one(strict, entry, prefer_team=False)
    if len(loose) == 1:
        return loose[0], None
    if len(loose) > 1:
        return _pick_one(loose, entry, prefer_team=False)
    return None, "не найден"


def apply_names(
    session,
    entries: list[XlsxPlayer],
    *,
    season: int,
    require_team: bool,
    do_apply: bool,
    problems_only: bool = False,
) -> dict[str, int]:
    stats = {"ok": 0, "skip": 0, "miss": 0, "ambig": 0, "team_miss": 0}
    by_team: dict[str, list[str]] = {}
    problems: list[tuple[str, str]] = []

    for e in entries:
        hit, err = find_db_row(session, e, require_team=require_team)
        if hit is None:
            stats["ambig" if err and "неоднознач" in err else "miss"] += 1
            line = f"  ? {e.surname_label} {e.position} {e.rating} {e.nation} — {err}"
            problems.append((e.team, line.strip()))
            by_team.setdefault(e.team, []).append(line)
            continue

        tbl, r = hit
        fn = e.first_name
        sn = e.surname_label
        old_fn = (getattr(r, "name", None) or "").strip()
        old_sn = (getattr(r, "surname", None) or "").strip()
        if old_fn == fn and old_sn == sn:
            stats["skip"] += 1
            continue

        stats["ok"] += 1
        if problems_only:
            continue
        club = (r.team or e.team).strip()
        line = (
            f"  {tbl} id={r.id} {club}: "
            f"«{old_fn or '—'} / {old_sn or '—'}» → «{fn or '—'} / {sn}»"
        )
        by_team.setdefault(e.team if require_team else club, []).append(line)
        if do_apply:
            r.name = fn
            r.surname = sn

    if not problems_only:
        for team in sorted(by_team.keys()):
            print(team)
            for line in by_team[team]:
                print(line)
            print()

    if problems:
        print("=" * 60)
        print("НЕ СОПОСТАВЛЕНО (из xlsx → нет строки в БД сезона)")
        print("=" * 60)
        cur = ""
        for team, line in sorted(problems, key=lambda x: (x[0].casefold(), x[1])):
            if team != cur:
                print(f"\n{team}")
                cur = team
            print(f"  {line}")

    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--xlsx",
        default=os.path.join(ROOT, "db", "names.xlsx"),
        help="Путь к Excel",
    )
    ap.add_argument("--season", type=int, default=2)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--problems-only",
        action="store_true",
        help="Только пропуски (?): не найден / неоднозначно",
    )
    args = ap.parse_args()

    if not os.path.isfile(args.xlsx):
        print(f"Нет файла: {args.xlsx}")
        sys.exit(1)

    entries = load_names_xlsx(args.xlsx)
    if not entries:
        print("В xlsx нет строк игроков.")
        sys.exit(1)

    require_team = args.season >= 2
    mode = f"сезон {args.season}" + (
        " + клуб + позиция + рейтинг" if require_team else " — фамилия + нация"
    )
    print(f"{'Запись' if args.apply else 'Просмотр'} ({mode}), строк в файле: {len(entries)}\n")

    prepare_season_archive_schema(args.season)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    path = os.path.join(ROOT, "db", f"season_{args.season}", "league.db")
    if not os.path.isfile(path):
        print(f"Нет {path}")
        sys.exit(1)

    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        stats = apply_names(
            session,
            entries,
            season=args.season,
            require_team=require_team,
            do_apply=args.apply,
            problems_only=args.problems_only,
        )
        if args.apply:
            session.commit()
            if args.season == 2:
                from utils.common_db import rebuild_common_database

                rebuild_common_database()
                print("common.db пересобран (активный сезон).")
        print(
            f"Итого: обновить {stats['ok']}, без изменений {stats['skip']}, "
            f"не найдено {stats['miss']}, неоднозначно {stats['ambig']}."
        )
        if not args.apply:
            print("\nДля записи добавь --apply")
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    main()
