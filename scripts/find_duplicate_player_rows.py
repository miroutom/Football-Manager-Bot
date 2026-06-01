#!/usr/bin/env python3
"""
Найти потенциальные дубли одного игрока в БД (только отчёт).

- Одно имя, разные позиции и/или клубы (Тонали ЦАП Ньюкасл + Тонали ФРВ Сити).
- Разные имена в одном клубе: алиасы ``data/player_name_aliases.json`` (Силва → Рафа)
  и эвристика «тот же профиль»: клуб + позиция + нация + м/г/п.

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
from utils.player_identity import resolve_canonical_name
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
    "multiple_positions": "одно имя · один клуб, несколько позиций",
    "multiple_clubs": "одно имя · несколько клубов",
    "clubs_and_positions": "одно имя · несколько клубов и позиций",
    "different_names": "разные имена · алиас или совпадение клуб/поз/нация/стата",
    "other": "прочее (дубли строк)",
}


@dataclass(frozen=True)
class DuplicateGroup:
    kind: str
    match: str  # same_name | alias | profile
    title: str
    rows: tuple[PlayerRow, ...]


def _row_key(r: PlayerRow) -> tuple[str, str, int]:
    return (r.db_label, r.table, r.row_id)


def _filter_free_agent(
    grp: list[PlayerRow], *, include_free_agent: bool
) -> list[PlayerRow] | None:
    if include_free_agent:
        return grp
    real = [r for r in grp if _norm_cmp(r.team) != _norm_cmp(FREE_AGENT_TEAM)]
    if len(real) < 2:
        return None
    return real


def _display_title(rows: list[PlayerRow]) -> str:
    names = sorted({r.name for r in rows}, key=str.lower)
    if len(names) == 1:
        return names[0]
    return " / ".join(names)


def _is_duplicate_candidate(grp: list[PlayerRow]) -> bool:
    if len(grp) < 2:
        return False
    names = {_norm_cmp(r.name) for r in grp}
    teams = {r.team for r in grp if r.team and r.team != "—"}
    teams.discard(FREE_AGENT_TEAM.title())
    pos = {r.position for r in grp if r.position}
    if len(names) >= 2:
        return True
    return len(teams) >= 2 or len(pos) >= 2


def find_duplicate_groups(
    rows: list[PlayerRow],
    *,
    include_free_agent: bool,
) -> list[DuplicateGroup]:
    seen: set[frozenset[tuple[str, str, int]]] = set()
    out: list[DuplicateGroup] = []

    def _add(kind: str, match: str, grp: list[PlayerRow]) -> None:
        filtered = _filter_free_agent(grp, include_free_agent=include_free_agent)
        if not filtered or not _is_duplicate_candidate(filtered):
            return
        key = frozenset(_row_key(r) for r in filtered)
        if key in seen:
            return
        seen.add(key)
        sorted_rows = sorted(
            filtered, key=lambda x: (-x.matches, x.team, x.position, x.name.lower())
        )
        out.append(
            DuplicateGroup(
                kind=kind,
                match=match,
                title=_display_title(sorted_rows),
                rows=tuple(sorted_rows),
            )
        )

    # 1) Одно имя — несколько строк
    by_name: dict[str, list[PlayerRow]] = defaultdict(list)
    for r in rows:
        by_name[_norm_cmp(r.name)].append(r)
    for grp in by_name.values():
        if len(grp) < 2:
            continue
        teams = {r.team for r in grp}
        pos = {r.position for r in grp}
        if len(pos) < 2 and len(teams) < 2:
            continue
        _add(_classify(grp), "same_name", grp)

    # 2) Алиас в клубе: resolve_canonical_name сводит к одному имени
    by_team_canon: dict[tuple[str, str], list[PlayerRow]] = defaultdict(list)
    for r in rows:
        if not r.team or r.team == "—":
            continue
        canon = resolve_canonical_name(r.team, r.name)
        by_team_canon[(r.team, _norm_cmp(canon))].append(r)
    for grp in by_team_canon.values():
        if len({_norm_cmp(r.name) for r in grp}) < 2:
            continue
        _add("different_names", "alias", grp)

    # 3) Разные имена, полное совпадение профиля: клуб + поз + нация + рейтинг + м/г/п
    by_profile: dict[tuple[str, str, str, int, int, int, int], list[PlayerRow]] = defaultdict(
        list
    )
    for r in rows:
        if not r.team or r.team == "—":
            continue
        if _norm_cmp(r.team) == _norm_cmp(FREE_AGENT_TEAM):
            continue
        by_profile[
            (
                r.team,
                r.position,
                _norm_cmp(r.nation),
                r.overall,
                r.matches,
                r.goals,
                r.assists,
            )
        ].append(r)
    for grp in by_profile.values():
        if len({_norm_cmp(r.name) for r in grp}) < 2:
            continue
        _add("different_names", "profile", grp)

    out.sort(key=lambda g: (g.kind, g.title.lower()))
    return out


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

    _MATCH_RU = {
        "same_name": "одно имя",
        "alias": "алиас в player_name_aliases.json",
        "profile": "совпали клуб, позиция, нация, м/г/п",
    }

    if args.json:
        payload = []
        for g in groups:
            payload.append(
                {
                    "kind": g.kind,
                    "kind_ru": _KIND_RU.get(g.kind, g.kind),
                    "match": g.match,
                    "match_ru": _MATCH_RU.get(g.match, g.match),
                    "title": g.title,
                    "rows": [asdict(r) for r in g.rows],
                }
            )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    db_paths = ", ".join(p for _, p in paths)
    print(f"Скан: {db_paths}")
    print(f"Групп дублей: {len(groups)}\n")

    by_kind: dict[str, list[DuplicateGroup]] = defaultdict(list)
    for g in groups:
        by_kind[g.kind].append(g)

    for kind in (
        "different_names",
        "clubs_and_positions",
        "multiple_clubs",
        "multiple_positions",
        "other",
    ):
        items = by_kind.get(kind) or []
        if not items:
            continue
        print(f"{'=' * 72}")
        print(f"{_KIND_RU[kind]} — {len(items)}")
        print(f"{'=' * 72}\n")
        for g in sorted(
            items,
            key=lambda x: (-max(r.matches for r in x.rows), x.title.lower()),
        ):
            grp = g.rows
            teams = sorted({r.team for r in grp})
            pos = sorted({r.position for r in grp})
            print(
                f"{g.title}  ({len(grp)} строк · {_MATCH_RU.get(g.match, g.match)} · "
                f"клубы: {', '.join(teams)} · поз: {', '.join(pos)})"
            )
            for r in grp:
                canon = resolve_canonical_name(r.team, r.name)
                extra = ""
                if _norm_cmp(canon) != _norm_cmp(r.name):
                    extra = f" → канон. «{canon}»"
                print(r.line() + extra)
            print()


if __name__ == "__main__":
    main()
