#!/usr/bin/env python3
"""
Импорт имён из CSV (export_player_name_roster.py).

Обновляет только ``name`` и ``surname`` по (table, id), стата не трогается.

  python3 scripts/import_player_names.py --season 2 data/season2_player_names.csv
  python3 scripts/import_player_names.py --season 2 data/season2_player_names.csv --apply
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.migrate_player_surname import migrate_all_player_surname_columns
from utils.player_names import is_empty_first_name_value
from utils.player_transfer import normalize_player_name_for_db

_TABLE_TO_CLS = {
    "forwards": Forward,
    "midfielders": Midfielder,
    "defenders": Defender,
    "goalkeepers": Goalkeeper,
}


def _first_name_from_csv(raw: str) -> str:
    """Пустая ячейка или «-» → нет отдельного имени (прозвище в surname)."""
    s = normalize_player_name_for_db(raw)
    if is_empty_first_name_value(s):
        return ""
    return s


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv_path", help="Файл из export_player_name_roster.py")
    ap.add_argument("--season", type=int, default=2)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(args.csv_path):
        print(f"Нет файла: {args.csv_path}")
        sys.exit(1)

    migrate_all_player_surname_columns()

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    path = os.path.join(ROOT, "db", f"season_{args.season}", "league.db")
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    updated = 0
    missing = 0
    try:
        with open(args.csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                tbl = (row.get("table") or "").strip().lower()
                rid = int(row.get("id") or 0)
                Cls = _TABLE_TO_CLS.get(tbl)
                if Cls is None or not rid:
                    continue
                r = session.get(Cls, rid)
                if r is None:
                    missing += 1
                    continue
                fn = _first_name_from_csv(row.get("first_name") or "")
                sn = (
                    normalize_player_name_for_db(row.get("surname") or "")
                    or fn
                    or (getattr(r, "surname", None) or "")
                )
                if not sn:
                    continue
                old_fn = (getattr(r, "name", None) or "").strip()
                old_sn = (getattr(r, "surname", None) or "").strip()
                if old_fn == fn and old_sn == sn:
                    continue
                print(
                    f"  {tbl} id={rid} {(r.team or '').strip()}: "
                    f"«{old_fn or '—'} {old_sn}» → «{fn or '—'} {sn}»"
                )
                if args.apply:
                    r.name = fn
                    r.surname = sn
                updated += 1
        if args.apply:
            session.commit()
            from utils.common_db import rebuild_common_database

            rebuild_common_database()
            print(f"\n✓ Обновлено {updated} строк, common.db пересобран.")
        else:
            print(f"\n(dry-run) Будет обновлено {updated} строк, нет в БД: {missing}")
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    main()
