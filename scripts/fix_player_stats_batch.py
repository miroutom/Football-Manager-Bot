#!/usr/bin/env python3
"""
Точечная перезапись `matches / goals / assists / ga` для указанных игроков.

Формат входа (текстовый файл; пустые строки и `#`-комментарии игнорируются):

    Аталанта
    Миранчук ФРВ 8 6 5 8 8 2
    Муриэль ЛФА 8 6 2 8 2 1
    Де Кетеларе ЦАП 1 0 1 0 0 0
    ...

    Наполи
    Квара ЛФА 8 8 4 8 7 3
    ...

Каждая «не-игроковая» строка трактуется как **название клуба**. Каждая игровая
строка: имя (может быть из нескольких слов), позиция, далее **6 чисел** через
пробел:
``матчи_лиги голы_лиги ассисты_лиги матчи_ЛЧ голы_ЛЧ ассисты_ЛЧ``.

Правила:
- Пишем строго в `db/season_2/league.db` (лиговая часть) и в
  `db/season_2/champions_league.db` (ЛЧ-часть). Только сезон 2.
- Перезаписываем только ``matches``, ``goals``, ``assists`` и ``ga = g + a``.
  Никаких других полей не трогаем (жк/кк, сухие, status, overall, nation,
  награды, трофеи).
- Если клуб не в пуле ЛЧ, а CL-числа ≠ 0 — ошибка.
- Если игрок не найден в нужной БД для (team, name, position) — ошибка.
- Вратарь (`ВРТ`) — ошибка (по договорённости не присылаем).
- Атомарность: при наличии **любой** ошибки в партии ничего не пишем.
- После записи: бэкап БД, ``rebuild_common_database`` и
  ``rebuild_all_time_databases_from_season_archives``.

Запуск:
    python scripts/fix_player_stats_batch.py path/to/input.txt           # dry-run
    python scripts/fix_player_stats_batch.py path/to/input.txt --apply   # запись
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from player_stats import (  # noqa: E402
    LEAGUE_TEAMS,
    _norm_cmp,
    find_player_by_name,
    get_player_class,
    get_position_type,
    get_session,
)
from utils.common_db import resolve_team_name_for_cl_pool  # noqa: E402
from utils.utils import (  # noqa: E402
    defenders,
    forwards,
    goalkeepers,
    midfielders,
)

ALL_POSITIONS: set[str] = set(forwards + midfielders + defenders + goalkeepers)


def _is_int(token: str) -> bool:
    t = token.strip()
    if not t:
        return False
    return t.lstrip("-").isdigit()


@dataclass
class PlayerRow:
    name: str
    position: str
    team: str
    league_m: int
    league_g: int
    league_a: int
    cl_m: int
    cl_g: int
    cl_a: int
    src_line: str


def _resolve_team_in_any_league(team: str) -> tuple[str | None, str | None]:
    """Найти каноническое имя клуба и код национальной лиги (rpl/eng/esp/ger/ita)."""
    tn = _norm_cmp(team)
    for code, names in LEAGUE_TEAMS.items():
        for canon in names:
            if _norm_cmp(canon) == tn:
                return canon, code
    return None, None


def parse_input(path: str) -> tuple[list[PlayerRow], list[str]]:
    rows: list[PlayerRow] = []
    errs: list[str] = []
    with open(path, encoding="utf-8") as f:
        raw_lines = f.readlines()

    current_team: str | None = None
    for ln_no, raw in enumerate(raw_lines, start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        toks = line.split()
        # Заголовок клуба: < 8 токенов или последние 6 не все числа
        is_header = len(toks) < 8 or not all(_is_int(t) for t in toks[-6:])
        if is_header:
            current_team = line
            continue
        if current_team is None:
            errs.append(f"L{ln_no}: «{line}» — не указан клуб (нет заголовка выше).")
            continue
        nums = [int(x) for x in toks[-6:]]
        position = toks[-7]
        name = " ".join(toks[:-7]).strip()
        if not name:
            errs.append(f"L{ln_no}: «{line}» — не разобрать имя.")
            continue
        if position.upper() not in ALL_POSITIONS:
            errs.append(
                f"L{ln_no}: «{line}» — неизвестная позиция «{position}». "
                f"Доступные: {sorted(ALL_POSITIONS)}"
            )
            continue
        if any(n < 0 for n in nums):
            errs.append(f"L{ln_no}: «{line}» — отрицательные числа недопустимы.")
            continue
        rows.append(
            PlayerRow(
                name=name,
                position=position.upper(),
                team=current_team,
                league_m=nums[0],
                league_g=nums[1],
                league_a=nums[2],
                cl_m=nums[3],
                cl_g=nums[4],
                cl_a=nums[5],
                src_line=line,
            )
        )
    return rows, errs


@dataclass
class PlannedChange:
    tournament: str  # 'league' | 'cl'
    name: str
    team: str
    position: str
    before: tuple[int, int, int, int]  # (m, g, a, ga)
    after: tuple[int, int, int, int]
    src_line: str


def _resolve_row(session, team: str, name: str, position: str):
    """Найти строку в БД по (team, name, position)."""
    cls = get_player_class(position)
    cand = []
    for r in session.query(cls).all():
        if _norm_cmp(r.team) != _norm_cmp(team):
            continue
        if _norm_cmp(r.name) != _norm_cmp(name):
            continue
        if _norm_cmp(r.position) != _norm_cmp(position):
            continue
        cand.append(r)
    if len(cand) > 1:
        return None, "несколько строк с тем же (имя+позиция+клуб) — это баг данных"
    if not cand:
        # fallback: попробуем по имени+клубу без позиции
        p, _ = find_player_by_name(session, name, team)
        if p and _norm_cmp(p.position) == _norm_cmp(position):
            return p, None
        return None, "не найден"
    return cand[0], None


def plan_changes(rows: list[PlayerRow]) -> tuple[list[PlannedChange], list[str]]:
    """Сформировать список планируемых изменений; вернуть (плюс ошибки)."""
    plans: list[PlannedChange] = []
    errs: list[str] = []

    s_league = get_session("league")
    s_cl = get_session("cl")

    for r in rows:
        canon_team, league_code = _resolve_team_in_any_league(r.team)
        if canon_team is None:
            errs.append(
                f"«{r.team}»: клуб не из списков нац. лиг (rpl/eng/esp/ger/ita). "
                f"Игрок: {r.src_line}"
            )
            continue

        if get_position_type(r.position) == "goalkeeper":
            errs.append(
                f"«{r.team}» {r.name} {r.position}: вратарь в этом скрипте не поддержан "
                f"(g/a/ga к нему не пишутся)."
            )
            continue

        # Лига: всегда. m может быть 0 — это норм.
        p_l, err_l = _resolve_row(s_league, canon_team, r.name, r.position)
        if err_l:
            errs.append(
                f"league.db: «{canon_team}» {r.name} ({r.position}) — {err_l}. "
                f"Строка: {r.src_line}"
            )
        else:
            before = (
                int(p_l.matches or 0),
                int(p_l.goals or 0),
                int(p_l.assists or 0),
                int(getattr(p_l, "ga", 0) or 0),
            )
            after = (r.league_m, r.league_g, r.league_a, r.league_g + r.league_a)
            if before != after:
                plans.append(
                    PlannedChange(
                        tournament="league",
                        name=p_l.name,
                        team=p_l.team,
                        position=p_l.position,
                        before=before,
                        after=after,
                        src_line=r.src_line,
                    )
                )

        # ЛЧ: только если клуб в пуле ЛЧ
        cl_team = resolve_team_name_for_cl_pool(canon_team)
        cl_has_values = r.cl_m or r.cl_g or r.cl_a
        if cl_team:
            p_c, err_c = _resolve_row(s_cl, cl_team, r.name, r.position)
            if err_c:
                if cl_has_values:
                    errs.append(
                        f"champions_league.db: «{cl_team}» {r.name} ({r.position}) — {err_c}. "
                        f"Строка: {r.src_line}"
                    )
                # если все нули и игрока нет — норм, не пишем ничего
            else:
                before = (
                    int(p_c.matches or 0),
                    int(p_c.goals or 0),
                    int(p_c.assists or 0),
                    int(getattr(p_c, "ga", 0) or 0),
                )
                after = (r.cl_m, r.cl_g, r.cl_a, r.cl_g + r.cl_a)
                if before != after:
                    plans.append(
                        PlannedChange(
                            tournament="cl",
                            name=p_c.name,
                            team=p_c.team,
                            position=p_c.position,
                            before=before,
                            after=after,
                            src_line=r.src_line,
                        )
                    )
        else:
            if cl_has_values:
                errs.append(
                    f"«{canon_team}» вне пула ЛЧ, а у {r.name} CL-числа ненулевые "
                    f"({r.cl_m}/{r.cl_g}/{r.cl_a}). Строка: {r.src_line}"
                )

    return plans, errs


def _print_plan(plans: list[PlannedChange]) -> None:
    if not plans:
        print("Изменений нет — данные совпадают с БД.")
        return
    print(f"\nПлан изменений: {len(plans)} строк(и)")
    print(f"  {'#':>3} {'БД':<7} {'Команда':<16} {'Игрок':<22} "
          f"{'Поз':<5} {'было (m/g/a/ga)':<22} → {'станет':<22}")
    for i, p in enumerate(plans, 1):
        b = "/".join(str(x) for x in p.before)
        a = "/".join(str(x) for x in p.after)
        print(
            f"  {i:>3} {p.tournament:<7} {p.team:<16} {p.name:<22} "
            f"{p.position:<5} {b:<22} → {a:<22}"
        )


def _apply_plan(plans: list[PlannedChange]) -> None:
    s_league = get_session("league")
    s_cl = get_session("cl")
    by_sess = {"league": s_league, "cl": s_cl}
    for p in plans:
        sess = by_sess[p.tournament]
        # Перечитываем строку (resolve_row возвращает свежий объект из этой сессии)
        cls = get_player_class(p.position)
        row = None
        for r in sess.query(cls).all():
            if (_norm_cmp(r.team) == _norm_cmp(p.team)
                    and _norm_cmp(r.name) == _norm_cmp(p.name)
                    and _norm_cmp(r.position) == _norm_cmp(p.position)):
                row = r
                break
        if row is None:
            raise RuntimeError(
                f"Не нашёл строку при записи: {p.tournament} {p.team} {p.name} {p.position}"
            )
        m, g, a, ga = p.after
        row.matches = int(m)
        row.goals = int(g)
        row.assists = int(a)
        row.ga = int(ga)
    s_league.commit()
    s_cl.commit()


def _backup_dbs() -> str:
    """Бэкап league.db и champions_league.db сезона 2 в db/season_2/backup_<ts>/."""
    ts = time.strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(ROOT, "db", "season_2", f"backup_{ts}")
    os.makedirs(dest, exist_ok=True)
    for fn in ("league.db", "champions_league.db", "common.db"):
        src = os.path.join(ROOT, "db", "season_2", fn)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dest, fn))
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Файл с партией (см. формат в шапке).")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Записать изменения. По умолчанию — dry-run.",
    )
    args = parser.parse_args()

    rows, parse_errs = parse_input(args.input)
    if parse_errs:
        print("=== Ошибки парсинга ===")
        for e in parse_errs:
            print(" ", e)
    if not rows:
        print("Игроков в файле нет.")
        return 1 if parse_errs else 0

    plans, plan_errs = plan_changes(rows)
    if plan_errs:
        print("\n=== Ошибки валидации ===")
        for e in plan_errs:
            print(" ", e)

    _print_plan(plans)

    if parse_errs or plan_errs:
        print("\nЕсть ошибки — ничего не записано. Исправь и запусти снова.")
        return 1

    if not args.apply:
        print("\n(dry-run) Чтобы записать, повтори запуск с --apply.")
        return 0

    if not plans:
        print("\nНечего применять — изменений нет.")
        return 0

    print("\n--- Бэкап ---")
    dest = _backup_dbs()
    print(f"  скопировано в: {dest}")

    print("\n--- Запись в league.db / champions_league.db ---")
    _apply_plan(plans)
    print(f"  обновлено строк: {len(plans)}")

    print("\n--- Пересборка common.db ---")
    from utils.common_db import rebuild_common_database

    rebuild_common_database()
    print("  common.db пересобран")

    print("\n--- Пересборка *_synced.db ---")
    from utils.cumulative_db import rebuild_all_time_databases_from_season_archives

    log = rebuild_all_time_databases_from_season_archives()
    for line in log.get("cumulative", []) or []:
        print(f"  {line}")
    print(f"  сезоны: {log.get('seasons')}")

    print("\nГотово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
