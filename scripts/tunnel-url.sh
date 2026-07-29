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

case "$public_url" in
  https://*.trycloudflare.com) ;;
  *)
    printf '%s\n' "Quick Tunnel URL 형식이 올바르지 않습니다." >&2
    exit 1
    ;;
esac

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

desired_origins="http://127.0.0.1:8080,$public_url"
current_origins=$(sed -n 's/^ESAFE_PUBLIC_ORIGINS=//p' "$ROOT/.env")
if [ "$current_origins" != "$desired_origins" ]; then
  temporary_env=$(mktemp "$ROOT/.env.public-origin.XXXXXX")
  trap 'rm -f "$live_file" "$demo_file" "$temporary_env"' EXIT INT TERM
  awk -v origins="$desired_origins" '
    BEGIN { replaced = 0 }
    /^ESAFE_PUBLIC_ORIGINS=/ {
      print "ESAFE_PUBLIC_ORIGINS=" origins
      replaced = 1
      next
    }
    { print }
    END { if (!replaced) print "ESAFE_PUBLIC_ORIGINS=" origins }
  ' "$ROOT/.env" >"$temporary_env"
  chmod 600 "$temporary_env"
  mv -f "$temporary_env" "$ROOT/.env"
  docker compose up -d --no-deps api-live api-demo >/dev/null
  attempts=0
  while [ "$attempts" -lt 30 ]; do
    live_health=$(docker inspect --format '{{.State.Health.Status}}' esafe-api-live-1 2>/dev/null || true)
    demo_health=$(docker inspect --format '{{.State.Health.Status}}' esafe-api-demo-1 2>/dev/null || true)
    [ "$live_health" = healthy ] && [ "$demo_health" = healthy ] && break
    attempts=$((attempts + 1))
    sleep 2
  done
  if [ "$attempts" -ge 30 ]; then
    printf '%s\n' "공개 Origin 반영 후 API가 healthy 상태가 되지 않았습니다." >&2
    exit 1
  fi
fi

printf '%s\n' "$public_url"
