# -*- coding: utf-8 -*-
"""
Формат ЧМ как в IRL (модель FIFA WC 2026 / 48 команд):

- 12 групп (A–L) по 4 команды;
- в группе каждый с каждым один раз (3 тура, 6 матчей на группу);
- в плей-офф: 1-е и 2-е места всех групп + **8 лучших третьих**;
- далее: 1/16 → 1/8 → 1/4 → 1/2 → матч за 3-е → финал.

Ранжирование третьих: очки → разница мячей → забитые.
(Жёлтые/красные и рейтинг FIFA — позже, если понадобится.)
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Iterable

GROUP_IDS = tuple("ABCDEFGHIJKL")  # 12 групп
GROUP_SIZE = 4
N_GROUPS = 12
N_TEAMS = N_GROUPS * GROUP_SIZE  # 48
BEST_THIRDS = 8
KNOCKOUT_ROUND_OF = 32  # 12*2 + 8

# Порядок туров в группе: пары индексов 0..3
GROUP_ROUND_PAIRINGS: tuple[tuple[tuple[int, int], ...], ...] = (
    ((0, 1), (2, 3)),
    ((0, 2), (1, 3)),
    ((0, 3), (1, 2)),
)

KNOCKOUT_ROUNDS: tuple[str, ...] = (
    "r32",
    "r16",
    "qf",
    "sf",
    "third",
    "final",
)


@dataclass
class GroupStandingRow:
    team: str
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    gf: int = 0
    ga: int = 0
    points: int = 0

    @property
    def gd(self) -> int:
        return int(self.gf) - int(self.ga)

    def sort_key(self) -> tuple:
        return (-self.points, -self.gd, -self.gf, self.team.casefold())


@dataclass
class WcFormatSnapshot:
    groups: dict[str, list[str]] = field(default_factory=dict)
    notes: str = ""


def confederation_pots(nations_by_conf: dict[str, list[str]]) -> dict[str, list[str]]:
    """Копия списков по конфедерациям (нормализованные имена)."""
    out: dict[str, list[str]] = {}
    for conf, teams in (nations_by_conf or {}).items():
        out[str(conf)] = [str(t).strip() for t in teams if str(t).strip()]
    return out


def flatten_nations(nations_by_conf: dict[str, list[str]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for teams in confederation_pots(nations_by_conf).values():
        for t in teams:
            k = t.casefold()
            if k in seen:
                continue
            seen.add(k)
            names.append(t)
    return names


def validate_nation_count(nations_by_conf: dict[str, list[str]]) -> tuple[bool, str]:
    names = flatten_nations(nations_by_conf)
    n = len(names)
    if n != N_TEAMS:
        return False, f"Нужно ровно {N_TEAMS} сборных, сейчас {n}"
    return True, f"OK · {N_TEAMS} сборных · {N_GROUPS} групп × {GROUP_SIZE}"


# Порядок конфедераций для посева (сильнейшие регионы первыми в «змейке»).
_CONF_SEED_ORDER: tuple[str, ...] = (
    "Европа",
    "Юж. Америка",
    "Африка",
    "Азия",
    "Сев. Америка",
)

# Макс. команд одной конфедерации в группе (при 27 UEFA — до 3).
_MAX_CONF_PER_GROUP: dict[str, int] = {
    "Европа": 3,
    "Юж. Америка": 1,
    "Африка": 1,
    "Азия": 1,
    "Сев. Америка": 1,
}

N_POTS = 4
POT_SIZE = N_TEAMS // N_POTS  # 12


def nation_to_confederation(nations_by_conf: dict[str, list[str]]) -> dict[str, str]:
    """Имя сборной → конфедерация."""
    out: dict[str, str] = {}
    for conf, teams in confederation_pots(nations_by_conf).items():
        for t in teams:
            out[t] = conf
    return out


def build_fifa_pots(
    nations_by_conf: dict[str, list[str]],
) -> list[list[tuple[str, str]]]:
    """
    4 корзины по 12: (сборка, конфедерация).

    Посев: порядок внутри списка конфедерации = сила; корзины — змейка по
    конфедерациям (как упрощённый FIFA-рейтинг).
    """
    ok, msg = validate_nation_count(nations_by_conf)
    if not ok:
        raise ValueError(msg)
    by = confederation_pots(nations_by_conf)
    # очереди по conf: [(team, conf), ...]
    queues: dict[str, list[tuple[str, str]]] = {
        conf: [(t, conf) for t in by.get(conf, [])] for conf in _CONF_SEED_ORDER
    }
    ranked: list[tuple[str, str]] = []
    while len(ranked) < N_TEAMS:
        progressed = False
        for conf in _CONF_SEED_ORDER:
            q = queues.get(conf) or []
            if q:
                ranked.append(q.pop(0))
                progressed = True
                if len(ranked) >= N_TEAMS:
                    break
        if not progressed:
            # хвост на случай неизвестных ключей conf
            for conf, q in queues.items():
                while q and len(ranked) < N_TEAMS:
                    ranked.append(q.pop(0))
            break
    if len(ranked) != N_TEAMS:
        raise ValueError(f"Посев: ожидалось {N_TEAMS}, получилось {len(ranked)}")
    pots: list[list[tuple[str, str]]] = []
    for i in range(N_POTS):
        pots.append(ranked[i * POT_SIZE : (i + 1) * POT_SIZE])
    return pots


def _can_place_in_group(
    group_confs: list[str],
    conf: str,
    *,
    max_per: dict[str, int] | None = None,
) -> bool:
    limits = max_per or _MAX_CONF_PER_GROUP
    lim = int(limits.get(conf, 1))
    return group_confs.count(conf) < lim


def draw_groups_fifa(
    nations_by_conf: dict[str, list[str]],
    *,
    seed: int | None = None,
    max_attempts: int = 4000,
) -> dict[str, list[str]]:
    """
    Жеребьёвка как у FIFA WC 2026 (упрощённо):

    - 4 корзины × 12;
    - из каждой корзины по одной команде в каждую группу;
    - лимит конфедераций в группе (UEFA до 3, остальные до 1).
    """
    pots = build_fifa_pots(nations_by_conf)
    rng = random.Random(seed)
    last_err = "не удалось соблюсти гео-ограничения"

    for _ in range(max_attempts):
        groups: dict[str, list[str]] = {g: [] for g in GROUP_IDS}
        confs: dict[str, list[str]] = {g: [] for g in GROUP_IDS}
        ok = True
        for pot in pots:
            bag = pot[:]
            rng.shuffle(bag)
            free = list(GROUP_IDS)
            rng.shuffle(free)
            for team, conf in bag:
                eligible = [
                    g
                    for g in free
                    if _can_place_in_group(confs[g], conf) and len(groups[g]) < GROUP_SIZE
                ]
                if not eligible:
                    ok = False
                    break
                g = eligible[0]
                groups[g].append(team)
                confs[g].append(conf)
                free.remove(g)
            if not ok:
                break
        if ok and all(len(groups[g]) == GROUP_SIZE for g in GROUP_IDS):
            return groups
        last_err = "гео-ограничения не сошлись"
    raise RuntimeError(f"Жеребьёвка ЧМ: {last_err} (seed={seed})")


def draw_groups(
    nations_by_conf: dict[str, list[str]],
    *,
    seed: int | None = None,
) -> dict[str, list[str]]:
    """Жеребьёвка групп (FIFA-корзины + гео-лимиты)."""
    return draw_groups_fifa(nations_by_conf, seed=seed)


def group_fixtures(group_teams: list[str]) -> list[tuple[str, str, int]]:
    """
    Матчи группы: (home, away, round_1_based).
    Каждый с каждым один раз.
    """
    teams = [str(t).strip() for t in group_teams if str(t).strip()]
    if len(teams) != GROUP_SIZE:
        raise ValueError(f"В группе должно быть {GROUP_SIZE} команды, есть {len(teams)}")
    out: list[tuple[str, str, int]] = []
    for rnd_i, pairs in enumerate(GROUP_ROUND_PAIRINGS, start=1):
        for a, b in pairs:
            out.append((teams[a], teams[b], rnd_i))
    return out


def all_group_fixtures(groups: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Плоский список матчей группового этапа."""
    rows: list[dict[str, Any]] = []
    for gid in GROUP_IDS:
        teams = groups.get(gid) or []
        for home, away, rnd in group_fixtures(teams):
            rows.append(
                {
                    "phase": "group",
                    "group": gid,
                    "round": rnd,
                    "home": home,
                    "away": away,
                    "league": "wc",
                }
            )
    return rows


