#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Имя == фамилия: подставить имя из names.xlsx по клубу назначения из transfers.json.

Для строки в клубе «откуда» (стата осталась) берётся последний трансфер с этим клубом
и фамилия в журнале; имя ищется в xlsx у клуба «куда».

Также удаляет заведомо лишние нулевые строки (см. ``SEASON2_ORPHAN_DELETES``).

  python3 scripts/fix_placeholder_names_from_transfers.py --season 2
  python3 scripts/fix_placeholder_names_from_transfers.py --season 2 --apply
"""
from __future__ import annotations

import argparse
import json
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
from player_stats import _norm_cmp
from scripts.import_player_names_xlsx import (
    XlsxPlayer,
    _canonical_xlsx_team,
    load_names_xlsx,
)
from utils.player_transfer import normalize_player_name_for_db
_ALL = (Forward, Midfielder, Defender, Goalkeeper)

# season 2: нулевая стата, дубли в ЛЧ / ошибочные строки (удаляются при --apply)
SEASON2_ORPHAN_DELETES: list[tuple[str, str, str, str, int | None]] = [
    # db_kind, team (подстрока), name, position, id или None
    ("cl", "Боруссия М", "Нгуму", "ПП", 74),
    ("cl", "Боруссия М", "Сиппель", "ВРТ", 23),
    ("cl", "Боруссия М", "Эрманн", "ПП", 76),
    ("cl", "Боруссия М", "Вольф", "ЛП", 75),
    ("league", "Брайтон", "Игорь", "ЦЗ", 19),
    ("common", "Брайтон", "Игорь", "ЦЗ", 1),
    ("cl", "Рома", "Бове", "ЦП", 131),
    ("cl", "Челси", "Броя", "ФРВ", 12),
    ("cl", "Челси", "Петрович", "ВРТ", 4),
    ("cl", "Челси", "Сарр", "ЦЗ", 19),
]

_DB_MAP = {
    "league": "league.db",
    "cl": "champions_league.db",
    "common": "common.db",
}


@dataclass
class TransferRec:
    player: str
    from_team: str
    to_team: str
    position: str
    ts: str


def _load_transfers(path: str) -> list[TransferRec]:
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out: list[TransferRec] = []
    for row in data.get("transfers") or []:
        out.append(
            TransferRec(
                player=(row.get("player") or "").strip(),
                from_team=(row.get("from_team") or "").strip(),
                to_team=(row.get("to_team") or "").strip(),
                position=(row.get("position") or "").strip().upper(),
                ts=(row.get("ts") or ""),
            )
        )
    out.sort(key=lambda t: t.ts)
    return out


def _player_token_matches(transfer_player: str, row_name: str, row_surname: str) -> bool:
    tp = _norm_cmp(transfer_player)
    if not tp:
        return False
    for raw in (row_name, row_surname):
        if _norm_cmp(raw) == tp:
            return True
    return False


def _find_latest_transfer(
    transfers: list[TransferRec],
    *,
    team: str,
    row_name: str,
    row_surname: str,
    position: str,
) -> TransferRec | None:
    team_n = _norm_cmp(team)
    pos_u = (position or "").strip().upper()
    hit: TransferRec | None = None
    for tr in transfers:
        if not _player_token_matches(tr.player, row_name, row_surname):
            continue
        from_n = _norm_cmp(tr.from_team)
        to_n = _norm_cmp(tr.to_team)
        if team_n not in (from_n, to_n):
            continue
        if tr.position and pos_u and tr.position != pos_u:
            continue
        hit = tr
    return hit


def _xlsx_lookup(
    entries: list[XlsxPlayer],
    *,
    team: str,
    surname: str,
    position: str,
    overall: int,
) -> tuple[str, str] | None:
    """Вернуть (first_name, surname) или None."""
    team_cf = _norm_cmp(_canonical_xlsx_team(team))
    sn = _norm_cmp(normalize_player_name_for_db(surname) or surname)
    pos_u = (position or "").strip().upper()
    ovr = int(overall or 0)

    def score(e: XlsxPlayer) -> tuple[int, int]:
        s = 0
        if (e.position or "").strip().upper() == pos_u:
            s += 4
        if int(e.rating or 0) == ovr and ovr > 0:
            s += 2
        if e.first_name:
            s += 1
        return (s, int(e.rating or 0))

    cands: list[XlsxPlayer] = []
    for e in entries:
        if _norm_cmp(_canonical_xlsx_team(e.team)) != team_cf:
            continue
        if _norm_cmp(normalize_player_name_for_db(e.surname_label) or e.surname_label) != sn:
            continue
        cands.append(e)
    if not cands:
        return None
    cands.sort(key=score, reverse=True)
    best = cands[0]
    fn = (best.first_name or "").strip()
    if not fn:
        return None
    sn_out = normalize_player_name_for_db(best.surname_label) or best.surname_label
    return fn, sn_out


def _iter_placeholders(session) -> list[tuple[type, object]]:
    out: list[tuple[type, object]] = []
    for Cls in _ALL:
        for r in session.query(Cls).all():
            n = (getattr(r, "name", None) or "").strip()
            s = (getattr(r, "surname", None) or "").strip()
            if n and s and n.casefold() == s.casefold():
                out.append((Cls, r))
    return out


def _plan_renames(
    season: int,
    transfers: list[TransferRec],
    xlsx_entries: list[XlsxPlayer],
) -> list[dict]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    plans: list[dict] = []
    for db_kind, fname in _DB_MAP.items():
        path = os.path.join(ROOT, "db", f"season_{season}", fname)
        if not os.path.isfile(path):
            continue
        eng = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(eng)
        Sess = sessionmaker(bind=eng)
        sess = Sess()
        try:
            for Cls, row in _iter_placeholders(sess):
                team = (getattr(row, "team", None) or "").strip()
                if not team or team.casefold() == "free agent":
                    continue
                name = (getattr(row, "name", None) or "").strip()
                surname = (getattr(row, "surname", None) or "").strip()
                pos = (getattr(row, "position", None) or "").strip().upper()
                ovr = int(getattr(row, "overall", 0) or 0)

                xlsx_team = team
                tr = _find_latest_transfer(
                    transfers,
                    team=team,
                    row_name=name,
                    row_surname=surname,
                    position=pos,
                )
                source = "xlsx@club"
                if tr:
                    from_n = _norm_cmp(tr.from_team)
                    to_n = _norm_cmp(tr.to_team)
                    team_n = _norm_cmp(team)
                    if team_n == from_n:
                        xlsx_team = tr.to_team
                        source = f"transfer→{tr.to_team}"
                    elif team_n == to_n:
                        xlsx_team = tr.to_team
                        source = f"transfer@dest"
                    else:
                        xlsx_team = tr.to_team
                        source = f"transfer?→{tr.to_team}"

                hit = _xlsx_lookup(
                    xlsx_entries,
                    team=xlsx_team,
                    surname=surname,
                    position=pos,
                    overall=ovr,
                )
                if not hit:
                    plans.append(
                        {
                            "action": "skip",
                            "db": db_kind,
                            "id": int(row.id),
                            "team": team,
                            "name": name,
                            "position": pos,
                            "reason": f"нет в xlsx ({source}, клуб {xlsx_team})",
                        }
                    )
                    continue
                new_name, new_surname = hit
                if _norm_cmp(new_name) == _norm_cmp(name) and _norm_cmp(
                    new_surname
                ) == _norm_cmp(surname):
                    continue
                plans.append(
                    {
                        "action": "rename",
                        "db": db_kind,
                        "table": Cls.__tablename__,
                        "id": int(row.id),
                        "team": team,
                        "position": pos,
                        "old_name": name,
                        "old_surname": surname,
                        "new_name": new_name,
                        "new_surname": new_surname,
                        "source": source,
                        "xlsx_team": xlsx_team,
                        "transfer": (
                            f"{tr.from_team}→{tr.to_team}" if tr else "—"
                        ),
                    }
                )
        finally:
            sess.close()
            eng.dispose()
    return plans


def _apply_renames(plans: list[dict], season: int) -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    by_db: dict[str, list[dict]] = {}
    for p in plans:
        if p.get("action") != "rename":
            continue
        by_db.setdefault(p["db"], []).append(p)

    n = 0
    for db_kind, items in by_db.items():
        path = os.path.join(ROOT, "db", f"season_{season}", _DB_MAP[db_kind])
        eng = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(eng)
        Sess = sessionmaker(bind=eng)
        sess = Sess()
        try:
            tbl_map = {c.__tablename__: c for c in _ALL}
            for p in items:
                Cls = tbl_map.get(p["table"])
                if not Cls:
                    continue
                row = sess.get(Cls, p["id"])
                if row is None:
                    continue
                row.name = p["new_name"]
                if hasattr(row, "surname"):
                    row.surname = p["new_surname"]
                n += 1
            sess.commit()
        finally:
            sess.close()
            eng.dispose()
    return n


def _apply_orphan_deletes(season: int, deletes: list[tuple]) -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    if season != 2:
        return 0
    n = 0
    for db_kind, team_sub, name, position, rid in deletes:
        path = os.path.join(ROOT, "db", f"season_{season}", _DB_MAP[db_kind])
        if not os.path.isfile(path):
            continue
        eng = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(eng)
        Sess = sessionmaker(bind=eng)
        sess = Sess()
        try:
            for Cls in _ALL:
                for row in list(sess.query(Cls).all()):
                    if rid is not None and int(row.id) != int(rid):
                        continue
                    t = (getattr(row, "team", None) or "").strip()
                    if team_sub.casefold() not in t.casefold():
                        continue
                    if _norm_cmp(getattr(row, "name", None) or "") != _norm_cmp(
                        name
                    ):
                        continue
                    if (getattr(row, "position", None) or "").strip().upper() != (
                        position or ""
                    ).strip().upper():
                        continue
                    sess.delete(row)
                    n += 1
                    break
            sess.commit()
        finally:
            sess.close()
            eng.dispose()
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--xlsx",
        default=os.path.join(ROOT, "db", "names.xlsx"),
    )
    ap.add_argument(
        "--transfers",
        default=os.path.join(ROOT, "data", "transfers.json"),
    )
    args = ap.parse_args()

    xlsx_entries = load_names_xlsx(args.xlsx)
    transfers = _load_transfers(args.transfers)
    print(f"Сезон {args.season}: xlsx={len(xlsx_entries)} строк, трансферов={len(transfers)}")

    if args.apply and args.season == 2:
        d = _apply_orphan_deletes(args.season, SEASON2_ORPHAN_DELETES)
        print(f"Удалено orphan-строк: {d}")

    plans = _plan_renames(args.season, transfers, xlsx_entries)
    renames = [p for p in plans if p.get("action") == "rename"]
    skips = [p for p in plans if p.get("action") == "skip"]

    for p in renames:
        print(
            f"{'APPLY' if args.apply else 'rename'}  s{args.season}:{p['db']:<6} "
            f"{p['team']:<12} {p['old_name']}/{p['old_surname']} → "
            f"{p['new_name']}/{p['new_surname']}  {p['position']}  "
            f"id={p['id']}  [{p['source']}; журнал {p['transfer']}; xlsx {p['xlsx_team']}]"
        )
    for p in skips[:30]:
        print(
            f"skip   s{args.season}:{p['db']:<6} {p['team']:<12} {p['name']} "
            f"{p['position']} id={p['id']} — {p['reason']}"
        )
    if len(skips) > 30:
        print(f"… ещё skip: {len(skips) - 30}")

    print(f"\nИтого: rename={len(renames)}, skip={len(skips)}")
    if args.apply:
        n = _apply_renames(renames, args.season)
        print(f"Записано имён: {n}")
    else:
        print("Повторите с --apply для записи.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
