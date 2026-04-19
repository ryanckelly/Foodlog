#!/usr/bin/env bash
set -euo pipefail

required_vars=(
  CLOUDFLARE_TUNNEL_TOKEN
  FOODLOG_PUBLIC_BASE_URL
  FOODLOG_OAUTH_LOGIN_SECRET
)

for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    echo "Missing required environment variable: ${var_name}" >&2
    exit 1
  fi
done

cleanup() {
  if [[ -n "${APP_PID:-}" ]]; then
    kill "${APP_PID}" 2>/dev/null || true
  fi
  if [[ -n "${TUNNEL_PID:-}" ]]; then
    kill "${TUNNEL_PID}" 2>/dev/null || true
  fi
}

trap cleanup TERM INT

cloudflared tunnel --no-autoupdate run &
TUNNEL_PID=$!

python -m foodlog.api.app &
APP_PID=$!

wait -n "${TUNNEL_PID}" "${APP_PID}"
exit_code=$?
cleanup
exit "${exit_code}"
