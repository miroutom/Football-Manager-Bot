#!/bin/bash
# Мультиплеер в одной Wi‑Fi: сервер слушает 0.0.0.0, друг открывает http://192.168.x.x:8765/
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd ../.. && pwd)"
cd "$ROOT"

if [[ ! -f tools/transfer_window_app/rosters.json ]]; then
  echo "Нет rosters.json — сначала:"
  echo "  python3 tools/transfer_window_app/export_rosters.py"
  exit 1
fi

PORT="${TW_PORT:-8765}"

_check_lan_mode() {
  local cfg mp lan
  cfg="$(curl -sf "http://127.0.0.1:${PORT}/api/config" 2>/dev/null || true)"
  [[ -n "$cfg" ]] || return 1
  mp="$(python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d.get('multiplayer') or {}))" <<<"$cfg" 2>/dev/null || echo '{}')"
  lan="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('lan_mode'))" "$mp" 2>/dev/null || echo False)"
  [[ "$lan" == "True" ]]
}

if curl -sf -o /dev/null "http://127.0.0.1:${PORT}/" 2>/dev/null; then
  if _check_lan_mode; then
    echo "Уже запущено в LAN-режиме:"
    python3 -c "
import json, urllib.request
d = json.load(urllib.request.urlopen('http://127.0.0.1:${PORT}/api/config', timeout=2))
mp = d.get('multiplayer') or {}
for ip in mp.get('lan_ips') or []:
    print(f'  http://{ip}:${PORT}/')
print('Локально: http://127.0.0.1:${PORT}/')
"
    exit 0
  fi
  echo "⚠️  На :${PORT} уже крутится сервер БЕЗ LAN (только localhost)."
  echo "    Друг по Wi‑Fi не подключится. Останови и запусти снова:"
  echo "      lsof -i :${PORT}"
  echo "      kill <PID>"
  echo "      $0"
  exit 1
fi

exec python3 tools/transfer_window_app/main.py --lan --port "$PORT" "$@"
