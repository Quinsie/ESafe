package egovframework.com.risk.service;

import java.util.List;
import java.util.Map;

import egovframework.com.risk.vo.RiskCombinedVO;
import egovframework.com.risk.vo.RiskFacilityHistoryVO;
import egovframework.com.risk.vo.RiskSearchVO;

public interface RiskCombinedService {

    List<RiskCombinedVO> selectCombinedList(RiskSearchVO searchVO);

    int selectCombinedListCnt(RiskSearchVO searchVO);

    RiskCombinedVO selectCombinedDetail(long bldgSeq);

    List<RiskFacilityHistoryVO> selectLatestFacilityHistory(long bldgSeq);

    Map<String, Object> selectFacilityHistoryDetail(String facilityType, long histSeq);

    List<RiskCombinedVO> selectGradeStats();

    List<RiskCombinedVO> selectHqSummary();

    List<RiskCombinedVO> selectBranchSummary();

    List<RiskCombinedVO> selectRegionSummary();

    List<RiskCombinedVO> selectRegionDistrictSummary();

    List<RiskCombinedVO> selectGradeChangedList();

    List<Map<String, Object>> selectDangerBuildingExportList(RiskSearchVO searchVO);

    List<Map<String, Object>> selectRiskMapDistrictLayer(String branchNm);

    List<Map<String, Object>> selectRiskMapBuildingLayer(
            String branchNm,
            Double minLon,
            Double minLat,
            Double maxLon,
            Double maxLat,
            List<String> riskCdList,
            Integer maxRows);
}
