# -*- coding: utf-8 -*-
"""
Вызовы в сборные ЧМ: игроки клубов по полю ``nation`` → ``world_cup_squads.json``.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from utils import season_paths
from utils.world_cup import load_wc_squads, save_wc_squads
from utils.world_cup_format import flatten_nations
from utils.world_cup import nations_by_confederation


def _norm_nat(s: str) -> str:
    t = (s or "").strip().casefold().replace("ё", "е")
    for a, b in (("’", "'"), ("`", "'"), ("´", "'"), ("ʻ", "'"), ("ʼ", "'")):
        t = t.replace(a, b)
    return " ".join(t.split())


def resolve_nation_name(raw: str) -> str | None:
    """Найти каноническое имя сборной из конфига (без регистра)."""
    want = _norm_nat(raw)
    if not want:
        return None
    for name in flatten_nations(nations_by_confederation()):
        if _norm_nat(name) == want:
            return name
    return None


def club_players_for_nation(nation: str, *, limit: int = 120) -> list[dict[str, Any]]:
    """
    Игроки из ``league.db`` с ``nation`` ≈ сборной.
    Сортировка: overall desc, имя.
    """
    canon = resolve_nation_name(nation) or (nation or "").strip()
    want = _norm_nat(canon)
    if not want:
        return []

    from data.defender import Defender
    from data.forward import Forward
    from data.goalkeeper import Goalkeeper
    from data.midfielder import Midfielder

    path = season_paths.get_league_db_path()
    eng = create_engine(f"sqlite:///{path}")
    Session = sessionmaker(bind=eng)
    rows: list[dict[str, Any]] = []
    try:
        with Session() as session:
            for Cls in (Forward, Midfielder, Defender, Goalkeeper):
                for r in session.query(Cls).all():
                    nat = getattr(r, "nation", None) or ""
                    if _norm_nat(str(nat)) != want:
                        continue
                    left = bool(getattr(r, "left_team", False))
                    if left:
                        continue
                    name = (getattr(r, "name", None) or "").strip()
                    if not name:
                        continue
                    rows.append(
                        {
                            "name": name,
                            "club": (getattr(r, "team", None) or "").strip(),
                            "position": (getattr(r, "position", None) or "").strip(),
                            "overall": int(getattr(r, "overall", 0) or 0),
                            "nation": canon,
                        }
                    )
    finally:
        eng.dispose()

    # дедуп по имени (один игрок мог продублироваться редко)
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for p in sorted(rows, key=lambda x: (-int(x["overall"]), x["name"].casefold())):
        k = p["name"].casefold()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(p)
        if len(uniq) >= limit:
            break
    return uniq


def squad_for_nation(nation: str) -> list[dict[str, Any]]:
    data = load_wc_squads()
    canon = resolve_nation_name(nation) or (nation or "").strip()
    teams = data.get("teams") or {}
    roster = teams.get(canon) or []
    if not isinstance(roster, list):
        return []
    return [dict(x) for x in roster if isinstance(x, dict)]


def is_called_up(nation: str, player_name: str) -> bool:
    want = (player_name or "").strip().casefold()
    return any(str(p.get("name") or "").casefold() == want for p in squad_for_nation(nation))


def toggle_callup(
    nation: str,
    *,
    name: str,
    club: str = "",
    position: str = "",
    overall: int = 0,
) -> tuple[bool, dict[str, Any]]:
    """
    Добавить или убрать вызов. Возвращает (сейчас_в_заявке, entry).
    """
    canon = resolve_nation_name(nation) or (nation or "").strip()
    if not canon:
        raise ValueError("Неизвестная сборная")
    data = load_wc_squads()
    data["season"] = season_paths.get_active_season()
    teams = data.setdefault("teams", {})
    roster: list = teams.setdefault(canon, [])
    want = (name or "").strip().casefold()
    for i, row in enumerate(list(roster)):
        if str(row.get("name") or "").casefold() == want:
            roster.pop(i)
            save_wc_squads(data)
            return False, dict(row)
    entry = {
        "name": (name or "").strip(),
        "club": (club or "").strip(),
        "position": (position or "").strip(),
        "overall": int(overall or 0),
        "source": "callup",
    }
    roster.append(entry)
    save_wc_squads(data)
    return True, entry


def squad_summary_html(nation: str | None = None) -> str:
    data = load_wc_squads()
    teams = data.get("teams") or {}
    if nation:
        canon = resolve_nation_name(nation) or nation
        roster = teams.get(canon) or []
        lines = [f"<b>Заявка · {canon}</b>", f"Игроков: <b>{len(roster)}</b>", ""]
        for p in sorted(roster, key=lambda x: (-int(x.get("overall") or 0), str(x.get("name") or "").casefold())):
            lines.append(
                f"· {p.get('name')} · {p.get('position') or '—'} · "
                f"{p.get('overall') or '—'} · {p.get('club') or '—'}"
            )
        return "\n".join(lines) if roster else f"<b>{canon}</b>\nЗаявка пуста."
    filled = sum(1 for v in teams.values() if isinstance(v, list) and v)
    total_players = sum(len(v) for v in teams.values() if isinstance(v, list))
    return (
        f"<b>Вызовы ЧМ</b>\n"
        f"Сборных с заявкой: <b>{filled}</b> / 48\n"
        f"Всего игроков: <b>{total_players}</b>"
    )
