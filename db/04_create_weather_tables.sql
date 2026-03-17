--------------------------------------------------------------------------------
-- Í∏∞ÏÉÅ?πÎ≥¥ ?∞Îèô ?åÏù¥Î∏?Oracle DDL
-- ?ùÏÑ±?? 2026-02-11
-- ?§Î™Ö: Í∏∞ÏÉÅÏ≤?API ?πÎ≥¥ ?∞Ïù¥???ÅÏû¨ Î∞?ÏßÄ??≥Ñ Í∏∞ÏÉÅ ?ÑÌóò?êÏàò ?∞Ï∂ú???åÏù¥Î∏?
--       TB_BLDG_RISK_STATIC (STEP1)?Ä Ï°∞Ïù∏?òÏó¨ Ï¢ÖÌï©?êÏàò ?©ÏÇ∞
--------------------------------------------------------------------------------

-- ?úÌÄÄ?? Í∏∞ÏÉÅ?πÎ≥¥ PK
CREATE SEQUENCE SEQ_WEATHER_ALERT
    START WITH 1
    INCREMENT BY 1
    NOCACHE
    NOCYCLE;

-- ?úÌÄÄ?? Í∏∞ÏÉÅ?ÑÌóò?êÏàò PK
CREATE SEQUENCE SEQ_WEATHER_RISK
    START WITH 1
    INCREMENT BY 1
    NOCACHE
    NOCYCLE;

