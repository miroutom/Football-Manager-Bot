#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Локальное приложение трансферного окна (40 клубов).

Окна:
  summer — 5 IN / 5 OUT
  winter — 2 IN / 2 OUT

Запуск из корня проекта:
  python3 tools/transfer_window_app/export_rosters.py
  python3 tools/transfer_window_app/main.py
  # или: ./tools/transfer_window_app/run.sh

Сборка:
  Windows: build_windows.bat → TransferWindow.exe
  macOS:   ./build_macos.sh → TransferWindow.app / TransferWindow
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_APP_DIR = Path(__file__).resolve().parent
_ROOT = _APP_DIR.parents[1] if len(_APP_DIR.parents) > 2 else _APP_DIR
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

WINDOW_QUOTAS: dict[str, dict[str, int]] = {
    "summer": {"max_in": 5, "max_out": 5, "label": "Лето"},
    "winter": {"max_in": 2, "max_out": 2, "label": "Зима"},
}
DEFAULT_WINDOW = "summer"


def _normalize_window(raw: str | None) -> str:
    w = (raw or DEFAULT_WINDOW).strip().lower()
    return w if w in WINDOW_QUOTAS else DEFAULT_WINDOW


def _data_dir() -> Path:
    """
    Стабильная папка сейвов/экспортов — не внутри dist/ (rebuild .app её не трёт).
    macOS: ~/Library/Application Support/FootballManagerBot/transfer_window
    """
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "FootballManagerBot"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home()) / "FootballManagerBot"
    else:
        base = Path.home() / ".local" / "share" / "FootballManagerBot"
    d = base / "transfer_window"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return _APP_DIR


def _legacy_state_dirs() -> list[Path]:
    dirs: list[Path] = [_APP_DIR, _APP_DIR / "dist", _ROOT]
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        if exe.parent.name == "MacOS" and exe.parent.parent.name == "Contents":
            dirs.append(exe.parents[2].parent)
            dirs.append(exe.parent)
        else:
            dirs.append(exe.parent)
    seen: set[str] = set()
    out: list[Path] = []
    for p in dirs:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _migrate_legacy_state_files() -> list[str]:
    """Перенести старые сейвы из dist/ и т.п. в ``_data_dir()``."""
    dest = _data_dir()
    moved: list[str] = []
    mapping = {
        "transfer_window_state_summer.json": "transfer_window_state_summer.json",
        "transfer_window_state_winter.json": "transfer_window_state_winter.json",
        "transfer_window_state.json": "transfer_window_state_summer.json",
    }
    for folder in _legacy_state_dirs():
        for src_name, dst_name in mapping.items():
            src = folder / src_name
            if not src.is_file():
                continue
            target = dest / dst_name
            if target.is_file():
                continue
            try:
                target.write_bytes(src.read_bytes())
                moved.append(f"{src} → {target}")
            except Exception:
                continue
    return moved


def _rosters_path() -> Path:
    candidates = [
        _APP_DIR / "rosters.json",
        _bundle_dir() / "rosters.json",
    ]
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        if exe.parent.name == "MacOS" and exe.parent.parent.name == "Contents":
            candidates.append(exe.parents[2].parent / "rosters.json")
            candidates.append(exe.parent / "rosters.json")
        candidates.append(exe.parent / "rosters.json")
    for p in candidates:
        if p.is_file():
            return p
    return _bundle_dir() / "rosters.json"


def _state_path(window: str = DEFAULT_WINDOW) -> Path:
    w = _normalize_window(window)
    return _data_dir() / f"transfer_window_state_{w}.json"


def _export_dir() -> Path:
    return _data_dir()


def _write_startup_log(msg: str) -> None:
    try:
        with (_data_dir() / "startup.log").open("a", encoding="utf-8") as f:
            f.write(msg.rstrip() + "\n")
    except Exception:
        pass


def _collect_player_locations(teams: list[dict]) -> dict[str, tuple[str, str, dict]]:
    """id -> (team_name, squad_zone, player dict)."""
    out: dict[str, tuple[str, str, dict]] = {}
    for team in teams:
        tname = team["name"]
        for zone in ("start", "bench", "reserve"):
            for p in team.get(zone) or []:
                if p and p.get("id") and p.get("name"):
                    out[p["id"]] = (tname, zone, p)
    return out


