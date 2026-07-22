#!/bin/bash
# Двойной клик в Finder — самый быстрый запуск (без сборки .app).
cd "$(dirname "$0")"
if [[ ! -f rosters.json ]]; then
  osascript -e 'display dialog "Нет rosters.json. Сначала: python3 export_rosters.py" buttons {"OK"} default button 1' >/dev/null 2>&1 || true
  exit 1
fi
# Если уже слушает 8765 — только браузер
if curl -sf -o /dev/null http://127.0.0.1:8765/; then
  open "http://127.0.0.1:8765/"
  exit 0
fi
exec python3 main.py "$@"
