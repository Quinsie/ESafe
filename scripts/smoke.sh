#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

wait_for_profile() {
  profile=$1
  expected=$2
  attempts=0
  until payload=$(curl --fail --silent --show-error "http://127.0.0.1:8080/$profile/api/v1/meta"); do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge 60 ]; then
      echo "Timed out waiting for $profile" >&2
      return 1
    fi
    sleep 2
  done
  actual=$(printf '%s' "$payload" | jq -r .data.profile)
  test "$actual" = "$expected"
}

wait_for_profile live LIVE
wait_for_profile demo DEMO

curl --fail --silent --show-error http://127.0.0.1:8080/live/ | grep -q 'E-Safe'
curl --fail --silent --show-error http://127.0.0.1:8080/demo/ | grep -q 'E-Safe'

docker compose exec -T db-live sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$0"' \
  "SELECT extname FROM pg_extension WHERE extname IN ('postgis','vector') ORDER BY extname" \
  | grep -q postgis
docker compose exec -T db-demo sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$0"' \
  "SELECT extname FROM pg_extension WHERE extname IN ('postgis','vector') ORDER BY extname" \
  | grep -q vector

live_queue=$(docker compose exec -T redis-live sh -c \
  'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --raw LLEN live')
demo_queue=$(docker compose exec -T redis-demo sh -c \
  'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --raw LLEN demo')
test "$live_queue" -ge 0
test "$demo_queue" -ge 0

echo "ESafe stack smoke passed"
