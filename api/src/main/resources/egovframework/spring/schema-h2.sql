-- Local H2 schema entrypoint for development.
-- Keeps H2 setup modular while preserving Spring init entrypoint.
RUNSCRIPT FROM 'classpath:egovframework/spring/h2/01_create_tables.sql';
RUNSCRIPT FROM 'classpath:egovframework/spring/h2/04_create_weather_tables.sql';
RUNSCRIPT FROM 'classpath:egovframework/spring/h2/09_seed_alert_zone_map.sql';
RUNSCRIPT FROM 'classpath:egovframework/spring/h2/05_create_facility_inspection_tables.sql';
RUNSCRIPT FROM 'classpath:egovframework/spring/h2/06_combined_queries.sql';
RUNSCRIPT FROM 'classpath:egovframework/spring/h2/07_create_branch_hq_map.sql';

