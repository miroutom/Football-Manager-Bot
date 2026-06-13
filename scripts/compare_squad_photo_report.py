#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сверка заявки из bulk-файла (@Клуб) с текущей БД — отчёт для dry-run.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="Сверка bulk-заявки с league.db")
    p.add_argument("file", help="Файл с блоком @Клуб")
    args = p.parse_args()
    path = Path(args.file)
    if not path.is_file():
        print("Файл не найден:", path, file=sys.stderr)
        return 1

    from scripts.apply_bulk_squad_declarations import resolve_team_label, split_bulk_blocks
    from utils.roster_manual import parse_squad_declaration_text
    from utils.player_transfer import _filter_team, _norm_cmp
    from utils.utils import session_league
    from data.forward import Forward
    from data.midfielder import Midfielder
    from data.defender import Defender
    from data.goalkeeper import Goalkeeper

    text = path.read_text(encoding="utf-8")
    blocks = split_bulk_blocks(text)
    if len(blocks) != 1:
        print(f"Ожидался один блок @Клуб, найдено {len(blocks)}", file=sys.stderr)
        return 1

    team_raw, body = blocks[0]
    team = resolve_team_label(team_raw)
    entries, errors = parse_squad_declaration_text(body)
    if errors:
        for e in errors:
            print("Ошибка:", e, file=sys.stderr)
        return 1

    db_rows: dict[tuple[str, str], dict] = {}
    for Cls in (Goalkeeper, Defender, Midfielder, Forward):
        for r in session_league.query(Cls).filter(_filter_team(Cls, team)).all():
            from utils.player_transfer import normalize_player_name_for_db
            from utils.transfer_input import normalize_position

            nm = normalize_player_name_for_db(r.name or "")
            pos = normalize_position(r.position or "")
            st = (getattr(r, "status", None) or "bench").strip().lower()
            if st not in ("start", "bench", "reserve"):
                st = "bench"
            key = (_norm_cmp(nm), _norm_cmp(pos))
            slot = (getattr(r, "lineup_slot", None) or "").strip().upper() or None
            db_rows[key] = {
                "name": nm,
                "pos": pos,
                "ovr": int(r.overall or 0),
                "status": st,
                "slot": slot,
            }

    want: dict[tuple[str, str], dict] = {}
    for nm, pos, st, ovr, _nat, slot in entries:
        key = (_norm_cmp(nm), _norm_cmp(pos))
        want[key] = {
            "name": nm,
            "pos": pos,
            "ovr": int(ovr) if ovr is not None else None,
            "status": st,
            "slot": (slot or "").strip().upper() or None if st == "start" else None,
        }

    print(f"=== {team} — сверка с фото ===\n")

    changes: list[str] = []
    for key, w in sorted(want.items(), key=lambda x: (x[1]["status"], -x[1].get("ovr") or 0)):
        db = db_rows.get(key)
        if db is None:
            changes.append(f"+ ДОБАВИТЬ  {w['name']} {w['pos']} {w['ovr']} {w['status']}")
            continue
        parts = []
        if db["ovr"] != w["ovr"] and w["ovr"] is not None:
            parts.append(f"ovr {db['ovr']}→{w['ovr']}")
        if db["status"] != w["status"]:
            parts.append(f"status {db['status']}→{w['status']}")
        if w["status"] == "start" and db.get("slot") != w.get("slot"):
            parts.append(f"slot {db.get('slot') or '—'}→{w.get('slot') or '—'}")
        if parts:
            changes.append(f"~ {w['name']} {w['pos']}: {', '.join(parts)}")

    for key, db in sorted(db_rows.items(), key=lambda x: x[1]["name"].lower()):
        if key not in want:
            changes.append(
                f"- УБРАТЬ    {db['name']} {db['pos']} {db['ovr']} ({db['status']})"
            )

    if not changes:
        print("Изменений нет — БД совпадает с заявкой.")
    else:
        print("Изменения:")
        for line in changes:
            print(line)

    print(f"\nВ заявке: {len(want)} · в БД: {len(db_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
