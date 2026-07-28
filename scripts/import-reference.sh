#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

: "${REFERENCE_IMPORT_ID:?REFERENCE_IMPORT_ID is required}"
: "${ADMIN_BOUNDARY_SNAPSHOT:?ADMIN_BOUNDARY_SNAPSHOT is required}"

SOURCE_ROOT="$ROOT/storage/reference/imports/$REFERENCE_IMPORT_ID"
BOUNDARY_ROOT="$ROOT/storage/reference/acquired/$ADMIN_BOUNDARY_SNAPSHOT"
test -r "$SOURCE_ROOT/source-manifest.json"
test -r "$SOURCE_ROOT/verified-manifest.json"
test -r "$BOUNDARY_ROOT/manifest.json"
test -r "$BOUNDARY_ROOT/admin_regions.geojson"

docker compose --profile tools build migrate-live import-live
docker compose up --detach --wait db-live db-demo
docker compose run --rm --no-deps migrate-live
docker compose run --rm --no-deps migrate-demo
docker compose --profile tools run --rm --no-deps import-live
docker compose --profile tools run --rm --no-deps import-demo
