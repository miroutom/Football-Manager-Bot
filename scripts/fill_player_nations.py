#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Игроки без поля ``nation`` — список и интерактивный ввод.

Сканирует активный сезон: league.db, champions_league.db, free_agents.db.

  python3 scripts/fill_player_nations.py
  python3 scripts/fill_player_nations.py --list
  python3 scripts/fill_player_nations.py --include-left
  python3 scripts/fill_player_nations.py --export missing_nations.tsv
  python3 scripts/fill_player_nations.py --import missing_nations.tsv --apply
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass, field
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.player_nation import normalize_nation_label
from utils.roster_manual import FREE_AGENT_TEAM
from utils.wc_callups import resolve_nation_name

_ALL = (Forward, Midfielder, Defender, Goalkeeper)
_TABLE_TO_CLS = {
    "forwards": Forward,
    "midfielders": Midfielder,
    "defenders": Defender,
    "goalkeepers": Goalkeeper,
}


@dataclass
class PlayerRef:
    store: str  # league | cl | fa
    table: str
    row_id: int
    name: str
    position: str
    team: str
    overall: int
    left_team: bool
    person_id: int | None = None
    refs: list["PlayerRef"] = field(default_factory=list)

    @property
    def key(self) -> tuple[Any, ...]:
        if self.person_id:
            return ("pid", int(self.person_id))
        return ("row", self.store, self.table, int(self.row_id))

    def label(self) -> str:
        lt = " · left" if self.left_team else ""
        pid = f" · pid={self.person_id}" if self.person_id else ""
        extras = ""
        if self.refs:
            stores = sorted({r.store for r in self.refs if r.store != self.store})
            if stores:
                extras = f" · also: {', '.join(stores)}"
        return (
            f"{self.name} · {self.position} · ovr={self.overall} · {self.team}"
            f" · {self.store}/{self.table}#{self.row_id}{pid}{lt}{extras}"
        )


def _is_blank_nation(raw: Any) -> bool:
    s = (raw or "").strip()
    return not s or s in ("—", "-", "?")


def _load_rows_from_db(
    store: str,
    db_path: str,
    *,
    include_left: bool,
) -> list[PlayerRef]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    if not os.path.isfile(db_path):
        return []

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    out: list[PlayerRef] = []
    try:
        for Cls in _ALL:
            tbl = Cls.__tablename__
            q = session.query(Cls)
            if not include_left and hasattr(Cls, "left_team"):
                q = q.filter((Cls.left_team.is_(False)) | (Cls.left_team.is_(None)))
            for r in q.all():
                if not _is_blank_nation(getattr(r, "nation", None)):
                    continue
                name = (getattr(r, "name", None) or "").strip()
                pos = (getattr(r, "position", None) or "").strip().upper()
                team = (getattr(r, "team", None) or "").strip()
                if not name or not pos:
                    continue
                if store == "fa" and team and team != FREE_AGENT_TEAM:
                    continue
                pid = getattr(r, "person_id", None)
                out.append(
                    PlayerRef(
                        store=store,
                        table=tbl,
                        row_id=int(r.id),
                        name=name,
                        position=pos,
                        team=team or FREE_AGENT_TEAM,
                        overall=int(getattr(r, "overall", 0) or 0),
                        left_team=bool(getattr(r, "left_team", False)),
                        person_id=int(pid) if pid is not None else None,
                    )
                )
    finally:
        session.close()
        engine.dispose()
    return out


def collect_missing(*, include_left: bool) -> list[PlayerRef]:
    from utils import season_paths

    rows: list[PlayerRef] = []
    rows.extend(
        _load_rows_from_db(
            "league",
            season_paths.get_league_db_path(),
            include_left=include_left,
        )
    )
    rows.extend(
        _load_rows_from_db(
            "cl",
            season_paths.get_cl_db_path(),
            include_left=include_left,
        )
    )
    from utils.free_agents_db import get_free_agents_db_path

    rows.extend(
        _load_rows_from_db(
            "fa",
            get_free_agents_db_path(),
            include_left=True,
        )
    )

    grouped: dict[tuple[Any, ...], list[PlayerRef]] = {}
    for r in rows:
        grouped.setdefault(r.key, []).append(r)

    merged: list[PlayerRef] = []
    for refs in grouped.values():
        order = {"league": 0, "cl": 1, "fa": 2}
        refs.sort(key=lambda x: (order.get(x.store, 9), x.team.casefold(), x.name.casefold()))
        primary = refs[0]
        primary.refs = refs
        merged.append(primary)

    merged.sort(
        key=lambda x: (
            x.team.casefold(),
            -x.overall,
            x.name.casefold(),
            x.position,
        )
    )
    return merged


