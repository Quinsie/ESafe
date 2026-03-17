--------------------------------------------------------------------------------
-- Oracle unified DDL entrypoint
-- Usage (SQL*Plus / SQLcl):
--   cd C:\Users\user\Downloads\kescoaitest\db
--   sqlplus <user>/<password>@<tns> @00_oracle_full_setup.sql
--------------------------------------------------------------------------------

WHENEVER SQLERROR EXIT SQL.SQLCODE;
SET DEFINE OFF;

PROMPT [1/6] Applying 01_create_tables.sql ...
@@01_create_tables.sql

PROMPT [2/6] Applying 04_create_weather_tables.sql ...
@@04_create_weather_tables.sql

PROMPT [3/6] Applying 10_seed_alert_zone_map.sql ...
@@10_seed_alert_zone_map.sql

PROMPT [4/6] Applying 05_create_facility_inspection_tables.sql ...
@@05_create_facility_inspection_tables.sql

PROMPT [5/6] Applying 06_combined_queries.sql ...
@@06_combined_queries.sql

PROMPT [6/7] Applying 07_create_branch_hq_map.sql ...
@@07_create_branch_hq_map.sql

PROMPT [7/7] Applying 11_add_wildfire_columns.sql ...
@@11_add_wildfire_columns.sql

PROMPT [Optional] Branch name data-fix (run only when needed):
PROMPT   @@08_fix_branch_nm_seoul_north.sql

PROMPT [DONE] Oracle unified schema setup completed.
