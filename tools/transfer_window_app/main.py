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
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from multiplayer_state import (
    bump_state_meta,
    has_save_conflict,
    state_meta,
    state_revision,
)
from remote_tunnel import start_remote_tunnel, tunnel_backend

WINDOW_QUOTAS: dict[str, dict[str, int]] = {
    "summer": {"max_in": 5, "max_out": 5, "label": "Лето"},
    "winter": {"max_in": 2, "max_out": 2, "label": "Зима"},
}
DEFAULT_WINDOW = "summer"
_BIND_HOST = "127.0.0.1"
_SERVER_PORT = 8765
_TUNNEL_URL: str | None = None
_TUNNEL_PENDING = False
_TUNNEL_ERROR: str | None = None
_TUNNEL_PROC = None
_state_lock = threading.Lock()


def _lan_ip_priority(ip: str) -> int:
    parts = ip.split(".")
    if len(parts) != 4:
        return 50
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return 50
    if a == 192 and b == 168:
        return 0
    if a == 10:
        return 1
    if a == 100:  # Tailscale / CGNAT tailnet
        return 2
    if a == 172 and 16 <= b <= 31:
        return 4
    return 10


def _endpoint_label(ip: str) -> str:
    pr = _lan_ip_priority(ip)
    if pr == 0:
        return "Wi‑Fi"
    if pr == 1:
        return "Локальная сеть"
    if pr == 2:
        return "Tailscale"
    if pr >= 4:
        return "VPN (обычно не для друга)"
    return "Сеть"


def collect_share_endpoints(port: int | None = None) -> list[dict[str, str]]:
    """Адреса для мультиплеера: Wi‑Fi, Tailscale (100.x на utun), без VPN 172.x."""
    import re
    import subprocess

    p = int(port or _SERVER_PORT)
    out = ""
    try:
        out = subprocess.check_output(["ifconfig"], text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        ip = _guess_lan_ip_via_route()
        if ip:
            return [
                {
                    "ip": ip,
                    "url": f"http://{ip}:{p}/",
                    "label": _endpoint_label(ip),
                    "kind": "fallback",
                }
            ]
        return []

    skip_prefixes = ("lo", "gif", "stf", "bridge", "awdl", "llw")
    candidates: list[tuple[int, str, str]] = []

    for block in re.split(r"\n(?=\w)", out):
        head = block.split("\n", 1)[0]
        if ":" not in head:
            continue
        iface = head.split(":")[0]
        m = re.search(r"\n\tinet (\d+\.\d+\.\d+\.\d+)", block)
        if not m:
            continue
        ip = m.group(1)
        if ip.startswith("127."):
            continue

        if iface.startswith("utun"):
            if ip.startswith("100."):
                candidates.append((2, ip, "Tailscale"))
            continue

        if any(iface.startswith(pfx) for pfx in skip_prefixes):
            continue

        candidates.append((_lan_ip_priority(ip), ip, _endpoint_label(ip)))

    seen: set[str] = set()
    endpoints: list[dict[str, str]] = []
    for _prio, ip, label in sorted(candidates):
        if ip in seen:
            continue
        seen.add(ip)
        endpoints.append(
            {
                "ip": ip,
                "url": f"http://{ip}:{p}/",
                "label": label,
                "kind": label.casefold().replace(" ", "_"),
            }
        )

    if not endpoints:
        ip = _guess_lan_ip_via_route()
        if ip:
            endpoints.append(
                {
                    "ip": ip,
                    "url": f"http://{ip}:{p}/",
                    "label": _endpoint_label(ip),
                    "kind": "fallback",
                }
            )
    return endpoints


def _collect_lan_ips() -> list[str]:
    return [e["ip"] for e in collect_share_endpoints()]


def _guess_lan_ip_via_route() -> str | None:
    import re
    import subprocess

    try:
        out = subprocess.check_output(["route", "-n", "get", "default"], text=True, timeout=3)
        m = re.search(r"interface:\s*(\S+)", out)
        if not m:
            return None
        iface = m.group(1)
        out2 = subprocess.check_output(["ifconfig", iface], text=True, timeout=3)
        m2 = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out2)
        if m2:
            ip = m2.group(1)
            if not ip.startswith("127."):
                return ip
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _guess_lan_ip() -> str | None:
    ips = _collect_lan_ips()
    return ips[0] if ips else None


