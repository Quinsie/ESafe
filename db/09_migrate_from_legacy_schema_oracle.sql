--------------------------------------------------------------------------------
-- Legacy Oracle schema migration (schema-oracle.sql -> db standard)
-- Target standard:
--   01_create_tables.sql
--   04_create_weather_tables.sql
--   10_seed_alert_zone_map.sql
--   05_create_facility_inspection_tables.sql
--   06_combined_queries.sql
--   07_create_branch_hq_map.sql
--
-- Run this only for an already-created legacy DB.
-- For fresh setup, use 00_oracle_full_setup.sql instead.
--------------------------------------------------------------------------------

WHENEVER SQLERROR EXIT SQL.SQLCODE;
SET DEFINE OFF;
SET SERVEROUTPUT ON;

PROMPT [1/6] Validate required legacy tables ...
DECLARE
    v_cnt NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_cnt FROM USER_TABLES WHERE TABLE_NAME = 'TB_BLDG_RISK_STATIC';
    IF v_cnt = 0 THEN
        raise_application_error(-20010, 'TB_BLDG_RISK_STATIC not found. Use 00_oracle_full_setup.sql for fresh DB.');
    END IF;

    SELECT COUNT(*) INTO v_cnt FROM USER_TABLES WHERE TABLE_NAME = 'TB_WEATHER_RISK';
    IF v_cnt = 0 THEN
        raise_application_error(-20011, 'TB_WEATHER_RISK not found. Use 00_oracle_full_setup.sql for fresh DB.');
    END IF;
END;
/

PROMPT [2/6] Add missing columns/sequences/tables ...
DECLARE
    v_cnt NUMBER;

    PROCEDURE create_sequence_if_missing(p_seq_name IN VARCHAR2) IS
    BEGIN
        SELECT COUNT(*) INTO v_cnt
          FROM USER_SEQUENCES
         WHERE SEQUENCE_NAME = UPPER(p_seq_name);

        IF v_cnt = 0 THEN
            EXECUTE IMMEDIATE 'CREATE SEQUENCE ' || p_seq_name ||
                              ' START WITH 1 INCREMENT BY 1 NOCACHE NOCYCLE';
            DBMS_OUTPUT.PUT_LINE('Created sequence: ' || p_seq_name);
        END IF;
    END;

    PROCEDURE add_column_if_missing(
        p_table_name  IN VARCHAR2,
        p_column_name IN VARCHAR2,
        p_definition  IN VARCHAR2
    ) IS
    BEGIN
        SELECT COUNT(*) INTO v_cnt
          FROM USER_TAB_COLUMNS
         WHERE TABLE_NAME = UPPER(p_table_name)
           AND COLUMN_NAME = UPPER(p_column_name);

        IF v_cnt = 0 THEN
            EXECUTE IMMEDIATE 'ALTER TABLE ' || p_table_name || ' ADD (' ||
                              p_column_name || ' ' || p_definition || ')';
            DBMS_OUTPUT.PUT_LINE('Added column: ' || p_table_name || '.' || p_column_name);
        END IF;
    END;
