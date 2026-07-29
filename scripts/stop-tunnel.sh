#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

docker compose -f compose.tunnel.yaml stop cloudflared

printf '%s\n' "Quick Tunnel을 중지했습니다. 기존 URL은 다시 시작할 때 바뀔 수 있습니다."