--------------------------------------------------------------------------------
-- 1. Í∏∞ÏÉÅ?πÎ≥¥ ?êÎ≥∏ ?åÏù¥Î∏?(API ?ëÎãµ Í∑∏Î?Î°??Ä??
--------------------------------------------------------------------------------
CREATE TABLE TB_WEATHER_ALERT (
    ALERT_SEQ            NUMBER DEFAULT SEQ_WEATHER_ALERT.NEXTVAL NOT NULL,   -- ?úÌÄÄ??PK
    ALERT_DATE           DATE                NOT NULL,   -- Ï°∞Ìöå?ºÏûê (Î∞∞Ïπò ?§Ìñâ??
    ALERT_TYPE           VARCHAR2(20),                   -- ?πÎ≥¥Ï¢ÖÎ•ò (?úÌåå, ?∏Ïö∞, ?úÌíç...)
    ALERT_LEVEL          VARCHAR2(10),                   -- ?πÎ≥¥?òÏ? (Í≤ΩÎ≥¥, Ï£ºÏùò, ?àÎπÑ)
    ALERT_CMD            VARCHAR2(10),                   -- ?πÎ≥¥Î™ÖÎ†π (Î∞úÌëú, Î≥ÄÍ≤? ?¥Ï†ú)
    REGION_NM            VARCHAR2(50),                   -- ?πÎ≥¥Íµ¨Ïó≠Î™?
    REGION_CD            VARCHAR2(20),                   -- ?πÎ≥¥Íµ¨Ïó≠ÏΩîÎìú
    PARENT_REGION        VARCHAR2(30),                   -- ?ÅÏúÑÍµ¨Ïó≠Î™?
    ISSUE_DT             VARCHAR2(20),                   -- Î∞úÌëú?úÍ∞Å
    EFFECT_DT            VARCHAR2(20),                   -- Î∞úÌö®?úÍ∞Å
    CANCEL_NOTE          VARCHAR2(100),                  -- ?¥Ï†ú?àÍ≥†
    REG_DT               TIMESTAMP DEFAULT SYSTIMESTAMP, -- ?±Î°ù?ºÏãú

    CONSTRAINT PK_WEATHER_ALERT PRIMARY KEY (ALERT_SEQ)
);

COMMENT ON TABLE  TB_WEATHER_ALERT IS 'Í∏∞ÏÉÅ?πÎ≥¥ ?êÎ≥∏ (Í∏∞ÏÉÅÏ≤?API ?ëÎãµ)';
COMMENT ON COLUMN TB_WEATHER_ALERT.ALERT_SEQ IS '?úÌÄÄ??PK';
COMMENT ON COLUMN TB_WEATHER_ALERT.ALERT_DATE IS 'Ï°∞Ìöå?ºÏûê (Î∞∞Ïπò ?§Ìñâ??';
COMMENT ON COLUMN TB_WEATHER_ALERT.ALERT_TYPE IS '?πÎ≥¥Ï¢ÖÎ•ò (?úÌåå, ?∏Ïö∞, ?úÌíç, ??óº ??';
COMMENT ON COLUMN TB_WEATHER_ALERT.ALERT_LEVEL IS '?πÎ≥¥?òÏ? (Í≤ΩÎ≥¥, Ï£ºÏùò, ?àÎπÑ)';
COMMENT ON COLUMN TB_WEATHER_ALERT.ALERT_CMD IS '?πÎ≥¥Î™ÖÎ†π (Î∞úÌëú, Î≥ÄÍ≤? ?¥Ï†ú)';
COMMENT ON COLUMN TB_WEATHER_ALERT.REGION_NM IS '?πÎ≥¥Íµ¨Ïó≠Î™?(?? ?úÏö∏?ôÎÇ®Í∂? Í∞ïÎ¶â?úÌèâÏßÄ)';
COMMENT ON COLUMN TB_WEATHER_ALERT.REGION_CD IS '?πÎ≥¥Íµ¨Ïó≠ÏΩîÎìú (?? L1020110)';
COMMENT ON COLUMN TB_WEATHER_ALERT.PARENT_REGION IS '?ÅÏúÑÍµ¨Ïó≠Î™?(?úÎèÑ)';
COMMENT ON COLUMN TB_WEATHER_ALERT.ISSUE_DT IS 'Î∞úÌëú?úÍ∞Å (YYYYMMDDHHMM)';
COMMENT ON COLUMN TB_WEATHER_ALERT.EFFECT_DT IS 'Î∞úÌö®?úÍ∞Å (YYYYMMDDHHMM)';
COMMENT ON COLUMN TB_WEATHER_ALERT.CANCEL_NOTE IS '?¥Ï†ú?àÍ≥†';

-- ?∏Îç±??
CREATE INDEX IDX_WEATHER_ALERT_DATE ON TB_WEATHER_ALERT (ALERT_DATE);
CREATE INDEX IDX_WEATHER_ALERT_TYPE ON TB_WEATHER_ALERT (ALERT_TYPE, ALERT_LEVEL);
CREATE INDEX IDX_WEATHER_ALERT_REGION ON TB_WEATHER_ALERT (PARENT_REGION);

--------------------------------------------------------------------------------
-- 2. ÏßÄ??≥Ñ Í∏∞ÏÉÅ ?ÑÌóò?êÏàò ?åÏù¥Î∏?
--------------------------------------------------------------------------------
CREATE TABLE TB_WEATHER_RISK (
    RISK_SEQ             NUMBER DEFAULT SEQ_WEATHER_RISK.NEXTVAL NOT NULL,   -- ?úÌÄÄ??PK
    RISK_DATE            DATE                NOT NULL,   -- Í∏∞Ï??ºÏûê
    REGION_CD            VARCHAR2(10)        NOT NULL,   -- ÏßÄ??Ωî??(?âÏ†ïÍµ¨Ïó≠, TB_BLDG_RISK_STATICÍ≥?Ï°∞Ïù∏)
    REGION_NM            VARCHAR2(20),                   -- ?úÎèÑÎ™?
    DISTRICT_NM          VARCHAR2(30),                   -- Íµ¨Íµ∞Î™?
    WEATHER_SCORE        NUMBER(4,1)  DEFAULT 0,         -- Í∏∞ÏÉÅ Í∞Ä?∞Ï†ê ?©Í≥Ñ
    APPLIED_ALERTS       VARCHAR2(200),                  -- ?ÅÏö©???πÎ≥¥ Î™©Î°ù Î¨∏Ïûê??
    WILDFIRE_SCORE       NUMBER(4,1)  DEFAULT 0,         -- wildfire score (0/2/4/6/8/10)
    WILDFIRE_GRADE       VARCHAR2(20) DEFAULT 'NONE',    -- wildfire level (NONE~DETECTED)
    WILDFIRE_TM          VARCHAR2(12),                   -- source time (yyyyMMddHHmm)
    REG_DT               TIMESTAMP DEFAULT SYSTIMESTAMP, -- ?±Î°ù?ºÏãú

    CONSTRAINT PK_WEATHER_RISK PRIMARY KEY (RISK_SEQ),
    CONSTRAINT UK_WEATHER_RISK UNIQUE (RISK_DATE, REGION_CD)
);

COMMENT ON TABLE  TB_WEATHER_RISK IS 'ÏßÄ??≥Ñ Í∏∞ÏÉÅ ?ÑÌóò?êÏàò (?ºÎ≥Ñ)';
COMMENT ON COLUMN TB_WEATHER_RISK.RISK_SEQ IS '?úÌÄÄ??PK';
COMMENT ON COLUMN TB_WEATHER_RISK.RISK_DATE IS 'Í∏∞Ï??ºÏûê';
COMMENT ON COLUMN TB_WEATHER_RISK.REGION_CD IS 'ÏßÄ??Ωî??(TB_BLDG_RISK_STATIC.REGION_CD?Ä Ï°∞Ïù∏)';
COMMENT ON COLUMN TB_WEATHER_RISK.REGION_NM IS '?úÎèÑÎ™?;
COMMENT ON COLUMN TB_WEATHER_RISK.DISTRICT_NM IS 'Íµ¨Íµ∞Î™?;
COMMENT ON COLUMN TB_WEATHER_RISK.WEATHER_SCORE IS 'weather score total';
COMMENT ON COLUMN TB_WEATHER_RISK.APPLIED_ALERTS IS 'applied weather alert list';
COMMENT ON COLUMN TB_WEATHER_RISK.WILDFIRE_SCORE IS 'wildfire score (0/2/4/6/8/10)';
COMMENT ON COLUMN TB_WEATHER_RISK.WILDFIRE_GRADE IS 'wildfire level (NONE~DETECTED)';
COMMENT ON COLUMN TB_WEATHER_RISK.WILDFIRE_TM IS 'wildfire source time (yyyyMMddHHmm)';

-- ?∏Îç±??
CREATE INDEX IDX_WEATHER_RISK_DATE ON TB_WEATHER_RISK (RISK_DATE);
CREATE INDEX IDX_WEATHER_RISK_REGION ON TB_WEATHER_RISK (REGION_CD);

--------------------------------------------------------------------------------
-- 3. Í∏∞ÏÉÅ?πÎ≥¥ Íµ¨Ïó≠ Îß§Ìïë ?åÏù¥Î∏?(REG_ID -> Íµ¨Ïó≠Î™??ÅÏúÑÍµ¨Ïó≠)
--------------------------------------------------------------------------------
CREATE TABLE TB_ALERT_ZONE_MAP (
    ZONE_CD            VARCHAR2(20)       NOT NULL,
    ZONE_NM            VARCHAR2(120)      NOT NULL,
    PARENT_REGION      VARCHAR2(120),
    DISTRICT_EXPR      VARCHAR2(1000),
    SOURCE_TYPE        VARCHAR2(30) DEFAULT 'seed',
    USE_YN             CHAR(1)      DEFAULT 'Y' NOT NULL,
    REG_DT             TIMESTAMP    DEFAULT SYSTIMESTAMP,
    CONSTRAINT PK_ALERT_ZONE_MAP PRIMARY KEY (ZONE_CD)
);

COMMENT ON TABLE  TB_ALERT_ZONE_MAP IS 'Í∏∞ÏÉÅ?πÎ≥¥ Íµ¨Ïó≠ÏΩîÎìú Îß§Ìïë';
COMMENT ON COLUMN TB_ALERT_ZONE_MAP.ZONE_CD IS '?πÎ≥¥Íµ¨Ïó≠ÏΩîÎìú (REG_ID)';
COMMENT ON COLUMN TB_ALERT_ZONE_MAP.ZONE_NM IS '?πÎ≥¥Íµ¨Ïó≠Î™?;
COMMENT ON COLUMN TB_ALERT_ZONE_MAP.PARENT_REGION IS '?ÅÏúÑÍµ¨Ïó≠Î™?;
COMMENT ON COLUMN TB_ALERT_ZONE_MAP.DISTRICT_EXPR IS 'Í∏∞Î≥∏?âÏ†ïÍµ¨Ïó≠ ?úÌòÑ';
COMMENT ON COLUMN TB_ALERT_ZONE_MAP.SOURCE_TYPE IS 'Îß§Ìïë Ï∂úÏ≤ò (txt/history_csv)';
COMMENT ON COLUMN TB_ALERT_ZONE_MAP.USE_YN IS '?¨Ïö©?¨Î?';

CREATE INDEX IDX_ALERT_ZONE_MAP_USE ON TB_ALERT_ZONE_MAP (USE_YN);

--------------------------------------------------------------------------------
-- Í≤ÄÏ¶?ÏøºÎ¶¨
--------------------------------------------------------------------------------
-- Í∏∞ÏÉÅ?πÎ≥¥ ?êÎ≥∏ Í±¥Ïàò
-- SELECT ALERT_DATE, COUNT(*) AS CNT FROM TB_WEATHER_ALERT GROUP BY ALERT_DATE ORDER BY ALERT_DATE;

-- Í∏∞ÏÉÅ?êÏàò ?ÑÌô©
-- SELECT RISK_DATE, COUNT(*) AS REGION_CNT, AVG(WEATHER_SCORE) AS AVG_SCORE, MAX(WEATHER_SCORE) AS MAX_SCORE
--   FROM TB_WEATHER_RISK GROUP BY RISK_DATE ORDER BY RISK_DATE;

-- ?πÎ≥¥ ?†ÌòïÎ≥?ÏßëÍ≥Ñ
-- SELECT ALERT_TYPE, ALERT_LEVEL, COUNT(*) AS CNT
--   FROM TB_WEATHER_ALERT
--  WHERE ALERT_DATE = TRUNC(SYSDATE)
--  GROUP BY ALERT_TYPE, ALERT_LEVEL
--  ORDER BY ALERT_TYPE, ALERT_LEVEL;