BEGIN
    -- sequence compatibility for loaders (legacy schema may be identity-only)
    create_sequence_if_missing('SEQ_BLDG_RISK');
    create_sequence_if_missing('SEQ_WEATHER_ALERT');
    create_sequence_if_missing('SEQ_WEATHER_RISK');
    create_sequence_if_missing('SEQ_FACILITY_GENERAL_HIST');
    create_sequence_if_missing('SEQ_FACILITY_SELF_HIST');

    -- TB_BLDG_RISK_STATIC: add standard columns missing in legacy schema
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A1', 'VARCHAR2(50)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A2', 'VARCHAR2(30)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A3', 'VARCHAR2(20)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A4', 'VARCHAR2(200)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A5', 'VARCHAR2(10)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A6', 'VARCHAR2(10)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A7', 'VARCHAR2(30)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A8', 'VARCHAR2(30)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A9', 'VARCHAR2(10)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A10', 'VARCHAR2(30)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A11', 'VARCHAR2(10)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A12', 'VARCHAR2(30)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A14', 'VARCHAR2(50)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A15', 'NUMBER(15,2)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A16', 'VARCHAR2(10)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A17', 'VARCHAR2(50)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A18', 'VARCHAR2(10)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A19', 'VARCHAR2(50)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A20', 'NUMBER(10,2)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A21', 'NUMBER(5,1)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A22', 'NUMBER(5,1)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A23', 'VARCHAR2(20)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A24', 'VARCHAR2(20)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A25', 'NUMBER(5,1)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A26', 'VARCHAR2(10)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A27', 'VARCHAR2(20)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A28', 'VARCHAR2(10)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A29', 'VARCHAR2(20)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'A30', 'VARCHAR2(30)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'CENTER_X', 'NUMBER(15,6)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'CENTER_Y', 'NUMBER(15,6)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'BUILD_YEAR', 'NUMBER(4)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'BUILD_AGE', 'NUMBER(3)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'AGE_RANGE', 'VARCHAR2(20)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'FLOOD_OVERLAP', 'NUMBER(5,1)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'LANDSLIDE_DIST', 'NUMBER(10,3)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'AGE_FLOOD_SCORE', 'NUMBER(4,1)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'AGE_FLOOD_GRADE', 'VARCHAR2(10)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'AGE_FLOOD_CD', 'VARCHAR2(2)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'FLOOD_LAND_SCORE', 'NUMBER(4,1)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'FLOOD_LAND_GRADE', 'VARCHAR2(10)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'FLOOD_LAND_CD', 'VARCHAR2(2)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'AGE_LAND_SCORE', 'NUMBER(4,1)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'AGE_LAND_GRADE', 'VARCHAR2(10)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'AGE_LAND_CD', 'VARCHAR2(2)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'LAND_USE_CD', 'VARCHAR2(20)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'LAND_USE_NM', 'VARCHAR2(50)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'FIRE_HIST', 'NUMBER(1)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'FIRE_MULT', 'NUMBER(3,1)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'PREV_FIRE_OCCUR_DATE', 'VARCHAR2(1000)');
    add_column_if_missing('TB_BLDG_RISK_STATIC', 'BASE_SCORE', 'NUMBER(5,1)');

    -- weather tables: keep standard REG_DT columns
    add_column_if_missing('TB_WEATHER_ALERT', 'REG_DT', 'TIMESTAMP DEFAULT SYSTIMESTAMP');
    add_column_if_missing('TB_WEATHER_RISK', 'REG_DT', 'TIMESTAMP DEFAULT SYSTIMESTAMP');

    -- facility history tables for building-detail UI and +10/+6 score logic
    SELECT COUNT(*) INTO v_cnt FROM USER_TABLES WHERE TABLE_NAME = 'TB_FACILITY_GENERAL_HIST';
    IF v_cnt = 0 THEN
        EXECUTE IMMEDIATE q'[
            CREATE TABLE TB_FACILITY_GENERAL_HIST (
                HIST_SEQ              NUMBER DEFAULT SEQ_FACILITY_GENERAL_HIST.NEXTVAL NOT NULL,
                BLDG_SEQ              NUMBER              NOT NULL,
                BRANCH_NM             VARCHAR2(100),
                ADDR                  VARCHAR2(500),
                KEPCO_CUST_NO         VARCHAR2(50),
                CHECK_RESULT          VARCHAR2(20)        NOT NULL,
                ORAL_NOTICE_YN        CHAR(1),
                NONCONFORMITY_DETAIL  VARCHAR2(1000),
                LINE_NO               VARCHAR2(100),
                CAPACITY              VARCHAR2(100),
                CHECK_CYCLE           VARCHAR2(100),
                CONTRACT_TYPE         VARCHAR2(200),
                CHECK_DT              DATE                NOT NULL,
                RAW_JSON              CLOB,
                REG_DT                TIMESTAMP DEFAULT SYSTIMESTAMP,
                CONSTRAINT PK_FACILITY_GENERAL_HIST PRIMARY KEY (HIST_SEQ),
                CONSTRAINT FK_FACILITY_GENERAL_BLDG FOREIGN KEY (BLDG_SEQ)
                    REFERENCES TB_BLDG_RISK_STATIC (BLDG_SEQ),
                CONSTRAINT CK_FACILITY_GENERAL_ORAL_YN CHECK (ORAL_NOTICE_YN IN ('Y', 'N') OR ORAL_NOTICE_YN IS NULL)
            )
        ]';
        DBMS_OUTPUT.PUT_LINE('Created table: TB_FACILITY_GENERAL_HIST');
    END IF;

    SELECT COUNT(*) INTO v_cnt FROM USER_TABLES WHERE TABLE_NAME = 'TB_FACILITY_SELF_HIST';
    IF v_cnt = 0 THEN
        EXECUTE IMMEDIATE q'[
            CREATE TABLE TB_FACILITY_SELF_HIST (
                HIST_SEQ              NUMBER DEFAULT SEQ_FACILITY_SELF_HIST.NEXTVAL NOT NULL,
                BLDG_SEQ              NUMBER              NOT NULL,
                BRANCH_NM             VARCHAR2(100),
                ADDR                  VARCHAR2(500),
                KEPCO_CUST_NO         VARCHAR2(50),
                INSPECTION_RESULT     VARCHAR2(20)        NOT NULL,
                FAIL_DETAIL           VARCHAR2(1000),
                DEFECT_CNT            NUMBER,
                MOTOR_TYPE            VARCHAR2(200),
                CHECK_DT              DATE                NOT NULL,
                RAW_JSON              CLOB,
                REG_DT                TIMESTAMP DEFAULT SYSTIMESTAMP,
                CONSTRAINT PK_FACILITY_SELF_HIST PRIMARY KEY (HIST_SEQ),
                CONSTRAINT FK_FACILITY_SELF_BLDG FOREIGN KEY (BLDG_SEQ)
                    REFERENCES TB_BLDG_RISK_STATIC (BLDG_SEQ),
                CONSTRAINT CK_FACILITY_SELF_RESULT CHECK (INSPECTION_RESULT IN ('?⑷꺽', '遺덊빀寃?))
            )
        ]';
        DBMS_OUTPUT.PUT_LINE('Created table: TB_FACILITY_SELF_HIST');
    END IF;
    add_column_if_missing('TB_FACILITY_SELF_HIST', 'DEFECT_CNT', 'NUMBER');
    add_column_if_missing('TB_FACILITY_SELF_HIST', 'MOTOR_TYPE', 'VARCHAR2(200)');
    add_column_if_missing('TB_FACILITY_SELF_HIST', 'RAW_JSON', 'CLOB');
    add_column_if_missing('TB_FACILITY_GENERAL_HIST', 'LINE_NO', 'VARCHAR2(100)');
    add_column_if_missing('TB_FACILITY_GENERAL_HIST', 'CAPACITY', 'VARCHAR2(100)');
    add_column_if_missing('TB_FACILITY_GENERAL_HIST', 'CHECK_CYCLE', 'VARCHAR2(100)');
    add_column_if_missing('TB_FACILITY_GENERAL_HIST', 'CONTRACT_TYPE', 'VARCHAR2(200)');
    add_column_if_missing('TB_FACILITY_GENERAL_HIST', 'RAW_JSON', 'CLOB');

    SELECT COUNT(*) INTO v_cnt
      FROM USER_CONSTRAINTS
     WHERE TABLE_NAME = 'TB_FACILITY_GENERAL_HIST'
       AND CONSTRAINT_NAME = 'CK_FACILITY_GENERAL_RESULT';
    IF v_cnt > 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE TB_FACILITY_GENERAL_HIST DROP CONSTRAINT CK_FACILITY_GENERAL_RESULT';
        DBMS_OUTPUT.PUT_LINE('Dropped constraint: CK_FACILITY_GENERAL_RESULT');
    END IF;

    -- alert zone mapping table (for weather alert region resolution)
    SELECT COUNT(*) INTO v_cnt FROM USER_TABLES WHERE TABLE_NAME = 'TB_ALERT_ZONE_MAP';
    IF v_cnt = 0 THEN
        EXECUTE IMMEDIATE q'[
            CREATE TABLE TB_ALERT_ZONE_MAP (
                ZONE_CD            VARCHAR2(20)       NOT NULL,
                ZONE_NM            VARCHAR2(120)      NOT NULL,
                PARENT_REGION      VARCHAR2(120),
                DISTRICT_EXPR      VARCHAR2(1000),
                SOURCE_TYPE        VARCHAR2(30) DEFAULT 'seed',
                USE_YN             CHAR(1)      DEFAULT 'Y' NOT NULL,
                REG_DT             TIMESTAMP    DEFAULT SYSTIMESTAMP,
                CONSTRAINT PK_ALERT_ZONE_MAP PRIMARY KEY (ZONE_CD)
            )
        ]';
        DBMS_OUTPUT.PUT_LINE('Created table: TB_ALERT_ZONE_MAP');
    END IF;
