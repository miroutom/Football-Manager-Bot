#!/usr/bin/env python3
"""
Удалить игроков из ``db/season_2/league.db`` (и при --cl из champions_league.db).

  python3 scripts/remove_season2_roster_players.py
  python3 scripts/remove_season2_roster_players.py --apply
  python3 scripts/remove_season2_roster_players.py --apply --cl
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
from utils.migrate_player_surname import prepare_season_archive_schema
from utils.player_transfer import _norm_cmp

_ALL = (Forward, Midfielder, Defender, Goalkeeper)

# (клуб в БД или None = любой, подстрока в name/surname, позиция, *альт.позиции)
def _r(
    team: str | None, name: str, pos: str, *alt: str
) -> tuple[str | None, str, str, tuple[str, ...]]:
    return (team, name, pos, alt)


_REMOVALS: list[tuple[str | None, str, str, tuple[str, ...]]] = [
    _r("Дортмунд", "Бенсебаини", "ЛЗ"),
    _r("Барселона", "Ромеу", "ЦОП"),
    _r("Барселона", "Алонсо", "ЛЗ"),
    _r("Барселона", "Ли Кан", "ЛФА"),
    _r("Барселона", "Пенья", "ВРТ"),
    _r("Барселона", "Фалл", "ЦЗ"),
    _r("Атлетико", "Икарди", "ФРВ"),
    _r("Атлетико", "Аспиликуэта", "ПЗ"),
    _r("Хоффенхайм", "Бериша", "ФРВ"),
    _r("Хоффенхайм", "Кадерабек", "ПЗ"),
    _r("Бавария", "Мактоминей", "ЦОП"),
    _r("Бавария", "Ульрих", "ВРТ"),
    _r("Бавария", "Перец", "ВРТ"),
    _r("Интер", "Аугусто", "ЛП", "ЛФА"),
    _r("Милан", "Крунич", "ЦП"),
    _r("Милан", "Йович", "ФРВ"),
    _r("Арсенал", "Виейра", "ЦАП"),
    _r("Арсенал", "Элнени", "ЦП"),
    _r("Лейпциг", "Кампль", "ЦП"),
    _r("Лейпциг", "Паульсен", "ФРВ"),
    _r("Боруссия М", "Беренгер", "ЛФА"),
    _r("Боруссия М", "Омлин", "ВРТ"),
    _r("Боруссия М", "Янтшке", "ЦЗ"),
    _r("Байер", "Хложек", "ФРВ"),
    _r("Байер", "Бонифасе", "ФРВ"),
    _r("Байер", "Коварь", "ВРТ"),
    _r("Ювентус", "Милик", "ФРВ"),
    _r("Ювентус", "Де Шильо", "ПЗ"),
    _r("Ювентус", "Влахович", "ФРВ"),
    _r("Ювентус", "Пинсольо", "ВРТ"),
    _r("Рома", "Абрахам", "ФРВ"),
    _r("Рома", "Белотти", "ФРВ"),
    _r("Рома", "Лльоренте", "ЦЗ"),
    _r("Рома", "Ауар", "ЦАП"),
    _r("Рома", "Челик", "ПЗ"),
    _r("Рома", "Кумбулла", "ЦЗ"),
    _r("Атлетик", "Весга", "ЦП"),
    _r("Атлетик", "Берчиче", "ЛЗ"),
    _r("Атлетик", "Йоро", "ЦЗ"),
    _r("Атлетик", "Рауль", "ФРВ"),
    _r("Атлетик", "Гарсия", "ЦП"),
    _r("Мю", "Линделёф", "ЦЗ"),
    _r("Мю", "Маунт", "ЦАП"),
    # остатки на Free Agent (клуб уже снят)
    _r(None, "Бериша", "ФРВ"),
    _r(None, "Бонифасе", "ФРВ"),
    _r(None, "Мактоминей", "ЦОП"),
    _r(None, "Ульрих", "ВРТ"),
    _r(None, "Перец", "ВРТ"),
    _r(None, "Икарди", "ФРВ"),
    _r(None, "Аспиликуэта", "ПЗ"),
    _r(None, "Ли Кан", "ЛФА"),
]


def _name_matches(row, needle: str) -> bool:
    needle_n = _norm_cmp(needle)
    for part in (
        getattr(row, "name", None) or "",
        getattr(row, "surname", None) or "",
    ):
        p = (part or "").strip()
        if not p:
            continue
        pn = _norm_cmp(p)
        if pn == needle_n or needle_n in pn:
            return True
    return False


def _find_rows(
    session,
    team: str | None,
    name_needle: str,
    position: str,
    *,
    positions_alt: tuple[str, ...] = (),
) -> list[tuple[str, object]]:
    pos_set = {(position or "").strip().upper()}
    pos_set.update(p.strip().upper() for p in positions_alt if p)
    out: list[tuple[str, object]] = []
    for Cls in _ALL:
        tbl = Cls.__tablename__
        for r in session.query(Cls).all():
            if team is not None and _norm_cmp(r.team or "") != _norm_cmp(team):
                continue
            if (r.position or "").strip().upper() not in pos_set:
                continue
            if not _name_matches(r, name_needle):
                continue
            out.append((tbl, r))
    return out


def _delete_from_db(db_path: str, *, do_apply: bool) -> tuple[int, list[str]]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    if not os.path.isfile(db_path):
        return 0, [f"нет файла {db_path}"]

    prepare_season_archive_schema(2)
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    deleted = 0
    lines: list[str] = []
    seen: set[tuple[str, int]] = set()
    try:
        for team, name, pos, alt in _REMOVALS:
            hits = _find_rows(session, team, name, pos, positions_alt=alt)
            if not hits and team == "Атлетик" and name == "Рауль":
                hits = [
                    h
                    for h in _find_rows(session, team, "Гарсия", pos, positions_alt=alt)
                    if "рауль" in _norm_cmp(getattr(h[1], "name", "") or "")
                ]
            if not hits and team == "Атлетик" and name == "Гарсия":
                hits = [
                    h
                    for h in _find_rows(session, team, "Гарсия", pos, positions_alt=alt)
                    if "рауль" not in _norm_cmp(getattr(h[1], "name", "") or "")
                    and "даниэль" in _norm_cmp(getattr(h[1], "name", "") or "")
                ]
            if not hits:
                lines.append(f"  ? {team} {name} {pos} — не найден")
                continue
            for tbl, r in hits:
                key = (tbl, int(r.id))
                if key in seen:
                    continue
                seen.add(key)
                nm = (getattr(r, "name", None) or "").strip()
                sn = (getattr(r, "surname", None) or "").strip()
                lines.append(
                    f"  {tbl} id={r.id} {team}: {nm} / {sn} · {r.position} {r.overall}"
                )
                if do_apply:
                    session.delete(r)
                    deleted += 1
        if do_apply:
            session.commit()
    finally:
        session.close()
        engine.dispose()
    return deleted, lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--cl", action="store_true", help="Также champions_league.db")
    args = ap.parse_args()

    paths = [os.path.join(ROOT, "db", "season_2", "league.db")]
    if args.cl:
        paths.append(os.path.join(ROOT, "db", "season_2", "champions_league.db"))

    total = 0
    found = 0
    for path in paths:
        print(os.path.basename(path))
        n, lines = _delete_from_db(path, do_apply=args.apply)
        for ln in lines:
            print(ln)
            if not ln.strip().startswith("?"):
                found += 1
        print()
        total += n

    if args.apply:
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
        print(f"Удалено строк: {total}. common.db пересобран.")
    else:
        print(f"(dry-run) Найдено к удалению: {found}. Для записи: --apply")


if __name__ == "__main__":
    main()
