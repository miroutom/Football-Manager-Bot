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

if [[ -n "${TW_TUNNEL_URL:-}" ]]; then
  exec python3 tools/transfer_window_app/main.py --tunnel --tunnel-url "$TW_TUNNEL_URL" "$@"
fi

if [[ "${TW_TUNNEL_BACKEND:-cloudflared}" == "tunneler" ]]; then
  if ! command -v tunneler >/dev/null 2>&1 && [[ -z "${TUNNELER_BIN:-}" ]]; then
    echo "Нужен tunneler — см. https://docs.yandex-team.ru/si-infra/tunneler/tunneler"
    exit 1
  fi
else
  if ! command -v cloudflared >/dev/null 2>&1 && [[ -z "${CLOUDFLARED_BIN:-}" ]]; then
    echo "Нужен cloudflared:"
    echo "  brew install cloudflared"
    echo "  Windows: winget install Cloudflare.cloudflared"
    exit 1
  fi
fi

exec python3 tools/transfer_window_app/main.py --tunnel "$@"
