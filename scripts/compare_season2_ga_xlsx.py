#!/usr/bin/env python3
"""
Сравнение голов, ГП и г+а из db/season2_ga.xlsx с активным сезоном 2 в league.db и champions_league.db.

Матчи не сравниваются. По умолчанию печатаются только расхождения и игроки, не найденные в БД.

  python3 scripts/compare_season2_ga_xlsx.py
  python3 scripts/compare_season2_ga_xlsx.py --xlsx path/to/file.xlsx
  python3 scripts/compare_season2_ga_xlsx.py --summary   # только счётчики
  python3 scripts/compare_season2_ga_xlsx.py --apply     # записать г/гп/г+а из xlsx (матчи не трогаем)
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_NAME_NOTE_RE = re.compile(r"\s*\([^)]*\)\s*$")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from player_stats import _norm_cmp
from utils.common_db import resolve_team_name_for_cl_pool
from utils.transfer_input import resolve_team_name
from utils.utils import get_session, session_league

DEFAULT_XLSX = Path(ROOT) / "db" / "season2_ga.xlsx"

PLAYER_CLASSES = (Forward, Midfielder, Defender, Goalkeeper)
SKIP_TEAM_LABELS = frozenset({"Лига", "ЛЧ"})


@dataclass
class StatTriple:
    goals: int
    assists: int

    @property
    def ga(self) -> int:
        return self.goals + self.assists


@dataclass
class XlsxPlayerRow:
    team_raw: str
    name: str
    name_raw: str
    league: StatTriple
    cl: StatTriple


@dataclass
class DbPlayerRow:
    name: str
    position: str
    goals: int
    assists: int
    ga: int


def _as_int(v) -> int:
    if v is None or v == "":
        return 0
    return int(v)


def parse_xlsx(path: Path) -> tuple[list[XlsxPlayerRow], list[str]]:
    try:
        import openpyxl
    except ImportError as e:
        raise SystemExit("Нужен openpyxl: pip install openpyxl") from e

    rows_out: list[XlsxPlayerRow] = []
    errs: list[str] = []
    current_team: str | None = None

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    for ln, raw in enumerate(ws.iter_rows(values_only=True), start=1):
        if not raw or all(c is None for c in raw):
            continue
        cells = list(raw) + [None] * (8 - len(raw))

        label = cells[0]
        name_cell = cells[1]

        if label == "Номер" or name_cell == "Игрок":
            continue
        if label in SKIP_TEAM_LABELS or name_cell in SKIP_TEAM_LABELS:
            continue

        if name_cell is None and isinstance(label, str) and label.strip():
            current_team = label.strip()
            continue

        if current_team is None:
            if name_cell:
                errs.append(f"L{ln}: строка «{name_cell}» без заголовка клуба выше")
            continue

        if not isinstance(label, (int, float)) or not name_cell:
            continue

        name_raw = str(name_cell).strip()
        name = _NAME_NOTE_RE.sub("", name_raw).strip() or name_raw
        rows_out.append(
            XlsxPlayerRow(
                team_raw=current_team,
                name=name,
                name_raw=name_raw,
                league=StatTriple(_as_int(cells[3]), _as_int(cells[4])),
                cl=StatTriple(_as_int(cells[6]), _as_int(cells[7])),
            )
        )
    wb.close()
    return rows_out, errs


def _db_ga(row) -> int:
    g = int(row.goals or 0)
    a = int(row.assists or 0)
    return int(getattr(row, "ga", None) if getattr(row, "ga", None) is not None else g + a)


def find_orm_in_team(session, team: str, name: str) -> list[Any]:
    want_name = _norm_cmp(name)
    want_team = _norm_cmp(team)
    found: list[Any] = []
    for cls in PLAYER_CLASSES:
        for r in session.query(cls).all():
            if _norm_cmp(r.team) != want_team:
                continue
            if _norm_cmp(r.name) != want_name:
                continue
            found.append(r)
    return found


def find_all_in_team(session, team: str, name: str) -> list[DbPlayerRow]:
    return [
        DbPlayerRow(
            name=r.name,
            position=r.position,
            goals=int(r.goals or 0),
            assists=int(r.assists or 0),
            ga=_db_ga(r),
        )
        for r in find_orm_in_team(session, team, name)
    ]


def _triple_differs(row, triple: StatTriple) -> bool:
    return (
        int(row.goals or 0) != triple.goals
        or int(row.assists or 0) != triple.assists
        or _db_ga(row) != triple.ga
    )


def _apply_triple(row, triple: StatTriple) -> tuple[int, int, int]:
    """Записать г/гп/г+а; матчи не меняются. Возвращает (g, a, ga) после записи."""
    row.goals = int(triple.goals)
    row.assists = int(triple.assists)
    row.ga = int(triple.ga)
    return row.goals, row.assists, row.ga


def _resolve_league_team(team_raw: str) -> str | None:
    return resolve_team_name(team_raw, session_league)


def _field_mismatch(
    label: str, xlsx: StatTriple, db: DbPlayerRow | None, present: bool
) -> list[str]:
    if not present:
        if xlsx.goals == 0 and xlsx.assists == 0:
            return []
        return [
            f"  {label}: в xlsx г={xlsx.goals} гп={xlsx.assists} г+а={xlsx.ga}, "
            f"в БД записи нет"
        ]
    assert db is not None
    lines: list[str] = []
    if db.goals != xlsx.goals:
        lines.append(
            f"  {label} голы: xlsx={xlsx.goals}  БД={db.goals}  ({db.name}, {db.position})"
        )
    if db.assists != xlsx.assists:
        lines.append(
            f"  {label} ГП:   xlsx={xlsx.assists}  БД={db.assists}  ({db.name}, {db.position})"
        )
    if db.ga != xlsx.ga:
        lines.append(
            f"  {label} г+а:  xlsx={xlsx.ga}  БД={db.ga}  ({db.name}, {db.position})"
        )
    return lines


def compare_row(
    x: XlsxPlayerRow,
    league_team: str | None,
    cl_team: str | None,
) -> tuple[list[str], str | None]:
    """
    Возвращает (строки отчёта, категория: mismatch | not_found | ambiguous | ok).
    """
    if league_team is None:
        return [f"«{x.team_raw}» · {x.name}: клуб не найден в league.db"], "team_missing"

    s_league = get_session("league")
    s_cl = get_session("cl")

    league_players = find_all_in_team(s_league, league_team, x.name)
    cl_players: list[DbPlayerRow] = []
    if cl_team:
        cl_players = find_all_in_team(s_cl, cl_team, x.name)

    has_league_xlsx = x.league.goals or x.league.assists
    has_cl_xlsx = x.cl.goals or x.cl.assists

    if not league_players and not cl_players:
        if has_league_xlsx or has_cl_xlsx:
            label = x.name_raw if x.name_raw != x.name else x.name
            return [
                f"«{league_team}» · {label}: нет в league.db"
                + (f" / {cl_team} в champions_league.db" if cl_team else "")
            ], "not_found"
        return [], "ok"

    if len(league_players) > 1 or len(cl_players) > 1:
        parts = [f"«{league_team}» · {x.name}: несколько строк в БД — сверь вручную"]
        if len(league_players) > 1:
            parts.append(
                "  лига: "
                + ", ".join(f"{p.position} г={p.goals} гп={p.assists}" for p in league_players)
            )
        if len(cl_players) > 1:
            parts.append(
                "  ЛЧ: "
                + ", ".join(f"{p.position} г={p.goals} гп={p.assists}" for p in cl_players)
            )
        parts.append(
            f"  xlsx лига: г={x.league.goals} гп={x.league.assists} | "
            f"ЛЧ: г={x.cl.goals} гп={x.cl.assists}"
        )
        return parts, "ambiguous"

    league_db = league_players[0] if league_players else None
    cl_db = cl_players[0] if cl_players else None

    lines: list[str] = []
    lines.extend(
        _field_mismatch("лига", x.league, league_db, league_db is not None)
    )
    if cl_team or has_cl_xlsx:
        lines.extend(_field_mismatch("ЛЧ", x.cl, cl_db, cl_db is not None))
    elif has_cl_xlsx and not cl_team:
        lines.append(
            f"  ЛЧ: в xlsx г={x.cl.goals} гп={x.cl.assists}, клуб не в пуле ЛЧ"
        )

    if lines:
        header = f"«{league_team}» · {x.name_raw if x.name_raw != x.name else x.name}"
        if league_db:
            header += f" ({league_db.position})"
        return [header] + lines, "mismatch"
    return [], "ok"


@dataclass
class AppliedChange:
    tournament: str
    team: str
    name: str
    position: str
    before: StatTriple
    after: StatTriple


def apply_row_fixes(
    x: XlsxPlayerRow,
    league_team: str | None,
    cl_team: str | None,
) -> tuple[list[AppliedChange], list[str], str]:
    """Записать г/гп/г+а из xlsx при расхождении. Возвращает (изменения, ошибки, категория)."""
    if league_team is None:
        return [], [f"«{x.team_raw}» · {x.name}: клуб не найден в league.db"], "team_missing"

    s_league = get_session("league")
    s_cl = get_session("cl")

    league_orm = find_orm_in_team(s_league, league_team, x.name)
    cl_orm: list[Any] = []
    if cl_team:
        cl_orm = find_orm_in_team(s_cl, cl_team, x.name)

    has_league_xlsx = x.league.goals or x.league.assists
    has_cl_xlsx = x.cl.goals or x.cl.assists

    if len(league_orm) > 1 or len(cl_orm) > 1:
        return [], [f"«{league_team}» · {x.name}: несколько строк в БД"], "ambiguous"

    if not league_orm and not cl_orm:
        if has_league_xlsx or has_cl_xlsx:
            label = x.name_raw if x.name_raw != x.name else x.name
            return [], [f"«{league_team}» · {label}: нет в БД"], "not_found"
        return [], [], "ok"

    changes: list[AppliedChange] = []
    errs: list[str] = []

    if league_orm:
        row = league_orm[0]
        if _triple_differs(row, x.league):
            before = StatTriple(int(row.goals or 0), int(row.assists or 0))
            g, a, ga = _apply_triple(row, x.league)
            changes.append(
                AppliedChange(
                    "league",
                    league_team,
                    row.name,
                    row.position,
                    before,
                    StatTriple(g, a),
                )
            )
    elif has_league_xlsx:
        errs.append(f"«{league_team}» · {x.name}: лига — строки в БД нет")

    if cl_team or has_cl_xlsx:
        if cl_orm:
            row = cl_orm[0]
            if _triple_differs(row, x.cl):
                before = StatTriple(int(row.goals or 0), int(row.assists or 0))
                g, a, ga = _apply_triple(row, x.cl)
                changes.append(
                    AppliedChange(
                        "cl",
                        cl_team or row.team,
                        row.name,
                        row.position,
                        before,
                        StatTriple(g, a),
                    )
                )
        elif has_cl_xlsx:
            errs.append(
                f"«{cl_team or league_team}» · {x.name}: ЛЧ — строки в БД нет "
                f"(xlsx г={x.cl.goals} гп={x.cl.assists})"
            )

    if errs:
        return changes, errs, "partial"
    if changes:
        return changes, [], "mismatch"
    return [], [], "ok"


def _backup_dbs() -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    dest = Path(ROOT) / "db" / "season_2" / f"backup_{ts}"
    dest.mkdir(parents=True, exist_ok=True)
    for fn in ("league.db", "champions_league.db", "common.db"):
        src = Path(ROOT) / "db" / "season_2" / fn
        if src.is_file():
            shutil.copy2(src, dest / fn)
    return str(dest)


def _print_applied(changes: list[AppliedChange]) -> None:
    for c in changes:
        print(
            f"  {c.tournament:<6} {c.team:<14} {c.name} ({c.position})  "
            f"г/гп/г+а {c.before.goals}/{c.before.assists}/{c.before.ga} → "
            f"{c.after.goals}/{c.after.assists}/{c.after.ga}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--xlsx",
        type=Path,
        default=DEFAULT_XLSX,
        help=f"Путь к таблице (по умолчанию {DEFAULT_XLSX})",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Только итоговые счётчики, без списка расхождений",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Записать в БД голы, ГП и г+а из xlsx для всех расхождений (матчи не меняются)",
    )
    parser.add_argument(
        "--no-cumulative-rebuild",
        action="store_true",
        help="С --apply: не пересобирать *_synced.db",
    )
    args = parser.parse_args()

    path = args.xlsx.expanduser().resolve()
    if not path.is_file():
        print(f"Файл не найден: {path}")
        return 1

    players, parse_errs = parse_xlsx(path)
    for e in parse_errs:
        print("Парсинг:", e)

    counts = {
        "ok": 0,
        "mismatch": 0,
        "not_found": 0,
        "ambiguous": 0,
        "team_missing": 0,
        "partial": 0,
    }
    report_blocks: list[str] = []
    all_changes: list[AppliedChange] = []
    apply_errs: list[str] = []

    for row in players:
        league_team = _resolve_league_team(row.team_raw)
        cl_team = (
            resolve_team_name_for_cl_pool(league_team)
            if league_team
            else None
        )
        if args.apply:
            changes, errs, cat = apply_row_fixes(row, league_team, cl_team)
            all_changes.extend(changes)
            apply_errs.extend(errs)
            if changes:
                counts["mismatch"] += 1
            elif cat == "ok":
                counts["ok"] += 1
            else:
                counts[cat] = counts.get(cat, 0) + 1
            continue

        lines, cat = compare_row(row, league_team, cl_team)
        counts[cat] = counts.get(cat, 0) + 1
        if lines:
            report_blocks.append("\n".join(lines))

    print(f"Файл: {path}")
    print(f"Игроков в xlsx: {len(players)}")

    if args.apply:
        if apply_errs:
            print("\n=== Ошибки (без записи по этим строкам) ===")
            for e in apply_errs:
                print(" ", e)
            if apply_errs and not all_changes:
                return 1

        if not all_changes:
            print("\nРасхождений для записи нет (или всё уже совпадает).")
            return 0

        print(f"\nПлан записи: {len(all_changes)} обновлений (только г / гп / г+а)")
        _print_applied(all_changes)

        dest = _backup_dbs()
        print(f"\nБэкап: {dest}")
        s_league = get_session("league")
        s_cl = get_session("cl")
        s_league.commit()
        s_cl.commit()
        print(f"Записано обновлений: {len(all_changes)}")

        from utils.common_db import rebuild_common_database

        rebuild_common_database()
        print("common.db пересобран")

        if not args.no_cumulative_rebuild:
            from utils.cumulative_db import rebuild_all_time_databases_from_season_archives

            log = rebuild_all_time_databases_from_season_archives()
            print("synced:", log.get("cumulative"))

        print("\nПовторная сверка:")
        args.apply = False
        # re-run compare only for mismatches count
        m2 = 0
        for row in players:
            lt = _resolve_league_team(row.team_raw)
            ct = resolve_team_name_for_cl_pool(lt) if lt else None
            lines, cat = compare_row(row, lt, ct)
            if cat == "mismatch":
                m2 += 1
        print(f"Осталось расхождений: {m2}")
        return 0 if m2 == 0 else 1

    print(
        f"Совпало: {counts['ok']} | расхождения: {counts['mismatch']} | "
        f"не найден: {counts['not_found']} | неоднозначно: {counts['ambiguous']} | "
        f"клуб не в БД: {counts['team_missing']}"
    )

    if not args.summary and report_blocks:
        print("\n=== Расхождения и проблемы ===\n")
        print("\n\n".join(report_blocks))
    elif counts["mismatch"] == 0 and counts["not_found"] == 0 and counts["ambiguous"] == 0:
        print("\nВсе голы / ГП / г+а совпадают с БД.")

    return 1 if (counts["mismatch"] or counts["not_found"] or counts["ambiguous"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
