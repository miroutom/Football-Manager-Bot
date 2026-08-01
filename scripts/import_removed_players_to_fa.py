#!/usr/bin/env python3
"""
Кандидаты в св. агенты: были в архивах season_N, но нет в активной заявке S4.

По умолчанию — dry-run. Сначала смотри список; ``--apply`` пишет в ``free_agents.db``.

  python3 scripts/import_removed_players_to_fa.py
  python3 scripts/import_removed_players_to_fa.py --seasons 1,2,3
  python3 scripts/import_removed_players_to_fa.py --json -o /tmp/fa_candidates.json
  python3 scripts/import_removed_players_to_fa.py --apply

Пропускает игрока, если в активном сезоне уже есть строка с тем же ``person_id``
или тем же полным именем (без учёта регистра) в заявке (``left_team=False``).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils import season_paths
from utils.free_agents_db import add_free_agent_player, get_free_agents_db_path, list_free_agents
from utils.player_names import player_name_identity_token
from utils.player_transfer import normalize_player_name_for_db
from utils.roster_manual import FREE_AGENT_TEAM

_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")


@dataclass
class PlayerSnap:
    name: str
    position: str
    person_id: int | None
    team: str
    overall: int
    nation: str
    matches: int
    season: int
    source: str

    @property
    def name_cf(self) -> str:
        return (self.name or "").strip().casefold()

    @property
    def name_token(self) -> str:
        return player_name_identity_token(self.name).casefold()

    @property
    def pos_u(self) -> str:
        return (self.position or "").strip().upper()


@dataclass
class Candidate:
    snap: PlayerSnap
    action: str
    reason: str
    active_pids: list[int] = field(default_factory=list)
    active_teams: list[str] = field(default_factory=list)
    archive_pids: list[int] = field(default_factory=list)


def _load_db_rows(path: str, *, season: int | None, source: str) -> list[PlayerSnap]:
    import sqlite3

    if not os.path.isfile(path):
        return []
    conn = sqlite3.connect(path)
    out: list[PlayerSnap] = []
    try:
        for tbl in _TABLES:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
            if "name" not in cols or "position" not in cols:
                continue
            sel = ["name", "position"]
            for c in ("person_id", "team", "overall", "nation", "matches", "left_team"):
                if c in cols:
                    sel.append(c)
            q = f"SELECT {', '.join(sel)} FROM {tbl}"
            for row in conn.execute(q):
                data = dict(zip(sel, row))
                if data.get("left_team"):
                    continue
                team = (data.get("team") or "").strip()
                if team.casefold() == FREE_AGENT_TEAM.casefold():
                    continue
                name = (data.get("name") or "").strip()
                pos = (data.get("position") or "").strip()
                if not name or not pos:
                    continue
                pid_raw = data.get("person_id")
                pid = None
                if pid_raw is not None:
                    try:
                        v = int(pid_raw)
                        if v > 0:
                            pid = v
                    except (TypeError, ValueError):
                        pass
                out.append(
                    PlayerSnap(
                        name=name,
                        position=pos,
                        person_id=pid,
                        team=team,
                        overall=int(data.get("overall") or 0),
                        nation=(data.get("nation") or "") or "",
                        matches=int(data.get("matches") or 0),
                        season=int(season or 0),
                        source=source,
                    )
                )
    finally:
        conn.close()
    return out


def _active_index() -> dict[str, Any]:
    paths = [
        ("league", season_paths.get_league_db_path(), season_paths.get_active_season()),
        ("cl", season_paths.get_cl_db_path(), season_paths.get_active_season()),
    ]
    roster: list[PlayerSnap] = []
    for label, path, sn in paths:
        roster.extend(_load_db_rows(path, season=sn, source=label))

    left_paths = [(season_paths.get_league_db_path(), "league"), (season_paths.get_cl_db_path(), "cl")]
    left_only: list[PlayerSnap] = []
    import sqlite3

    for path, label in left_paths:
        if not os.path.isfile(path):
            continue
        conn = sqlite3.connect(path)
        try:
            for tbl in _TABLES:
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
                if "left_team" not in cols:
                    continue
                sel = ["name", "position", "person_id", "team", "overall", "nation", "matches", "left_team"]
                sel = [c for c in sel if c in cols]
                for row in conn.execute(f"SELECT {', '.join(sel)} FROM {tbl} WHERE left_team = 1"):
                    data = dict(zip(sel, row))
                    name = (data.get("name") or "").strip()
                    pos = (data.get("position") or "").strip()
                    if not name or not pos:
                        continue
                    pid = None
                    if data.get("person_id") is not None:
                        try:
                            v = int(data["person_id"])
                            if v > 0:
                                pid = v
                        except (TypeError, ValueError):
                            pass
                    left_only.append(
                        PlayerSnap(
                            name=name,
                            position=pos,
                            person_id=pid,
                            team=(data.get("team") or "").strip(),
                            overall=int(data.get("overall") or 0),
                            nation=(data.get("nation") or "") or "",
                            matches=int(data.get("matches") or 0),
                            season=season_paths.get_active_season(),
                            source=f"{label}_left",
                        )
                    )
        finally:
            conn.close()

    fa_keys = {
        (
            (p.get("name") or "").strip().casefold(),
            (p.get("position") or "").strip().upper(),
        )
        for p in list_free_agents()
    }

    by_pid: dict[int, list[PlayerSnap]] = {}
    by_name: dict[str, list[PlayerSnap]] = {}
    by_token: dict[str, list[PlayerSnap]] = {}
    for p in roster:
        if p.person_id is not None:
            by_pid.setdefault(p.person_id, []).append(p)
        by_name.setdefault(p.name_cf, []).append(p)
        by_token.setdefault(p.name_token, []).append(p)

    left_by_name = {}
    left_by_pid = {}
    for p in left_only:
        left_by_name.setdefault(p.name_cf, []).append(p)
        if p.person_id is not None:
            left_by_pid.setdefault(p.person_id, []).append(p)

    return {
        "roster": roster,
        "by_pid": by_pid,
        "by_name": by_name,
        "by_token": by_token,
        "left_by_name": left_by_name,
        "left_by_pid": left_by_pid,
        "fa_keys": fa_keys,
    }


def _archive_candidates(seasons: list[int]) -> dict[tuple, list[PlayerSnap]]:
    """Ключ группы: (person_id,) или (name_cf, pos)."""
    groups: dict[tuple, list[PlayerSnap]] = {}
    synced_path = season_paths.get_cumulative_league_db_path()
    synced = _load_db_rows(synced_path, season=0, source="synced")

    for sn in seasons:
        path = os.path.join(ROOT, "db", f"season_{sn}", season_paths.SEASON_LEAGUE_NAME)
        for snap in _load_db_rows(path, season=sn, source=f"s{sn}"):
            key = (snap.person_id,) if snap.person_id is not None else ("np", snap.name_cf, snap.pos_u)
            groups.setdefault(key, []).append(snap)

    # дополнить synced-строками для person_id, которых нет в архивах
    for snap in synced:
        if snap.person_id is None:
            continue
        key = (snap.person_id,)
        if key not in groups:
            groups[key] = [snap]

    return groups


def _pick_canonical_snaps(snaps: list[PlayerSnap]) -> PlayerSnap:
    synced = [s for s in snaps if s.source == "synced"]
    pool = synced or snaps
    return max(
        pool,
        key=lambda s: (s.matches, s.overall, s.season, s.name.casefold()),
    )


def classify_candidates(
    seasons: list[int],
    *,
    match_name_token: bool = False,
) -> list[Candidate]:
    active = _active_index()
    groups = _archive_candidates(seasons)
    out: list[Candidate] = []

    for _key, snaps in sorted(groups.items(), key=lambda x: (_pick_canonical_snaps(x[1]).name_cf, _pick_canonical_snaps(x[1]).pos_u)):
        canon = _pick_canonical_snaps(snaps)
        archive_pids = sorted({s.person_id for s in snaps if s.person_id is not None})

        fa_key = (canon.name_cf, canon.pos_u)
        if fa_key in active["fa_keys"]:
            out.append(
                Candidate(
                    snap=canon,
                    action="skip",
                    reason="already_fa",
                    archive_pids=archive_pids,
                )
            )
            continue

        active_hits: list[PlayerSnap] = []
        if canon.person_id is not None and canon.person_id in active["by_pid"]:
            active_hits.extend(active["by_pid"][canon.person_id])
        if canon.name_cf in active["by_name"]:
            for p in active["by_name"][canon.name_cf]:
                if p not in active_hits:
                    active_hits.append(p)
        if match_name_token and canon.name_token in active["by_token"]:
            for p in active["by_token"][canon.name_token]:
                if p not in active_hits:
                    active_hits.append(p)

        if active_hits:
            act_pids = sorted({p.person_id for p in active_hits if p.person_id is not None})
            act_teams = sorted({f"{p.team} · {p.pos_u}" for p in active_hits})
            pid_note = ""
            if archive_pids and act_pids and not set(archive_pids) & set(act_pids):
                pid_note = " · pid в архиве ≠ pid в S4"
            out.append(
                Candidate(
                    snap=canon,
                    action="skip",
                    reason=f"active_roster{pid_note}",
                    active_pids=act_pids,
                    active_teams=act_teams,
                    archive_pids=archive_pids,
                )
            )
            continue

        # только left_team в S4
        left_hits: list[PlayerSnap] = []
        if canon.person_id is not None and canon.person_id in active["left_by_pid"]:
            left_hits.extend(active["left_by_pid"][canon.person_id])
        if canon.name_cf in active["left_by_name"]:
            for p in active["left_by_name"][canon.name_cf]:
                if p not in left_hits:
                    left_hits.append(p)

        if left_hits:
            out.append(
                Candidate(
                    snap=canon,
                    action="skip",
                    reason="active_left_team_only",
                    active_pids=sorted({p.person_id for p in left_hits if p.person_id is not None}),
                    active_teams=sorted({f"{p.team} · {p.pos_u}" for p in left_hits}),
                    archive_pids=archive_pids,
                )
            )
            continue

        out.append(
            Candidate(
                snap=canon,
                action="add",
                reason="missing_from_active",
                archive_pids=archive_pids,
            )
        )

    return out


def _print_report(cands: list[Candidate], *, limit: int) -> None:
    from collections import Counter

    cnt = Counter(c.action + ":" + c.reason.split(" ·")[0] for c in cands)
    print(f"Активный сезон: {season_paths.get_active_season()}")
    print(f"free_agents.db: {get_free_agents_db_path()}")
    print("—" * 60)
    for k, v in sorted(cnt.items()):
        print(f"  {k}: {v}")
    print("—" * 60)

    adds = [c for c in cands if c.action == "add"]
    skips_roster = [c for c in cands if c.reason.startswith("active_roster")]
    skips_left = [c for c in cands if c.reason == "active_left_team_only"]

    print(f"\nБудет добавлено в FA: {len(adds)}")
    for c in adds[:limit]:
        s = c.snap
        pids = c.archive_pids or ([s.person_id] if s.person_id else [])
        pid_s = ", ".join(str(x) for x in pids) if pids else "—"
        print(
            f"  + {s.name} · {s.pos_u} · pid {pid_s} · ovr {s.overall} · "
            f"{s.nation or '—'} · S{s.season} {s.team}"
        )
    if len(adds) > limit:
        print(f"  … ещё {len(adds) - limit}")

    if skips_roster:
        print(f"\nПропуск — уже в заявке S4 (по имени/person_id): {len(skips_roster)}")
        for c in skips_roster[:limit]:
            s = c.snap
            ap = ", ".join(str(x) for x in c.active_pids) or "—"
            ar = ", ".join(str(x) for x in c.archive_pids) or "—"
            teams = "; ".join(c.active_teams[:3])
            print(f"  = {s.name} · {s.pos_u} · архив pid {ar} · S4 pid {ap} · {teams}")
        if len(skips_roster) > limit:
            print(f"  … ещё {len(skips_roster) - limit}")

    if skips_left:
        print(f"\nПропуск — только left_team в S4 (уже сняты): {len(skips_left)}")
        for c in skips_left[: min(limit, 15)]:
            s = c.snap
            print(f"  ~ {s.name} · {s.pos_u} · {', '.join(c.active_teams[:2])}")
        if len(skips_left) > 15:
            print(f"  … ещё {len(skips_left) - 15}")


def _apply_candidates(cands: list[Candidate]) -> dict[str, int]:
    stats = {"added": 0, "errors": 0}
    for c in cands:
        if c.action != "add":
            continue
        s = c.snap
        pid = s.person_id
        if pid is None and c.archive_pids:
            pid = c.archive_pids[0]
        try:
            add_free_agent_player(
                name=normalize_player_name_for_db(s.name),
                position=s.pos_u,
                overall=max(1, min(99, int(s.overall or 72))),
                nation=(s.nation or None),
                status="bench",
                person_id=pid,
            )
            stats["added"] += 1
        except ValueError as e:
            if "уже есть" in str(e).casefold():
                continue
            print(f"✗ {s.name}: {e}")
            stats["errors"] += 1
        except Exception as e:
            print(f"✗ {s.name}: {e}")
            stats["errors"] += 1
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--seasons",
        default="1,2,3",
        help="Архивные сезоны через запятую (default: 1,2,3)",
    )
    ap.add_argument("--apply", action="store_true", help="Записать в free_agents.db")
    ap.add_argument("--json", action="store_true", help="JSON в stdout")
    ap.add_argument("-o", "--output", help="JSON в файл")
    ap.add_argument("--limit", type=int, default=40, help="Строк в текстовом отчёте")
    ap.add_argument(
        "--match-name-token",
        action="store_true",
        help="Дополнительно матчить по фамилии (осторожно с омонимами)",
    )
    args = ap.parse_args()

    seasons = [int(x.strip()) for x in args.seasons.split(",") if x.strip()]
    cands = classify_candidates(seasons, match_name_token=args.match_name_token)

    payload = {
        "active_season": season_paths.get_active_season(),
        "archive_seasons": seasons,
        "summary": {},
        "candidates": [
            {
                **asdict(c),
                "snap": asdict(c.snap),
            }
            for c in cands
        ],
    }
    from collections import Counter

    payload["summary"] = dict(Counter(f"{c.action}:{c.reason.split(' ·')[0]}" for c in cands))

    if args.json:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"JSON → {args.output}")
        else:
            print(text)
    elif args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"JSON → {args.output}")

    if not args.json:
        _print_report(cands, limit=args.limit)
        if not args.apply:
            print("\n(dry-run — для записи добавь --apply)")

    if args.apply:
        stats = _apply_candidates(cands)
        print(f"\nПрименено: добавлено {stats['added']}, ошибок {stats['errors']}")


if __name__ == "__main__":
    main()
