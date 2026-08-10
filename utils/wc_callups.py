# -*- coding: utf-8 -*-
"""
Вызовы в сборные ЧМ: игроки клубов по полю ``nation`` → ``world_cup_squads.json``.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from utils import season_paths
from utils.roster_manual import FREE_AGENT_TEAM
from utils.wc_squad_quota import (
    WC_TOTAL,
    evaluate_wc_squad,
    format_wc_quota_summary_html,
)
from utils.world_cup import load_wc_squads, nations_by_confederation, save_wc_squads
from utils.world_cup_format import flatten_nations


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
    Игроки из ``league.db`` с ``nation`` ≈ сборной + свободные агенты той же нации.
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
    from utils.player_nation import effective_player_nation
    from utils.roster_manual import FREE_AGENT_TEAM

    path = season_paths.get_league_db_path()
    eng = create_engine(f"sqlite:///{path}")
    Session = sessionmaker(bind=eng)
    rows: list[dict[str, Any]] = []
    try:
        with Session() as session:
            for Cls in (Forward, Midfielder, Defender, Goalkeeper):
                for r in session.query(Cls).all():
                    left = bool(getattr(r, "left_team", False))
                    if left:
                        continue
                    name = (getattr(r, "name", None) or "").strip()
                    if not name:
                        continue
                    team = (getattr(r, "team", None) or "").strip()
                    db_nat = getattr(r, "nation", None) or ""
                    nat = effective_player_nation(name, team, db_nat or None, session)
                    if not nat or _norm_nat(str(nat)) != want:
                        continue
                    rows.append(
                        {
                            "name": name,
                            "club": team,
                            "position": (getattr(r, "position", None) or "").strip(),
                            "overall": int(getattr(r, "overall", 0) or 0),
                            "nation": canon,
                            "source": "club",
                            "person_id": getattr(r, "person_id", None),
                        }
                    )

            from utils.free_agents_db import list_free_agents

            for p in list_free_agents():
                name = p.get("name") or ""
                db_nat = p.get("nation") or ""
                nat = effective_player_nation(name, FREE_AGENT_TEAM, db_nat or None, session)
                if not nat or _norm_nat(str(nat)) != want:
                    continue
                rows.append(
                    {
                        "name": name,
                        "club": FREE_AGENT_TEAM,
                        "position": p.get("position") or "",
                        "overall": int(p.get("overall") or 0),
                        "nation": canon,
                        "source": "fa",
                        "person_id": p.get("person_id"),
                    }
                )
    finally:
        eng.dispose()

    # дедуп по имени (клубный приоритетнее FA-дубля)
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for p in sorted(
        rows,
        key=lambda x: (
            0 if x.get("source") == "club" else 1,
            -int(x["overall"]),
            x["name"].casefold(),
        ),
    ):
        k = p["name"].casefold()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(p)
        if len(uniq) >= limit:
            break

    from utils.player_nicknames import get_nickname_for_player

    for p in uniq:
        nick = get_nickname_for_player(
            person_id=p.get("person_id"),
            name=p.get("name"),
            team=p.get("club"),
        )
        if nick:
            p["nickname"] = nick
    return uniq


def add_fa_player_for_nation_callup(
    nation: str,
    *,
    name: str,
    position: str,
    overall: int,
) -> dict[str, Any]:
    """Игрок без клуба: ``free_agents.db`` + заявка сборной ЧМ."""
    from utils.free_agents_db import add_free_agent_player, fa_player_id, list_free_agents
    from utils.player_transfer import normalize_player_name_for_db
    from utils.transfer_input import normalize_position
    from utils.world_cup import add_manual_callup

    canon = resolve_nation_name(nation) or (nation or "").strip()
    nm = normalize_player_name_for_db(name)
    pos = normalize_position(position)
    ovr = max(1, min(99, int(overall or 72)))

    existing = None
    for p in list_free_agents():
        if (p.get("name") or "").strip().casefold() == nm.casefold() and (
            p.get("position") or ""
        ).strip().casefold() == pos.casefold():
            existing = p
            break
    if existing is None:
        row = add_free_agent_player(
            name=nm,
            position=pos,
            overall=ovr,
            nation=canon,
            status="bench",
        )
    else:
        row = existing

    entry = add_manual_callup(
        canon,
        name=nm,
        club=FREE_AGENT_TEAM,
        position=pos,
        overall=ovr,
        ensure_fa=False,
    )
    entry["fa_id"] = row.get("id") or fa_player_id(nm, pos)
    entry["person_id"] = row.get("person_id") or entry.get("person_id")
    return entry


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


_WC_STATUSES = ("start", "bench", "reserve")
_STATUS_CYCLE = ("reserve", "start", "bench")


def _norm_status(raw: Any) -> str:
    st = str(raw or "").strip().lower()
    return st if st in _WC_STATUSES else "reserve"


def set_squad_player_status(nation: str, name: str, status: str) -> dict[str, Any]:
    """Установить status игрока в заявке сборной."""
    canon = resolve_nation_name(nation) or (nation or "").strip()
    st = _norm_status(status)
    if st not in _WC_STATUSES:
        raise ValueError("status: start | bench | reserve")
    data = load_wc_squads()
    teams = data.get("teams") or {}
    roster: list = teams.get(canon) or []
    want = (name or "").strip().casefold()
    for row in roster:
        if str(row.get("name") or "").casefold() == want:
            row["status"] = st
            if st != "start":
                row.pop("lineup_slot", None)
            data["season"] = season_paths.get_active_season()
            save_wc_squads(data)
            return dict(row)
    raise ValueError(f"«{name}» не в заявке {canon}")


def cycle_squad_player_status(nation: str, name: str) -> tuple[str, dict[str, Any]]:
    """reserve → start → bench → reserve."""
    canon = resolve_nation_name(nation) or (nation or "").strip()
    data = load_wc_squads()
    roster: list = (data.get("teams") or {}).get(canon) or []
    want = (name or "").strip().casefold()
    for row in roster:
        if str(row.get("name") or "").casefold() == want:
            cur = _norm_status(row.get("status"))
            try:
                i = _STATUS_CYCLE.index(cur)
            except ValueError:
                i = -1
            nxt = _STATUS_CYCLE[(i + 1) % len(_STATUS_CYCLE)]
            row["status"] = nxt
            if nxt != "start":
                row.pop("lineup_slot", None)
            data["season"] = season_paths.get_active_season()
            save_wc_squads(data)
            return nxt, dict(row)
    raise ValueError(f"«{name}» не в заявке {canon}")


def squad_status_map(nation: str) -> dict[str, str]:
    """name.casefold() → status для игроков в заявке."""
    out: dict[str, str] = {}
    for p in squad_for_nation(nation):
        nm = str(p.get("name") or "").strip().casefold()
        if nm:
            out[nm] = _norm_status(p.get("status"))
    return out


def remove_from_squad(nation: str, name: str) -> bool:
    """Снять игрока с заявки. False если не был в заявке."""
    canon = resolve_nation_name(nation) or (nation or "").strip()
    data = load_wc_squads()
    teams = data.get("teams") or {}
    roster: list = teams.get(canon) or []
    want = (name or "").strip().casefold()
    for i, row in enumerate(list(roster)):
        if str(row.get("name") or "").casefold() == want:
            roster.pop(i)
            data["season"] = season_paths.get_active_season()
            save_wc_squads(data)
            return True
    return False


def toggle_assign_player_to_squad(
    nation: str,
    *,
    name: str,
    club: str = "",
    position: str = "",
    overall: int = 0,
    status: str = "reserve",
) -> tuple[str, dict[str, Any] | None]:
    """
    Назначить status; если игрок уже с этим status — снять с заявки.
    Возвращает (action, entry): added | changed | removed.
    """
    st = _norm_status(status)
    want = (name or "").strip().casefold()
    if is_called_up(nation, name):
        cur = squad_status_map(nation).get(want, "reserve")
        if cur == st:
            remove_from_squad(nation, name)
            return "removed", None
        return "changed", set_squad_player_status(nation, name, st)
    entry = assign_player_to_squad(
        nation,
        name=name,
        club=club,
        position=position,
        overall=overall,
        status=st,
    )
    return "added", entry


def toggle_squad_player_status(
    nation: str,
    name: str,
    status: str,
) -> tuple[str, dict[str, Any] | None]:
    """Сменить status или снять, если status уже такой же."""
    st = _norm_status(status)
    want = (name or "").strip().casefold()
    cur = squad_status_map(nation).get(want, "reserve")
    if cur == st:
        remove_from_squad(nation, name)
        return "removed", None
    return "changed", set_squad_player_status(nation, name, st)


def assign_player_to_squad(
    nation: str,
    *,
    name: str,
    club: str = "",
    position: str = "",
    overall: int = 0,
    status: str = "reserve",
) -> dict[str, Any]:
    """Добавить в заявку или сменить status (без снятия)."""
    if is_called_up(nation, name):
        return set_squad_player_status(nation, name, status)
    canon = resolve_nation_name(nation) or (nation or "").strip()
    if not canon:
        raise ValueError("Неизвестная сборная")
    data = load_wc_squads()
    data["season"] = season_paths.get_active_season()
    teams = data.setdefault("teams", {})
    roster: list = teams.setdefault(canon, [])
    if len(roster) >= WC_TOTAL:
        raise ValueError(f"Заявка полна ({WC_TOTAL} игроков). Сначала снимите кого-то.")
    st = _norm_status(status)
    entry = {
        "name": (name or "").strip(),
        "club": (club or "").strip(),
        "position": (position or "").strip(),
        "overall": int(overall or 0),
        "source": "callup",
        "status": st,
    }
    roster.append(entry)
    save_wc_squads(data)
    return entry


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
    if len(roster) >= WC_TOTAL:
        raise ValueError(f"Заявка полна ({WC_TOTAL} игроков). Сначала снимите кого-то.")
    entry = {
        "name": (name or "").strip(),
        "club": (club or "").strip(),
        "position": (position or "").strip(),
        "overall": int(overall or 0),
        "source": "callup",
        "status": "reserve",
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
        if not roster:
            return f"<b>{canon}</b>\nЗаявка пуста."
        ev = evaluate_wc_squad(roster)
        lines = [
            f"<b>Заявка · {canon}</b>",
            format_wc_quota_summary_html(ev),
            "",
            "<i>Формат: 26 = 11 старт + 7 запас + 8 резерв · 4-3-3 ат · 2 ВРТ</i>",
            "",
        ]
        order = {"start": 0, "bench": 1, "reserve": 2, "": 3}

        def _sort_key(p: dict) -> tuple:
            st = str(p.get("status") or "").strip().lower()
            if st not in order:
                st = ""
            slot = str(p.get("lineup_slot") or "")
            return (
                order[st],
                slot,
                -int(p.get("overall") or 0),
                str(p.get("name") or "").casefold(),
            )

        for p in sorted(roster, key=_sort_key):
            st = str(p.get("status") or "—").strip().lower() or "—"
            slot = p.get("lineup_slot")
            slot_s = f" · {slot}" if st == "start" and slot else ""
            lines.append(
                f"· [{st}{slot_s}] {p.get('name')} · {p.get('position') or '—'} · "
                f"{p.get('overall') or '—'} · {p.get('club') or '—'}"
            )
        return "\n".join(lines)
    filled = sum(1 for v in teams.values() if isinstance(v, list) and v)
    total_players = sum(len(v) for v in teams.values() if isinstance(v, list))
    complete = sum(
        1
        for v in teams.values()
        if isinstance(v, list) and v and evaluate_wc_squad(v).get("complete")
    )
    return (
        f"<b>Вызовы ЧМ</b>\n"
        f"Сборных с заявкой: <b>{filled}</b> / 48\n"
        f"Полных заявок (26): <b>{complete}</b>\n"
        f"Всего игроков: <b>{total_players}</b>"
    )
