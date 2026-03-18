-- Repository-safe H2 facility history seed.
-- Full local dataset was omitted because it exceeds GitHub file limits.
-- Regenerate full local dataset with api/scripts/regenerate_h2_full_facility_history.py when needed.
DELETE FROM TB_FACILITY_GENERAL_HIST;
DELETE FROM TB_FACILITY_SELF_HIST;
