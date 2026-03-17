package egovframework.com.risk.service.impl;

import java.util.List;
import java.util.Map;
import javax.annotation.Resource;

import egovframework.rte.fdl.cmmn.EgovAbstractServiceImpl;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.stereotype.Service;

import egovframework.com.risk.service.RiskWeatherService;
import egovframework.com.risk.vo.RiskSearchVO;
import egovframework.com.risk.vo.RiskWeatherVO;

/**
 * 기상특보 Service 구현체
 */
@Service("riskWeatherService")
public class RiskWeatherServiceImpl extends EgovAbstractServiceImpl implements RiskWeatherService {

    private static final String NAMESPACE = "RiskWeather.";

    @Resource(name = "sqlSession")
    private SqlSessionTemplate sqlSession;

    @Override
    public List<RiskWeatherVO> selectWeatherAlertToday() {
        return sqlSession.selectList(NAMESPACE + "selectWeatherAlertToday");
    }

    @Override
    public List<RiskWeatherVO> selectWeatherRiskScore(RiskSearchVO searchVO) {
        return sqlSession.selectList(NAMESPACE + "selectWeatherRiskScore", searchVO);
    }

    @Override
    public List<RiskWeatherVO> selectWeatherHistory(RiskSearchVO searchVO) {
        return sqlSession.selectList(NAMESPACE + "selectWeatherHistory", searchVO);
    }

    @Override
    public List<Map<String, Object>> selectBranchHqMap() {
        return sqlSession.selectList(NAMESPACE + "selectBranchHqMap");
    }
}
