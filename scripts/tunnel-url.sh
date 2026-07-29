#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

COMPOSE="docker compose -f compose.tunnel.yaml"
RUNTIME_DIR="$ROOT/storage/runtime"
URL_FILE="$RUNTIME_DIR/public-url.txt"
attempts=0
public_url=""

while [ "$attempts" -lt 30 ]; do
  public_url=$(
    $COMPOSE logs --no-color cloudflared 2>/dev/null \
      | grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' \
      | tail -n 1 \
      || true
  )
  if [ -n "$public_url" ]; then
    break
  fi
  attempts=$((attempts + 1))
  sleep 2
done

if [ -z "$public_url" ]; then
  printf '%s\n' "Quick Tunnel URL을 cloudflared 로그에서 찾지 못했습니다." >&2
  exit 1
fi

attempts=0
while [ "$attempts" -lt 30 ]; do
  if curl --fail --silent --show-error --max-time 10 \
    "$public_url/health" | grep -q '^ok$'; then
    break
  fi
  attempts=$((attempts + 1))
  sleep 2
done

if [ "$attempts" -ge 30 ]; then
  printf '%s\n' "Quick Tunnel 주소의 /health 검증에 실패했습니다." >&2
  exit 1
fi

live_file=$(mktemp /tmp/esafe-live.XXXXXX)
demo_file=$(mktemp /tmp/esafe-demo.XXXXXX)
trap 'rm -f "$live_file" "$demo_file"' EXIT INT TERM
curl --fail --silent --show-error --max-time 20 \
  "$public_url/live/" >"$live_file"
curl --fail --silent --show-error --max-time 20 \
  "$public_url/demo/" >"$demo_file"
grep -q 'E-Safe' "$live_file"
grep -q 'E-Safe' "$demo_file"

mkdir -p "$RUNTIME_DIR"
temporary_file=$(mktemp "$RUNTIME_DIR/public-url.XXXXXX")
printf '%s\n' "$public_url" >"$temporary_file"
chmod 600 "$temporary_file"
mv -f "$temporary_file" "$URL_FILE"

printf '%s\n' "$public_url"
