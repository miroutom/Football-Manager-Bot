#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Выгрузка списка трансферов из transfer_window_state.json."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="Список трансферов: игрок, клуб из, клуб в.")
    p.add_argument(
        "state",
        nargs="?",
        default=str(_ROOT / "data" / "transfer_window" / "transfer_window_state_s3.json"),
        help="transfer_window_state.json",
    )
    p.add_argument(
        "-o",
        "--out",
        default="",
        help="Путь к .txt (по умолчанию рядом со state: transfers_export.txt)",
    )
    p.add_argument(
        "--simple",
        action="store_true",
        help="Только три колонки: Игрок, Клуб (из), Клуб (в)",
    )
    p.add_argument(
        "--xlsx",
        action="store_true",
        help="Дополнительно сохранить .xlsx",
    )
    args = p.parse_args()

    state_path = Path(args.state)
    if not state_path.is_file():
        print("Файл не найден:", state_path, file=sys.stderr)
        return 1

    from tools.transfer_window_app.main import (
        _write_export_txt,
        _write_export_xlsx,
        compute_transfers,
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    rows = state.get("transfers") or compute_transfers(state)
    out_txt = Path(args.out) if args.out else state_path.parent / "transfers_export.txt"

    if args.simple:
        lines = ["Игрок\tКлуб (из)\tКлуб (в)"]
        for r in rows:
            lines.append(f"{r['name']}\t{r['from_team']}\t{r['to_team']}")
        out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        _write_export_txt(out_txt, rows)

    print(f"Трансферов: {len(rows)} → {out_txt}")

    if args.xlsx:
        out_xlsx = out_txt.with_suffix(".xlsx")
        try:
            _write_export_xlsx(out_xlsx, rows)
            print(f"XLSX → {out_xlsx}")
        except ImportError:
            print("openpyxl не установлен, xlsx пропущен", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
