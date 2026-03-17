--------------------------------------------------------------------------------
-- [BUGFIX] 서울북부지사/서울동부지사 관할 구 BRANCH_NM 오류 수정 (Oracle 운영 적용)
-- 작성일: 2026-02-18
--
-- 원인: 데이터 적재 시 구->지사 매핑 오류
--   - 도봉구/강북구/성북구/노원구/중랑구  -> 서울동부지사로 잘못 적재 (서울북부지사 관할)
--   - 강동구/송파구                        -> 서울남부지사로 잘못 적재 (서울동부지사 관할)
--
-- 근거: 전국 사업소 일람표.txt
--   서울북부지사: 도봉구, 강북구, 성북구, 노원구, 중랑구
--   서울동부지사: 동대문구, 성동구, 광진구, 강동구, 송파구
--------------------------------------------------------------------------------

-- [1] 영향 건수 사전 확인 (선택 실행)
-- SELECT BRANCH_NM, DISTRICT_NM, COUNT(*) CNT
-- FROM TB_BLDG_RISK_STATIC
-- WHERE DISTRICT_NM IN ('도봉구', '강북구', '성북구', '노원구', '중랑구', '강동구', '송파구')
--   AND REGION_NM = '서울'
-- GROUP BY BRANCH_NM, DISTRICT_NM
-- ORDER BY DISTRICT_NM;

-- [2] 수정 실행 - 서울북부지사 (도봉구/강북구/성북구/노원구/중랑구)
UPDATE TB_BLDG_RISK_STATIC
SET BRANCH_NM = '서울북부지사'
WHERE DISTRICT_NM IN ('도봉구', '강북구', '성북구', '노원구', '중랑구')
  AND REGION_NM = '서울';

-- [3] 수정 실행 - 서울동부지사 (강동구/송파구)
UPDATE TB_BLDG_RISK_STATIC
SET BRANCH_NM = '서울동부지사'
WHERE DISTRICT_NM IN ('강동구', '송파구')
  AND REGION_NM = '서울';

COMMIT;

-- [4] 수정 결과 검증 (선택 실행)
-- SELECT BRANCH_NM, DISTRICT_NM, COUNT(*) CNT
-- FROM TB_BLDG_RISK_STATIC
-- WHERE DISTRICT_NM IN ('도봉구', '강북구', '성북구', '노원구', '중랑구', '강동구', '송파구')
--   AND REGION_NM = '서울'
-- GROUP BY BRANCH_NM, DISTRICT_NM
-- ORDER BY DISTRICT_NM;
-- 기대 결과:
--   서울북부지사: 도봉구, 강북구, 성북구, 노원구, 중랑구
--   서울동부지사: 강동구, 송파구
