#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

mkdir -p storage/reference/rag-embeddings
docker compose --profile tools run --rm rag-embedding-build
