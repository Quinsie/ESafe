package egovframework.com.risk.service;

import java.util.Map;

/**
 * 기상특보 자동 수집/갱신 Service 인터페이스
 */
public interface WeatherUpdateService {

    /** 기상특보 수집 + 점수 계산 + DB 갱신 */
    Map<String, Object> updateWeatherData();
}