def empty_table(teams: Iterable[str]) -> dict[str, GroupStandingRow]:
    return {str(t): GroupStandingRow(team=str(t)) for t in teams if str(t).strip()}


def apply_result(
    table: dict[str, GroupStandingRow],
    home: str,
    away: str,
    home_goals: int,
    away_goals: int,
) -> None:
    h = table[home]
    a = table[away]
    hg, ag = int(home_goals), int(away_goals)
    h.played += 1
    a.played += 1
    h.gf += hg
    h.ga += ag
    a.gf += ag
    a.ga += hg
    if hg > ag:
        h.won += 1
        a.lost += 1
        h.points += 3
    elif hg < ag:
        a.won += 1
        h.lost += 1
        a.points += 3
    else:
        h.drawn += 1
        a.drawn += 1
        h.points += 1
        a.points += 1


def ranked_table(table: dict[str, GroupStandingRow]) -> list[GroupStandingRow]:
    return sorted(table.values(), key=lambda r: r.sort_key())


def compute_group_tables(
    groups: dict[str, list[str]],
    results: Iterable[dict[str, Any]],
) -> dict[str, list[GroupStandingRow]]:
    """
    ``results``: dict с home/away/home_score/away_score и опционально group.
    """
    tables: dict[str, dict[str, GroupStandingRow]] = {
        gid: empty_table(groups.get(gid) or []) for gid in GROUP_IDS
    }
    team_to_group = {
        t: gid for gid, teams in groups.items() for t in teams
    }
    for m in results:
        home = str(m.get("home") or "").strip()
        away = str(m.get("away") or "").strip()
        if not home or not away:
            continue
        gid = str(m.get("group") or team_to_group.get(home) or team_to_group.get(away) or "")
        if gid not in tables:
            continue
        if home not in tables[gid] or away not in tables[gid]:
            continue
        try:
            hs = int(m.get("home_score"))
            aws = int(m.get("away_score"))
        except (TypeError, ValueError):
            continue
        apply_result(tables[gid], home, away, hs, aws)
    return {gid: ranked_table(tbl) for gid, tbl in tables.items()}


