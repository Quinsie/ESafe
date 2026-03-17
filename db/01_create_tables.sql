--------------------------------------------------------------------------------
-- 건물 위험분석 정적 데이터 Oracle DDL
-- 생성일: 2026-02-11
-- 설명: Python 분석 결과(CSV)를 Oracle에 적재하기 위한 테이블 정의
--       A0~A30 건축물대장 원본 데이터 포함
--------------------------------------------------------------------------------

-- 시퀀스: 건물 PK
CREATE SEQUENCE SEQ_BLDG_RISK
    START WITH 1
    INCREMENT BY 1
    NOCACHE
    NOCYCLE;

--------------------------------------------------------------------------------
-- 1. 건물별 정적 위험점수 테이블
--------------------------------------------------------------------------------
CREATE TABLE TB_BLDG_RISK_STATIC (
    -- PK
    BLDG_SEQ            NUMBER              NOT NULL,   -- 시퀀스 PK

    -- 사업소 정보 (폴더명에서 추출)
    BRANCH_NM            VARCHAR2(50),                   -- 사업소명

    -- ===== A0~A30: 건축물대장 원본 데이터 =====
    A0                   VARCHAR2(20),                   -- 건물고유번호
    A1                   VARCHAR2(50),                   -- 관리번호
    A2                   VARCHAR2(30),                   -- 대장PK
    A3                   VARCHAR2(20),                   -- PNU(필지고유번호)
    A4                   VARCHAR2(200),                  -- 시도군구 주소
    A5                   VARCHAR2(10),                   -- 본번
    A6                   VARCHAR2(10),                   -- 번구분(일반/산)
    A7                   VARCHAR2(30),                   -- 부번(지번)
    A8                   VARCHAR2(30),                   -- 특수지코드
    A9                   VARCHAR2(10),                   -- 블록
    A10                  VARCHAR2(30),                   -- 로트(건축물종류)
    A11                  VARCHAR2(10),                   -- 대장종류코드
    A12                  VARCHAR2(30),                   -- 대장종류명
    A13                  VARCHAR2(100),                  -- 건물명
    A14                  VARCHAR2(50),                   -- 동명
    A15                  NUMBER(15,2),                   -- 연면적(㎡)
    A16                  VARCHAR2(10),                   -- 주용도코드
    A17                  VARCHAR2(50),                   -- 주구조
    A18                  VARCHAR2(10),                   -- 주용도코드2
    A19                  VARCHAR2(50),                   -- 주용도명
    A20                  NUMBER(10,2),                   -- 높이(m)
    A21                  NUMBER(5,1),                    -- 층수
    A22                  NUMBER(5,1),                    -- 지하층수
    A23                  VARCHAR2(20),                   -- 착공일
    A24                  VARCHAR2(20),                   -- 사용승인일
    A25                  NUMBER(5,1),                    -- 건물연령(원본)
    A26                  VARCHAR2(10),                   -- 연령코드
    A27                  VARCHAR2(20),                   -- 연령대(원본)
    A28                  VARCHAR2(10),                   -- 연령상세코드
    A29                  VARCHAR2(20),                   -- 연령상세명
    A30                  VARCHAR2(30),                   -- 데이터기준일시

    -- ===== 위치/주소 정보 =====
    REGION_NM            VARCHAR2(20),                   -- 지역(시도)
    DISTRICT_NM          VARCHAR2(30),                   -- 구군
    REGION_CD            VARCHAR2(10),                   -- 지역코드
    ADDR                 VARCHAR2(500),                  -- 주소(조합)
    CENTER_X             NUMBER(15,6),                   -- 중심점X
    CENTER_Y             NUMBER(15,6),                   -- 중심점Y
    LON                  NUMBER(15,6),                   -- 경도
    LAT                  NUMBER(15,6),                   -- 위도

    -- ===== 노후도 분석 =====
    BUILD_YEAR           NUMBER(4),                      -- 건축년도
    BUILD_AGE            NUMBER(3),                      -- 건물연령
    AGE_RANGE            VARCHAR2(20),                   -- 연령대
    AGE_GRADE            VARCHAR2(10),                   -- 노후등급
    AGE_SCORE            NUMBER(2),                      -- 노후점수

    -- ===== 홍수 분석 =====
    FLOOD_OVERLAP        NUMBER(5,1),                    -- 겹침비율
    FLOOD_GRADE          VARCHAR2(10),                   -- 홍수등급
    FLOOD_SCORE          NUMBER(2),                      -- 홍수점수

    -- ===== 산사태 분석 =====
    LANDSLIDE_DIST       NUMBER(10,3),                   -- 산사태거리
    LANDSLIDE_GRADE      VARCHAR2(10),                   -- 산사태등급
    LANDSLIDE_SCORE      NUMBER(2),                      -- 산사태점수

    -- ===== 교차 위험점수 (35컬럼/69컬럼 포맷) =====
    AGE_FLOOD_SCORE      NUMBER(4,1),                    -- 노후홍수점수
    AGE_FLOOD_GRADE      VARCHAR2(10),                   -- 노후홍수등급
    AGE_FLOOD_CD         VARCHAR2(2),                    -- 노후홍수코드
    FLOOD_LAND_SCORE     NUMBER(4,1),                    -- 홍수산사태점수
    FLOOD_LAND_GRADE     VARCHAR2(10),                   -- 홍수산사태등급
    FLOOD_LAND_CD        VARCHAR2(2),                    -- 홍수산사태코드
    AGE_LAND_SCORE       NUMBER(4,1),                    -- 노후산사태점수
    AGE_LAND_GRADE       VARCHAR2(10),                   -- 노후산사태등급
    AGE_LAND_CD          VARCHAR2(2),                    -- 노후산사태코드

    -- ===== 용도 분석 =====
    LAND_USE_CD          VARCHAR2(20),                   -- 용도코드
    LAND_USE_NM          VARCHAR2(50),                   -- 용도명
    LAND_USE_SCORE       NUMBER(4,1),                    -- 용도점수

    -- ===== 전기화재 =====
    FIRE_HIST            NUMBER(1),                      -- 전기화재(이력유무)
    FIRE_MULT            NUMBER(3,1),                    -- 화재배수
    FIRE_SCORE           NUMBER(2),                      -- 화재점수
    PREV_FIRE_OCCUR_DATE VARCHAR2(1000),                -- 이전화재발생일(파이프(|) 구분 다건 가능)

    -- ===== 종합점수 =====
    BASE_SCORE           NUMBER(5,1),                    -- 기본점수(화재배수 적용 전)
    TOTAL_SCORE          NUMBER(5,1),                    -- 종합점수
    TOTAL_GRADE          VARCHAR2(10),                   -- 종합등급
    RISK_CD              VARCHAR2(2),                    -- 위험코드(A~E)

    -- ===== 시스템 컬럼 =====
    ANAL_DATE            DATE,                           -- 분석일자(파일명에서 추출)
    REG_DT               TIMESTAMP DEFAULT SYSTIMESTAMP, -- 등록일시

    -- PK
    CONSTRAINT PK_BLDG_RISK_STATIC PRIMARY KEY (BLDG_SEQ)
);