def _multiplayer_config_payload() -> dict:
    endpoints = collect_share_endpoints(_SERVER_PORT)
    lan_ips = [e["ip"] for e in endpoints]
    lan_url = None
    tailscale_url = None
    for ep in endpoints:
        if ep.get("label") == "Tailscale":
            tailscale_url = ep["url"]
        elif _lan_ip_priority(ep["ip"]) <= 1 and not lan_url:
            lan_url = ep["url"]
    if not lan_url and lan_ips and _BIND_HOST == "0.0.0.0":
        lan_url = f"http://{lan_ips[0]}:{_SERVER_PORT}/"

    share_url = _TUNNEL_URL or tailscale_url or lan_url
    live_sync = bool(_TUNNEL_URL or _TUNNEL_PENDING or _BIND_HOST == "0.0.0.0")
    return {
        "sync": True,
        "live_sync": live_sync,
        "lan_mode": _BIND_HOST == "0.0.0.0",
        "tunnel_mode": _TUNNEL_PENDING or bool(_TUNNEL_URL),
        "tunnel_pending": _TUNNEL_PENDING and not _TUNNEL_URL and not _TUNNEL_ERROR,
        "tunnel_error": _TUNNEL_ERROR,
        "host": _BIND_HOST,
        "port": _SERVER_PORT,
        "endpoints": endpoints,
        "lan_ips": lan_ips,
        "lan_url": lan_url,
        "tailscale_url": tailscale_url,
        "tunnel_url": _TUNNEL_URL,
        "share_url": share_url,
    }


def _on_tunnel_url(url: str) -> None:
    global _TUNNEL_URL, _TUNNEL_PENDING
    _TUNNEL_URL = url.rstrip("/") + "/"
    _TUNNEL_PENDING = False
    print("\n🌐 Удалённый доступ — отправь другу (любая квартира / мобильный интернет):")
    print(f"  {_TUNNEL_URL}")
    print("  Держи терминал открытым. Ссылка временная; сохраняйте часто (↻ синхронизация).")
    print("  ⚠️  Кто знает ссылку — может зайти. Только для доверенного напарника.\n")


def _on_tunnel_error(msg: str) -> None:
    global _TUNNEL_PENDING, _TUNNEL_ERROR
    _TUNNEL_PENDING = False
    _TUNNEL_ERROR = msg
    print(f"⚠️  Туннель: {msg}", file=sys.stderr)


def _start_remote_tunnel(port: int, *, preset_url: str = "", spawn: bool = True) -> None:
    global _TUNNEL_PENDING, _TUNNEL_PROC, _TUNNEL_URL
    preset = (preset_url or "").strip()
    if preset:
        _on_tunnel_url(preset)
        return
    if not spawn:
        _TUNNEL_PENDING = True
        print(
            "⏳ Режим --tunnel-manual: подними туннель в другом терминале "
            "(cloudflared или tunneler).",
            file=sys.stderr,
        )
        print(
            "  Затем перезапусти с --tunnel-url 'https://…' "
            "или TW_TUNNEL_URL=…",
            file=sys.stderr,
        )
        return
    _TUNNEL_PENDING = True
    backend = tunnel_backend()
    label = "cloudflared" if backend == "cloudflared" else "Yandex tunneler"
    print(f"⏳ Создаём публичную ссылку через {label}…")
    _TUNNEL_PROC = start_remote_tunnel(
        port,
        on_url=_on_tunnel_url,
        on_error=_on_tunnel_error,
    )


def _print_share_startup_hints(port: int, *, tunnel_mode: bool, lan_mode: bool) -> None:
    if tunnel_mode:
        if _TUNNEL_URL:
            print(f"Удалённая ссылка: {_TUNNEL_URL}")
        elif _TUNNEL_ERROR:
            print(f"⚠️  Туннель не поднялся: {_TUNNEL_ERROR}", file=sys.stderr)
        return

    if lan_mode:
        endpoints = collect_share_endpoints(port)
        wifi = [e for e in endpoints if _lan_ip_priority(e["ip"]) <= 1]
        tailscale = [e for e in endpoints if e.get("label") == "Tailscale"]
        if tailscale:
            print("Tailscale — работает из разных квартир (если оба в одной tailnet):")
            for ep in tailscale:
                print(f"  {ep['url']}")
        if wifi:
            print("LAN — только одна Wi‑Fi сеть (одна квартира / офис):")
            for ep in wifi:
                mark = " ← обычно эта" if ep["ip"].startswith("192.168.") else ""
                print(f"  {ep['url']}{mark}")
        if not wifi and not tailscale:
            print(
                f"LAN: IP не найден — напарнику http://<ваш-WiFi-IP>:{port}/",
                file=sys.stderr,
            )
        vpn_only = [e for e in endpoints if _lan_ip_priority(e["ip"]) >= 4]
        if vpn_only:
            print(
                "  (172.31… — часто VPN; для друга из другой квартиры не подходит)",
                file=sys.stderr,
            )
        print(
            "Из разных квартир без Tailscale: python3 tools/transfer_window_app/main.py --tunnel"
        )
        print("Сохраняйте часто (↻ синхронизация).")


def _load_window_state_file(window: str, *, mode: str = "clubs") -> dict | None:
    sp = _state_path(window, mode=mode)
    if not sp.is_file():
        return None
    try:
        raw = json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _ensure_national_rosters_json() -> Path:
    p = _national_rosters_path()
    if p.is_file():
        return p
    try:
        from export_national_rosters import export_all_national_rosters

        data = export_all_national_rosters()
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as e:
        _write_startup_log(f"national_rosters export failed: {e}")
    return p