def _collect_fa_locations(free_agents: list[dict]) -> dict[str, tuple[str, str, dict]]:
    out: dict[str, tuple[str, str, dict]] = {}
    for p in free_agents or []:
        if p and p.get("id") and p.get("name"):
            st = (p.get("status") or "bench") or "bench"
            out[p["id"]] = ("Free Agent", st, p)
    return out


def _merge_squads_from_bot_export(
    teams_in: list[dict], text: str
) -> tuple[list[dict], list[str]]:
    """
    Подтянуть рейтинги/позиции из squads_export бота в текущее состояние приложения.
    Не меняет baseline и не переставляет игроков по слотам — только поля карточек.
    """
    from scripts.apply_bulk_squad_declarations import resolve_team_label, split_bulk_blocks
    from utils.roster_manual import parse_squad_declaration_text
    from utils.transfer_window_apply import strip_transfers_appendix

    teams = json.loads(json.dumps(teams_in))
    by_name = {t["name"]: t for t in teams}
    notes: list[str] = []
    updated = 0
    body = strip_transfers_appendix(text or "")
    for team_raw, block in split_bulk_blocks(body):
        team_name = resolve_team_label(team_raw)
        team = by_name.get(team_name)
        if not team:
            notes.append(f"нет команды в state: {team_name}")
            continue
        entries, errors = parse_squad_declaration_text(block)
        if errors:
            notes.append(f"{team_name}: {errors[0]}")
            continue
        index: dict[str, dict] = {}
        for zone in ("start", "bench", "reserve"):
            for p in team.get(zone) or []:
                if not p or not p.get("id"):
                    continue
                key = f"{(p.get('name') or '').strip().casefold()}|{(p.get('position') or '').strip().upper()}"
                index[p["id"]] = p
                index[key] = p
        for ent in entries:
            name = (ent.get("name") or "").strip()
            pos = (ent.get("position") or "").strip().upper()
            ovr = int(ent.get("overall") or 0)
            if not name:
                continue
            pid = f"{team_name}|{name}|{pos}"
            key = f"{name.casefold()}|{pos}"
            target = index.get(pid) or index.get(key)
            if not target:
                for p in index.values():
                    if isinstance(p, dict) and (p.get("name") or "").strip().casefold() == name.casefold():
                        target = p
                        break
            if not target:
                notes.append(f"{team_name}: не найден {name} ({pos})")
                continue
            changed = False
            if ovr and int(target.get("overall") or 0) != ovr:
                target["overall"] = ovr
                changed = True
            if pos and (target.get("position") or "").upper() != pos:
                target["position"] = pos
                changed = True
            if changed:
                updated += 1
    notes.insert(0, f"обновлено карточек: {updated}")
    return teams, notes


def compute_squads(state: dict) -> list[dict]:
    """Все игроки с текущим статусом (start/bench/reserve)."""
    rows: list[dict] = []
    for team in state.get("teams") or []:
        tname = team["name"]
        for s in team.get("start") or []:
            if s.get("name"):
                rows.append(
                    {
                        "team": tname,
                        "status": "start",
                        "slot": s.get("slot") or "",
                        "name": s["name"],
                        "position": s.get("position") or "",
                        "overall": int(s.get("overall") or 0),
                    }
                )
        for p in team.get("bench") or []:
            if p.get("name"):
                rows.append(
                    {
                        "team": tname,
                        "status": "bench",
                        "slot": "",
                        "name": p["name"],
                        "position": p.get("position") or "",
                        "overall": int(p.get("overall") or 0),
                    }
                )
        for p in team.get("reserve") or []:
            if p.get("name"):
                rows.append(
                    {
                        "team": tname,
                        "status": "reserve",
                        "slot": "",
                        "name": p["name"],
                        "position": p.get("position") or "",
                        "overall": int(p.get("overall") or 0),
                    }
                )
    rows.sort(key=lambda r: (r["team"], {"start": 0, "bench": 1, "reserve": 2}[r["status"]], -r["overall"], r["name"]))
    return rows


def _player_name_from_id(pid: str) -> str:
    parts = pid.split("|")
    if len(parts) >= 3:
        return parts[1]
    return pid


