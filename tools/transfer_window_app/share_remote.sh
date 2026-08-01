#!/bin/bash
# Мультиплеер из разных квартир: публичная HTTPS-ссылка через cloudflared.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd ../.. && pwd)"
cd "$ROOT"

if [[ ! -f tools/transfer_window_app/rosters.json ]]; then
  echo "Нет rosters.json — сначала:"
  echo "  python3 tools/transfer_window_app/export_rosters.py"
  exit 1
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Нужен cloudflared:"
  echo "  brew install cloudflared"
  echo "Или: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
  exit 1
fi

exec python3 tools/transfer_window_app/main.py --tunnel "$@"