END;
/

PROMPT [3/6] Align TB_WEATHER_RISK unique key and remove duplicates ...
DECLARE
    v_cnt NUMBER;
BEGIN
    -- Keep one row per (RISK_DATE, REGION_CD), prefer latest RISK_SEQ.
    DELETE FROM TB_WEATHER_RISK t
     WHERE t.ROWID IN (
        SELECT rid
          FROM (
            SELECT ROWID rid,
                   ROW_NUMBER() OVER (
                       PARTITION BY RISK_DATE, REGION_CD
                       ORDER BY RISK_SEQ DESC NULLS LAST, ROWID DESC
                   ) AS rn
              FROM TB_WEATHER_RISK
             WHERE REGION_CD IS NOT NULL
          )
         WHERE rn > 1
     );
    DBMS_OUTPUT.PUT_LINE('Removed duplicate TB_WEATHER_RISK rows: ' || SQL%ROWCOUNT);

    FOR c IN (
        SELECT CONSTRAINT_NAME
          FROM USER_CONSTRAINTS
         WHERE TABLE_NAME = 'TB_WEATHER_RISK'
           AND CONSTRAINT_TYPE = 'U'
    ) LOOP
        EXECUTE IMMEDIATE 'ALTER TABLE TB_WEATHER_RISK DROP CONSTRAINT ' || c.CONSTRAINT_NAME;
        DBMS_OUTPUT.PUT_LINE('Dropped unique constraint: ' || c.CONSTRAINT_NAME);
    END LOOP;

    SELECT COUNT(*) INTO v_cnt
      FROM USER_INDEXES
     WHERE INDEX_NAME = 'UX_WEATHER_RISK_DATE_REGION_DIST';
    IF v_cnt > 0 THEN
        EXECUTE IMMEDIATE 'DROP INDEX UX_WEATHER_RISK_DATE_REGION_DIST';
        DBMS_OUTPUT.PUT_LINE('Dropped legacy unique index: UX_WEATHER_RISK_DATE_REGION_DIST');
    END IF;

    SELECT COUNT(*) INTO v_cnt
      FROM USER_CONSTRAINTS
     WHERE TABLE_NAME = 'TB_WEATHER_RISK'
       AND CONSTRAINT_NAME = 'UK_WEATHER_RISK';
    IF v_cnt = 0 THEN
        EXECUTE IMMEDIATE
            'ALTER TABLE TB_WEATHER_RISK ADD CONSTRAINT UK_WEATHER_RISK UNIQUE (RISK_DATE, REGION_CD)';
        DBMS_OUTPUT.PUT_LINE('Created UK_WEATHER_RISK');
    END IF;