def compute_transfers(state: dict) -> list[dict]:
    baseline_home: dict[str, str] = state.get("baseline_home") or {}
    removed = set((state.get("removed_from_squad") or {}).keys())
    loc = _collect_player_locations(state.get("teams") or [])
    loc.update(_collect_fa_locations(state.get("free_agents") or []))
    rows: list[dict] = []
    for pid, from_team in sorted(baseline_home.items(), key=lambda x: x[1]):
        if pid in removed:
            continue
        if pid not in loc:
            continue
        to_team, status, p = loc[pid]
        if to_team == from_team:
            continue
        parts = pid.split("|")
        rows.append(
            {
                "id": pid,
                "name": p.get("name") or _player_name_from_id(pid),
                "position": p.get("position") or (parts[2] if len(parts) >= 3 else ""),
                "overall": int(p.get("overall") or 0),
                "from_team": from_team,
                "to_team": to_team,
                "status": status,
            }
        )
    rows.sort(key=lambda r: (r["to_team"], -r["overall"], r["name"]))
    return rows


def build_state_payload(data: dict) -> dict:
    """Persisted state: squads + baseline + computed transfer log + window."""
    baseline_home = data.get("baseline_home") or {}
    teams = data.get("teams") or []
    free_agents = data.get("free_agents") or []
    removed_from_squad = data.get("removed_from_squad") or {}
    window = _normalize_window(data.get("window"))
    state = {
        "window": window,
        "baseline_home": baseline_home,
        "teams": teams,
        "free_agents": free_agents,
        "removed_from_squad": removed_from_squad,
    }
    state["transfers"] = compute_transfers(state)
    return state


