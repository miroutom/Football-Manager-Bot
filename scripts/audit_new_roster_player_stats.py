#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Показать полевую статистику игроков из списка «новых в заявке» (season 2).

  python3 scripts/audit_new_roster_player_stats.py
  python3 scripts/audit_new_roster_player_stats.py --cl
  python3 scripts/audit_new_roster_player_stats.py --apply   # обнулить стату (после просмотра)

По умолчанию — dry-run (только вывод). Строки с ненулевой статой помечены «⚠».
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
from utils.player_identity import row_stats_snapshot
from utils.player_transfer import _norm_cmp
from utils.transfer_input import _team_name_as_in_db

_ALL = (Forward, Midfielder, Defender, Goalkeeper)

_STAT_KEYS = (
    "matches",
    "goals",
    "assists",
    "ga",
    "clean_sheets",
    "missed_goals",
    "trophies",
    "golden_balls",
    "golden_boots",
    "golden_gloves",
    "golden_boys",
    "yellow_cards",
    "red_cards",
)


def _r(team: str, name: str, pos: str) -> tuple[str, str, str]:
    return (team.strip(), name.strip(), pos.strip().upper())


# (клуб, имя, позиция) — заявки из чата
_CHECKS: list[tuple[str, str, str]] = [
    _r("Наполи", "Кинтеро", "ЦАП"),
    _r("Наполи", "Круз", "ЦП"),
    _r("Наполи", "Энрике", "ЦП"),
    _r("Наполи", "Маммана", "ЦЗ"),
    _r("Лацио", "Машадо", "ЛЗ"),
    _r("Лацио", "Монтиэль", "ПЗ"),
    _r("Лацио", "Станчиу", "ЦП"),
    _r("Лацио", "Райкович", "ВРТ"),
    _r("Жирона", "Марчесин", "ВРТ"),
    _r("Жирона", "Сотока", "ФРВ"),
    _r("Жирона", "Брабек", "ЦЗ"),
    _r("Жирона", "Сучич", "ЦАП"),
    _r("Жирона", "Батурина", "ЦП"),
    _r("Жирона", "Ангуло", "ЦЗ"),
    _r("Жирона", "Комер", "ЦЗ"),
    _r("Локомотив", "Фабиански", "ВРТ"),
    _r("Локомотив", "Теате", "ЦЗ"),
    _r("Локомотив", "Диатта", "ПП"),
    _r("Локомотив", "Франковски", "ПЗ"),
    _r("Локомотив", "Мартинш", "ПП"),
    _r("Локомотив", "Капрари", "ФРВ"),
    _r("Локомотив", "Минамино", "ФРВ"),
    _r("Локомотив", "Гедеш", "ЛФА"),
    _r("Локомотив", "Локо", "ЛЗ"),
    _r("Урал", "Гуе", "ЦП"),
    _r("Урал", "Саванье", "ЦАП"),
    _r("Урал", "Мунетси", "ЦП"),
    _r("Урал", "Гиго", "ЦЗ"),
    _r("Урал", "Лападула", "ФРВ"),
    _r("Урал", "Ареоля", "ВРТ"),
    _r("Урал", "Лафонт", "ВРТ"),
    _r("Крылья Советов", "Гуаита", "ВРТ"),
    _r("Крылья Советов", "Эдуард", "ФРВ"),
    _r("Крылья Советов", "Тарковски", "ЦЗ"),
    _r("Крылья Советов", "Калимуендо", "ФРВ"),
    _r("Крылья Советов", "Дауд", "ЦП"),
    _r("Крылья Советов", "Какерет", "ЦП"),
    _r("Зенит", "Паласиос", "ПФА"),
    _r("Зенит", "Градит", "ЦЗ"),
    _r("Зенит", "Бовен", "ПФА"),
    _r("Зенит", "Эмболо", "ФРВ"),
    _r("Зенит", "Сельс", "ВРТ"),
    _r("Цска", "Вебстер", "ЦЗ"),
    _r("Цска", "Сако", "ПЗ"),
    _r("Цска", "Манданда", "ВРТ"),
    _r("Цска", "Де Томас", "ФРВ"),
    _r("Цска", "Кайо Энрике", "ЛЗ"),
    _r("Цска", "Витинья", "ФРВ"),
    _r("Краснодар", "Жуниор", "ПФА"),
    _r("Краснодар", "Верету", "ЦП"),
    _r("Краснодар", "Умтити", "ЦЗ"),
    _r("Краснодар", "Теума", "ЦП"),
    _r("Краснодар", "Ляказет", "ФРВ"),
    _r("Краснодар", "Лопез", "ВРТ"),
    _r("Краснодар", "Милла", "ЦП"),
    _r("Краснодар", "Мата", "ПЗ"),
    _r("Аталанта", "Вахи", "ФРВ"),
    _r("Аталанта", "Мбемба", "ЦЗ"),
    _r("Аталанта", "Буригард", "ЦП"),
    _r("Аталанта", "Джало", "ЦЗ"),
    _r("Аталанта", "Хендерсон", "ВРТ"),
    _r("Фиорентина", "Зума", "ЦЗ"),
    _r("Фиорентина", "Са", "ВРТ"),
    _r("Фиорентина", "Садик", "ФРВ"),
    _r("Фиорентина", "Уналь", "ФРВ"),
    _r("Фиорентина", "Джене", "ЦЗ"),
    _r("Фиорентина", "Ворд-Прауз", "ЦП"),
    _r("Фиорентина", "Нуньез", "ЦЗ"),
    _r("Динамо", "Альваро Гарсия", "ЛФА"),
    _r("Динамо", "Антонио", "ФРВ"),
    _r("Динамо", "Салемайкерс", "ПФА"),
    _r("Динамо", "Сангаре", "ЦОП"),
    _r("Динамо", "Альварез", "ЦЗ"),
    _r("Динамо", "Хенри", "ЛЗ"),
    _r("Спартак", "Бето", "ФРВ"),
    _r("Спартак", "Фуллкруг", "ФРВ"),
    _r("Спартак", "Данк", "ЦЗ"),
    _r("Спартак", "Митома", "ЛФА"),
    _r("Спартак", "Ми", "ЦЗ"),
    _r("Спартак", "Нандез", "ПП"),
    _r("Спартак", "Маффео", "ПЗ"),
    _r("Вольфсбург", "Пош", "ПЗ"),
    _r("Вольфсбург", "Холс", "ЦЗ"),
    _r("Вольфсбург", "Ромариньо", "ФРВ"),
    _r("Вольфсбург", "Вега", "ЛФА"),
    _r("Вольфсбург", "Ливай Гарсия", "ФРВ"),
    _r("Вольфсбург", "Буфаль", "ФРВ"),
    _r("Вольфсбург", "Оздоев", "ЦП"),
    _r("Дортмунд", "Галларно", "ЛЗ"),
    _r("Дортмунд", "Шарахили", "ЦЗ"),
    _r("Дортмунд", "Влаходимос", "ВРТ"),
    _r("Барселона", "Тавареш", "ЛЗ"),
    _r("Барселона", "Дорли", "ЦП"),
    _r("Барселона", "Висса", "ЛФА"),
    _r("Барселона", "Огбу", "ЦЗ"),
    _r("Барселона", "Флеккен", "ВРТ"),
    _r("Реал", "Льюин", "ФРВ"),
    _r("Реал", "Поттер", "ЛФА"),
    _r("Атлетико", "Адамс", "ЦОП"),
    _r("Атлетико", "Альварез", "ПЗ"),
    _r("Атлетико", "Фернандо", "ФРВ"),
    _r("Атлетико", "Рамирез", "ЛЗ"),
    _r("Хоффенхайм", "Мартин", "ФРВ"),
    _r("Хоффенхайм", "Аспас", "ФРВ"),
    _r("Хоффенхайм", "Муньоз", "ПЗ"),
    _r("Хоффенхайм", "Керкес", "ЛЗ"),
    _r("Бавария", "Давсари", "ЛП"),
    _r("Бавария", "Куеллар", "ЦОП"),
    _r("Бавария", "Айду", "ЦЗ"),
    _r("Бавария", "Грохе", "ВРТ"),
    _r("Бавария", "Сориа", "ВРТ"),
    _r("Интер", "Койта", "ФРВ"),
    _r("Интер", "Миша", "ПП"),
    _r("Интер", "Теллес", "ЛЗ"),
    _r("Милан", "Зубер", "ФРВ"),
    _r("Милан", "Пинеда", "ЦАП"),
    _r("Милан", "Вейналдум", "ЦП"),
    _r("Милан", "Эль Ямик", "ЦЗ"),
    _r("Лейпциг", "Биссума", "ЦОП"),
    _r("Лейпциг", "Солет", "ЦЗ"),
    _r("Лейпциг", "Судаков", "ЦАП"),
    _r("Лейпциг", "Изуни", "ФРВ"),
    _r("Боруссия М", "Фелипе", "ЦЗ"),
    _r("Боруссия М", "Коронадо", "ЦАП"),
    _r("Боруссия М", "Телло", "ЛФА"),
    _r("Боруссия М", "Миньоле", "ВРТ"),
    _r("Байер", "Кухта", "ФРВ"),
    _r("Байер", "Оспина", "ВРТ"),
    _r("Байер", "Барроу", "ФРВ"),
    _r("Байер", "Конан", "ЛЗ"),
    _r("Ювентус", "Моффи", "ФРВ"),
    _r("Ювентус", "Бах", "ПЗ"),
    _r("Ювентус", "Черки", "ЦАП"),
    _r("Ювентус", "Рейс", "ЦЗ"),
    _r("Ювентус", "Адан", "ВРТ"),
    _r("Рома", "Бергвин", "ЛФА"),
    _r("Рома", "Бергвис", "ЦАП"),
    _r("Рома", "Ренч", "ПЗ"),
    _r("Рома", "Бренет", "ПЗ"),
    _r("Рома", "Виктор", "ЦЗ"),
    _r("Рома", "Дилросун", "ПФА"),
    _r("Рома", "Тейлор", "ЦП"),
    _r("Рома", "Угальде", "ФРВ"),
    _r("Ливерпуль", "Джуст", "ЦЗ"),
    _r("Ливерпуль", "Маурис", "ЦП"),
    _r("Ливерпуль", "Микаутадзе", "ФРВ"),
    _r("Ливерпуль", "Браганса", "ЦП"),
    _r("Ньюкасл", "Хараслин", "ЛФА"),
    _r("Ньюкасл", "Эспино", "ЛЗ"),
    _r("Ньюкасл", "Мавропанос", "ЦЗ"),
    _r("Ньюкасл", "Колпани", "ЦП"),
    _r("Астон Вилла", "Хато", "ЦЗ"),
    _r("Астон Вилла", "Гирасси", "ФРВ"),
    _r("Астон Вилла", "Гехи", "ЦЗ"),
    _r("Астон Вилла", "Акпом", "ФРВ"),
    _r("Арсенал", "Дамсгаард", "ЦАП"),
    _r("Арсенал", "Соланко", "ФРВ"),
    _r("Арсенал", "Дукуре", "ЦП"),
    _r("Арсенал", "Кирех", "ЦАП"),
    _r("Сити", "Одои", "ЛФА"),
    _r("Сити", "Брайда", "ЛЗ"),
    _r("Тоттенхэм", "Семеньо", "ФРВ"),
    _r("Тоттенхэм", "Сарабиа", "ПП"),
    _r("Тоттенхэм", "Билинг", "ЦП"),
    _r("Тоттенхэм", "Диуф", "ЦП"),
]


