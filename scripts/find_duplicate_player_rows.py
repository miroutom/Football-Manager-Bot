#!/usr/bin/env python3
"""
Найти игроков с одним именем и несколькими строками в БД (разные позиции и/или клубы).

Пример: Тонали ЦАП Ньюкасл + Тонали ФРВ Сити — один человек, две строки.

Только отчёт, БД не меняет.

  python3 scripts/find_duplicate_player_rows.py
  python3 scripts/find_duplicate_player_rows.py --db cl
  python3 scripts/find_duplicate_player_rows.py --json > /tmp/dupes.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from player_stats import _norm_cmp
from utils import season_paths
from utils.roster_manual import FREE_AGENT_TEAM

_ALL = (Forward, Midfielder, Defender, Goalkeeper)


@dataclass(frozen=True)
class PlayerRow:
    db_label: str
    table: str
    row_id: int
    name: str
    position: str
    team: str
    overall: int
    nation: str
    matches: int
    goals: int
    assists: int

    def line(self) -> str:
        return (
            f"  [{self.db_label}] {self.team} · {self.position} · ovr {self.overall} · "
            f"{self.nation} · м={self.matches} г={self.goals} п={self.assists} · "
            f"id={self.row_id} ({self.table})"
        )


def _load_rows(db_label: str, db_path: str) -> list[PlayerRow]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    if not os.path.isfile(db_path):
        raise FileNotFoundError(db_path)

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    out: list[PlayerRow] = []
    try:
        for Cls in _ALL:
            tbl = Cls.__tablename__
            for r in session.query(Cls).all():
                team = (getattr(r, "team", None) or "").strip()
                name = (getattr(r, "name", None) or "").strip()
                if not name:
                    continue
                out.append(
                    PlayerRow(
                        db_label=db_label,
                        table=tbl,
                        row_id=int(r.id),
                        name=name,
                        position=(getattr(r, "position", None) or "").strip().upper(),
                        team=team.title() if team else "—",
                        overall=int(getattr(r, "overall", 0) or 0),
                        nation=(getattr(r, "nation", None) or "").strip() or "—",
                        matches=int(getattr(r, "matches", 0) or 0),
                        goals=int(getattr(r, "goals", 0) or 0),
                        assists=int(getattr(r, "assists", 0) or 0),
                    )
                )
    finally:
        session.close()
        engine.dispose()
    return out


def _classify(rows: list[PlayerRow]) -> str:
    teams = {r.team for r in rows if r.team and r.team != "—"}
    teams.discard(FREE_AGENT_TEAM.title())
    pos = {r.position for r in rows if r.position}
    if len(teams) >= 2 and len(pos) >= 2:
        return "clubs_and_positions"
    if len(teams) >= 2:
        return "multiple_clubs"
    if len(pos) >= 2:
        return "multiple_positions"
    return "other"


_KIND_RU = {
    "multiple_positions": "один клуб, несколько позиций",
    "multiple_clubs": "несколько клубов, одна позиция (или совпали)",
    "clubs_and_positions": "несколько клубов и позиций (как после трансфера)",
    "other": "прочее (дубли строк)",
}


def find_duplicate_groups(
    rows: list[PlayerRow],
    *,
    include_free_agent: bool,
) -> list[tuple[str, str, list[PlayerRow]]]:
    by_name: dict[str, list[PlayerRow]] = defaultdict(list)
    for r in rows:
        by_name[_norm_cmp(r.name)].append(r)

    groups: list[tuple[str, str, list[PlayerRow]]] = []
    for norm, grp in sorted(by_name.items(), key=lambda x: (x[1][0].name.lower(), x[0])):
        if len(grp) < 2:
            continue
        teams = {r.team for r in grp}
        pos = {r.position for r in grp}
        if len(pos) < 2 and len(teams) < 2:
            continue
        if not include_free_agent:
            real = [r for r in grp if _norm_cmp(r.team) != _norm_cmp(FREE_AGENT_TEAM)]
            if len(real) < 2:
                continue
            grp = real
        kind = _classify(grp)
        display_name = grp[0].name
        groups.append(
            (kind, display_name, sorted(grp, key=lambda x: (-x.matches, x.team, x.position)))
        )
    return groups


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        choices=("league", "cl", "both"),
        default="league",
        help="Какую БД сканировать (по умолчанию league.db сезона)",
    )
    ap.add_argument(
        "--include-free-agent",
        action="store_true",
        help="Не отбрасывать группы, где вторая строка только Free Agent",
    )
    ap.add_argument("--json", action="store_true", help="Вывод в JSON")
    args = ap.parse_args()

    paths: list[tuple[str, str]] = []
    if args.db in ("league", "both"):
        paths.append(("league", season_paths.get_league_db_path()))
    if args.db in ("cl", "both"):
        paths.append(("cl", season_paths.get_cl_db_path()))

    all_rows: list[PlayerRow] = []
    for label, path in paths:
        all_rows.extend(_load_rows(label, path))

    groups = find_duplicate_groups(
        all_rows, include_free_agent=args.include_free_agent
    )

    if args.json:
        payload = []
        for kind, name, grp in groups:
            payload.append(
                {
                    "kind": kind,
                    "kind_ru": _KIND_RU.get(kind, kind),
                    "name": name,
                    "rows": [asdict(r) for r in grp],
                }
            )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    db_paths = ", ".join(p for _, p in paths)
    print(f"Скан: {db_paths}")
    print(f"Групп (одно имя, 2+ строк, разные позиции и/или клубы): {len(groups)}\n")

    by_kind: dict[str, list[tuple[str, list[PlayerRow]]]] = defaultdict(list)
    for kind, name, grp in groups:
        by_kind[kind].append((name, grp))

    for kind in (
        "clubs_and_positions",
        "multiple_clubs",
        "multiple_positions",
        "other",
    ):
        items = by_kind.get(kind) or []
        if not items:
            continue
        print(f"{'=' * 72}")
        print(f"{_KIND_RU[kind]} — {len(items)} игрок(ов)")
        print(f"{'=' * 72}\n")
        for name, grp in sorted(items, key=lambda x: (-max(r.matches for r in x[1]), x[0].lower())):
            teams = sorted({r.team for r in grp})
            pos = sorted({r.position for r in grp})
            print(f"{name}  ({len(grp)} строк · клубы: {', '.join(teams)} · поз: {', '.join(pos)})")
            for r in grp:
                print(r.line())
            print()


if __name__ == "__main__":
    main()
