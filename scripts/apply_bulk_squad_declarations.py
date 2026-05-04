#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Временное применение текстовых заявок в том же формате, что «Полная заявка» в боте.

Файл по умолчанию: data/bulk_squads_apply.txt — блоки, начинающиеся со строки ``@НазваниеКлуба``,
далее тело заявки (секции ``==== start ===`` и т.д.).

  python3 scripts/apply_bulk_squad_declarations.py
  python3 scripts/apply_bulk_squad_declarations.py path/to/file.txt --dry-run

Пишет в рабочие БД через ``apply_team_squad_declaration`` (статусы как в тексте, без каскада).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


TEAM_ALIASES: dict[str, str] = {
    "атлетик (бильбао)": "Атлетик",
    "атлетик бильбао": "Атлетик",
    "бильбао": "Атлетик",
}


def split_bulk_blocks(text: str) -> list[tuple[str, str]]:
    """Разбить текст на пары (первая строка блока — имя клуба, остальное — заявка)."""
    text = (text or "").strip()
    if not text:
        return []
    parts = re.split(r"(?m)^@\s*", text)
    out: list[tuple[str, str]] = []
    for block in parts:
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        team_line = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        if not team_line or not body:
            continue
        out.append((team_line, body))
    return out


def resolve_team_label(raw: str) -> str:
    from config.squad_team_aliases import canonical_team_name

    s = raw.strip()
    key = s.casefold()
    if key in TEAM_ALIASES:
        return TEAM_ALIASES[key]
    return canonical_team_name(s)


def main() -> int:
    p = argparse.ArgumentParser(description="Применить заявки из файла @Клуб.")
    p.add_argument(
        "file",
        nargs="?",
        default=str(_ROOT / "data" / "bulk_squads_apply.txt"),
        help="UTF-8 текст с блоками @Команда",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Только разбор, без записи в БД",
    )
    args = p.parse_args()
    path = Path(args.file)
    if not path.is_file():
        print("Файл не найден:", path, file=sys.stderr)
        return 1

    from utils.roster_manual import apply_team_squad_declaration, parse_squad_declaration_text

    text = path.read_text(encoding="utf-8")
    blocks = split_bulk_blocks(text)
    if not blocks:
        print("Нет блоков вида «@Команда» с телом заявки.", file=sys.stderr)
        return 1

    exit_code = 0
    for team_raw, body in blocks:
        team = resolve_team_label(team_raw)
        entries, errors = parse_squad_declaration_text(body)
        if errors:
            print(f"--- Ошибки разбора: {team} (исходная строка: {team_raw!r}) ---", file=sys.stderr)
            for e in errors:
                print(e, file=sys.stderr)
            exit_code = 1
            continue
        if args.dry_run:
            print(f"OK {team}: {len(entries)} строк заявки")
            continue
        try:
            r = apply_team_squad_declaration(team, entries)
        except Exception as ex:
            print(f"{team}: ошибка применения: {ex}", file=sys.stderr)
            exit_code = 1
            continue
        print(
            f"{team}: заявлено {r['declared']}, снято с состава/СА: {r['released']}"
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