def _resolve_team_in_session(session, team: str) -> str:
    want = _norm_cmp(_team_name_as_in_db(team.strip()))
    for Cls in _ALL:
        for (tm,) in session.query(Cls.team).filter(Cls.team.isnot(None)).distinct():
            if tm and _norm_cmp(str(tm)) == want:
                return str(tm).strip()
    return _team_name_as_in_db(team.strip())


def _name_matches(row, needle: str) -> bool:
    needle_n = _norm_cmp(needle)
    nm = _norm_cmp(getattr(row, "name", None) or "")
    if nm == needle_n or needle_n in nm or nm in needle_n:
        return True
    return False


def _find_rows(session, team: str, name: str, position: str) -> list[tuple[str, object]]:
    rteam = _resolve_team_in_session(session, team)
    pos_u = position.strip().upper()
    out: list[tuple[str, object]] = []
    for Cls in _ALL:
        for r in session.query(Cls).all():
            if _norm_cmp(getattr(r, "team", "") or "") != _norm_cmp(rteam):
                continue
            if (getattr(r, "position", "") or "").strip().upper() != pos_u:
                continue
            if not _name_matches(r, name):
                continue
            out.append((Cls.__tablename__, r))
    return out


def _stats_nonzero(st: dict[str, int]) -> bool:
    return any(int(st.get(k, 0) or 0) != 0 for k in _STAT_KEYS if k in st)


