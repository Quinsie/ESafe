#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

TMP_DIR=$(mktemp -d /tmp/esafe-smoke.XXXXXX)
trap 'rm -rf "$TMP_DIR"' EXIT INT TERM
PUBLIC_USER_ID=$(sed -n 's/^ESAFE_PUBLIC_USER_ID=//p' .env)
PUBLIC_USER_PASSWORD=$(sed -n 's/^ESAFE_PUBLIC_USER_PASSWORD=//p' .env)
ORIGIN=http://127.0.0.1:8080

wait_for_profile() {
  profile=$1
  expected=$2
  attempts=0
  until payload=$(curl --fail --silent --show-error "$ORIGIN/$profile/api/v1/health/live"); do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge 60 ]; then
      echo "Timed out waiting for $profile" >&2
      return 1
    fi
    sleep 2
  done
  actual=$(printf '%s' "$payload" | jq -r .meta.profile)
  test "$actual" = "$expected"
}

assert_status() {
  expected=$1
  url=$2
  actual=$(curl --silent --output /dev/null --write-out '%{http_code}' "$url")
  test "$actual" = "$expected"
}

login_and_verify() {
  profile=$1
  expected=$2
  jar="$TMP_DIR/$profile.cookies"
  body=$(jq -n --arg user "$PUBLIC_USER_ID" --arg password "$PUBLIC_USER_PASSWORD" \
    '{userId: $user, password: $password}')
  curl --fail --silent --show-error \
    --cookie-jar "$jar" \
    --header "Origin: $ORIGIN" \
    --header 'Content-Type: application/json' \
    --data "$body" \
    "$ORIGIN/$profile/api/v1/auth/login" >/dev/null

  payload=$(curl --fail --silent --show-error \
    --cookie "$jar" "$ORIGIN/$profile/api/v1/meta")
  actual=$(printf '%s' "$payload" | jq -r .data.profile)
  test "$actual" = "$expected"

  csrf_name="esafe_${profile}_csrf"
  csrf=$(awk -v name="$csrf_name" '$6 == name { print $7 }' "$jar")
  test -n "$csrf"
  curl --fail --silent --show-error \
    --cookie "$jar" \
    --header "Origin: $ORIGIN" \
    --header "X-CSRF-Token: $csrf" \
    --request POST \
    "$ORIGIN/$profile/api/v1/auth/logout" >/dev/null
}

wait_for_profile live LIVE
wait_for_profile demo DEMO

assert_status 401 "$ORIGIN/live/api/v1/meta"
assert_status 401 "$ORIGIN/demo/api/v1/reference/meta"
assert_status 404 "$ORIGIN/live/api/v1/health/ready"
assert_status 404 "$ORIGIN/demo/api/docs"

login_and_verify live LIVE
login_and_verify demo DEMO

curl --fail --silent --show-error "$ORIGIN/live/" | grep -q 'E-Safe'
curl --fail --silent --show-error "$ORIGIN/demo/" | grep -q 'E-Safe'

docker compose exec -T db-live sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$0"' \
  "SELECT extname FROM pg_extension WHERE extname IN ('postgis','vector') ORDER BY extname" \
  | grep -q postgis
docker compose exec -T db-demo sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$0"' \
  "SELECT extname FROM pg_extension WHERE extname IN ('postgis','vector') ORDER BY extname" \
  | grep -q vector

live_schema=$(docker compose exec -T db-live sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$0"' \
  "SELECT (SELECT version_num FROM alembic_version) || ':' || (SELECT value FROM system_metadata WHERE key = 'bootstrap_profile')")
demo_schema=$(docker compose exec -T db-demo sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$0"' \
  "SELECT (SELECT version_num FROM alembic_version) || ':' || (SELECT value FROM system_metadata WHERE key = 'bootstrap_profile')")
test "$live_schema" = "20260729_0003:LIVE"
test "$demo_schema" = "20260729_0003:DEMO"

live_queue=$(docker compose exec -T redis-live sh -c \
  'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --raw LLEN live')
demo_queue=$(docker compose exec -T redis-demo sh -c \
  'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --raw LLEN demo')
test "$live_queue" -ge 0
test "$demo_queue" -ge 0

echo "ESafe authenticated stack smoke passed"