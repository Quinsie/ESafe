package egovframework.com.risk.web;

import java.util.HashMap;
import java.util.Map;
import javax.annotation.Resource;
import javax.servlet.http.HttpServletResponse;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;

import egovframework.com.risk.service.WeatherUpdateService;

@RestController
public class WeatherUpdateController {

    @Resource(name = "weatherUpdateService")
    private WeatherUpdateService weatherUpdateService;
    @Resource(name = "riskWeatherController")
    private RiskWeatherController riskWeatherController;

    @Value("${risk.weather.refresh.allow-legacy-get:false}")
    private boolean allowLegacyGet;

    @RequestMapping(value = "/refreshWeatherData.do", method = RequestMethod.POST)
    public Map<String, Object> refreshWeatherData() {
        Map<String, Object> result = weatherUpdateService.updateWeatherData();
        if ("OK".equals(result.get("resultCode"))) {
            Map<String, Object> mapRefreshResult = riskWeatherController.refreshMapCachesNow(true, true, true);
            mapRefreshResult.put("landslideMapRefreshed", Boolean.valueOf(riskWeatherController.refreshLandslideMapCache()));
            result.put("mapRefresh", mapRefreshResult);
        }
        return result;
    }

    @RequestMapping(value = "/refreshWeatherData.do", method = RequestMethod.GET)
    public Map<String, Object> refreshWeatherDataLegacy(HttpServletResponse response) {
        if (allowLegacyGet) {
            return weatherUpdateService.updateWeatherData();
        }

        response.setStatus(HttpServletResponse.SC_METHOD_NOT_ALLOWED);

        Map<String, Object> result = new HashMap<String, Object>();
        result.put("resultCode", "FAIL");
        result.put("message", "GET method is disabled. Use POST /refreshWeatherData.do");
        return result;
    }
}
