--------------------------------------------------------------------------------
-- Combined risk view (Oracle)
-- total = static + weather + facility inspection bonus(+10 fail / +6 absent-close)
--------------------------------------------------------------------------------

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
    NVL(b.FACILITY_RISK_SCORE, 0) AS FACILITY_RISK_SCORE,
    w.RISK_DATE,
    NVL(w.WEATHER_SCORE, 0) AS WEATHER_SCORE,
    NVL(w.WILDFIRE_SCORE, 0) AS WILDFIRE_SCORE,
    NVL(w.WILDFIRE_GRADE, 'NONE') AS WILDFIRE_GRADE,
    NVL(w.APPLIED_ALERTS, '') AS APPLIED_ALERTS,
    b.TOTAL_SCORE + NVL(w.WEATHER_SCORE, 0) + NVL(b.FACILITY_RISK_SCORE, 0) AS COMBINED_SCORE,
    CASE
        WHEN b.TOTAL_SCORE + NVL(w.WEATHER_SCORE, 0) + NVL(b.FACILITY_RISK_SCORE, 0) >= 40 THEN 'E'
        WHEN b.TOTAL_SCORE + NVL(w.WEATHER_SCORE, 0) + NVL(b.FACILITY_RISK_SCORE, 0) >= 30 THEN 'D'
        WHEN b.TOTAL_SCORE + NVL(w.WEATHER_SCORE, 0) + NVL(b.FACILITY_RISK_SCORE, 0) >= 20 THEN 'C'
        WHEN b.TOTAL_SCORE + NVL(w.WEATHER_SCORE, 0) + NVL(b.FACILITY_RISK_SCORE, 0) >= 10 THEN 'B'
        ELSE 'A'
    END AS COMBINED_RISK_CD,
    CASE
        WHEN b.TOTAL_SCORE + NVL(w.WEATHER_SCORE, 0) + NVL(b.FACILITY_RISK_SCORE, 0) >= 40 THEN '위험'
        WHEN b.TOTAL_SCORE + NVL(w.WEATHER_SCORE, 0) + NVL(b.FACILITY_RISK_SCORE, 0) >= 30 THEN '경고'
        WHEN b.TOTAL_SCORE + NVL(w.WEATHER_SCORE, 0) + NVL(b.FACILITY_RISK_SCORE, 0) >= 20 THEN '주의'
        WHEN b.TOTAL_SCORE + NVL(w.WEATHER_SCORE, 0) + NVL(b.FACILITY_RISK_SCORE, 0) >= 10 THEN '관심'
        ELSE '안전'
    END AS COMBINED_GRADE_NM,
    CASE
        WHEN b.RISK_CD != (
            CASE
                WHEN b.TOTAL_SCORE + NVL(w.WEATHER_SCORE, 0) + NVL(b.FACILITY_RISK_SCORE, 0) >= 40 THEN 'E'
                WHEN b.TOTAL_SCORE + NVL(w.WEATHER_SCORE, 0) + NVL(b.FACILITY_RISK_SCORE, 0) >= 30 THEN 'D'
                WHEN b.TOTAL_SCORE + NVL(w.WEATHER_SCORE, 0) + NVL(b.FACILITY_RISK_SCORE, 0) >= 20 THEN 'C'
                WHEN b.TOTAL_SCORE + NVL(w.WEATHER_SCORE, 0) + NVL(b.FACILITY_RISK_SCORE, 0) >= 10 THEN 'B'
                ELSE 'A'
            END
        ) THEN 'Y' ELSE 'N'
    END AS GRADE_CHANGED_YN,
    b.ANAL_DATE,
    b.REG_DT
FROM (
    SELECT
        s.*,
        NVL(f.FACILITY_RISK_SCORE, 0) AS FACILITY_RISK_SCORE
    FROM TB_BLDG_RISK_STATIC s
    LEFT JOIN (
        SELECT
            t.BLDG_SEQ,
            MAX(t.FACILITY_RISK_SCORE) AS FACILITY_RISK_SCORE
        FROM (
            SELECT
                g.BLDG_SEQ,
                CASE
                    WHEN g.CHECK_RESULT = '부적합' THEN 10
                    WHEN REPLACE(NVL(g.CHECK_RESULT, ''), ' ', '') = '부재종결' THEN 6
                    ELSE 0
                END AS FACILITY_RISK_SCORE
            FROM (
                SELECT
                    gg.BLDG_SEQ,
                    gg.KEPCO_CUST_NO,
                    gg.CHECK_RESULT,
                    ROW_NUMBER() OVER (
                        PARTITION BY gg.BLDG_SEQ, NVL(gg.KEPCO_CUST_NO, '__NULL__')
                        ORDER BY gg.CHECK_DT DESC, gg.REG_DT DESC, gg.HIST_SEQ DESC
                    ) AS RN
                FROM TB_FACILITY_GENERAL_HIST gg
            ) g
            WHERE g.RN = 1

            UNION ALL

            SELECT
                s.BLDG_SEQ,
                -- defect_cnt(지적건수)는 정보 컬럼이며 점수 산정은 결과값으로만 판단.
                CASE WHEN s.INSPECTION_RESULT = '불합격' THEN 10 ELSE 0 END AS FACILITY_RISK_SCORE
            FROM (
                SELECT
                    ss.BLDG_SEQ,
                    ss.KEPCO_CUST_NO,
                    ss.INSPECTION_RESULT,
                    ROW_NUMBER() OVER (
                        PARTITION BY ss.BLDG_SEQ, NVL(ss.KEPCO_CUST_NO, '__NULL__')
                        ORDER BY ss.CHECK_DT DESC, ss.REG_DT DESC, ss.HIST_SEQ DESC
                    ) AS RN
                FROM TB_FACILITY_SELF_HIST ss
            ) s
            WHERE s.RN = 1
        ) t
        GROUP BY t.BLDG_SEQ
    ) f
        ON f.BLDG_SEQ = s.BLDG_SEQ
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
   AND w.RISK_DATE = TRUNC(SYSDATE);

COMMENT ON TABLE VW_RISK_COMBINED IS '정적+기상+설비점검 종합 위험점수 뷰';
