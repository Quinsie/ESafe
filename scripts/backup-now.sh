#!/bin/sh
set -eu

BACKUP_ROOT=/backups/daily
backup_id=$(date -u +%Y%m%dT%H%M%SZ)
staging="$BACKUP_ROOT/.tmp-$backup_id"
destination="$BACKUP_ROOT/$backup_id"

case "$staging" in
  /backups/daily/.tmp-20??????T??????Z) ;;
  *)
    printf '%s\n' "안전하지 않은 backup staging 경로입니다." >&2
    exit 1
    ;;
esac
case "$destination" in
  /backups/daily/20??????T??????Z) ;;
  *)
    printf '%s\n' "안전하지 않은 backup destination 경로입니다." >&2
    exit 1
    ;;
esac

if [ -e "$staging" ] || [ -e "$destination" ]; then
  printf '%s\n' "같은 backup ID가 이미 존재합니다: $backup_id" >&2
  exit 1
fi

mkdir -p "$BACKUP_ROOT" "$staging"
cleanup() {
  if [ -d "$staging" ]; then
    rm -rf -- "$staging"
  fi
}
trap cleanup EXIT INT TERM

export PGPASSWORD=$POSTGRES_PASSWORD
pg_dump --host=db-live --username="$POSTGRES_USER" \
  --dbname="$LIVE_DATABASE_NAME" --format=custom --compress=6 \
  --no-owner --no-acl --file="$staging/live.dump"
pg_dump --host=db-demo --username="$POSTGRES_USER" \
  --dbname="$DEMO_DATABASE_NAME" --format=custom --compress=6 \
  --no-owner --no-acl --file="$staging/demo.dump"
pg_dump --host=db-control --username="$POSTGRES_USER" \
  --dbname="$CONTROL_DATABASE_NAME" --format=custom --compress=6 \
  --no-owner --no-acl --file="$staging/control.dump"

tar -C /source/live -czf "$staging/live-files.tar.gz" .
tar -C /source/demo -czf "$staging/demo-files.tar.gz" .

reference_list="$staging/reference-files.list"
(
  cd /source/reference
  find . -type f \
    \( -name 'CURRENT' -o -name 'manifest*.json' -o \
       -name '*-manifest.json' -o -name 'manifest.sha256' -o \
       -name 'verified-manifest.json' -o -name 'source-manifest.json' \) \
    -print | LC_ALL=C sort
) > "$reference_list"
if [ -s "$reference_list" ]; then
  tar -C /source/reference -czf "$staging/reference-metadata.tar.gz" \
    -T "$reference_list"
else
  tar -czf "$staging/reference-metadata.tar.gz" --files-from=/dev/null
fi

live_schema=$(psql --host=db-live --username="$POSTGRES_USER" \
  --dbname="$LIVE_DATABASE_NAME" --tuples-only --no-align \
  --command='SELECT version_num FROM alembic_version')
demo_schema=$(psql --host=db-demo --username="$POSTGRES_USER" \
  --dbname="$DEMO_DATABASE_NAME" --tuples-only --no-align \
  --command='SELECT version_num FROM alembic_version')
unset PGPASSWORD

cat > "$staging/manifest.txt" <<EOF
backup_id=$backup_id
created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
build_commit=$ESAFE_BUILD_COMMIT
live_schema=$live_schema
demo_schema=$demo_schema
retention_generations=7
EOF

pg_restore --list "$staging/live.dump" >/dev/null
pg_restore --list "$staging/demo.dump" >/dev/null
pg_restore --list "$staging/control.dump" >/dev/null
tar -tzf "$staging/live-files.tar.gz" >/dev/null
tar -tzf "$staging/demo-files.tar.gz" >/dev/null
tar -tzf "$staging/reference-metadata.tar.gz" >/dev/null

(
  cd "$staging"
  sha256sum live.dump demo.dump control.dump \
    live-files.tar.gz demo-files.tar.gz reference-metadata.tar.gz \
    manifest.txt > SHA256SUMS
  sha256sum --check SHA256SUMS >/dev/null
)

mv "$staging" "$destination"
trap - EXIT INT TERM

find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d \
  -name '20??????T??????Z' -print \
  | LC_ALL=C sort -r \
  | awk 'NR > 7' \
  | while IFS= read -r expired; do
      case "$expired" in
        /backups/daily/20??????T??????Z) rm -rf -- "$expired" ;;
        *)
          printf '%s\n' "보존 삭제 대상 경로가 안전하지 않습니다: $expired" >&2
          exit 1
          ;;
      esac
    done

printf '%s\n' "$destination"