def qualify_from_groups(
    ranked_groups: dict[str, list[GroupStandingRow]],
) -> dict[str, Any]:
    """
    Возвращает:
      winners, runners_up, thirds_all, thirds_qualified, eliminated_thirds
    """
    winners: list[tuple[str, str]] = []  # (group, team)
    runners: list[tuple[str, str]] = []
    thirds: list[tuple[str, GroupStandingRow]] = []
    for gid in GROUP_IDS:
        rows = ranked_groups.get(gid) or []
        if len(rows) < 3:
            continue
        winners.append((gid, rows[0].team))
        runners.append((gid, rows[1].team))
        thirds.append((gid, rows[2]))
    thirds_sorted = sorted(thirds, key=lambda x: x[1].sort_key())
    qualified_thirds = thirds_sorted[:BEST_THIRDS]
    eliminated = thirds_sorted[BEST_THIRDS:]
    return {
        "winners": winners,
        "runners_up": runners,
        "thirds_all": [(g, r.team, r.points, r.gd, r.gf) for g, r in thirds_sorted],
        "thirds_qualified": [
            (g, r.team, r.points, r.gd, r.gf) for g, r in qualified_thirds
        ],
        "thirds_eliminated": [(g, r.team, r.points, r.gd, r.gf) for g, r in eliminated],
        "knockout_teams": (
            [t for _, t in winners]
            + [t for _, t in runners]
            + [r.team for _, r in qualified_thirds]
        ),
    }


def format_rules_ru() -> str:
    return (
        f"ЧМ · {N_TEAMS} сборных · {N_GROUPS} групп (A–L) по {GROUP_SIZE}\n"
        f"Группа: каждый с каждым один раз (3 тура).\n"
        f"В плей-офф: 1–2 места всех групп + {BEST_THIRDS} лучших третьих "
        f"(итого {KNOCKOUT_ROUND_OF}).\n"
        f"Далее: 1/16 → 1/8 → 1/4 → 1/2 → матч за 3-е → финал."
    )
