------------------------------------------------------------------------
-- SQL*Loader 컨트롤 파일: A0~A30 포함 58컬럼 CSV → TB_BLDG_RISK_STATIC
-- 대상: A0-A30이 포함된 58컬럼 포맷 CSV
-- 인코딩: UTF-8 (CHARACTERSET UTF8 지정)
------------------------------------------------------------------------
OPTIONS (
    SKIP=1,
    ERRORS=1000,
    ROWS=5000,
    BINDSIZE=10485760,
    READSIZE=10485760
)
LOAD DATA
CHARACTERSET UTF8
INFILE 'data.csv'
APPEND
INTO TABLE TB_BLDG_RISK_STATIC
FIELDS TERMINATED BY ','
OPTIONALLY ENCLOSED BY '"'
TRAILING NULLCOLS
(
    -- PK (시퀀스)
    BLDG_SEQ        "SEQ_BLDG_RISK.NEXTVAL",

    -- A0 ~ A30 (건축물대장 원본, CSV 위치 1~31)
    A0              CHAR(20),
    A1              CHAR(50),
    A2              CHAR(30),
    A3              CHAR(20),
    A4              CHAR(200),
    A5              CHAR(10),
    A6              CHAR(10),
    A7              CHAR(30),
    A8              CHAR(30),
    A9              CHAR(10),
    A10             CHAR(30),
    A11             CHAR(10),
    A12             CHAR(30),
    A13             CHAR(100),
    A14             CHAR(50),
    A15             DECIMAL EXTERNAL,
    A16             CHAR(10),
    A17             CHAR(50),
    A18             CHAR(10),
    A19             CHAR(50),
    A20             DECIMAL EXTERNAL,
    A21             DECIMAL EXTERNAL,
    A22             DECIMAL EXTERNAL,
    A23             CHAR(20),
    A24             CHAR(20),
    A25             DECIMAL EXTERNAL,
    A26             CHAR(10),
    A27             CHAR(20),
    A28             CHAR(10),
    A29             CHAR(20),
    A30             CHAR(30),

    -- 분석 결과 컬럼 (CSV 위치 32~58)
    BUILD_AGE       DECIMAL EXTERNAL NULLIF BUILD_AGE=BLANKS,
    BUILD_YEAR      DECIMAL EXTERNAL NULLIF BUILD_YEAR=BLANKS,
    AGE_GRADE       CHAR(10),
    AGE_SCORE       DECIMAL EXTERNAL NULLIF AGE_SCORE=BLANKS,
    AGE_RANGE       CHAR(20),
    FLOOD_SCORE     DECIMAL EXTERNAL NULLIF FLOOD_SCORE=BLANKS,
    FLOOD_GRADE     CHAR(10),
    FLOOD_OVERLAP   DECIMAL EXTERNAL NULLIF FLOOD_OVERLAP=BLANKS,
    LANDSLIDE_DIST  DECIMAL EXTERNAL NULLIF LANDSLIDE_DIST=BLANKS,
    LANDSLIDE_GRADE CHAR(10),
    LANDSLIDE_SCORE DECIMAL EXTERNAL NULLIF LANDSLIDE_SCORE=BLANKS,
    TOTAL_SCORE     DECIMAL EXTERNAL NULLIF TOTAL_SCORE=BLANKS,
    TOTAL_GRADE     CHAR(10),
    RISK_CD         CHAR(2),
    CENTER_X        DECIMAL EXTERNAL NULLIF CENTER_X=BLANKS,
    CENTER_Y        DECIMAL EXTERNAL NULLIF CENTER_Y=BLANKS,
    LON             DECIMAL EXTERNAL NULLIF LON=BLANKS,
    LAT             DECIMAL EXTERNAL NULLIF LAT=BLANKS,
    ADDR            CHAR(500),
    REGION_NM       CHAR(20),
    DISTRICT_NM     CHAR(30),
    REGION_CD       CHAR(10),
    LAND_USE_CD     CHAR(20),
    LAND_USE_NM     CHAR(50),
    LAND_USE_SCORE  DECIMAL EXTERNAL NULLIF LAND_USE_SCORE=BLANKS,
    FIRE_HIST       DECIMAL EXTERNAL NULLIF FIRE_HIST=BLANKS,
    FIRE_SCORE      DECIMAL EXTERNAL NULLIF FIRE_SCORE=BLANKS,

    -- 시스템 컬럼
    BRANCH_NM       CONSTANT '',
    ANAL_DATE       CONSTANT '',
    REG_DT          EXPRESSION "SYSTIMESTAMP"
)