def _persist_window_state(
    payload: dict,
    *,
    expected_revision: int | None,
    client_name: str,
    client_id: str,
) -> tuple[dict, bool]:
    """
    Сохранить state с revision++.
    Возвращает (payload, conflict).
    """
    window = _normalize_window(payload.get("window"))
    mode = _normalize_mode(payload.get("mode"))
    with _state_lock:
        current = _load_window_state_file(window, mode=mode)
        if has_save_conflict(current, expected_revision):
            return current or {}, True
        new_rev = state_revision(current) + 1
        out = bump_state_meta(
            payload,
            revision=new_rev,
            client_name=client_name,
            client_id=client_id,
        )
        out["mode"] = mode
        sp = _state_path(window, mode=mode)
        sp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        return out, False


def _parse_runtime_args(argv: list[str]) -> tuple[str, int, bool, bool, str, bool]:
    """host, port, open_browser, tunnel_mode, tunnel_url, tunnel_spawn."""
    host = "127.0.0.1"
    port = 8765
    open_browser = True
    tunnel_mode = "--tunnel" in argv or "--remote" in argv
    tunnel_url = (os.environ.get("TW_TUNNEL_URL") or "").strip()
    if "--tunnel-url" in argv:
        tunnel_url = argv[argv.index("--tunnel-url") + 1].strip()
    tunnel_spawn = "--tunnel-manual" not in argv
    if "--host" in argv:
        host = argv[argv.index("--host") + 1]
    elif "--lan" in argv:
        host = "0.0.0.0"
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    if "--no-browser" in argv:
        open_browser = False
    return host, port, open_browser, tunnel_mode, tunnel_url, tunnel_spawn


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


def _normalize_mode(raw: str | None) -> str:
    m = (raw or "clubs").strip().lower()
    return "nations" if m in ("nations", "nation", "wc", "national") else "clubs"


def _national_rosters_path() -> Path:
    p = _bundle_dir() / "national_rosters.json"
    if p.is_file():
        return p
    return _APP_DIR / "national_rosters.json"


def _rosters_path_for_mode(mode: str) -> Path:
    if _normalize_mode(mode) == "nations":
        return _national_rosters_path()
    return _rosters_path()


def _state_path(window: str = DEFAULT_WINDOW, *, mode: str = "clubs") -> Path:
    if _normalize_mode(mode) == "nations":
        return _data_dir() / "transfer_window_state_nations.json"
    w = _normalize_window(window)
    return _data_dir() / f"transfer_window_state_{w}.json"


def _export_dir() -> Path:
    """Папка для выгрузок из приложения (составы, трансферы, сборные)."""
    d = Path.home() / "Downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _enrich_teams_person_ids(teams: list) -> None:
    """Добавить person_id в JSON-заявку, если в экспорте его не было."""
    try:
        from utils.person_registry import lookup_canonical_person_id_by_team
    except Exception:
        return
    for team in teams or []:
        tn = str(team.get("name") or "").strip()
        if not tn:
            continue
        for zone in ("start", "bench", "reserve"):
            for p in team.get(zone) or []:
                if not isinstance(p, dict) or not p.get("name"):
                    continue
                if p.get("person_id"):
                    continue
                pid = lookup_canonical_person_id_by_team(str(p["name"]), team=tn)
                if pid:
                    p["person_id"] = int(pid)


def _load_nations_catalog() -> dict[str, list[str]]:
    """Сборные из world_cup_config.json (несколько путей — dev, .app bundle)."""
    paths = [
        _ROOT / "data" / "world_cup_config.json",
        _bundle_dir() / "data" / "world_cup_config.json",
        Path(__file__).resolve().parents[2] / "data" / "world_cup_config.json",
    ]
    for path in paths:
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            by_conf = raw.get("nations_by_confederation") or {}
            if isinstance(by_conf, dict) and by_conf:
                return {
                    str(k): [str(x) for x in v]
                    for k, v in by_conf.items()
                    if isinstance(v, list)
                }
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    try:
        from utils.world_cup import nations_by_confederation

        cat = nations_by_confederation()
        if cat:
            return cat
    except Exception:
        pass
    return {}


def _nations_flat(catalog: dict[str, list[str]] | None = None) -> list[str]:
    cat = catalog if catalog is not None else _load_nations_catalog()
    seen: set[str] = set()
    out: list[str] = []
    for lst in cat.values():
        for name in lst:
            s = str(name).strip()
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(s)
    out.sort(key=lambda x: x.casefold())
    return out


def _load_coaches_list() -> list[str]:
    try:
        from coach_squad_state import list_coach_display_names

        return list_coach_display_names()
    except Exception:
        return []


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


