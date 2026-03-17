-- H2 local combined risk view (static + weather + facility inspection).

CREATE OR REPLACE VIEW VW_RISK_COMBINED AS
SELECT
    b.BLDG_SEQ,
    b.BRANCH_NM,
    b.A0,
    b.A13,
    b.A17,
    b.A19,
    b.REGION_NM,
    b.DISTRICT_NM,
    b.REGION_CD,
    b.ADDR,
    b.LON,
    b.LAT,
    b.BUILD_YEAR,
    b.BUILD_AGE,
    b.A24,
    b.AGE_GRADE,
    b.AGE_SCORE,
    b.FLOOD_GRADE,
    b.FLOOD_SCORE,
    b.LANDSLIDE_DIST,
    b.LANDSLIDE_GRADE,
    b.LANDSLIDE_SCORE,
    b.FIRE_SCORE,
    b.PREV_FIRE_OCCUR_DATE,
    b.LAND_USE_SCORE,
    b.TOTAL_SCORE,
    b.TOTAL_GRADE,
    b.RISK_CD,
    COALESCE(b.FACILITY_RISK_SCORE, 0) AS FACILITY_RISK_SCORE,
    w.RISK_DATE,
    COALESCE(w.WEATHER_SCORE, 0) AS WEATHER_SCORE,
    COALESCE(w.WILDFIRE_SCORE, 0) AS WILDFIRE_SCORE,
    COALESCE(w.APPLIED_ALERTS, '') AS APPLIED_ALERTS,
    (b.TOTAL_SCORE + COALESCE(w.WEATHER_SCORE, 0) + COALESCE(b.FACILITY_RISK_SCORE, 0)) AS COMBINED_SCORE,
    CASE
        WHEN (b.TOTAL_SCORE + COALESCE(w.WEATHER_SCORE, 0) + COALESCE(b.FACILITY_RISK_SCORE, 0)) >= 40 THEN 'E'
        WHEN (b.TOTAL_SCORE + COALESCE(w.WEATHER_SCORE, 0) + COALESCE(b.FACILITY_RISK_SCORE, 0)) >= 30 THEN 'D'
        WHEN (b.TOTAL_SCORE + COALESCE(w.WEATHER_SCORE, 0) + COALESCE(b.FACILITY_RISK_SCORE, 0)) >= 20 THEN 'C'
        WHEN (b.TOTAL_SCORE + COALESCE(w.WEATHER_SCORE, 0) + COALESCE(b.FACILITY_RISK_SCORE, 0)) >= 10 THEN 'B'
        ELSE 'A'
    END AS COMBINED_RISK_CD,
    CASE
        WHEN (b.TOTAL_SCORE + COALESCE(w.WEATHER_SCORE, 0) + COALESCE(b.FACILITY_RISK_SCORE, 0)) >= 40 THEN '위험'
        WHEN (b.TOTAL_SCORE + COALESCE(w.WEATHER_SCORE, 0) + COALESCE(b.FACILITY_RISK_SCORE, 0)) >= 30 THEN '경고'
        WHEN (b.TOTAL_SCORE + COALESCE(w.WEATHER_SCORE, 0) + COALESCE(b.FACILITY_RISK_SCORE, 0)) >= 20 THEN '주의'
        WHEN (b.TOTAL_SCORE + COALESCE(w.WEATHER_SCORE, 0) + COALESCE(b.FACILITY_RISK_SCORE, 0)) >= 10 THEN '관심'
        ELSE '안전'
    END AS COMBINED_GRADE_NM,
    CASE
        WHEN b.RISK_CD <> (
            CASE
                WHEN (b.TOTAL_SCORE + COALESCE(w.WEATHER_SCORE, 0) + COALESCE(b.FACILITY_RISK_SCORE, 0)) >= 40 THEN 'E'
                WHEN (b.TOTAL_SCORE + COALESCE(w.WEATHER_SCORE, 0) + COALESCE(b.FACILITY_RISK_SCORE, 0)) >= 30 THEN 'D'
                WHEN (b.TOTAL_SCORE + COALESCE(w.WEATHER_SCORE, 0) + COALESCE(b.FACILITY_RISK_SCORE, 0)) >= 20 THEN 'C'
                WHEN (b.TOTAL_SCORE + COALESCE(w.WEATHER_SCORE, 0) + COALESCE(b.FACILITY_RISK_SCORE, 0)) >= 10 THEN 'B'
                ELSE 'A'
            END
        ) THEN 'Y' ELSE 'N'
    END AS GRADE_CHANGED_YN,
    b.ANAL_DATE,
    b.REG_DT
