#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

verify_database() {
  service=$1
  docker compose exec -T "$service" sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
DO $$
DECLARE
  actual bigint;
BEGIN
  SELECT count(*) INTO actual FROM building;
  IF actual <> 217238 THEN RAISE EXCEPTION 'building count: %', actual; END IF;
  SELECT count(*) INTO actual FROM building_risk_snapshot;
  IF actual <> 217238 THEN RAISE EXCEPTION 'risk count: %', actual; END IF;
  SELECT count(*) INTO actual FROM facility_entity;
  IF actual <> 948464 THEN RAISE EXCEPTION 'facility count: %', actual; END IF;
  SELECT count(*) INTO actual FROM building_facility_link;
  IF actual <> 1678463 THEN RAISE EXCEPTION 'facility link count: %', actual; END IF;
  SELECT count(*) INTO actual FROM building WHERE geometry_status <> 'VALID'
    OR NOT ST_IsValid(geometry) OR ST_SRID(geometry) <> 4326;
  IF actual <> 0 THEN RAISE EXCEPTION 'invalid building geometry: %', actual; END IF;
  SELECT count(*) INTO actual FROM building_risk_snapshot WHERE final_score IS NULL
    OR final_score < 0 OR final_score > 1 OR regional_rank < 1
    OR is_synthetic OR source_class <> 'V27_1_FOCUS_FINAL_SCORE';
  IF actual <> 0 THEN RAISE EXCEPTION 'invalid risk rows: %', actual; END IF;
  SELECT count(DISTINCT regional_rank) INTO actual FROM building_risk_snapshot;
  IF actual <> 217238 THEN RAISE EXCEPTION 'risk rank cardinality: %', actual; END IF;
  SELECT count(*) INTO actual FROM building
    WHERE quality_flags ? 'ADMIN_BOUNDARY_CENTROID_MISMATCH';
  IF actual <> 141 THEN RAISE EXCEPTION 'boundary mismatch flag count: %', actual; END IF;
  SELECT count(*) INTO actual FROM reference_dataset_state s
    JOIN reference_import i ON i.import_id = s.active_import_id
    WHERE s.active_import_id = '20260729T0438-s2-v27-1'
      AND i.source_manifest_sha256 = '23200ecdea8c4b8bf0912a033bb40ac136fd7e2dce1bc75b9204cc794b5bde29'
      AND i.building_count = 217238 AND i.risk_count = 217238
      AND i.facility_count = 948464 AND i.facility_link_count = 1678463;
  IF actual <> 1 THEN RAISE EXCEPTION 'active reference lineage mismatch'; END IF;
END $$;
SQL
}

checksum_database() {
  service=$1
  docker compose exec -T "$service" sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At' <<'SQL'
SELECT count(*) || ':' || sum(hashtextextended(
  source_building_key || ':' || region_code || ':' || lot_address, 0)::numeric)
FROM building;
SELECT count(*) || ':' || sum(hashtextextended(
  b.source_building_key || ':' || r.final_score::text || ':' || r.regional_rank::text, 0)::numeric)
FROM building_risk_snapshot r JOIN building b USING (building_id);
SELECT count(*) || ':' || sum(hashtextextended(
  f.source_key || ':' || b.source_building_key || ':' || l.candidate_rank::text, 0)::numeric)
FROM building_facility_link l
JOIN facility_entity f USING (facility_id)
JOIN building b USING (building_id);
SQL
}

verify_database db-live
verify_database db-demo
live_checksum=$(checksum_database db-live)
demo_checksum=$(checksum_database db-demo)
if [ "$live_checksum" != "$demo_checksum" ]; then
  echo "LIVE and DEMO reference checksums differ" >&2
  exit 1
fi

plan=$(docker compose exec -T db-live sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At' <<'SQL'
EXPLAIN (ANALYZE, BUFFERS)
SELECT building_id FROM building
WHERE geometry && ST_MakeEnvelope(126.85, 35.14, 126.86, 35.15, 4326)
  AND ST_Intersects(geometry, ST_MakeEnvelope(126.85, 35.14, 126.86, 35.15, 4326))
LIMIT 1000;
SQL
)
printf '%s\n' "$plan" | grep -q 'ix_building_geometry_gist'

printf '%s\n' "reference verification passed"