def _format_stats(st: dict[str, int]) -> str:
    parts: list[str] = []
    for k in _STAT_KEYS:
        if k not in st:
            continue
        v = int(st.get(k, 0) or 0)
        if v:
            parts.append(f"{k}={v}")
    return ", ".join(parts) if parts else "все нули"


def _zero_row(row: object) -> None:
    for k in _STAT_KEYS:
        if hasattr(row, k):
            setattr(row, k, 0)
    if hasattr(row, "ga"):
        row.ga = 0


def _audit_db(db_path: str, label: str, *, apply: bool) -> tuple[int, int, int]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    if not os.path.isfile(db_path):
        print(f"=== {label}: нет файла {db_path}\n")
        return 0, 0, 0

    prepare_season_archive_schema(2)
    eng = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    session = Session()
    found = 0
    missing = 0
    nonzero = 0
    try:
        print(f"=== {label} ({os.path.basename(db_path)}) ===\n")
        cur_team = ""
        for team, name, pos in _CHECKS:
            if team != cur_team:
                cur_team = team
                print(f"── {team} ──")
            hits = _find_rows(session, team, name, pos)
            if not hits:
                print(f"  ? {name} ({pos}) — не найден")
                missing += 1
                continue
            for tbl, r in hits:
                found += 1
                st = row_stats_snapshot(r)
                nz = _stats_nonzero(st)
                if nz:
                    nonzero += 1
                mark = "⚠" if nz else "✓"
                left = " left_team" if bool(getattr(r, "left_team", False)) else ""
                ovr = int(getattr(r, "overall", 0) or 0)
                print(
                    f"  {mark} {name} ({pos}) · {tbl} id={r.id} ovr={ovr}{left}: "
                    f"{_format_stats(st)}"
                )
                if apply and nz:
                    _zero_row(r)
        if apply:
            session.commit()
    finally:
        session.close()
        eng.dispose()
    print()
    return found, missing, nonzero


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cl", action="store_true", help="Также champions_league.db")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Обнулить ненулевую стату у найденных строк",
    )
    args = ap.parse_args()

    paths = [(os.path.join(ROOT, "db", "season_2", "league.db"), "Лига")]
    if args.cl:
        paths.append(
            (os.path.join(ROOT, "db", "season_2", "champions_league.db"), "ЛЧ")
        )

    tf = 0
    tm = 0
    tn = 0
    for path, lab in paths:
        f, m, n = _audit_db(path, lab, apply=args.apply)
        tf += f
        tm += m
        tn += n

    mode = "записано" if args.apply else "dry-run"
    print(
        f"Итого ({mode}): найдено строк {tf}, не найдено {tm}, "
        f"с ненулевой статой {tn}."
    )
    if not args.apply and tn:
        print("Чтобы обнулить все найденные ненулевые: добавь --apply")
    if args.apply and tn:
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
        print("season_2/common.db пересобран.")


if __name__ == "__main__":
    main()