FROM (
    SELECT
        s.*,
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM TB_FACILITY_GENERAL_HIST g
                WHERE g.BLDG_SEQ = s.BLDG_SEQ
                  AND g.CHECK_RESULT = '부적합'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM TB_FACILITY_GENERAL_HIST g2
                      WHERE g2.BLDG_SEQ = g.BLDG_SEQ
                        AND COALESCE(g2.KEPCO_CUST_NO, '__NULL__') = COALESCE(g.KEPCO_CUST_NO, '__NULL__')
                        AND (
                            g2.CHECK_DT > g.CHECK_DT
                            OR (g2.CHECK_DT = g.CHECK_DT AND COALESCE(g2.REG_DT, TIMESTAMP '1970-01-01 00:00:00') > COALESCE(g.REG_DT, TIMESTAMP '1970-01-01 00:00:00'))
                            OR (g2.CHECK_DT = g.CHECK_DT AND COALESCE(g2.REG_DT, TIMESTAMP '1970-01-01 00:00:00') = COALESCE(g.REG_DT, TIMESTAMP '1970-01-01 00:00:00') AND g2.HIST_SEQ > g.HIST_SEQ)
                        )
                  )
            ) THEN 10
            WHEN EXISTS (
                SELECT 1
                FROM TB_FACILITY_SELF_HIST ss
                WHERE ss.BLDG_SEQ = s.BLDG_SEQ
                  AND ss.INSPECTION_RESULT = '불합격'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM TB_FACILITY_SELF_HIST ss2
                      WHERE ss2.BLDG_SEQ = ss.BLDG_SEQ
                        AND COALESCE(ss2.KEPCO_CUST_NO, '__NULL__') = COALESCE(ss.KEPCO_CUST_NO, '__NULL__')
                        AND (
                            ss2.CHECK_DT > ss.CHECK_DT
                            OR (ss2.CHECK_DT = ss.CHECK_DT AND COALESCE(ss2.REG_DT, TIMESTAMP '1970-01-01 00:00:00') > COALESCE(ss.REG_DT, TIMESTAMP '1970-01-01 00:00:00'))
                            OR (ss2.CHECK_DT = ss.CHECK_DT AND COALESCE(ss2.REG_DT, TIMESTAMP '1970-01-01 00:00:00') = COALESCE(ss.REG_DT, TIMESTAMP '1970-01-01 00:00:00') AND ss2.HIST_SEQ > ss.HIST_SEQ)
                        )
                  )
            ) THEN 10
            WHEN EXISTS (
                SELECT 1
                FROM TB_FACILITY_GENERAL_HIST g
                WHERE g.BLDG_SEQ = s.BLDG_SEQ
                  AND REPLACE(COALESCE(g.CHECK_RESULT, ''), ' ', '') = '부재종결'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM TB_FACILITY_GENERAL_HIST g2
                      WHERE g2.BLDG_SEQ = g.BLDG_SEQ
                        AND COALESCE(g2.KEPCO_CUST_NO, '__NULL__') = COALESCE(g.KEPCO_CUST_NO, '__NULL__')
                        AND (
                            g2.CHECK_DT > g.CHECK_DT
                            OR (g2.CHECK_DT = g.CHECK_DT AND COALESCE(g2.REG_DT, TIMESTAMP '1970-01-01 00:00:00') > COALESCE(g.REG_DT, TIMESTAMP '1970-01-01 00:00:00'))
                            OR (g2.CHECK_DT = g.CHECK_DT AND COALESCE(g2.REG_DT, TIMESTAMP '1970-01-01 00:00:00') = COALESCE(g.REG_DT, TIMESTAMP '1970-01-01 00:00:00') AND g2.HIST_SEQ > g.HIST_SEQ)
                        )
                  )
            ) THEN 6
            ELSE 0
        END AS FACILITY_RISK_SCORE
    FROM TB_BUILDING_RISK s
) b
LEFT JOIN TB_WEATHER_RISK w
    ON (
           (NULLIF(TRIM(b.REGION_CD), '') IS NOT NULL AND TRIM(b.REGION_CD) = TRIM(w.REGION_CD))
        OR (
               NULLIF(TRIM(b.REGION_CD), '') IS NULL
           AND COALESCE(TRIM(b.REGION_NM), '') = COALESCE(TRIM(w.REGION_NM), '')
           AND COALESCE(TRIM(b.DISTRICT_NM), '') = COALESCE(TRIM(w.DISTRICT_NM), '')
        )
    )
   AND w.RISK_DATE = CURRENT_DATE;
