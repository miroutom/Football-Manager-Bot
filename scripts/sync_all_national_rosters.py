#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Синхронизация заявок **всех** национальных лиг из Python-модулей в рабочие БД (лига + ЛЧ + common).

Источник: ``utils.merged_national_squads`` (АПЛ, Бундес, Серия А, Ла Лига, РПЛ).

По умолчанию **без prune**: не удаляются игроки, которых нет в заявке (меньше риска потерять
статистику из‑за опечатки в имени). Обновляются только ``overall``, ``position``, ``nation``,
``status``; при смене позиции строка переносится между таблицами с сохранением матчевой статы.

  python scripts/sync_all_national_rosters.py
  python scripts/sync_all_national_rosters.py --prune
  python scripts/sync_all_national_rosters.py --no-common-rebuild
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> None:
    p = argparse.ArgumentParser(description="Синк заявок всех нац. лиг в рабочие SQLite.")
    p.add_argument(
        "--prune",
        action="store_true",
        help="Удалить из команд игроков, которых нет в заявке (осторожно с именами).",
    )
    p.add_argument(
        "--no-common-rebuild",
        action="store_true",
        help="Не вызывать rebuild_common_database() после синка.",
    )
    args = p.parse_args()

    from utils.squad_roster_sync import run_all_national_leagues_roster_sync

    out = run_all_national_leagues_roster_sync(
        prune=args.prune,
        rebuild_common=not args.no_common_rebuild,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