def _normalize_fa_player(raw: dict) -> dict | None:
    from utils.free_agents_db import fa_player_id

    name = str(raw.get("name") or "").strip()
    pos = str(raw.get("position") or "").strip().upper()
    if not name or not pos:
        return None
    pid = raw.get("id") or fa_player_id(name, pos)
    nick = raw.get("nickname")
    return {
        "id": pid,
        "person_id": raw.get("person_id"),
        "name": name,
        "position": pos,
        "overall": int(raw.get("overall") or 0),
        "nation": (raw.get("nation") or "") or "",
        "nickname": (nick or "") or "",
        "status": (raw.get("status") or "bench") or "bench",
        "fired": bool(raw.get("fired")),
    }


def import_fa_payload(data: dict, *, sync_db: bool = True) -> tuple[list[dict], list[str]]:
    """JSON из бота (free_agents.json) → список для UI; опционально пишет в free_agents.db."""
    raw = data.get("players")
    if not isinstance(raw, list):
        raw = data.get("free_agents")
    if not isinstance(raw, list):
        raise ValueError("Нужен JSON из бота: поле players (free_agents.json).")

    notes: list[str] = []
    if sync_db:
        from utils.free_agents_db import add_free_agent_player

        for row in raw:
            p = _normalize_fa_player(row if isinstance(row, dict) else {})
            if not p:
                continue
            try:
                add_free_agent_player(
                    name=p["name"],
                    position=p["position"],
                    overall=int(p["overall"] or 72),
                    nation=(p.get("nation") or "") or None,
                    person_id=p.get("person_id"),
                    nickname=(p.get("nickname") or "") or None,
                    status=p.get("status") or "bench",
                )
            except ValueError as e:
                notes.append(str(e))

    try:
        from utils.free_agents_db import list_free_agents

        players = list_free_agents()
    except Exception:
        players = [p for row in raw if (p := _normalize_fa_player(row if isinstance(row, dict) else {}))]
    return players, notes


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
            if isinstance(ent, dict):
                name = (ent.get("name") or "").strip()
                pos = (ent.get("position") or "").strip().upper()
                ovr = int(ent.get("overall") or 0)
            else:
                name = (ent[0] or "").strip()
                pos = (ent[1] or "").strip().upper()
                ovr = int(ent[3] or 0) if len(ent) > 3 and ent[3] is not None else 0
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


def _squads_validation_error(data: dict) -> str | None:
    mode = _normalize_mode(data.get("mode"))
    teams = data.get("teams") or []
    if mode == "nations":
        from utils.wc_squad_quota import WC_TOTAL, evaluate_wc_squad, format_wc_quota_hint

        lines: list[str] = []
        for team in teams:
            name = team.get("name") or "?"
            roster = []
            for zone in ("start", "bench", "reserve"):
                for p in team.get(zone) or []:
                    if p and p.get("name"):
                        row = dict(p)
                        row["status"] = zone
                        if zone == "start" and row.get("slot"):
                            row["lineup_slot"] = row["slot"]
                        roster.append(row)
            ev = evaluate_wc_squad(roster)
            if ev.get("complete"):
                continue
            lines.append(f"{name}: {format_wc_quota_hint(ev)}")
        if not lines:
            return None
        head = f"Неполная заявка сборной ({WC_TOTAL} игроков):"
        tail = f"\n… и ещё {len(lines) - 12}" if len(lines) > 12 else ""
        return head + "\n" + "\n".join(lines[:12]) + tail

    from utils.transfer_squad_quota import evaluate_all_teams, format_missing_hint

    formations = data.get("formations")
    if not formations:
        rp = _rosters_path()
        if rp.is_file():
            formations = json.loads(rp.read_text(encoding="utf-8")).get("formations") or []
    ev = evaluate_all_teams(teams, formations or [])
    if ev.get("all_complete"):
        return None
    lines: list[str] = []
    for row in ev.get("teams") or []:
        if row.get("complete"):
            continue
        hint = format_missing_hint(row)
        lines.append(f"{row.get('team')}: {hint}")
    if not lines:
        return None
    head = "Неполная заявка (32 игрока: 11 основа + 21 замена по слотам схемы):"
    tail = f"\n… и ещё {len(lines) - 12}" if len(lines) > 12 else ""
    return head + "\n" + "\n".join(lines[:12]) + tail