END;
/

PROMPT [4/6] Ensure standard indexes ...
DECLARE
    v_cnt NUMBER;

    PROCEDURE create_index_if_missing(
        p_index_name IN VARCHAR2,
        p_ddl        IN VARCHAR2
    ) IS
    BEGIN
        SELECT COUNT(*) INTO v_cnt
          FROM USER_INDEXES
         WHERE INDEX_NAME = UPPER(p_index_name);

        IF v_cnt = 0 THEN
            EXECUTE IMMEDIATE p_ddl;
            DBMS_OUTPUT.PUT_LINE('Created index: ' || p_index_name);
        END IF;
    END;
BEGIN
    create_index_if_missing('IDX_BLDG_RISK_REGION', 'CREATE INDEX IDX_BLDG_RISK_REGION ON TB_BLDG_RISK_STATIC (REGION_CD)');
    create_index_if_missing('IDX_BLDG_RISK_BRANCH', 'CREATE INDEX IDX_BLDG_RISK_BRANCH ON TB_BLDG_RISK_STATIC (BRANCH_NM)');
    create_index_if_missing('IDX_BLDG_RISK_GRADE',  'CREATE INDEX IDX_BLDG_RISK_GRADE ON TB_BLDG_RISK_STATIC (TOTAL_GRADE)');
    create_index_if_missing('IDX_BLDG_RISK_RISKCD', 'CREATE INDEX IDX_BLDG_RISK_RISKCD ON TB_BLDG_RISK_STATIC (RISK_CD)');
    create_index_if_missing('IDX_BLDG_RISK_A0',     'CREATE INDEX IDX_BLDG_RISK_A0 ON TB_BLDG_RISK_STATIC (A0)');
    create_index_if_missing('IDX_BLDG_RISK_A3',     'CREATE INDEX IDX_BLDG_RISK_A3 ON TB_BLDG_RISK_STATIC (A3)');
    create_index_if_missing('IDX_BLDG_RISK_ANAL',   'CREATE INDEX IDX_BLDG_RISK_ANAL ON TB_BLDG_RISK_STATIC (ANAL_DATE)');
    create_index_if_missing('IDX_WEATHER_ALERT_DATE', 'CREATE INDEX IDX_WEATHER_ALERT_DATE ON TB_WEATHER_ALERT (ALERT_DATE)');
    create_index_if_missing('IDX_WEATHER_ALERT_TYPE', 'CREATE INDEX IDX_WEATHER_ALERT_TYPE ON TB_WEATHER_ALERT (ALERT_TYPE, ALERT_LEVEL)');
    create_index_if_missing('IDX_WEATHER_ALERT_REGION', 'CREATE INDEX IDX_WEATHER_ALERT_REGION ON TB_WEATHER_ALERT (PARENT_REGION)');
    create_index_if_missing('IDX_WEATHER_RISK_DATE', 'CREATE INDEX IDX_WEATHER_RISK_DATE ON TB_WEATHER_RISK (RISK_DATE)');
    create_index_if_missing('IDX_WEATHER_RISK_REGION', 'CREATE INDEX IDX_WEATHER_RISK_REGION ON TB_WEATHER_RISK (REGION_CD)');
    create_index_if_missing('IDX_FACILITY_GENERAL_BLDG', 'CREATE INDEX IDX_FACILITY_GENERAL_BLDG ON TB_FACILITY_GENERAL_HIST (BLDG_SEQ, CHECK_DT DESC)');
    create_index_if_missing('IDX_FACILITY_GENERAL_CUST', 'CREATE INDEX IDX_FACILITY_GENERAL_CUST ON TB_FACILITY_GENERAL_HIST (BLDG_SEQ, KEPCO_CUST_NO)');
    create_index_if_missing('IDX_FACILITY_SELF_BLDG', 'CREATE INDEX IDX_FACILITY_SELF_BLDG ON TB_FACILITY_SELF_HIST (BLDG_SEQ, CHECK_DT DESC)');
    create_index_if_missing('IDX_FACILITY_SELF_CUST', 'CREATE INDEX IDX_FACILITY_SELF_CUST ON TB_FACILITY_SELF_HIST (BLDG_SEQ, KEPCO_CUST_NO)');
    create_index_if_missing('IDX_ALERT_ZONE_MAP_USE', 'CREATE INDEX IDX_ALERT_ZONE_MAP_USE ON TB_ALERT_ZONE_MAP (USE_YN)');
END;
/

PROMPT [5/6] Seed alert-zone map (idempotent merge) ...
@@10_seed_alert_zone_map.sql

PROMPT [6/6] Recreate combined view to standard join condition ...
@@06_combined_queries.sql

COMMIT;

PROMPT [DONE] Legacy Oracle schema migration completed.
PROMPT [CHECK] Verify:
PROMPT   - TB_BLDG_RISK_STATIC has A1~A30 and standard scoring columns.
PROMPT   - TB_WEATHER_RISK has UK_WEATHER_RISK (RISK_DATE, REGION_CD).
PROMPT   - TB_FACILITY_GENERAL_HIST / TB_FACILITY_SELF_HIST exist.
PROMPT   - TB_ALERT_ZONE_MAP has seeded rows (ZONE_CD mapping).
PROMPT   - VW_RISK_COMBINED exists and joins by TRUNC(SYSDATE) weather rows.