def _normalize_input_nation(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        raise ValueError("пустая нация")
    canon = resolve_nation_name(s)
    if canon:
        return canon
    norm = normalize_nation_label(s)
    if not norm:
        raise ValueError(f"не удалось разобрать нацию: {raw!r}")
    # после алиасов опечаток (франци → Франция) resolve может сработать
    canon = resolve_nation_name(norm)
    if canon:
        return canon
    return norm


def _suggest_nation(raw: str) -> str | None:
    """Подсказка ближайшей сборной ЧМ при опечатке."""
    from utils.world_cup_format import flatten_nations
    from utils.world_cup import nations_by_confederation
    from utils.wc_callups import _norm_nat

    want = _norm_nat(raw)
    if not want or len(want) < 3:
        return None
    best: tuple[int, str] | None = None
    for name in flatten_nations(nations_by_confederation()):
        nn = _norm_nat(name)
        if not nn:
            continue
        if nn.startswith(want) or want.startswith(nn):
            score = abs(len(nn) - len(want))
            if best is None or score < best[0]:
                best = (score, name)
    return best[1] if best is not None and best[0] <= 2 else None


def _apply_nation_to_ref(ref: PlayerRef, nation: str, *, dry_run: bool) -> list[str]:
    logs: list[str] = []
    nation = _normalize_input_nation(nation)
    targets = ref.refs or [ref]

    for t in targets:
        if t.store in ("league", "cl") and not t.left_team:
            if dry_run:
                logs.append(f"  dry-run {t.store} {t.table}#{t.row_id} → {nation}")
                continue
            if t.store == "league":
                from utils.player_field_edit import apply_player_field_update

                apply_player_field_update(
                    t.team,
                    t.name,
                    t.position,
                    "nation",
                    nation,
                    rebuild_common=False,
                    row_id=t.row_id,
                    table=t.table,
                )
                logs.append(f"  league {t.table}#{t.row_id} → {nation}")
            else:
                from utils.player_field_edit import find_player_row_by_pk
                from utils.utils import session_cl

                Cls, row = find_player_row_by_pk(session_cl, t.table, t.row_id)
                if row is None:
                    logs.append(f"  ! cl {t.table}#{t.row_id} не найден")
                    continue
                row.nation = nation
                session_cl.commit()
                logs.append(f"  cl {t.table}#{t.row_id} → {nation}")
            continue

        if dry_run:
            logs.append(f"  dry-run {t.store} {t.table}#{t.row_id} → {nation}")
            continue

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        if t.store == "fa":
            from utils.free_agents_db import get_free_agents_db_path

            db_path = get_free_agents_db_path()
        elif t.store == "league":
            from utils import season_paths

            db_path = season_paths.get_league_db_path()
        else:
            from utils import season_paths

            db_path = season_paths.get_cl_db_path()

        Cls = _TABLE_TO_CLS[t.table]
        engine = create_engine(f"sqlite:///{db_path}")
        Session = sessionmaker(bind=engine)
        session = Session()
        try:
            row = session.get(Cls, t.row_id)
            if row is None:
                logs.append(f"  ! {t.store} {t.table}#{t.row_id} не найден")
                continue
            row.nation = nation
            session.commit()
            logs.append(f"  {t.store} {t.table}#{t.row_id} → {nation}")
        finally:
            session.close()
            engine.dispose()

    if not dry_run and any(t.store == "league" and not t.left_team for t in targets):
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
        logs.append("  common.db пересобран")

    return logs


def _print_list(players: list[PlayerRef]) -> None:
    if not players:
        print("Все игроки с заполненной нацией (в выбранном scope).")
        return
    print(f"Без нации: {len(players)} игрок(ов)\n")
    for i, p in enumerate(players, 1):
        print(f"{i:3}. {p.label()}")


def _export_tsv(path: str, players: list[PlayerRef]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(
            [
                "store",
                "table",
                "row_id",
                "name",
                "position",
                "team",
                "overall",
                "person_id",
                "nation",
            ]
        )
        for p in players:
            w.writerow(
                [
                    p.store,
                    p.table,
                    p.row_id,
                    p.name,
                    p.position,
                    p.team,
                    p.overall,
                    p.person_id or "",
                    "",
                ]
            )
    print(f"Экспорт: {path} ({len(players)} строк, колонка nation — для заполнения)")


def _import_tsv(path: str, *, apply: bool, dry_run: bool) -> int:
    updated = 0
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            nation_raw = (row.get("nation") or "").strip()
            if not nation_raw:
                continue
            ref = PlayerRef(
                store=(row.get("store") or "").strip(),
                table=(row.get("table") or "").strip(),
                row_id=int(row.get("row_id") or 0),
                name=(row.get("name") or "").strip(),
                position=(row.get("position") or "").strip().upper(),
                team=(row.get("team") or "").strip(),
                overall=int(row.get("overall") or 0),
                left_team=False,
                person_id=int(row["person_id"]) if (row.get("person_id") or "").strip() else None,
            )
            if not ref.store or not ref.table or not ref.row_id:
                print(f"! пропуск строки без store/table/row_id: {row}")
                continue
            print(ref.label())
            try:
                nation = _normalize_input_nation(nation_raw)
            except ValueError as e:
                print(f"  ! {e}")
                continue
            if not apply:
                print(f"  → {nation} (dry/import preview)")
                updated += 1
                continue
            for line in _apply_nation_to_ref(ref, nation, dry_run=dry_run):
                print(line)
            updated += 1
    print(f"\n{'Будет обновлено' if not apply else 'Обновлено'}: {updated}")
    return 0


def _interactive(players: list[PlayerRef], *, dry_run: bool) -> int:
    if not players:
        return 0

    print(
        "Интерактивный ввод наций.\n"
        "  Enter — пропустить\n"
        "  q — выйти\n"
        "  s — пропустить оставшихся\n"
    )
    updated = 0
    for i, p in enumerate(players, 1):
        print(f"\n[{i}/{len(players)}] {p.label()}")
        try:
            raw = input("Нация: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nВыход.")
            break
        low = raw.casefold()
        if low in ("q", "quit", "exit"):
            break
        if low in ("s", "skip rest", "skip"):
            print("Оставшиеся пропущены.")
            break
        if not raw:
            continue
        try:
            nation = _normalize_input_nation(raw)
        except ValueError as e:
            hint = _suggest_nation(raw)
            print(f"  ! {e}" + (f" · может, «{hint}»?" if hint else ""))
            continue
        warn = ""
        if resolve_nation_name(nation) is None:
            hint = _suggest_nation(raw)
            warn = " (не в списке сборных ЧМ"
            if hint and hint != nation:
                warn += f", может «{hint}»"
            warn += ")"
        elif nation != raw.strip() and raw.strip().casefold() != nation.casefold():
            warn = f" (из «{raw.strip()}»)"
        print(f"  → {nation}{warn}")
        for line in _apply_nation_to_ref(p, nation, dry_run=dry_run):
            print(line)
        updated += 1

    print(f"\n{'Было бы обновлено' if dry_run else 'Обновлено'}: {updated}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Список игроков без nation и интерактивный ввод")
    parser.add_argument("--list", action="store_true", help="Только список, без вопросов")
    parser.add_argument(
        "--include-left",
        action="store_true",
        help="Включить игроков с left_team=True",
    )
    parser.add_argument("--dry-run", action="store_true", help="Не писать в БД")
    parser.add_argument("--export", metavar="FILE.tsv", help="Экспорт в TSV для заполнения offline")
    parser.add_argument(
        "--import",
        dest="import_path",
        metavar="FILE.tsv",
        help="Импорт колонки nation из TSV (--apply чтобы записать)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="С --import: записать nation в БД",
    )
    args = parser.parse_args()

    from utils import season_paths

    season = season_paths.get_active_season()
    print(f"Сезон {season}")

    players = collect_missing(include_left=args.include_left)

    if args.export:
        _export_tsv(args.export, players)
        return 0

    if args.import_path:
        return _import_tsv(
            args.import_path,
            apply=args.apply,
            dry_run=args.dry_run,
        )

    _print_list(players)
    if args.list or not players:
        return 0

    return _interactive(players, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
