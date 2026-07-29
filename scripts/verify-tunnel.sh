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

PUBLIC_USER_ID=$(sed -n 's/^ESAFE_PUBLIC_USER_ID=//p' .env)
PUBLIC_USER_PASSWORD=$(sed -n 's/^ESAFE_PUBLIC_USER_PASSWORD=//p' .env)
test -n "$PUBLIC_USER_ID"
test -n "$PUBLIC_USER_PASSWORD"
temporary_dir=$(mktemp -d /tmp/esafe-tunnel-verify.XXXXXX)
trap 'rm -rf "$temporary_dir"' EXIT INT TERM

verify_profile_login() {
  profile=$1
  expected=$2
  jar="$temporary_dir/$profile.cookies"
  login_body=$(jq -n --arg user "$PUBLIC_USER_ID" --arg password "$PUBLIC_USER_PASSWORD" \
    '{userId: $user, password: $password}')
  curl --fail --silent --show-error --max-time 20 \
    --cookie-jar "$jar" \
    --header "Origin: $public_url" \
    --header 'Content-Type: application/json' \
    --data "$login_body" \
    "$public_url/$profile/api/v1/auth/login" >/dev/null

  meta=$(curl --fail --silent --show-error --max-time 20 \
    --cookie "$jar" "$public_url/$profile/api/v1/meta")
  test "$(printf '%s' "$meta" | jq -r .data.profile)" = "$expected"

  csrf_name="esafe_${profile}_csrf"
  csrf=$(awk -v name="$csrf_name" '$6 == name { print $7 }' "$jar")
  test -n "$csrf"
  curl --fail --silent --show-error --max-time 20 \
    --cookie "$jar" \
    --header "Origin: $public_url" \
    --header "X-CSRF-Token: $csrf" \
    --request POST \
    "$public_url/$profile/api/v1/auth/logout" >/dev/null
}

verify_profile_login live LIVE
verify_profile_login demo DEMO

printf '%s\n' "$public_url"
