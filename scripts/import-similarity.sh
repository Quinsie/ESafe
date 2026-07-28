#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

REFERENCE_IMPORT_ID=${REFERENCE_IMPORT_ID:-$(sed -n 's/^REFERENCE_IMPORT_ID=//p' .env)}
ADMIN_BOUNDARY_SNAPSHOT=${ADMIN_BOUNDARY_SNAPSHOT:-$(sed -n 's/^ADMIN_BOUNDARY_SNAPSHOT=//p' .env)}
: "${REFERENCE_IMPORT_ID:?REFERENCE_IMPORT_ID is required}"
: "${ADMIN_BOUNDARY_SNAPSHOT:?ADMIN_BOUNDARY_SNAPSHOT is required}"
export REFERENCE_IMPORT_ID ADMIN_BOUNDARY_SNAPSHOT

SOURCE_ROOT="$ROOT/storage/reference/imports/$REFERENCE_IMPORT_ID"
test -r "$SOURCE_ROOT/RAG/전국다중이용시설/multiuse_facilities_all.csv"
test -d "$SOURCE_ROOT/RAG/일반사고보고"
test -d "$SOURCE_ROOT/RAG/중대사고보고"

docker compose --profile tools build migrate-live import-similarity-live
docker compose up --detach --wait db-live db-demo
docker compose run --rm --no-deps migrate-live
docker compose run --rm --no-deps migrate-demo
docker compose --profile tools run --rm --no-deps import-similarity-live
docker compose --profile tools run --rm --no-deps import-similarity-demo