def _squad_rules_payload(mode: str = "clubs") -> dict:
    if _normalize_mode(mode) == "nations":
        from utils.wc_squad_quota import WC_BENCH, WC_RESERVE, WC_START, WC_TOTAL

        return {
            "total": WC_TOTAL,
            "start": WC_START,
            "bench": WC_BENCH,
            "reserve": WC_RESERVE,
            "hint": f"{WC_TOTAL} игроков: {WC_START} старт + {WC_BENCH} запас + {WC_RESERVE} резерв (ЧМ)",
        }
    from utils.squad_limits import transfer_app_squad_limits
    from utils.transfer_squad_quota import SQUAD_RESERVE, SQUAD_START, SQUAD_TOTAL

    lim = transfer_app_squad_limits()
    return {
        "total": lim["total"],
        "start": lim["start"],
        "reserve": lim["reserve"],
        "reserve_per_slot": {"default": 2, "GK": 1},
        "hint": (
            f"{SQUAD_TOTAL} игроков: {SQUAD_START} в основе + {SQUAD_RESERVE} замен "
            "(по 2 на каждый слот схемы, у вратаря 1)"
        ),
    }


def build_state_payload(data: dict) -> dict:
    """Persisted state: squads + baseline + computed transfer log + window."""
    baseline_home = data.get("baseline_home") or {}
    teams = data.get("teams") or []
    free_agents = data.get("free_agents") or []
    removed_from_squad = data.get("removed_from_squad") or {}
    season = data.get("season")
    window = _normalize_window(data.get("window"))
    state = {
        "mode": _normalize_mode(data.get("mode")),
        "window": window,
        "season": season,
        "rosters_revision": data.get("rosters_revision"),
        "baseline_home": baseline_home,
        "teams": teams,
        "free_agents": free_agents,
        "removed_from_squad": removed_from_squad,
    }
    if state["mode"] == "clubs":
        state["transfers"] = compute_transfers(state)
    else:
        state["transfers"] = []
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
            try:
                from utils.utils import defenders, forwards, goalkeepers, midfielders

                positions = list(
                    dict.fromkeys([*goalkeepers, *defenders, *midfielders, *forwards])
                )
            except Exception:
                positions = [
                    "ВРТ", "ЛЗ", "ПЗ", "ЦЗ", "ЛЦЗ", "ПЦЗ", "ЛФЗ", "ПФЗ",
                    "ЦП", "ЦАП", "ЦОП", "ЛП", "ПП", "ЛЦП", "ПЦП",
                    "ЛФА", "ПФА", "ФРВ",
                ]
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
            try:
                nations_catalog = _load_nations_catalog()
            except Exception:
                nations_catalog = {}
            coaches_list = _load_coaches_list()
            return self._send_json(
                {
                    "default_window": DEFAULT_WINDOW,
                    "default_mode": "clubs",
                    "modes": {
                        "clubs": {"label": "Клубы", "squad_rules": _squad_rules_payload("clubs")},
                        "nations": {
                            "label": "Сборные ЧМ",
                            "squad_rules": _squad_rules_payload("nations"),
                        },
                    },
                    "windows": WINDOW_QUOTAS,
                    "data_dir": str(_data_dir()),
                    "leagues": leagues,
                    "positions": positions,
                    "coaches": coaches_list,
                    "fa_team": "Free Agent",
                    "squad_rules": _squad_rules_payload("clubs"),
                    "multiplayer": _multiplayer_config_payload(),
                    "nations_by_confederation": nations_catalog,
                    "nations": _nations_flat(nations_catalog),
                }
            )
        if path == "/api/nations":
            catalog = _load_nations_catalog()
            return self._send_json(
                {
                    "ok": True,
                    "nations_by_confederation": catalog,
                    "nations": _nations_flat(catalog),
                    "count": len(_nations_flat(catalog)),
                }
            )
        if path == "/api/coaches":
            return self._send_json({"ok": True, "coaches": _load_coaches_list()})
        if path == "/api/player-profiles":
            from player_profiles import load_profiles

            return self._send_json(
                {"ok": True, "profiles": load_profiles(_data_dir())}
            )
        if path == "/api/paths":
            return self._send_json(
                {
                    "data_dir": str(_data_dir()),
                    "export_dir": str(_export_dir()),
                    "rosters": str(_rosters_path()),
                    "national_rosters": str(_national_rosters_path()),
                    "state_summer": str(_state_path("summer")),
                    "state_winter": str(_state_path("winter")),
                    "state_nations": str(_state_path(mode="nations")),
                }
            )
        if path == "/api/rosters":
            qs = parse_qs(parsed.query)
            mode = _normalize_mode((qs.get("mode") or ["clubs"])[0])
            if mode == "nations":
                p = _ensure_national_rosters_json()
            else:
                p = _rosters_path()
            if not p.is_file():
                return self._send_json({"error": f"нет {p}"}, 500)
            payload = json.loads(p.read_text(encoding="utf-8"))
            if mode != "nations":
                _enrich_teams_person_ids(payload.get("teams") or [])
            try:
                payload["rosters_revision"] = int(p.stat().st_mtime)
            except OSError:
                payload.setdefault("rosters_revision", payload.get("exported_at"))
            try:
                from utils.free_agents_db import list_free_agents

                payload["free_agents"] = list_free_agents()
            except Exception:
                payload.setdefault("free_agents", payload.get("free_agents") or [])
            payload.setdefault("mode", mode)
            return self._send_json(payload)
        if path == "/api/national-pools":
            try:
                from national_pools import build_all_national_pools

                data = build_all_national_pools()
            except Exception as e:
                return self._send_json({"ok": False, "error": str(e)}, 500)
            return self._send_json({"ok": True, **data})
        if path == "/api/free-agents":
            try:
                from utils.free_agents_db import list_free_agents

                rows = list_free_agents()
            except Exception as e:
                return self._send_json({"error": str(e)}, 500)
            return self._send_json({"players": rows, "team_label": "Free Agent"})
        if path == "/api/state/meta":
            qs = parse_qs(parsed.query)
            mode = _normalize_mode((qs.get("mode") or ["clubs"])[0])
            window = _normalize_window((qs.get("window") or [DEFAULT_WINDOW])[0])
            raw = _load_window_state_file(window, mode=mode)
            meta = state_meta(raw)
            meta["window"] = window
            meta["mode"] = mode
            return self._send_json(meta)
        if path == "/api/state":
            qs = parse_qs(parsed.query)
            mode = _normalize_mode((qs.get("mode") or ["clubs"])[0])
            window = _normalize_window((qs.get("window") or [DEFAULT_WINDOW])[0])
            raw = _load_window_state_file(window, mode=mode)
            if raw is not None:
                raw.setdefault("window", window)
                raw.setdefault("mode", mode)
                return self._send_json(raw)
            self.send_response(404)
            self.end_headers()
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/player-profiles":
            data = self._read_json()
            from player_profiles import load_profiles, merge_profile, save_profiles

            profiles = load_profiles(_data_dir())
            raw = data.get("profiles")
            if isinstance(raw, dict):
                profiles = {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}
            else:
                pid = data.get("person_id")
                try:
                    person_id = int(pid) if pid is not None else 0
                except (TypeError, ValueError):
                    person_id = 0
                if person_id > 0:
                    ovr = data.get("overall")
                    try:
                        overall = int(ovr) if ovr is not None else None
                    except (TypeError, ValueError):
                        overall = None
                    nation = data.get("nation")
                    nick = data.get("nickname")
                    profiles = merge_profile(
                        profiles,
                        person_id,
                        name=str(data.get("name") or "") or None,
                        position=str(data.get("position") or "") or None,
                        overall=overall,
                        nation=str(nation).strip() if nation is not None else None,
                        nickname=str(nick).strip() if nick is not None else None,
                        nickname_set="nickname" in data,
                    )
            save_profiles(_data_dir(), profiles)
            return self._send_json({"ok": True, "profiles": profiles})
        if parsed.path == "/api/player/update":
            data = self._read_json()
            try:
                from player_update import update_existing_player

                ovr_raw = data.get("overall")
                overall = None
                if ovr_raw is not None and str(ovr_raw).strip() != "":
                    overall = int(ovr_raw)
                result = update_existing_player(
                    team=str(data.get("team") or ""),
                    name=str(data.get("name") or ""),
                    position=str(data.get("position") or ""),
                    person_id=int(data["person_id"])
                    if data.get("person_id") not in (None, "")
                    else None,
                    new_name=str(data["new_name"]).strip()
                    if data.get("new_name") is not None
                    else None,
                    new_position=str(data["new_position"]).strip().upper()
                    if data.get("new_position") is not None
                    else None,
                    new_overall=overall,
                    new_nation=str(data.get("nation") or "").strip()
                    if "nation" in data
                    else None,
                    nation_set="nation" in data,
                    nickname=str(data.get("nickname") or "").strip()
                    if "nickname" in data
                    else None,
                    nickname_set="nickname" in data,
                )
                pid = result.get("person_id")
                if pid:
                    from player_profiles import load_profiles, merge_profile, save_profiles

                    profs = load_profiles(_data_dir())
                    p = result.get("player") or {}
                    profs = merge_profile(
                        profs,
                        int(pid),
                        name=p.get("name"),
                        position=p.get("position"),
                        overall=p.get("overall"),
                        nation=p.get("nation") or None,
                        nickname=p.get("nickname") or "",
                        nickname_set="nickname" in data,
                    )
                    save_profiles(_data_dir(), profs)
                    result["profiles"] = profs
            except Exception as e:
                return self._send_json({"ok": False, "error": str(e)}, 400)
            return self._send_json(result)
        if parsed.path == "/api/save":
            data = self._read_json()
            payload = build_state_payload(data)
            expected = data.get("revision")
            try:
                expected_revision = int(expected) if expected is not None else None
            except (TypeError, ValueError):
                expected_revision = None
            client_name = str(data.get("client_name") or "")
            client_id = str(data.get("client_id") or "")
            saved, conflict = _persist_window_state(
                payload,
                expected_revision=expected_revision,
                client_name=client_name,
                client_id=client_id,
            )
            if conflict:
                return self._send_json(
                    {
                        "ok": False,
                        "conflict": True,
                        "revision": state_revision(saved),
                        "updated_by": saved.get("updated_by") or "",
                        "server_state": saved,
                        "error": "Кто-то уже сохранил новее. Обновите или перезапишите.",
                    },
                    409,
                )
            window = saved["window"]
            mode = _normalize_mode(saved.get("mode"))
            sp = _state_path(window, mode=mode)
            return self._send_json(
                {
                    "ok": True,
                    "path": str(sp),
                    "window": window,
                    "mode": mode,
                    "revision": state_revision(saved),
                    "updated_by": saved.get("updated_by") or "",
                    "transfers_count": len(saved.get("transfers") or []),
                    "data_dir": str(_data_dir()),
                }
            )
        if parsed.path == "/api/export":
            qs = parse_qs(parsed.query)
            fmt = (qs.get("fmt") or ["txt"])[0]
            kind = (qs.get("kind") or ["squads"])[0]
            data = self._read_json()
            if kind in ("squads", "wc-squads"):
                err = _squads_validation_error(data)
                if err:
                    return self._send_json({"ok": False, "error": err}, 400)
            out_dir = _export_dir()
            if kind == "wc-squads":
                from utils.wc_squad_app import format_wc_squads_export_txt

                out = out_dir / "wc_squads_export.txt"
                out.write_text(
                    format_wc_squads_export_txt(data.get("teams") or []),
                    encoding="utf-8",
                )
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
                        "nations": len(data.get("teams") or []),
                    }
                )
            if kind == "national":
                try:
                    from national_pools import (
                        build_all_national_pools,
                        write_national_pools_json,
                        write_national_pools_txt,
                    )

                    pools = build_all_national_pools()
                except Exception as e:
                    return self._send_json({"ok": False, "error": str(e)}, 500)
                out_dir = _export_dir()
                if fmt == "json":
                    out = out_dir / "national_pools.json"
                    write_national_pools_json(str(out), pools)
                else:
                    out = out_dir / "national_pools.txt"
                    write_national_pools_txt(str(out), pools)
                return self._send_json(
                    {
                        "ok": True,
                        "path": str(out),
                        "nations": len(pools.get("nations") or []),
                        "count": pools.get("player_count") or 0,
                    }
                )
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
        if parsed.path == "/api/import-wc-squads":
            data = self._read_json()
            text = str(data.get("text") or "")
            try:
                from utils.wc_squad_app import parse_wc_squads_export_txt

                teams = parse_wc_squads_export_txt(text)
            except Exception as e:
                return self._send_json({"ok": False, "error": str(e)}, 400)
            if not teams:
                return self._send_json({"ok": False, "error": "Не найдено сборных (@Нация …)"}, 400)
            return self._send_json({"ok": True, "teams": teams, "count": len(teams)})
        if parsed.path == "/api/import-squads":
            data = self._read_json()
            text = str(data.get("text") or "")
            teams_in = data.get("teams") or []
            updated, notes = _merge_squads_from_bot_export(teams_in, text)
            return self._send_json({"ok": True, "teams": updated, "notes": notes})
        if parsed.path == "/api/import-national-pools":
            data = self._read_json()
            try:
                from national_pools import parse_national_pools_json

                parsed = parse_national_pools_json(data)
            except Exception as e:
                return self._send_json({"ok": False, "error": str(e)}, 400)
            return self._send_json({"ok": True, **parsed})
        if parsed.path == "/api/import-fa":
            data = self._read_json()
            try:
                players, notes = import_fa_payload(data, sync_db=True)
            except Exception as e:
                return self._send_json({"ok": False, "error": str(e)}, 400)
            return self._send_json(
                {
                    "ok": True,
                    "players": players,
                    "count": len(players),
                    "notes": notes[:15],
                }
            )
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
        if parsed.path == "/api/fa/release":
            data = self._read_json()
            try:
                from utils.free_agents_db import list_free_agents, release_club_player_to_fa

                info = release_club_player_to_fa(
                    str(data.get("name") or ""),
                    str(data.get("position") or ""),
                    str(data.get("from_team") or ""),
                    new_status=str(data.get("status") or "bench"),
                    new_overall=int(data["overall"]) if data.get("overall") is not None else None,
                )
                fa_id = info.get("fa_id") or ""
                player = next(
                    (p for p in list_free_agents() if p.get("id") == fa_id),
                    None,
                )
                if not player:
                    player = _normalize_fa_player(
                        {
                            "id": fa_id,
                            "name": info.get("name"),
                            "position": info.get("position"),
                            "person_id": info.get("person_id"),
                            "fired": True,
                            "status": data.get("status") or "bench",
                            "overall": data.get("overall") or 0,
                        }
                    )
            except Exception as e:
                return self._send_json({"ok": False, "error": str(e)}, 400)
            return self._send_json({"ok": True, "player": player})
        if parsed.path == "/api/fa/delete":
            data = self._read_json()
            try:
                from utils.free_agents_db import delete_free_agent_player

                pid = data.get("person_id")
                person_id = int(pid) if pid is not None and str(pid).strip() else None
                ok = delete_free_agent_player(
                    name=str(data.get("name") or ""),
                    position=str(data.get("position") or ""),
                    person_id=person_id,
                    fa_id=str(data.get("id") or "") or None,
                )
            except Exception as e:
                return self._send_json({"ok": False, "error": str(e)}, 400)
            if not ok:
                return self._send_json(
                    {"ok": False, "error": "игрок не найден в free_agents.db"},
                    404,
                )
            return self._send_json({"ok": True})
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


