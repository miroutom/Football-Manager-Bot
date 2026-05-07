#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Восстановить статистику игроков, которые оказались в Free Agent со старой позицией.

Кейсы из заявки:
- Нгамалу ЛФА -> Нгамалу ПФА (Зенит)
- Телла ЛФА -> Телла ПФА (Краснодар)
- Кокшаров ЦАП -> Кокшаров ФРВ (Краснодар)
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _apply_carry_to_row(row, carry: dict) -> None:
    for key, val in carry.items():
        if hasattr(row, key):
            setattr(row, key, int(val or 0))


def _merge_one(
    sess,
    *,
    src_team: str,
    src_name: str,
    src_pos: str,
    dst_team: str,
    dst_name: str,
    dst_pos: str,
) -> tuple[bool, str]:
    from utils.player_field_edit import find_player_row
    from utils.squad_roster_sync import _carry_from_row, _merge_carry_dicts

    _Cls_s, src = find_player_row(sess, src_team, src_name, src_pos)
    _Cls_d, dst = find_player_row(sess, dst_team, dst_name, dst_pos)
    if src is None and dst is None:
        return False, f"нет ни источника, ни цели: {src_name} {src_pos} -> {dst_team}"
    if dst is None:
        return False, f"нет целевой строки: {dst_team} {dst_name} {dst_pos}"
    if src is None:
        return False, f"источник не найден (возможно уже перенесено): {src_name} {src_pos}"

    c_src = _carry_from_row(src)
    c_dst = _carry_from_row(dst)
    merged = _merge_carry_dicts(c_dst, c_src)
    _apply_carry_to_row(dst, merged)
    sess.delete(src)
    return True, (
        f"{src_name} {src_pos} -> {dst_team} {dst_name} {dst_pos} | "
        f"matches {int(c_dst.get('matches', 0) or 0)} + {int(c_src.get('matches', 0) or 0)}"
    )


def main() -> int:
    from utils.common_db import _team_in_cl_pool, rebuild_common_database
    from utils.utils import session_cl, session_league

    mappings = [
        ("Free Agent", "Нгамалу", "ЛФА", "Зенит", "Нгамалу", "ПФА"),
        ("Free Agent", "Телла", "ЛФА", "Краснодар", "Телла", "ПФА"),
        ("Free Agent", "Кокшаров", "ЦАП", "Краснодар", "Кокшаров", "ФРВ"),
    ]

    out: list[str] = []
    had_error = False

    try:
        for src_team, src_name, src_pos, dst_team, dst_name, dst_pos in mappings:
            ok_l, msg_l = _merge_one(
                session_league,
                src_team=src_team,
                src_name=src_name,
                src_pos=src_pos,
                dst_team=dst_team,
                dst_name=dst_name,
                dst_pos=dst_pos,
            )
            out.append(f"league: {'OK' if ok_l else 'SKIP'} - {msg_l}")
            if (not ok_l) and ("нет целевой строки" in msg_l):
                had_error = True
            if _team_in_cl_pool(dst_team):
                ok_c, msg_c = _merge_one(
                    session_cl,
                    src_team=src_team,
                    src_name=src_name,
                    src_pos=src_pos,
                    dst_team=dst_team,
                    dst_name=dst_name,
                    dst_pos=dst_pos,
                )
                out.append(f"cl: {'OK' if ok_c else 'SKIP'} - {msg_c}")
                if (not ok_c) and ("нет целевой строки" in msg_c):
                    had_error = True
        session_league.commit()
        session_cl.commit()
    except Exception:
        session_league.rollback()
        session_cl.rollback()
        raise

    rebuild_common_database()
    print("\n".join(out))
    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())

