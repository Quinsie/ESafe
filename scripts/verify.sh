#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

DOCKER_BUILDKIT=0 docker build --target test --tag esafe-backend-test:dev --file backend/Dockerfile .
DOCKER_BUILDKIT=0 docker build --target test --tag esafe-frontend-test:dev --file frontend/Dockerfile .
DOCKER_BUILDKIT=0 docker build --target test --tag esafe-importer-test:dev --file infra/importer/Dockerfile .
docker compose config --quiet

if [ "${1:-}" = "--stack" ]; then
  docker compose up --detach --build
  "$ROOT/scripts/smoke.sh"
fi