def _fetch_running_config(port: int) -> dict | None:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/config", timeout=1.5) as r:
            raw = json.loads(r.read().decode("utf-8"))
            return raw if isinstance(raw, dict) else None
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None


def _handle_already_running(port: int, *, want_lan: bool, open_browser: bool) -> int:
    url = f"http://127.0.0.1:{port}/"
    cfg = _fetch_running_config(port)
    mp = (cfg or {}).get("multiplayer") or {}
    lan_mode = bool(mp.get("lan_mode"))
    lan_url = mp.get("lan_url")
    tunnel_url = mp.get("tunnel_url")
    share_url = mp.get("share_url") or tunnel_url or lan_url

    if want_lan and not lan_mode and not tunnel_url:
        print(
            f"⚠️  Порт {port} занят старым Transfer Window (только localhost, без LAN).\n"
            "    Остановите его и запустите снова с --lan:\n"
            f"    lsof -i :{port}\n"
            "    kill <PID>\n"
            "    python3 tools/transfer_window_app/main.py --lan",
            file=sys.stderr,
        )
        if open_browser:
            webbrowser.open(url)
        return 1

    if tunnel_url:
        print(f"Уже запущено · удалённый доступ: {tunnel_url}")
        print(f"Локально: {url}")
    elif lan_mode and lan_url:
        ips = mp.get("lan_ips") or []
        if ips:
            print("Уже запущено · LAN (мультиплеер):")
            for ip in ips:
                mark = " ← обычно эта" if _lan_ip_priority(str(ip)) <= 1 else ""
                print(f"  http://{ip}:{port}/{mark}")
        else:
            print(f"Уже запущено · LAN (мультиплеер): {lan_url}")
        print(f"Локально: {url}")
    else:
        print(f"Уже запущено → {url}")
        if want_lan:
            lan = _guess_lan_ip()
            if lan:
                print(
                    f"⚠️  LAN-режим не подтверждён. Если нужен мультиплеер — перезапустите с --lan.",
                    file=sys.stderr,
                )
    _write_startup_log(f"already running → {url} lan={lan_mode} tunnel={bool(tunnel_url)}")
    if open_browser:
        webbrowser.open(share_url or url)
    return 0


