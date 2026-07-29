#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

if ! docker network inspect esafe_edge >/dev/null 2>&1; then
  printf '%s\n' "esafe_edge 네트워크가 없습니다. 기본 앱 stack을 먼저 시작하세요." >&2
  exit 1
fi

gateway_health=$(
  docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
    esafe-gateway-1 2>/dev/null || true
)
if [ "$gateway_health" != "healthy" ]; then
  printf '%s\n' "gateway가 healthy 상태가 아닙니다: ${gateway_health:-not-found}" >&2
  exit 1
fi

docker compose -f compose.tunnel.yaml up -d

attempts=0
while [ "$attempts" -lt 20 ]; do
  health=$(docker inspect --format '{{.State.Health.Status}}' esafe-tunnel-cloudflared-1 2>/dev/null || true)
  if [ "$health" = "healthy" ]; then
    exec "$ROOT/scripts/tunnel-url.sh"
  fi
  attempts=$((attempts + 1))
  sleep 2
done

docker compose -f compose.tunnel.yaml logs --no-color --tail=50 cloudflared >&2
exit 1
