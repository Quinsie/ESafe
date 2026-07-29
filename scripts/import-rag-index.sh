#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

docker compose --profile tools build migrate-live import-rag-live
docker compose up --detach --wait db-live db-demo
docker compose run --rm --no-deps migrate-live
docker compose run --rm --no-deps migrate-demo
docker compose --profile tools run --rm --no-deps import-rag-live
docker compose --profile tools run --rm --no-deps import-rag-demo