def _open_browser_when_ready(url: str, port: int) -> None:
    """Открыть браузер сразу после готовности порта (без лишней паузы)."""
    for _ in range(40):  # ~2 с
        if _port_is_open(port):
            webbrowser.open(url)
            return
        threading.Event().wait(0.05)
    webbrowser.open(url)


def main() -> int:
    global _BIND_HOST, _SERVER_PORT
    _BIND_HOST, _SERVER_PORT, open_browser, tunnel_mode, tunnel_url, tunnel_spawn = (
        _parse_runtime_args(sys.argv)
    )
    port = _SERVER_PORT
    host = _BIND_HOST
    url = f"http://127.0.0.1:{port}/"

    migrated = _migrate_legacy_state_files()
    data = _data_dir()

    # Повторный клик по .app: сервер уже крутится — сразу браузер, без второго процесса.
    if _port_is_open(port):
        return _handle_already_running(
            port, want_lan=(host == "0.0.0.0"), open_browser=open_browser
        )

    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as e:
        _write_startup_log(f"bind failed: {e}")
        if _port_is_open(port):
            return _handle_already_running(
                port, want_lan=(host == "0.0.0.0"), open_browser=open_browser
            )
        raise

    print(f"Transfer Window: {url}")
    if tunnel_mode:
        _start_remote_tunnel(port, preset_url=tunnel_url, spawn=tunnel_spawn)
    if host == "0.0.0.0" or tunnel_mode:
        _print_share_startup_hints(port, tunnel_mode=tunnel_mode, lan_mode=(host == "0.0.0.0"))
    print(f"Сейвы и экспорты: {data}")
    print("Окна: лето 5/5, зима 2/2 — переключатель в шапке.")
    if migrated:
        print("Перенесены старые сейвы:")
        for line in migrated:
            print(f"  {line}")
    _write_startup_log(f"start {url} host={host} data={data}")
    if open_browser:
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
