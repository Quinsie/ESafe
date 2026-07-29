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

  briefing=$(curl --fail --silent --show-error \
    --cookie "$jar" "$ORIGIN/$profile/api/v1/briefing")
  test "$(printf '%s' "$briefing" | jq -r .data.riskReference.buildingCount)" = "217238"
  test "$(printf '%s' "$briefing" | jq -r '.data.priorityRegions | length')" = "5"

  tasks=$(curl --fail --silent --show-error \
    --cookie "$jar" "$ORIGIN/$profile/api/v1/tasks/summary")
  test "$(printf '%s' "$tasks" | jq -r '.data.items | type')" = "array"

  sources=$(curl --fail --silent --show-error \
    --cookie "$jar" "$ORIGIN/$profile/api/v1/sources/health")
  test "$(printf '%s' "$sources" | jq -r '.data.sources | length')" = "3"

  map_config=$(curl --fail --silent --show-error \
    --cookie "$jar" "$ORIGIN/$profile/api/v1/map/config")
  test "$(printf '%s' "$map_config" | jq -r '.data.providers | length')" -ge 1

  regions=$(curl --fail --silent --show-error \
    --cookie "$jar" "$ORIGIN/$profile/api/v1/map/regions")
  test "$(printf '%s' "$regions" | jq -r '.data.features | length')" = "2"

  districts=$(curl --fail --silent --show-error \
    --cookie "$jar" "$ORIGIN/$profile/api/v1/map/districts?parentCode=29")
  test "$(printf '%s' "$districts" | jq -r '.data.features | length')" = "5"

  region=$(curl --fail --silent --show-error \
    --cookie "$jar" "$ORIGIN/$profile/api/v1/regions/29170")
  test "$(printf '%s' "$region" | jq -r '.data.distribution.buildingCount > 0')" = "true"
  building_id=$(printf '%s' "$region" | jq -r '.data.topBuildings[0].buildingId')
  test -n "$building_id"

  building=$(curl --fail --silent --show-error \
    --cookie "$jar" "$ORIGIN/$profile/api/v1/buildings/$building_id")
  test "$(printf '%s' "$building" | jq -r .data.buildingId)" = "$building_id"

  similar_incidents=$(curl --fail --silent --show-error \
    --cookie "$jar" "$ORIGIN/$profile/api/v1/similar/incidents?pageSize=1")
  test "$(printf '%s' "$similar_incidents" | jq -r '.data.pagination.total')" = "197"
  incident_id=$(printf '%s' "$similar_incidents" | jq -r '.data.items[0].incidentId')
  test -n "$incident_id"

  matched_incidents=$(curl --fail --silent --show-error \
    --cookie "$jar" "$ORIGIN/$profile/api/v1/similar/incidents?building=$building_id&pageSize=2")
  test "$(printf '%s' "$matched_incidents" | jq -r '.data.filters.sort')" = "match"
  test "$(printf '%s' "$matched_incidents" | jq -r '.data.items[0].conditionMatch.isProbability')" = "false"
  test "$(printf '%s' "$matched_incidents" | jq -r '.data.items[0].conditionMatch.score >= .data.items[1].conditionMatch.score')" = "true"

  oldest_incidents=$(curl --fail --silent --show-error \
    --cookie "$jar" "$ORIGIN/$profile/api/v1/similar/incidents?sort=oldest&from=1900-01-01&to=2099-12-31&pageSize=2")
  test "$(printf '%s' "$oldest_incidents" | jq -r '.data.filters.sort')" = "oldest"
  test "$(printf '%s' "$oldest_incidents" | jq -r '.data.pagination.total')" = "197"

  invalid_body="$TMP_DIR/$profile-invalid-date.json"
  invalid_status=$(curl --silent --show-error --output "$invalid_body" --write-out '%{http_code}' \
    --cookie "$jar" "$ORIGIN/$profile/api/v1/similar/incidents?from=2026-05-02&to=2026-05-01")
  test "$invalid_status" = "422"
  test "$(jq -r '.error.code' "$invalid_body")" = "INVALID_DATE_RANGE"
  similar_candidates=$(curl --fail --silent --show-error \
    --cookie "$jar" "$ORIGIN/$profile/api/v1/similar/facilities?referenceIncident=$incident_id&pageSize=1")
  test "$(printf '%s' "$similar_candidates" | jq -r '.data.pagination.total')" = "217238"
  candidate_id=$(printf '%s' "$similar_candidates" | jq -r '.data.items[0].buildingId')
  test -n "$candidate_id"

  comparison=$(curl --fail --silent --show-error \
    --cookie "$jar" "$ORIGIN/$profile/api/v1/similar/compare?referenceIncident=$incident_id&candidateBuilding=$candidate_id")
  test "$(printf '%s' "$comparison" | jq -r '.data.conditionMatch.isProbability')" = "false"
  test "$(printf '%s' "$comparison" | jq -r '.data.evidence.status')" = "INSUFFICIENT"
  viewport=$(curl --fail --silent --show-error \
    --cookie "$jar" "$ORIGIN/$profile/api/v1/map/buildings?bbox=126.88%2C35.15%2C126.96%2C35.23&zoom=14&pageSize=10")
  test "$(printf '%s' "$viewport" | jq -r '.data.items | length > 0')" = "true"

  tile_size=$(curl --fail --silent --show-error \
    --cookie "$jar" --output /dev/null --write-out '%{size_download}' \
    "$ORIGIN/$profile/api/v1/map/buildings/14/13968/6479.mvt")
  test "$tile_size" -gt 0
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
test "$live_schema" = "20260729_0015:LIVE"
test "$demo_schema" = "20260729_0015:DEMO"

live_similarity=$(docker compose exec -T db-live sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$0"' \
  "SELECT (SELECT count(*) FROM historical_incident) || ':' || (SELECT count(*) FROM public_facility_reference)")
demo_similarity=$(docker compose exec -T db-demo sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$0"' \
  "SELECT (SELECT count(*) FROM historical_incident) || ':' || (SELECT count(*) FROM public_facility_reference)")
test "$live_similarity" = "197:4961"
test "$demo_similarity" = "197:4961"

live_queue=$(docker compose exec -T redis-live sh -c \
  'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --raw LLEN live')
demo_queue=$(docker compose exec -T redis-demo sh -c \
  'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --raw LLEN demo')
test "$live_queue" -ge 0
test "$demo_queue" -ge 0

echo "ESafe authenticated stack smoke passed"