-- 코멘트
COMMENT ON TABLE  TB_BLDG_RISK_STATIC IS '건물별 정적 위험점수 (A0-A30 건축물대장 원본 포함)';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.BLDG_SEQ IS '건물 시퀀스 PK';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.BRANCH_NM IS '사업소명 (폴더명)';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.A0 IS '건물고유번호';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.A1 IS '관리번호';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.A2 IS '대장PK';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.A3 IS 'PNU(필지고유번호)';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.A4 IS '시도군구 주소';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.A13 IS '건물명';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.A15 IS '연면적(㎡)';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.A17 IS '주구조';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.A19 IS '주용도명';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.A23 IS '착공일';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.A24 IS '사용승인일';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.A30 IS '데이터기준일시';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.AGE_FLOOD_SCORE IS '노후+홍수 교차 위험점수';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.FLOOD_LAND_SCORE IS '홍수+산사태 교차 위험점수';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.AGE_LAND_SCORE IS '노후+산사태 교차 위험점수';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.FIRE_MULT IS '화재배수(전기화재 이력 반영 계수)';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.PREV_FIRE_OCCUR_DATE IS '이전화재발생일(파이프(|) 구분 다건 가능)';
COMMENT ON COLUMN TB_BLDG_RISK_STATIC.BASE_SCORE IS '기본점수(화재배수 적용 전 종합)';

-- 인덱스
CREATE INDEX IDX_BLDG_RISK_REGION ON TB_BLDG_RISK_STATIC (REGION_CD);
CREATE INDEX IDX_BLDG_RISK_BRANCH ON TB_BLDG_RISK_STATIC (BRANCH_NM);
CREATE INDEX IDX_BLDG_RISK_GRADE  ON TB_BLDG_RISK_STATIC (TOTAL_GRADE);
CREATE INDEX IDX_BLDG_RISK_RISKCD ON TB_BLDG_RISK_STATIC (RISK_CD);
CREATE INDEX IDX_BLDG_RISK_A0     ON TB_BLDG_RISK_STATIC (A0);
CREATE INDEX IDX_BLDG_RISK_A3     ON TB_BLDG_RISK_STATIC (A3);
CREATE INDEX IDX_BLDG_RISK_ANAL   ON TB_BLDG_RISK_STATIC (ANAL_DATE);

