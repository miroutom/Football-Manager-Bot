#!/bin/bash
# Запуск Transfer Window (macOS / Linux).
# Из этой папки: ./run.sh
# Или из корня проекта: ./tools/transfer_window_app/run.sh
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -f rosters.json ]]; then
  echo "Нет rosters.json — сначала:"
  echo "  python3 export_rosters.py   # из корня проекта с БД"
  exit 1
fi
exec python3 main.py "$@"
