#!/bin/bash
# Запуск Transfer Window (macOS / Linux).
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -f rosters.json ]]; then
  echo "Нет rosters.json — сначала:"
  echo "  python3 export_rosters.py   # из корня проекта с БД"
  exit 1
fi
if curl -sf -o /dev/null http://127.0.0.1:8765/ 2>/dev/null; then
  echo "Уже запущено на :8765"
  python3 main.py --lan --no-browser 2>/dev/null || true
  open "http://127.0.0.1:8765/" 2>/dev/null || true
  exit 0
fi
exec python3 main.py "$@"
