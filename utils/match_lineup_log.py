# -*- coding: utf-8 -*-
"""Журнал присутствия игроков в матче (для «влияния» / win-rate с игроком)."""
from __future__ import annotations

import json
import os
from typing import Any, Iterator

from utils.utils import PROJECT_ROOT

STORE_PATH = os.path.join(PROJECT_ROOT, "data", "match_lineup_log.json")


def _norm_team(name: str) -> str:
    return (name or "").strip().title()


def _norm_key(s: str) -> str:
    return (s or "").strip().casefold()


def _load() -> list[dict[str, Any]]:
    if not os.path.isfile(STORE_PATH):
        return []
    try:
        with open(STORE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return []
    return raw if isinstance(raw, list) else []


def _save(rows: list[dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def _slot_key(row: dict[str, Any]) -> tuple:
    return (
        int(row.get("season") or 0),
        _norm_key(str(row.get("home") or "")),
        _norm_key(str(row.get("away") or "")),
        str(row.get("tournament") or "league").strip().lower(),
        str(row.get("cl_phase") or "").strip().lower(),
        int(row["day"]) if row.get("day") is not None else -1,
    )


def record_match_lineup(
    *,
    players: list[dict[str, Any]],
    home: str,
    away: str,
    tournament: str = "league",
    day: int | None = None,
    home_score: int | None = None,
    away_score: int | None = None,
    league_code: str | None = None,
    cl_phase: str | None = None,
    season: int | None = None,
    source: str = "stats",
) -> dict[str, Any]:
    """
    Записать состав матча (заменяет предыдущую запись слота).

    ``players``: [{player, team, position?}, ...] — только сыгравшие.
    """
    from utils import season_paths

    sn = int(season if season is not None else season_paths.get_active_season())
    tourn = (tournament or "league").strip().lower()
    clean: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for p in players or []:
        name = str(p.get("player") or p.get("name") or "").strip()
        team = _norm_team(str(p.get("team") or ""))
        if not name or not team:
            continue
        key = (_norm_key(name), _norm_key(team))
        if key in seen:
            continue
        seen.add(key)
        clean.append(
            {
                "player": name,
                "team": team,
                "position": str(p.get("position") or "").strip().upper(),
            }
        )
    row: dict[str, Any] = {
        "season": sn,
        "day": int(day) if day is not None else None,
        "home": _norm_team(home),
        "away": _norm_team(away),
        "tournament": tourn,
        "players": clean,
        "source": (source or "stats").strip().lower(),
    }
    if home_score is not None:
        row["home_score"] = int(home_score)
    if away_score is not None:
        row["away_score"] = int(away_score)
    if league_code:
        row["league_code"] = str(league_code).strip().lower()
    if tourn == "cl" and cl_phase:
        row["cl_phase"] = str(cl_phase).strip().lower()

    rows = _load()
    if row["home"] and row["away"]:
        key = _slot_key(row)
        for i, old in enumerate(rows):
            if _slot_key(old) == key:
                old_n = len(old.get("players") or [])
                if len(clean) < old_n:
                    return old
                rows[i] = row
                _save(rows)
                return row
    rows.append(row)
    _save(rows)
    return row


def record_lineup_from_played_keys(
    *,
    played_keys: list[str] | set[str] | None,
    home: str,
    away: str,
    tournament: str,
    day: int | None,
    home_score: int | None,
    away_score: int | None,
    league_code: str | None,
    cl_phase: str | None,
) -> None:
    """Ключи вида ``name_norm|team_norm`` из ввода «кто играл»."""
    if not played_keys:
        return
    from player_stats import find_player_by_name, get_session

    tourn = "cl" if (tournament or "").strip().lower() == "cl" else "league"
    sess = get_session(tourn)
    players: list[dict[str, Any]] = []
    for raw in played_keys:
        parts = str(raw).split("|", 1)
        name_q = (parts[0] or "").strip()
        team_q = (parts[1] or "").strip() if len(parts) > 1 else ""
        if not name_q:
            continue
        pl, _ = find_player_by_name(sess, name_q, team_q or None)
        if pl is None and team_q:
            # попробовать title team
            pl, _ = find_player_by_name(sess, name_q, team_q.title())
        if pl is None:
            continue
        players.append(
            {
                "player": str(pl.name),
                "team": str(pl.team),
                "position": str(getattr(pl, "position", "") or "").strip().upper(),
            }
        )
    if not players:
        return
    record_match_lineup(
        players=players,
        home=home,
        away=away,
        tournament=tourn,
        day=day,
        home_score=home_score,
        away_score=away_score,
        league_code=league_code,
        cl_phase=cl_phase,
        source="stats",
    )


def sync_lineups_from_ratings() -> int:
    """Импорт присутствия из ``match_performance_ratings.json`` (непустой рейтинг)."""
    from utils import match_ratings as mr

    st = mr._load_store()  # noqa: SLF001
    bm = st.get("by_match") or {}
    n = 0
    for mk, ent in bm.items():
        if not isinstance(ent, dict):
            continue
        rec = mr.find_journal_record_by_rating_key(str(mk))
        if not rec:
            continue
        home = str(rec.get("home") or "").strip()
        away = str(rec.get("away") or "").strip()
        players: list[dict[str, Any]] = []
        for side, team in (("home", home), ("away", away)):
            side_d = ent.get(side) or {}
            if not isinstance(side_d, dict):
                continue
            for key, val in side_d.items():
                if not val:
                    continue  # пусто = не играл
                parts = str(key).split("|", 1)
                name = parts[0].strip().title() if parts else str(key)
                pos = parts[1].strip().upper() if len(parts) > 1 else ""
                players.append({"player": name, "team": team, "position": pos})
        if not players:
            continue
        lg = str(rec.get("league") or "").strip().lower()
        tourn = "cl" if lg == "cl" else "league"
        record_match_lineup(
            players=players,
            home=home,
            away=away,
            tournament=tourn,
            day=rec.get("day"),
            home_score=rec.get("home_score"),
            away_score=rec.get("away_score"),
            league_code=lg or None,
            cl_phase=rec.get("cl_phase"),
            season=None,
            source="ratings",
        )
        n += 1
    return n


def iter_player_match_presence(*, team: str | None = None) -> Iterator[dict[str, Any]]:
    """
    Для каждого игрока в каждом матче с составом — результат клуба (W/D/L).

    Подтягивает рейтинги при первом обращении, если лог пуст.
    """
    from bot.team_history import match_result_for_team

    rows = _load()
    if not rows:
        try:
            sync_lineups_from_ratings()
            rows = _load()
        except Exception:
            rows = _load()

    want = _norm_key(team) if team else None
    for row in rows:
        home = str(row.get("home") or "")
        away = str(row.get("away") or "")
        # подставить счёт из журнала, если нет
        hs = row.get("home_score")
        aws = row.get("away_score")
        match = {
            "home": home,
            "away": away,
            "home_score": hs,
            "away_score": aws,
            "penalties_by_team": row.get("penalties_by_team"),
        }
        if hs is None or aws is None:
            try:
                from match_results import find_journal_match_record

                lg = str(row.get("league_code") or "").strip().lower()
                codes = [lg] if lg and lg not in ("league",) else []
                codes.extend(["esp", "eng", "ita", "ger", "rpl", "cl"])
                seen_c: set[str] = set()
                for code in codes:
                    if not code or code in seen_c:
                        continue
                    seen_c.add(code)
                    rec = find_journal_match_record(
                        home,
                        away,
                        code,
                        cl_phase=row.get("cl_phase"),
                    )
                    if rec and rec.get("home_score") is not None:
                        match["home_score"] = rec.get("home_score")
                        match["away_score"] = rec.get("away_score")
                        match["penalties_by_team"] = rec.get("penalties_by_team")
                        break
            except Exception:
                pass
        if match.get("home_score") is None or match.get("away_score") is None:
            continue

        for pl in row.get("players") or []:
            if not isinstance(pl, dict):
                continue
            tm = str(pl.get("team") or "").strip()
            if want and _norm_key(tm) != want:
                continue
            res, _pts, _gf, _ga = match_result_for_team(match, tm)
            yield {
                "player": str(pl.get("player") or "").strip(),
                "team": tm,
                "position": str(pl.get("position") or "").strip().upper(),
                "result": res,
                "home": home,
                "away": away,
                "day": row.get("day"),
            }
