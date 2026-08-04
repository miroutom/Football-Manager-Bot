#!/usr/bin/env python3
"""Remove duplicate transfer-window player ids (baseline + squads + transfers)."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.transfer_window_app.main import build_state_payload, compute_transfers
from utils.free_agents_db import fa_player_id

DEFAULT_PATHS = [
    Path.home() / "Library/Application Support/FootballManagerBot/transfer_window/transfer_window_state_summer.json",
    Path.home() / "Downloads/transfer_window_state_summer_draft.json",
]


def np_key(name, pos):
    return (str(name or "").strip().casefold(), str(pos or "").strip().upper())


def pid_np(pid):
    parts = (pid or "").split("|")
    if len(parts) >= 3 and parts[1].strip():
        return (parts[1].strip().casefold(), parts[2].strip().upper())
    return None


def canonical_id(name, position, from_team):
    ft = str(from_team or "").strip()
    if ft.lower() in ("free agent", "freeagent", "fa", ""):
        return fa_player_id(name, position)
    return f"{ft}|{str(name).strip()}|{str(position).strip().upper()}"


def fix_data(data):
    notes = []
    bh = dict(data.get("baseline_home") or {})

    # Bastoni: destination id without duplicate yet
    for team in data.get("teams") or []:
        for zone in ("start", "bench", "reserve"):
            for pl in team.get(zone) or []:
                if np_key(pl.get("name"), pl.get("position")) == ("бастони", "ЦЗ"):
                    if pl.get("id") != "Интер|Бастони|ЦЗ":
                        notes.append(f"Bastoni squad id {pl.get('id')} -> Интер|Бастони|ЦЗ")
                        pl["id"] = "Интер|Бастони|ЦЗ"
    if bh.pop("Арсенал|Бастони|ЦЗ", None) is not None or "Интер|Бастони|ЦЗ" not in bh:
        bh["Интер|Бастони|ЦЗ"] = "Интер"
        notes.append("Bastoni baseline -> Интер|Бастони|ЦЗ")

    data["baseline_home"] = bh

    for _ in range(8):
        computed = compute_transfers(data)
        groups = defaultdict(list)
        for t in computed:
            groups[np_key(t.get("name"), t.get("position"))].append(t)
        dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
        if not dup_groups:
            break

        for (name_cf, pos), ts in dup_groups.items():
            ref = ts[0]
            from_team = str(ref.get("from_team") or "").strip() or "Free Agent"
            name = ref.get("name") or name_cf
            correct = canonical_id(name, pos, from_team)

            matching_keys = [
                k
                for k in bh
                if pid_np(k) == (name_cf, pos) or (k.startswith("|") and pid_np(k) == (name_cf, pos))
            ]
            wrong_keys = [k for k in matching_keys if k != correct]
            for k in wrong_keys:
                bh.pop(k, None)
            bh[correct] = from_team

            for team in data.get("teams") or []:
                tname = team.get("name")
                for zone in ("start", "bench", "reserve"):
                    for pl in team.get(zone) or []:
                        if np_key(pl.get("name"), pl.get("position")) != (name_cf, pos):
                            continue
                        if pl.get("id") != correct:
                            notes.append(f"{name}: squad {pl.get('id')} -> {correct} ({tname})")
                            pl["id"] = correct

            notes.append(f"{name}/{pos}: drop {wrong_keys}, keep {correct}")

        data["baseline_home"] = bh

    seen = set()
    clean = []
    for tr in data.get("transfers") or []:
        ft = str(tr.get("from_team") or "").strip() or "Free Agent"
        key = (np_key(tr.get("name"), tr.get("position")), ft, str(tr.get("to_team") or "").strip())
        if key in seen:
            continue
        seen.add(key)
        tr = dict(tr)
        tr["id"] = canonical_id(tr.get("name") or "", tr.get("position") or "", ft)
        if not tr.get("from_team"):
            tr["from_team"] = "Free Agent"
        clean.append(tr)
    data["transfers"] = clean

    payload = build_state_payload(data)
    data.clear()
    data.update(payload)
    return notes


def verify(data):
    computed = compute_transfers(data)
    c = Counter(
        (np_key(t.get("name"), t.get("position")), t.get("from_team"), t.get("to_team"))
        for t in computed
    )
    dups = [k for k, v in c.items() if v > 1]
    return dups, len(computed)


def main():
    paths = [Path(p) for p in sys.argv[1:]] if len(sys.argv) > 1 else DEFAULT_PATHS
    for path in paths:
        if not path.is_file():
            print("skip missing", path)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        notes = fix_data(data)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        dups, n_tr = verify(json.loads(path.read_text(encoding="utf-8")))
        print(f"{path.name}: {len(notes)} fixes, transfers={n_tr}, dups={dups or 'none'}")
        for n in notes:
            print(" ", n)


if __name__ == "__main__":
    main()
