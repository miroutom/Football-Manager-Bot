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
  PATHS=$(curl -sf http://127.0.0.1:8765/api/paths 2>/dev/null || true)
  CFG=$(curl -sf http://127.0.0.1:8765/api/config 2>/dev/null || true)
  STALE=
  if [[ -n "$PATHS" ]] && ! echo "$PATHS" | grep -q export_dir; then
    STALE=1
  fi
  if [[ -n "$CFG" ]] && ! echo "$CFG" | grep -q '"modes"'; then
    STALE=1
  fi
  if [[ -n "$CFG" ]] && ! echo "$CFG" | grep -q '"coaches"'; then
    STALE=1
  fi
  if [[ -n "$STALE" ]]; then
    echo "На :8765 старый сервер (нет режима «Сборные ЧМ» или списка тренеров) — останови (Ctrl+C) и запусти run.sh снова."
    echo "Или: lsof -ti :8765 | xargs kill -9 && ./run.sh"
    exit 1
  fi
  echo "Уже запущено на :8765"
  python3 main.py --lan --no-browser 2>/dev/null || true
  open "http://127.0.0.1:8765/" 2>/dev/null || true
  exit 0
fi
exec python3 main.py "$@"
