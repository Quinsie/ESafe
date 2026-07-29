#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

docker compose --profile tools build rag-source-build
docker compose --profile tools run --rm rag-source-build
docker compose --profile tools run --rm rag-source-build \
  verify --snapshot-root "/reference/source-documents/${RAG_SOURCE_SNAPSHOT:-initial-20260729}"
