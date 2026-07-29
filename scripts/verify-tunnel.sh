#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

url_file="$ROOT/storage/runtime/public-url.txt"
if [ ! -s "$url_file" ]; then
  printf '%s\n' "기록된 Quick Tunnel URL이 없습니다." >&2
  exit 1
fi
public_url=$(sed -n '1p' "$url_file")
case "$public_url" in
  https://*.trycloudflare.com) ;;
  *)
    printf '%s\n' "기록된 URL 형식이 올바르지 않습니다." >&2
    exit 1
    ;;
esac

test "$(docker inspect --format '{{.State.Health.Status}}' \
  esafe-tunnel-cloudflared-1)" = "healthy"
test "$(curl --fail --silent --show-error --max-time 10 \
  "$public_url/health")" = "ok"
curl --fail --silent --show-error --max-time 20 \
  "$public_url/live/" | grep -q 'E-Safe'
curl --fail --silent --show-error --max-time 20 \
  "$public_url/demo/" | grep -q 'E-Safe'

printf '%s\n' "$public_url"
