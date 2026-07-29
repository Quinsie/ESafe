#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BACKUP_ROOT="$ROOT/backups/daily"
requested=${1:-}

if [ -n "$requested" ]; then
  backup_dir=$(realpath -e -- "$requested")
else
  backup_dir=$(
    find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d \
      -name '20??????T??????Z' -print \
      | LC_ALL=C sort -r \
      | head -n 1
  )
fi

case "$backup_dir" in
  "$BACKUP_ROOT"/20??????T??????Z) ;;
  *)
    printf '%s\n' "복원 시험 대상이 검증된 daily backup 경로가 아닙니다." >&2
    exit 1
    ;;
esac

for required in live.dump demo.dump control.dump \
  live-files.tar.gz demo-files.tar.gz reference-metadata.tar.gz SHA256SUMS; do
  test -f "$backup_dir/$required"
done

(
  cd "$backup_dir"
  sha256sum --check SHA256SUMS >/dev/null
)

app_version=$(sed -n 's/^ESAFE_APP_VERSION=//p' "$ROOT/.env")
test -n "$app_version"
image="esafe-database:$app_version"
docker image inspect "$image" >/dev/null

container="esafe-restore-test-$$"
case "$container" in
  esafe-restore-test-[0-9]*) ;;
  *)
    printf '%s\n' "복원 시험 컨테이너 이름이 안전하지 않습니다." >&2
    exit 1
    ;;
esac
if docker inspect "$container" >/dev/null 2>&1; then
  printf '%s\n' "같은 이름의 복원 시험 컨테이너가 이미 존재합니다." >&2
  exit 1
fi

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker run --detach --name "$container" \
  --network none \
  --tmpfs /var/lib/postgresql/data:rw,size=8g \
  --tmpfs /restore-files:rw,size=1g \
  --mount "type=bind,src=$backup_dir,dst=/backup,readonly" \
  --env POSTGRES_PASSWORD=restore-test-only \
  --env POSTGRES_DB=restore_test \
  "$image" >/dev/null

attempts=0
while [ "$attempts" -lt 30 ]; do
  if docker exec "$container" pg_isready \
    --username=postgres --dbname=restore_test >/dev/null 2>&1; then
    break
  fi
  attempts=$((attempts + 1))
  sleep 2
done
if [ "$attempts" -ge 30 ]; then
  printf '%s\n' "임시 PostgreSQL 시작 제한시간을 초과했습니다." >&2
  exit 1
fi

restore_database() {
  label=$1
  dump=$2
  docker exec --env PGPASSWORD=restore-test-only "$container" \
    dropdb --username=postgres --if-exists restore_test
  docker exec --env PGPASSWORD=restore-test-only "$container" \
    createdb --username=postgres restore_test
  docker exec --env PGPASSWORD=restore-test-only "$container" \
    pg_restore --username=postgres --dbname=restore_test \
      --exit-on-error --no-owner --no-acl "$dump"
  printf '%s\n' "$label restored"
}

restore_database LIVE /backup/live.dump
live_contract=$(
  docker exec --env PGPASSWORD=restore-test-only "$container" \
    psql --username=postgres --dbname=restore_test --tuples-only --no-align \
    --command="SELECT (SELECT version_num FROM alembic_version) || ':' ||
      (SELECT count(*) FROM building) || ':' ||
      (SELECT count(*) FROM rag_chunk)"
)
test "$live_contract" = "20260729_0013:217238:14311"

restore_database DEMO /backup/demo.dump
demo_contract=$(
  docker exec --env PGPASSWORD=restore-test-only "$container" \
    psql --username=postgres --dbname=restore_test --tuples-only --no-align \
    --command="SELECT (SELECT version_num FROM alembic_version) || ':' ||
      (SELECT count(*) FROM building) || ':' ||
      (SELECT count(*) FROM demo_scenario)"
)
test "$demo_contract" = "20260729_0013:217238:6"

restore_database CONTROL /backup/control.dump
control_tables=$(
  docker exec --env PGPASSWORD=restore-test-only "$container" \
    psql --username=postgres --dbname=restore_test --tuples-only --no-align \
    --command="SELECT count(*) FROM information_schema.tables
      WHERE table_schema = 'public'"
)
test "$control_tables" -gt 0

docker exec "$container" sh -c \
  'mkdir -p /restore-files/live /restore-files/demo /restore-files/reference &&
   tar -xzf /backup/live-files.tar.gz -C /restore-files/live &&
   tar -xzf /backup/demo-files.tar.gz -C /restore-files/demo &&
   tar -xzf /backup/reference-metadata.tar.gz -C /restore-files/reference'

printf '%s\n' "restore test passed: $backup_dir"