--------------------------------------------------------------------------------
-- 2. 사업소-지역 매핑 테이블
--------------------------------------------------------------------------------
CREATE TABLE TB_BRANCH_REGION_MAP (
    BRANCH_CD            VARCHAR2(10)   NOT NULL,        -- 사업소코드
    BRANCH_NM            VARCHAR2(50)   NOT NULL,        -- 사업소명
    REGION_CD            VARCHAR2(10)   NOT NULL,        -- 지역코드
    REGION_NM            VARCHAR2(20),                   -- 시도명
    DISTRICT_NM          VARCHAR2(30),                   -- 구군명
    USE_YN               CHAR(1) DEFAULT 'Y',            -- 사용여부
    REG_DT               TIMESTAMP DEFAULT SYSTIMESTAMP,

    CONSTRAINT PK_BRANCH_REGION_MAP PRIMARY KEY (BRANCH_CD, REGION_CD)
);

COMMENT ON TABLE TB_BRANCH_REGION_MAP IS '사업소-지역 매핑 테이블';

--------------------------------------------------------------------------------
-- 3. 위험등급 코드표
--------------------------------------------------------------------------------
CREATE TABLE TB_RISK_GRADE_CODE (
    RISK_CD              VARCHAR2(2)    NOT NULL,        -- 위험코드(A~E)
    GRADE_NM             VARCHAR2(10)   NOT NULL,        -- 등급명
    SCORE_FROM           NUMBER(5,1),                    -- 점수 하한
    SCORE_TO             NUMBER(5,1),                    -- 점수 상한
    GRADE_DESC           VARCHAR2(200),                  -- 등급설명
    SORT_ORDER           NUMBER(2),                      -- 정렬순서
    USE_YN               CHAR(1) DEFAULT 'Y',
    REG_DT               TIMESTAMP DEFAULT SYSTIMESTAMP,

    CONSTRAINT PK_RISK_GRADE_CODE PRIMARY KEY (RISK_CD)
);

COMMENT ON TABLE TB_RISK_GRADE_CODE IS '위험등급 코드표';

-- 위험등급 초기 데이터
INSERT INTO TB_RISK_GRADE_CODE (RISK_CD, GRADE_NM, SCORE_FROM, SCORE_TO, GRADE_DESC, SORT_ORDER)
VALUES ('A', '안전', 0, 10, '종합위험점수 0~10점', 1);
INSERT INTO TB_RISK_GRADE_CODE (RISK_CD, GRADE_NM, SCORE_FROM, SCORE_TO, GRADE_DESC, SORT_ORDER)
VALUES ('B', '관심', 10, 20, '종합위험점수 10~20점', 2);
INSERT INTO TB_RISK_GRADE_CODE (RISK_CD, GRADE_NM, SCORE_FROM, SCORE_TO, GRADE_DESC, SORT_ORDER)
VALUES ('C', '주의', 20, 30, '종합위험점수 20~30점', 3);
INSERT INTO TB_RISK_GRADE_CODE (RISK_CD, GRADE_NM, SCORE_FROM, SCORE_TO, GRADE_DESC, SORT_ORDER)
VALUES ('D', '경고', 30, 40, '종합위험점수 30~40점', 4);
INSERT INTO TB_RISK_GRADE_CODE (RISK_CD, GRADE_NM, SCORE_FROM, SCORE_TO, GRADE_DESC, SORT_ORDER)
VALUES ('E', '위험', 40, 999, '종합위험점수 40점 이상', 5);

COMMIT;

--------------------------------------------------------------------------------
-- 검증 쿼리
--------------------------------------------------------------------------------
-- 테이블 건수 확인
-- SELECT COUNT(*) AS TOTAL_CNT FROM TB_BLDG_RISK_STATIC;

-- 사업소별 건수
-- SELECT BRANCH_NM, COUNT(*) AS CNT FROM TB_BLDG_RISK_STATIC GROUP BY BRANCH_NM ORDER BY BRANCH_NM;

-- 등급별 분포
-- SELECT TOTAL_GRADE, RISK_CD, COUNT(*) AS CNT
--   FROM TB_BLDG_RISK_STATIC
--  GROUP BY TOTAL_GRADE, RISK_CD
--  ORDER BY RISK_CD;

-- A0 건물고유번호 누락 건수 (27컬럼 포맷은 A0 없음)
-- SELECT COUNT(*) AS NO_A0_CNT FROM TB_BLDG_RISK_STATIC WHERE A0 IS NULL;

-- 분석일자별 건수
-- SELECT ANAL_DATE, COUNT(*) AS CNT FROM TB_BLDG_RISK_STATIC GROUP BY ANAL_DATE ORDER BY ANAL_DATE;
