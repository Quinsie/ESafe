-- DEPRECATED: Do not use this file for Oracle schema setup.
-- Standard Oracle DDL entrypoint:
--   <project-root>\db\00_oracle_full_setup.sql
-- Canonical scripts:
--   db/01_create_tables.sql
--   db/04_create_weather_tables.sql
--   db/10_seed_alert_zone_map.sql
--   db/05_create_facility_inspection_tables.sql
--   db/06_combined_queries.sql
--   db/07_create_branch_hq_map.sql
-- Optional patch:
--   db/08_fix_branch_nm_seoul_north.sql

BEGIN
  raise_application_error(
    -20001,
    'schema-oracle.sql is deprecated. Use db/00_oracle_full_setup.sql.'
  );
END;
/
