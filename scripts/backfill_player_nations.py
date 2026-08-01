#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Заполнить/исправить поле ``nation`` в league.db активного сезона."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.player_nation import backfill_nation_for_row, nation_to_flagcdn_code
from utils.season_paths import get_league_db_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill player nation in league.db")
    parser.add_argument("--db", type=Path, default=None, help="Path to league.db")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db_path = args.db or Path(get_league_db_path())
    if not db_path.is_file():
        print(f"Нет файла: {db_path}", file=sys.stderr)
        return 1

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()
    updated = 0
    try:
        for Cls in (Forward, Midfielder, Defender, Goalkeeper):
            for row in session.query(Cls).all():
                new_nat = backfill_nation_for_row(
                    row.name,
                    getattr(row, "team", None),
                    getattr(row, "nation", None),
                    session,
                )
                if not new_nat:
                    continue
                old = getattr(row, "nation", None)
                print(f"  {row.name} ({row.team}): {old!r} -> {new_nat!r}")
                if not args.dry_run:
                    row.nation = new_nat
                updated += 1
        if not args.dry_run:
            session.commit()
    finally:
        session.close()
        engine.dispose()

    print(f"{'Would update' if args.dry_run else 'Updated'}: {updated} rows in {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
