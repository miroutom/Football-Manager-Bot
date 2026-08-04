#!/bin/bash
# Мультиплеер из разных квартир: HTTPS через Yandex si-infra tunneler.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd ../.. && pwd)"
cd "$ROOT"

if [[ ! -f tools/transfer_window_app/rosters.json ]]; then
  echo "Нет rosters.json — сначала:"
  echo "  python3 tools/transfer_window_app/export_rosters.py"
  exit 1
fi

DOCS="https://docs.yandex-team.ru/si-infra/tunneler/tunneler"

if [[ -n "${TW_TUNNEL_URL:-}" ]]; then
  exec python3 tools/transfer_window_app/main.py --tunnel --tunnel-url "$TW_TUNNEL_URL" "$@"
fi

if ! command -v tunneler >/dev/null 2>&1 && [[ -z "${TUNNELER_BIN:-}" ]]; then
  echo "Нужен Yandex tunneler (si-infra):"
  echo "  $DOCS"
  echo ""
  echo "Если tunneler уже запущен вручную — передай ссылку:"
  echo "  TW_TUNNEL_URL='https://…' $0"
  echo "  python3 tools/transfer_window_app/main.py --tunnel --tunnel-url 'https://…'"
  exit 1
fi

exec python3 tools/transfer_window_app/main.py --tunnel "$@"
