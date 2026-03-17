--------------------------------------------------------------------------------
-- Facility inspection history tables (Oracle 19c)
-- Purpose:
-- 1) Store latest general/self-use facility inspection results per building.
-- 2) Support +10 / +6 facility risk score rules in combined view.
--------------------------------------------------------------------------------

CREATE SEQUENCE SEQ_FACILITY_GENERAL_HIST
    START WITH 1
    INCREMENT BY 1
    NOCACHE
    NOCYCLE;

CREATE SEQUENCE SEQ_FACILITY_SELF_HIST
    START WITH 1
    INCREMENT BY 1
    NOCACHE
    NOCYCLE;

--------------------------------------------------------------------------------
-- 1) General-use facility inspection history
--------------------------------------------------------------------------------
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
);

CREATE INDEX IDX_FACILITY_GENERAL_BLDG
    ON TB_FACILITY_GENERAL_HIST (BLDG_SEQ, CHECK_DT DESC);
CREATE INDEX IDX_FACILITY_GENERAL_CUST
    ON TB_FACILITY_GENERAL_HIST (BLDG_SEQ, KEPCO_CUST_NO);

--------------------------------------------------------------------------------
-- 2) Self-use facility inspection history
--------------------------------------------------------------------------------
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
        REFERENCES TB_BLDG_RISK_STATIC (BLDG_SEQ)
);

CREATE INDEX IDX_FACILITY_SELF_BLDG
    ON TB_FACILITY_SELF_HIST (BLDG_SEQ, CHECK_DT DESC);
CREATE INDEX IDX_FACILITY_SELF_CUST
    ON TB_FACILITY_SELF_HIST (BLDG_SEQ, KEPCO_CUST_NO);
