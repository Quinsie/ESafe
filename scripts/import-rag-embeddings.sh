#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

docker compose --profile tools run --rm import-rag-embeddings-live
docker compose --profile tools run --rm import-rag-embeddings-demo