def _write_squads_txt(path: Path, state: dict) -> None:
    """Текстовые заявки @Клуб (как в боте) + таблица статусов."""
    lines: list[str] = []
    for team in state.get("teams") or []:
        tname = team["name"]
        lines.append(f"@{tname}")
        lines.append("==== start ===")
        for s in team.get("start") or []:
            if s.get("name"):
                slot = s.get("slot") or ""
                lines.append(f"{s['name']} {slot} {s['position']} {s['overall']}".strip())
        lines.append("=== bench ===")
        for p in team.get("bench") or []:
            if p.get("name"):
                lines.append(f"{p['name']} {p['position']} {p['overall']}")
        lines.append("=== reserve ===")
        for p in team.get("reserve") or []:
            if p.get("name"):
                lines.append(f"{p['name']} {p['position']} {p['overall']}")
        lines.append("")
    transfers = state.get("transfers") or compute_transfers(state)
    if transfers:
        lines.append("=== transfers ===")
        for t in transfers:
            status = t.get("status") or ""
            status_suffix = f" ({status})" if status else ""
            lines.append(
                f"{t['name']} {t['position']} {t['overall']}  "
                f"{t['from_team']} -> {t['to_team']}{status_suffix}"
            )
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_squads_table_txt(path: Path, rows: list[dict]) -> None:
    lines = ["Клуб\tСтатус\tСлот\tИгрок\tПозиция\tРейтинг"]
    for r in rows:
        lines.append(
            f"{r['team']}\t{r['status']}\t{r['slot']}\t{r['name']}\t{r['position']}\t{r['overall']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_squads_xlsx(path: Path, rows: list[dict]) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Составы"
    ws.append(["Клуб", "Статус", "Слот", "Игрок", "Позиция", "Рейтинг"])
    for r in rows:
        ws.append([r["team"], r["status"], r["slot"], r["name"], r["position"], r["overall"]])
    wb.save(path)


def _write_export_txt(path: Path, rows: list[dict]) -> None:
    lines = ["Игрок\tПозиция\tРейтинг\tКоманда (из)\tКоманда (в)"]
    for r in rows:
        lines.append(
            f"{r['name']}\t{r['position']}\t{r['overall']}\t{r['from_team']}\t{r['to_team']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_transfers_simple_txt(path: Path, rows: list[dict]) -> None:
    lines = ["Игрок\tКлуб (из)\tКлуб (в)"]
    for r in rows:
        lines.append(f"{r['name']}\t{r['from_team']}\t{r['to_team']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_export_xlsx(path: Path, rows: list[dict]) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Трансферы"
    ws.append(["Игрок", "Позиция", "Рейтинг", "Команда (из)", "Команда (в)"])
    for r in rows:
        ws.append([r["name"], r["position"], r["overall"], r["from_team"], r["to_team"]])
    wb.save(path)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        pass

    def _send_json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _send_file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            return self._send_file(_bundle_dir() / "web" / "index.html")
        if path.startswith("/web/"):
            rel = path[len("/web/") :]
            return self._send_file(_bundle_dir() / "web" / rel)
        if path == "/api/config":
            leagues: list[dict] = []
            positions = ["GK", "CB", "LB", "RB", "CDM", "CM", "CAM", "LW", "RW", "ST"]
            try:
                from player_stats import LEAGUE_NAMES, LEAGUE_TEAMS
                from utils.transfer_market_draft import _EXCLUDED_TEAMS

                for code in ("rpl", "eng", "esp", "ita", "ger"):
                    teams_l = [
                        t
                        for t in LEAGUE_TEAMS.get(code, [])
                        if t not in _EXCLUDED_TEAMS
                    ]
                    leagues.append(
                        {
                            "code": code,
                            "name": LEAGUE_NAMES.get(code, code),
                            "teams": teams_l,
                        }
                    )
            except Exception:
                pass
            return self._send_json(
                {
                    "default_window": DEFAULT_WINDOW,
                    "windows": WINDOW_QUOTAS,
                    "data_dir": str(_data_dir()),
                    "leagues": leagues,
                    "positions": positions,
                    "fa_team": "Free Agent",
                }
            )
        if path == "/api/paths":
            return self._send_json(
                {
                    "data_dir": str(_data_dir()),
                    "rosters": str(_rosters_path()),
                    "state_summer": str(_state_path("summer")),
                    "state_winter": str(_state_path("winter")),
                }
            )
        if path == "/api/rosters":
            p = _rosters_path()
            if not p.is_file():
                return self._send_json({"error": f"нет {p}"}, 500)
            payload = json.loads(p.read_text(encoding="utf-8"))
            try:
                from utils.free_agents_db import list_free_agents

                payload["free_agents"] = list_free_agents()
            except Exception:
                payload.setdefault("free_agents", payload.get("free_agents") or [])
            return self._send_json(payload)
        if path == "/api/free-agents":
            try:
                from utils.free_agents_db import list_free_agents

                rows = list_free_agents()
            except Exception as e:
                return self._send_json({"error": str(e)}, 500)
            return self._send_json({"players": rows, "team_label": "Free Agent"})
        if path == "/api/state":
            qs = parse_qs(parsed.query)
            window = _normalize_window((qs.get("window") or [DEFAULT_WINDOW])[0])
            sp = _state_path(window)
            if sp.is_file():
                raw = json.loads(sp.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raw = {}
                raw.setdefault("window", window)
                return self._send_json(raw)
            self.send_response(404)
            self.end_headers()
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/save":
            data = self._read_json()
            payload = build_state_payload(data)
            window = payload["window"]
            sp = _state_path(window)
            sp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return self._send_json(
                {
                    "ok": True,
                    "path": str(sp),
                    "window": window,
                    "transfers_count": len(payload.get("transfers") or []),
                    "data_dir": str(_data_dir()),
                }
            )
        if parsed.path == "/api/export":
            qs = parse_qs(parsed.query)
            fmt = (qs.get("fmt") or ["txt"])[0]
            kind = (qs.get("kind") or ["squads"])[0]
            data = self._read_json()
            out_dir = _export_dir()
            if kind == "transfers":
                rows = compute_transfers(data)
                window = _normalize_window(data.get("window"))
                suffix = f"_{window}"
                if fmt == "xlsx":
                    out = out_dir / f"transfers_export{suffix}.xlsx"
                    try:
                        _write_export_xlsx(out, rows)
                    except ImportError:
                        return self._send_json({"ok": False, "error": "нужен openpyxl"}, 500)
                elif fmt == "simple":
                    out = out_dir / f"transfers_simple{suffix}.txt"
                    _write_transfers_simple_txt(out, rows)
                else:
                    out = out_dir / f"transfers_export{suffix}.txt"
                    _write_export_txt(out, rows)
                return self._send_json({"ok": True, "path": str(out), "count": len(rows)})
            rows = compute_squads(data)
            window = _normalize_window(data.get("window"))
            suffix = f"_{window}"
            if fmt == "xlsx":
                out = out_dir / f"squads_export{suffix}.xlsx"
                try:
                    _write_squads_xlsx(out, rows)
                except ImportError:
                    return self._send_json({"ok": False, "error": "нужен openpyxl"}, 500)
            elif fmt == "table":
                out = out_dir / f"squads_table{suffix}.txt"
                _write_squads_table_txt(out, rows)
            else:
                out = out_dir / f"squads_export{suffix}.txt"
                _write_squads_txt(out, data)
                return self._send_json(
                    {
                        "ok": True,
                        "path": str(out),
                        "count": sum(
                            1
                            for t in data.get("teams") or []
                            for z in ("start", "bench", "reserve")
                            for p in t.get(z) or []
                            if p.get("name")
                        ),
                    }
                )
            return self._send_json({"ok": True, "path": str(out), "count": len(rows)})
        if parsed.path == "/api/import-squads":
            data = self._read_json()
            text = str(data.get("text") or "")
            teams_in = data.get("teams") or []
            updated, notes = _merge_squads_from_bot_export(teams_in, text)
            return self._send_json({"ok": True, "teams": updated, "notes": notes})
        if parsed.path == "/api/fa/create":
            data = self._read_json()
            try:
                from utils.free_agents_db import add_free_agent_player

                row = add_free_agent_player(
                    name=str(data.get("name") or ""),
                    position=str(data.get("position") or ""),
                    overall=int(data.get("overall") or 72),
                    nation=str(data.get("nation") or "") or None,
                    nickname=str(data.get("nickname") or "") or None,
                    status=str(data.get("status") or "bench"),
                )
            except Exception as e:
                return self._send_json({"ok": False, "error": str(e)}, 400)
            return self._send_json({"ok": True, "player": row})
        if parsed.path == "/api/fa/apply-to-db":
            """Записать нового игрока сразу в клуб (минуя FA pool) — для подтверждения из UI."""
            data = self._read_json()
            try:
                from utils.player_transfer import add_player_to_club

                add_player_to_club(
                    str(data.get("name") or ""),
                    str(data.get("position") or ""),
                    str(data.get("team") or ""),
                    str(data.get("status") or "bench"),
                    int(data.get("overall") or 72),
                    nation=str(data.get("nation") or "") or None,
                )
                if data.get("nickname"):
                    from utils.person_registry import lookup_canonical_person_id
                    from utils.player_nicknames import set_nickname

                    pid = lookup_canonical_person_id(
                        str(data.get("name") or ""),
                        str(data.get("position") or ""),
                        team=str(data.get("team") or ""),
                    )
                    if pid:
                        set_nickname(
                            int(pid),
                            str(data.get("nickname")),
                            name=str(data.get("name") or ""),
                            team=str(data.get("team") or ""),
                        )
            except Exception as e:
                return self._send_json({"ok": False, "error": str(e)}, 400)
            return self._send_json({"ok": True})
        self.send_error(404)


def _port_is_open(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.15)
        try:
            return s.connect_ex(("127.0.0.1", port)) == 0
        except OSError:
            return False


def _open_browser_when_ready(url: str, port: int) -> None:
    """Открыть браузер сразу после готовности порта (без лишней паузы)."""
    for _ in range(40):  # ~2 с
        if _port_is_open(port):
            webbrowser.open(url)
            return
        threading.Event().wait(0.05)
    webbrowser.open(url)


def main() -> int:
    port = 8765
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    url = f"http://127.0.0.1:{port}/"

    migrated = _migrate_legacy_state_files()
    data = _data_dir()

    # Повторный клик по .app: сервер уже крутится — сразу браузер, без второго процесса.
    if _port_is_open(port):
        _write_startup_log(f"already running → {url}")
        webbrowser.open(url)
        return 0

    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        _write_startup_log(f"bind failed: {e}")
        if _port_is_open(port):
            webbrowser.open(url)
            return 0
        raise

    print(f"Transfer Window: {url}")
    print(f"Сейвы и экспорты: {data}")
    print("Окна: лето 5/5, зима 2/2 — переключатель в шапке.")
    if migrated:
        print("Перенесены старые сейвы:")
        for line in migrated:
            print(f"  {line}")
    _write_startup_log(f"start {url} data={data}")
    threading.Thread(
        target=_open_browser_when_ready, args=(url, port), daemon=True
    ).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nСтоп.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
