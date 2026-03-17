package egovframework.com.risk.service;

import java.util.List;
import java.util.Map;
import egovframework.com.risk.vo.RiskSearchVO;
import egovframework.com.risk.vo.RiskWeatherVO;

/**
 * 기상특보 Service 인터페이스
 */
public interface RiskWeatherService {

    /** 당일 특보 현황 */
    List<RiskWeatherVO> selectWeatherAlertToday();

    /** 지역별 기상점수 */
    List<RiskWeatherVO> selectWeatherRiskScore(RiskSearchVO searchVO);

    /** 특보 이력 (일자별) */
    List<RiskWeatherVO> selectWeatherHistory(RiskSearchVO searchVO);

    List<Map<String, Object>> selectBranchHqMap();
}
