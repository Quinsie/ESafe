package egovframework.com.risk.service.impl;

import java.io.BufferedReader;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import javax.annotation.Resource;
import javax.net.ssl.HttpsURLConnection;

import org.mybatis.spring.SqlSessionTemplate;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.interceptor.TransactionAspectSupport;

import egovframework.com.risk.service.WeatherUpdateService;
import egovframework.com.risk.vo.RiskWeatherVO;
import egovframework.rte.fdl.cmmn.EgovAbstractServiceImpl;

/**
 * Collect weather alerts from KMA API and update TB_WEATHER_ALERT / TB_WEATHER_RISK.
 */
@Service("weatherUpdateService")
public class WeatherUpdateServiceImpl extends EgovAbstractServiceImpl implements WeatherUpdateService {

    private static final Logger LOGGER = LoggerFactory.getLogger(WeatherUpdateServiceImpl.class);
    private static final AtomicBoolean UPDATE_RUNNING = new AtomicBoolean(false);

    private static final String API_URL = "https://apihub-pub.kma.go.kr/api/typ01/url/wrn_met_data.php";
    private static final String NAMESPACE = "WeatherUpdate.";
    private static final String ALERT_ZONE_FILE_PROPERTY = "risk.weather.alert.zone.file";
    private static final String ALERT_ZONE_FILE_ENV = "RISK_ALERT_ZONE_FILE";
    private static final String ALERT_ZONE_CLASSPATH = "egovframework/spring/alert-zones.csv";
    private static final String LOOKBACK_DAYS_PROPERTY = "kma.wrn.met.lookback.days";
    private static final int DEFAULT_LOOKBACK_DAYS = 30;
    private static final int WEATHER_API_CONNECT_TIMEOUT_MS = 15000;
    private static final int WEATHER_API_READ_TIMEOUT_MS = 30000;
    private static final int WEATHER_API_MAX_RETRIES = 3;
    private static final long WEATHER_API_RETRY_DELAY_MS = 1500L;
    private static final DateTimeFormatter KMA_TIME_FORMAT = DateTimeFormatter.ofPattern("yyyyMMddHHmm");
    private static final ZoneId KST_ZONE = ZoneId.of("Asia/Seoul");
    private static final String WILDFIRE_TEXT_API_URL = "https://apihub-pub.kma.go.kr/api/typ01/cgi-bin/sat/nph-sat_ana_txt";
    private static final int WILDFIRE_API_CONNECT_TIMEOUT_MS = 10000;
    private static final int WILDFIRE_API_READ_TIMEOUT_MS = 15000;
    private static final int WILDFIRE_FR_BACKTRACK_DAYS = 7;
    private static final int WILDFIRE_FF_BACKTRACK_STEPS = 6;
    private static final double WILDFIRE_KOREA_MIN_LON = 124.0d;
    private static final double WILDFIRE_KOREA_MAX_LON = 132.5d;
    private static final double WILDFIRE_KOREA_MIN_LAT = 32.5d;
    private static final double WILDFIRE_KOREA_MAX_LAT = 39.5d;
    private static final Pattern WILDFIRE_VALUE_SPLIT = Pattern.compile("[,\\s]+");
    private static final Pattern WILDFIRE_KV_PATTERN = Pattern.compile("(?im)^\\s*([a-zA-Z0-9_]+)\\s*[:=]\\s*(.*?)\\s*$");
    private static final Pattern WILDFIRE_VALUE_TOKEN_PATTERN = Pattern.compile("(?i)\\b(?:I\\d+|[-+]?\\d+(?:\\.\\d+)?)\\b");

    // Supported warning scores: advisory=2, warning-watch=6, warning=10
    private static final Map<String, Map<String, Integer>> WEATHER_SCORES = new HashMap<String, Map<String, Integer>>();
    static {
        Map<String, Integer> scoreMap = new HashMap<String, Integer>();
        scoreMap.put("예비", 2);
        scoreMap.put("주의보", 6);
        scoreMap.put("경보", 10);

        WEATHER_SCORES.put("호우", scoreMap);
        WEATHER_SCORES.put("태풍", scoreMap);
        WEATHER_SCORES.put("풍랑", scoreMap);
        WEATHER_SCORES.put("대설", scoreMap);
        WEATHER_SCORES.put("건조", scoreMap);
    }

    private static final String[] SUFFIXES = {"시", "도", "읍", "면", "리", "바다", "해역"};
    private static final String[] REGION_SUFFIXES = {"특별시", "광역시", "특별자치시", "특별자치도", "도"};

    // DB의 도 약칭 → KMA API 반환 전체 명칭 매핑
    private static final Map<String, String> REGION_ALIASES = new HashMap<String, String>();
    static {
        REGION_ALIASES.put("경북", "경상북도");
        REGION_ALIASES.put("경남", "경상남도");
        REGION_ALIASES.put("전북", "전라북도");
        REGION_ALIASES.put("전남", "전라남도");
        REGION_ALIASES.put("충북", "충청북도");
        REGION_ALIASES.put("충남", "충청남도");
    }

    // Mountain/coastal special zones that should map to specific districts.
    private static final Map<String, String> SPECIAL_ZONE_DISTRICT_EXPR = new HashMap<String, String>();
    static {
        SPECIAL_ZONE_DISTRICT_EXPR.put("강원북부산지", "속초시,인제군,고성군,양양군,양구군");
        SPECIAL_ZONE_DISTRICT_EXPR.put("강원중부산지", "강릉시,평창군,홍천군");
        SPECIAL_ZONE_DISTRICT_EXPR.put("강원남부산지", "동해시,삼척시,정선군");
        SPECIAL_ZONE_DISTRICT_EXPR.put("경북북동산지", "봉화군,영양군,울진군");
        SPECIAL_ZONE_DISTRICT_EXPR.put("전남동부남해안산지", "여수시,광양시,순천시");
    }

    @Resource(name = "sqlSession")
    private SqlSessionTemplate sqlSession;

    @org.springframework.beans.factory.annotation.Value("${risk.weather.alert.zone.file:}")
    private String alertZoneFile;

    private final Map<String, AlertZoneMapping> alertZoneByCode = new HashMap<String, AlertZoneMapping>();
    private final Map<String, AlertZoneMapping> alertZoneByName = new HashMap<String, AlertZoneMapping>();
    private volatile boolean alertZoneLoaded = false;

    @Override
    @Scheduled(cron = "0 0 * * * *", zone = "Asia/Seoul")
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> updateWeatherData() {
        LOGGER.info("=== Weather update started ===");

        Map<String, Object> result = new HashMap<String, Object>();
        if (!UPDATE_RUNNING.compareAndSet(false, true)) {
            result.put("resultCode", "SKIP");
            result.put("message", "Weather update is already running");
            result.put("resultMsg", "Weather update is already running");
            LOGGER.warn("Weather update skipped due to concurrent execution");
            return result;
        }

        try {
            String authKey = resolveAuthKey();
            List<Map<String, String>> rawAlerts = fetchWeatherAlerts(authKey);
            LOGGER.info("Fetched {} weather alerts", Integer.valueOf(rawAlerts.size()));

            sqlSession.delete(NAMESPACE + "deleteWeatherAlertToday");

            int alertCount = 0;
            for (Map<String, String> alert : rawAlerts) {
                RiskWeatherVO vo = new RiskWeatherVO();
                vo.setAlertType(alert.get("alertType"));
                vo.setAlertLevel(alert.get("alertLevel"));
                vo.setAlertCmd(alert.get("alertCmd"));
                vo.setRegionNm(alert.get("regionNm"));
                vo.setRegionCd(alert.get("regionCd"));
                vo.setParentRegion(alert.get("parentRegion"));
                vo.setIssueDt(alert.get("issueDt"));
                vo.setEffectDt(alert.get("effectDt"));
                sqlSession.insert(NAMESPACE + "insertWeatherAlert", vo);
                alertCount++;
            }

            List<RiskWeatherVO> regions = sqlSession.selectList(NAMESPACE + "selectDistinctRegions");
            List<Map<String, Object>> regionCoordinateStats = sqlSession.selectList(NAMESPACE + "selectRegionCoordinateStats");
            WildfireComputationResult wildfireResult = computeWildfireScores(authKey, regionCoordinateStats);
            sqlSession.delete(NAMESPACE + "deleteWeatherRiskToday");

            int scoreCount = 0;
            int wildfireRegionCount = 0;
            for (RiskWeatherVO region : regions) {
                List<String[]> matchedAlerts = findMatchingAlerts(
                        rawAlerts,
                        region.getRegionCd(),
                        region.getRegionNm(),
                        region.getDistrictNm());

                double weatherScore = 0.0d;
                String appliedAlerts = "";
                if (!matchedAlerts.isEmpty()) {
                    Object[] scoreResult = calculateWeatherScore(matchedAlerts);
                    weatherScore = ((Double) scoreResult[0]).doubleValue();
                    appliedAlerts = (String) scoreResult[1];
                }

                RiskWeatherVO riskVO = new RiskWeatherVO();
                riskVO.setRegionCd(nvl(region.getRegionCd()));
                riskVO.setRegionNm(region.getRegionNm());
                riskVO.setDistrictNm(region.getDistrictNm());
                riskVO.setWeatherScore(weatherScore);
                riskVO.setAppliedAlerts(appliedAlerts);
                String wildfireKey = buildWildfireRegionKey(
                        region.getRegionCd(),
                        region.getRegionNm(),
                        region.getDistrictNm());
                WildfireScore wildfireScore = wildfireResult.regionScoreByRegionKey.get(wildfireKey);
                if (wildfireScore != null) {
                    riskVO.setWildfireScore(wildfireScore.score);
                    riskVO.setWildfireGrade(wildfireScore.grade);
                    riskVO.setWildfireTm(wildfireScore.tm);
                    if (wildfireScore.score > 0d) {
                        wildfireRegionCount++;
                    }
                } else {
                    riskVO.setWildfireScore(0d);
                    riskVO.setWildfireGrade("NONE");
                    riskVO.setWildfireTm("");
                }
                sqlSession.insert(NAMESPACE + "insertWeatherRisk", riskVO);
                scoreCount++;
            }

            result.put("resultCode", "OK");
            result.put("alertCount", Integer.valueOf(alertCount));
            result.put("scoreRegionCount", Integer.valueOf(scoreCount));
            result.put("wildfireRegionCount", Integer.valueOf(wildfireRegionCount));
            result.put("wildfireFrTm", wildfireResult.frSourceTm);
            result.put("wildfireFfTm", wildfireResult.ffSourceTm);
            result.put("message", "Weather data refreshed");
            result.put("resultMsg", "Weather data refreshed");

            LOGGER.info("=== Weather update completed (alerts={}, regions={}, wildfire_regions={}, fr_tm={}, ff_tm={}) ===",
                    Integer.valueOf(alertCount),
                    Integer.valueOf(scoreCount),
                    Integer.valueOf(wildfireRegionCount),
                    wildfireResult.frSourceTm,
                    wildfireResult.ffSourceTm);
        } catch (Exception e) {
            LOGGER.error("Weather update failed", e);
            result.put("resultCode", "FAIL");
            result.put("message", "Weather update failed: " + e.getMessage());
            result.put("resultMsg", "Weather update failed: " + e.getMessage());
            try {
                TransactionAspectSupport.currentTransactionStatus().setRollbackOnly();
            } catch (Exception txEx) {
                LOGGER.warn("Transaction rollback marking failed", txEx);
            }
        } finally {
            UPDATE_RUNNING.set(false);
        }

        return result;
    }

    private List<Map<String, String>> fetchWeatherAlerts(String authKey) throws Exception {
        int lookbackDays = resolveLookbackDays();
        LocalDateTime now = LocalDateTime.now();
        String tmfc1 = now.minusDays(lookbackDays).format(KMA_TIME_FORMAT);
        String tmfc2 = now.plusDays(1).format(KMA_TIME_FORMAT);

        ensureAlertZoneLoaded();
        String urlStr = buildWeatherApiUrl(authKey, tmfc1, tmfc2);

        Exception lastException = null;
        for (int attempt = 1; attempt <= WEATHER_API_MAX_RETRIES; attempt++) {
            try {
                Map<String, MetAlertRecord> latestByKey = fetchLatestByKey(urlStr);
                return toAlertList(latestByKey);
            } catch (Exception e) {
                lastException = e;
                if (!isTimeoutException(e) || attempt >= WEATHER_API_MAX_RETRIES) {
                    throw e;
                }
                LOGGER.warn("KMA alert API timeout (attempt {}/{}). Retrying in {}ms. url={}",
                        Integer.valueOf(attempt),
                        Integer.valueOf(WEATHER_API_MAX_RETRIES),
                        Long.valueOf(WEATHER_API_RETRY_DELAY_MS),
                        maskAuthKey(urlStr));
                try {
                    Thread.sleep(WEATHER_API_RETRY_DELAY_MS * attempt);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    throw new IOException("Interrupted while waiting to retry KMA alert API", ie);
                }
            }
        }

        if (lastException != null) {
            throw lastException;
        }
        throw new IllegalStateException("Unknown error while fetching weather alerts from KMA API");
    }

    private String buildWeatherApiUrl(String authKey, String tmfc1, String tmfc2) {
        // wrn_met_data returns warning command history. Build active warnings by taking latest command per (region, type).
        return API_URL
                + "?reg=0&wrn=A"
                + "&tmfc1=" + tmfc1
                + "&tmfc2=" + tmfc2
                + "&disp=0&help=0"
                + "&authKey=" + authKey;
    }

    private Map<String, MetAlertRecord> fetchLatestByKey(String urlStr) throws Exception {
        URL url = new URL(urlStr);
        HttpsURLConnection conn = (HttpsURLConnection) url.openConnection();
        conn.setRequestMethod("GET");
        conn.setConnectTimeout(WEATHER_API_CONNECT_TIMEOUT_MS);
        conn.setReadTimeout(WEATHER_API_READ_TIMEOUT_MS);

        Map<String, MetAlertRecord> latestByKey = new HashMap<String, MetAlertRecord>();
        try {
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(conn.getInputStream(), Charset.forName("EUC-KR")))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    line = line.trim();
                    if (line.isEmpty() || line.startsWith("#")) {
                        continue;
                    }

                    String[] parts = line.split(",", -1);
                    if (parts.length < 11) {
                        continue;
                    }

                    String issueDt = parts[0].trim();
                    String effectDt = parts[1].trim();
                    String inputDt = parts[2].trim();
                    String regionCd = parts[4].trim();
                    String wrnCode = parts[5].trim();
                    String levelCode = parts[6].trim();
                    String commandCode = parts[7].trim();
                    String cnt = parts[9].trim();

                    if (isBlank(regionCd) || isBlank(wrnCode)) {
                        continue;
                    }
                    if (!isBlank(cnt) && !"4".equals(cnt)) {
                        continue;
                    }

                    String key = regionCd + "|" + wrnCode;
                    MetAlertRecord candidate = new MetAlertRecord(
                            regionCd, wrnCode, levelCode, commandCode, issueDt, effectDt, inputDt);
                    MetAlertRecord current = latestByKey.get(key);
                    if (current == null || candidate.isLaterThan(current)) {
                        latestByKey.put(key, candidate);
                    }
                }
            }
        } finally {
            conn.disconnect();
        }
        return latestByKey;
    }

    private List<Map<String, String>> toAlertList(Map<String, MetAlertRecord> latestByKey) {
        List<Map<String, String>> alerts = new ArrayList<Map<String, String>>();
        for (MetAlertRecord record : latestByKey.values()) {
            if (!isActiveCommand(record.commandCode)) {
                continue;
            }

            AlertZoneMapping mapping = alertZoneByCode.get(record.regionCd);
            String regionNm = mapping != null && !isBlank(mapping.name) ? mapping.name : record.regionCd;
            String parentRegion = mapping != null ? mapping.regionNm : "";

            Map<String, String> alert = new HashMap<String, String>();
            alert.put("regionNm", regionNm);
            alert.put("regionCd", record.regionCd);
            alert.put("alertType", normalizeWarningType(record.warningCode));
            alert.put("alertLevel", normalizeAlertLevel(record.levelCode));
            alert.put("alertCmd", normalizeAlertCommand(record.commandCode));
            alert.put("parentRegion", parentRegion);
            alert.put("issueDt", record.issueDt);
            alert.put("effectDt", record.effectDt);
            alerts.add(alert);
        }

        return alerts;
    }

    private WildfireComputationResult computeWildfireScores(String authKey, List<Map<String, Object>> regionCoordinateStats) {
        WildfireComputationResult result = new WildfireComputationResult();
        if (regionCoordinateStats == null || regionCoordinateStats.isEmpty()) {
            return result;
        }

        WildfireGridData frGrid = fetchWildfireRiskGrid(authKey);
        WildfireGridData ffGrid = fetchWildfireDetectionGrid(authKey);
        result.frSourceTm = frGrid != null ? frGrid.tm : "";
        result.ffSourceTm = ffGrid != null ? ffGrid.tm : "";

        for (Map<String, Object> row : regionCoordinateStats) {
            String regionCd = mapString(row, "regionCd");
            String regionNm = mapString(row, "regionNm");
            String districtNm = mapString(row, "districtNm");
            String regionKey = buildWildfireRegionKey(regionCd, regionNm, districtNm);
            if (isBlank(regionKey)) {
                continue;
            }

            List<GeoPoint> samplePoints = buildRegionSamplePoints(row);
            if (samplePoints.isEmpty()) {
                continue;
            }
            int maxScore = 0;
            String bestTm = "";
            List<Integer> sampledScores = new ArrayList<Integer>();

            for (GeoPoint point : samplePoints) {
                String frToken = frGrid != null ? frGrid.tokenAt(point.lon, point.lat) : "";
                String ffToken = ffGrid != null ? ffGrid.tokenAt(point.lon, point.lat) : "";
                int frScore = frGrid != null ? scoreFromFrToken(frToken) : 0;
                int ffScore = ffGrid != null ? scoreFromFfToken(ffToken) : 0;

                int pointScore = Math.max(frScore, ffScore);
                sampledScores.add(Integer.valueOf(pointScore));
                if (pointScore > maxScore) {
                    maxScore = pointScore;
                    bestTm = ffScore >= frScore
                            ? (ffGrid != null ? ffGrid.tm : "")
                            : (frGrid != null ? frGrid.tm : "");
                }
            }

            int regionScore = maxScore;
            // Stabilized mode example (kept for future activation):
            // int regionScore = calculateStableWildfireScore(sampledScores, maxScore);

            WildfireScore score = new WildfireScore(
                    (double) regionScore,
                    wildfireGrade(regionScore),
                    bestTm);
            result.regionScoreByRegionKey.put(regionKey, score);
        }

        return result;
    }

    private WildfireGridData fetchWildfireRiskGrid(String authKey) {
        List<String> tmCandidates = buildWildfireFrTmCandidates();
        for (String tm : tmCandidates) {
            String url = buildWildfireTextUrl(authKey, tm, "fr", "");
            try {
                String payload = fetchHttpText(url, WEATHER_API_READ_TIMEOUT_MS);
                WildfireGridData data = parseWildfireGridData(payload, tm, "fr");
                if (data != null) {
                    return data;
                }
            } catch (Exception e) {
                LOGGER.warn("wildfire fr fetch failed tm={} url={} msg={}",
                        tm, maskAuthKey(url), e.getMessage());
            }

            String datUrl = buildWildfireTextUrl(authKey, tm, "", "fr");
            try {
                String payloadDat = fetchHttpText(datUrl, WEATHER_API_READ_TIMEOUT_MS);
                WildfireGridData datData = parseWildfireGridData(payloadDat, tm, "dat=fr");
                if (datData != null) {
                    return datData;
                }
            } catch (Exception e) {
                LOGGER.warn("wildfire fr(dat) fetch failed tm={} url={} msg={}",
                        tm, maskAuthKey(datUrl), e.getMessage());
            }
        }
        return null;
    }

    private WildfireGridData fetchWildfireDetectionGrid(String authKey) {
        List<String> tmCandidates = buildWildfireFfTmCandidates();
        for (String tm : tmCandidates) {
            String obsUrl = buildWildfireTextUrl(authKey, tm, "ff", "");
            try {
                String payloadObs = fetchHttpText(obsUrl, WILDFIRE_API_READ_TIMEOUT_MS);
                WildfireGridData obsData = parseWildfireGridData(payloadObs, tm, "obs=ff");
                if (obsData != null) {
                    return obsData;
                }
            } catch (Exception e) {
                LOGGER.warn("wildfire ff(obs) fetch failed tm={} url={} msg={}",
                        tm, maskAuthKey(obsUrl), e.getMessage());
            }

            String datUrl = buildWildfireTextUrl(authKey, tm, "", "ff");
            try {
                String payloadDat = fetchHttpText(datUrl, WILDFIRE_API_READ_TIMEOUT_MS);
                WildfireGridData datData = parseWildfireGridData(payloadDat, tm, "dat=ff");
                if (datData != null) {
                    return datData;
                }
            } catch (Exception e) {
                LOGGER.warn("wildfire ff(dat) fetch failed tm={} url={} msg={}",
                        tm, maskAuthKey(datUrl), e.getMessage());
            }
        }
        return null;
    }

    private List<String> buildWildfireFrTmCandidates() {
        List<String> candidates = new ArrayList<String>();
        LocalDateTime nowKst = LocalDateTime.now(KST_ZONE);
        LocalDateTime latestRun = nowKst.withHour(9).withMinute(0).withSecond(0).withNano(0);
        if (nowKst.isBefore(latestRun)) {
            latestRun = latestRun.minusDays(1);
        }
        for (int i = 0; i < WILDFIRE_FR_BACKTRACK_DAYS; i++) {
            candidates.add(latestRun.minusDays(i).format(KMA_TIME_FORMAT));
        }
        return candidates;
    }

    private List<String> buildWildfireFfTmCandidates() {
        List<String> candidates = new ArrayList<String>();
        LocalDateTime nowKst = LocalDateTime.now(KST_ZONE).minusMinutes(20);
        int flooredMinute = (nowKst.getMinute() / 10) * 10;
        LocalDateTime base = nowKst.withMinute(flooredMinute).withSecond(0).withNano(0);
        for (int i = 0; i < WILDFIRE_FF_BACKTRACK_STEPS; i++) {
            candidates.add(base.minusMinutes(i * 10L).format(KMA_TIME_FORMAT));
        }
        return candidates;
    }

    private String buildWildfireTextUrl(String authKey, String tm, String obs, String dat) {
        StringBuilder sb = new StringBuilder(WILDFIRE_TEXT_API_URL);
        sb.append("?tm=").append(tm);
        if (!isBlank(obs)) {
            sb.append("&obs=").append(obs);
        }
        if (!isBlank(dat)) {
            sb.append("&dat=").append(dat);
        }
        sb.append("&help=0");
        sb.append("&authKey=").append(authKey);
        return sb.toString();
    }

    private String fetchHttpText(String urlStr, int readTimeoutMs) throws Exception {
        URL url = new URL(urlStr);
        HttpsURLConnection conn = (HttpsURLConnection) url.openConnection();
        conn.setRequestMethod("GET");
        conn.setConnectTimeout(WILDFIRE_API_CONNECT_TIMEOUT_MS);
        conn.setReadTimeout(readTimeoutMs);
        try {
            int status = conn.getResponseCode();
            InputStream stream = status >= 200 && status < 300 ? conn.getInputStream() : conn.getErrorStream();
            if (stream == null) {
                return "";
            }
            try (InputStream in = stream) {
                byte[] payload = readAll(in);
                if (payload.length == 0) {
                    return "";
                }
                String text = new String(payload, StandardCharsets.UTF_8);
                if (text.indexOf('\uFFFD') >= 0) {
                    text = new String(payload, Charset.forName("EUC-KR"));
                }
                return text;
            }
        } finally {
            conn.disconnect();
        }
    }

    private byte[] readAll(InputStream stream) throws IOException {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        byte[] buffer = new byte[4096];
        int read;
        while ((read = stream.read(buffer)) != -1) {
            out.write(buffer, 0, read);
        }
        return out.toByteArray();
    }

    private WildfireGridData parseWildfireGridData(String rawText, String tm, String sourceType) {
        if (isBlank(rawText)) {
            return null;
        }
        String loweredText = rawText.toLowerCase(Locale.ROOT);
        if (loweredText.contains("err=-1") || loweredText.startsWith("err")) {
            return null;
        }

        Map<String, String> kv = new HashMap<String, String>();
        Matcher kvMatcher = WILDFIRE_KV_PATTERN.matcher(rawText);
        while (kvMatcher.find()) {
            String key = nvl(kvMatcher.group(1)).trim().toLowerCase(Locale.ROOT);
            String value = nvl(kvMatcher.group(2)).trim();
            if (!isBlank(key) && !isBlank(value)) {
                kv.put(key, value);
            }
        }

        int nx = parseIntSafe(kv.get("nx"));
        int ny = parseIntSafe(kv.get("ny"));
        int expected = nx * ny;
        List<String> values = parseWildfireValues(rawText);
        if (values.isEmpty()) {
            values = parseWildfireValuesFallback(rawText, expected);
        }
        if (values.isEmpty()) {
            return null;
        }

        if (nx <= 0 || ny <= 0 || expected <= 0) {
            int inferredNx = (int) Math.round(Math.sqrt(values.size()));
            nx = inferredNx > 0 ? inferredNx : values.size();
            ny = nx > 0 ? Math.max(1, values.size() / nx) : 1;
            expected = nx * ny;
        }
        if (expected <= 0 || values.size() < expected) {
            return null;
        }

        double[] bounds = resolveWildfireBounds(kv);
        return new WildfireGridData(nx, ny, values, bounds[0], bounds[1], bounds[2], bounds[3], tm, sourceType);
    }

    private List<String> parseWildfireValues(String rawText) {
        String text = nvl(rawText);
        Matcher valueMatcher = Pattern.compile("(?is)\\b(?:value|values|val|data|output|result)\\b\\s*[:=]\\s*(.*)$").matcher(text);
        if (!valueMatcher.find()) {
            return new ArrayList<String>();
        }
        String valueBlob = nvl(valueMatcher.group(1)).trim();
        if (isBlank(valueBlob)) {
            return new ArrayList<String>();
        }

        String[] tokens = WILDFIRE_VALUE_SPLIT.split(valueBlob);
        List<String> values = new ArrayList<String>();
        for (String token : tokens) {
            String trimmed = nvl(token).trim();
            if (!isBlank(trimmed)) {
                values.add(trimmed);
            }
        }
        return values;
    }

    private List<String> parseWildfireValuesFallback(String rawText, int expectedCount) {
        List<String> tokens = new ArrayList<String>();
        Matcher matcher = WILDFIRE_VALUE_TOKEN_PATTERN.matcher(nvl(rawText));
        while (matcher.find()) {
            String token = nvl(matcher.group()).trim();
            if (isBlank(token)) {
                continue;
            }
            tokens.add(token);
        }
        if (tokens.isEmpty()) {
            return tokens;
        }
        if (expectedCount > 0 && tokens.size() > expectedCount) {
            return new ArrayList<String>(tokens.subList(tokens.size() - expectedCount, tokens.size()));
        }
        return tokens;
    }

    private double[] resolveWildfireBounds(Map<String, String> kv) {
        double x1 = parseDoubleSafe(kv.get("x1"));
        double x2 = parseDoubleSafe(kv.get("x2"));
        double x3 = parseDoubleSafe(kv.get("x3"));
        double x4 = parseDoubleSafe(kv.get("x4"));
        double y1 = parseDoubleSafe(kv.get("y1"));
        double y2 = parseDoubleSafe(kv.get("y2"));
        double y3 = parseDoubleSafe(kv.get("y3"));
        double y4 = parseDoubleSafe(kv.get("y4"));

        double minLon = minValid(x1, x2, x3, x4);
        double maxLon = maxValid(x1, x2, x3, x4);
        double minLat = minValid(y1, y2, y3, y4);
        double maxLat = maxValid(y1, y2, y3, y4);
        if (maxLon <= minLon || maxLat <= minLat || !isSupportedWildfireBounds(minLon, maxLon, minLat, maxLat)) {
            return new double[] {
                    WILDFIRE_KOREA_MIN_LON, WILDFIRE_KOREA_MAX_LON,
                    WILDFIRE_KOREA_MIN_LAT, WILDFIRE_KOREA_MAX_LAT
            };
        }
        return new double[] { minLon, maxLon, minLat, maxLat };
    }

    private boolean isSupportedWildfireBounds(double minLon, double maxLon, double minLat, double maxLat) {
        return isPlausibleKoreaBounds(minLon, maxLon, minLat, maxLat)
                || isPlausibleProjectedBounds(minLon, maxLon, minLat, maxLat);
    }

    private boolean isPlausibleKoreaBounds(double minLon, double maxLon, double minLat, double maxLat) {
        if (Double.isNaN(minLon) || Double.isNaN(maxLon) || Double.isNaN(minLat) || Double.isNaN(maxLat)) {
            return false;
        }
        if (minLon < 120.0d || maxLon > 136.0d || minLat < 30.0d || maxLat > 42.0d) {
            return false;
        }
        if ((maxLon - minLon) < 2.0d || (maxLat - minLat) < 2.0d) {
            return false;
        }
        return true;
    }

    private boolean isPlausibleProjectedBounds(double minX, double maxX, double minY, double maxY) {
        if (Double.isNaN(minX) || Double.isNaN(maxX) || Double.isNaN(minY) || Double.isNaN(maxY)) {
            return false;
        }
        if (minX < -100000d || maxX > 1000000d || minY < -100000d || maxY > 1200000d) {
            return false;
        }
        if ((maxX - minX) < 10000d || (maxY - minY) < 10000d) {
            return false;
        }
        return true;
    }

    private List<GeoPoint> buildRegionSamplePoints(Map<String, Object> row) {
        List<GeoPoint> points = new ArrayList<GeoPoint>();
        addRawAndNormalizedPoint(points, mapDouble(row, "avgLon"), mapDouble(row, "avgLat"));
        addRawAndNormalizedPoint(points, mapDouble(row, "minLon"), mapDouble(row, "minLat"));
        addRawAndNormalizedPoint(points, mapDouble(row, "minLon"), mapDouble(row, "maxLat"));
        addRawAndNormalizedPoint(points, mapDouble(row, "maxLon"), mapDouble(row, "minLat"));
        addRawAndNormalizedPoint(points, mapDouble(row, "maxLon"), mapDouble(row, "maxLat"));
        return points;
    }

    private void addRawAndNormalizedPoint(List<GeoPoint> points, double rawLon, double rawLat) {
        // Raw DB coordinates can be projected (e.g. EPSG:5186). Only sample raw values when they are valid WGS84.
        if (isValidWgs84(rawLon, rawLat)) {
            addPoint(points, new GeoPoint(rawLon, rawLat));
        }
        addPoint(points, normalizeGeoPoint(rawLon, rawLat));
    }

    private void addPoint(List<GeoPoint> points, GeoPoint point) {
        if (point == null) {
            return;
        }
        for (GeoPoint existing : points) {
            if (Math.abs(existing.lon - point.lon) < 1.0e-8d && Math.abs(existing.lat - point.lat) < 1.0e-8d) {
                return;
            }
        }
        points.add(point);
    }

    private GeoPoint normalizeGeoPoint(double rawLon, double rawLat) {
        if (isValidWgs84(rawLon, rawLat)) {
            return new GeoPoint(rawLon, rawLat);
        }
        if (isLikelyEpsg5186(rawLon, rawLat)) {
            GeoPoint converted = toWgs84FromEpsg5186(rawLon, rawLat);
            if (converted != null && isValidWgs84(converted.lon, converted.lat)) {
                return converted;
            }
        }
        return null;
    }

    private boolean isValidWgs84(double lon, double lat) {
        return lon >= WILDFIRE_KOREA_MIN_LON && lon <= WILDFIRE_KOREA_MAX_LON
                && lat >= WILDFIRE_KOREA_MIN_LAT && lat <= WILDFIRE_KOREA_MAX_LAT;
    }

    private boolean isLikelyEpsg5186(double x, double y) {
        return x > 50000d && x < 450000d && y > 100000d && y < 800000d;
    }

    private GeoPoint toWgs84FromEpsg5186(double x, double y) {
        final double a = 6378137.0d;
        final double f = 1.0d / 298.257222101d;
        final double e2 = 2 * f - (f * f);
        final double ep2 = e2 / (1.0d - e2);
        final double k0 = 1.0d;
        final double lon0 = Math.toRadians(127.0d);
        final double lat0 = Math.toRadians(38.0d);
        final double falseEasting = 200000.0d;
        final double falseNorthing = 600000.0d;

        double m0 = meridionalArc(a, e2, lat0);
        double m = m0 + (y - falseNorthing) / k0;
        double mu = m / (a * (1.0d - e2 / 4.0d - 3.0d * Math.pow(e2, 2) / 64.0d - 5.0d * Math.pow(e2, 3) / 256.0d));

        double e1 = (1.0d - Math.sqrt(1.0d - e2)) / (1.0d + Math.sqrt(1.0d - e2));
        double j1 = 3.0d * e1 / 2.0d - 27.0d * Math.pow(e1, 3) / 32.0d;
        double j2 = 21.0d * Math.pow(e1, 2) / 16.0d - 55.0d * Math.pow(e1, 4) / 32.0d;
        double j3 = 151.0d * Math.pow(e1, 3) / 96.0d;
        double j4 = 1097.0d * Math.pow(e1, 4) / 512.0d;
        double fp = mu
                + j1 * Math.sin(2.0d * mu)
                + j2 * Math.sin(4.0d * mu)
                + j3 * Math.sin(6.0d * mu)
                + j4 * Math.sin(8.0d * mu);

        double sinFp = Math.sin(fp);
        double cosFp = Math.cos(fp);
        double tanFp = Math.tan(fp);
        double n1 = a / Math.sqrt(1.0d - e2 * sinFp * sinFp);
        double r1 = a * (1.0d - e2) / Math.pow(1.0d - e2 * sinFp * sinFp, 1.5d);
        double c1 = ep2 * cosFp * cosFp;
        double t1 = tanFp * tanFp;
        double d = (x - falseEasting) / (n1 * k0);

        double q1 = d * d / 2.0d;
        double q2 = (5.0d + 3.0d * t1 + 10.0d * c1 - 4.0d * c1 * c1 - 9.0d * ep2) * Math.pow(d, 4) / 24.0d;
        double q3 = (61.0d + 90.0d * t1 + 298.0d * c1 + 45.0d * t1 * t1 - 252.0d * ep2 - 3.0d * c1 * c1)
                * Math.pow(d, 6) / 720.0d;
        double lat = fp - (n1 * tanFp / r1) * (q1 - q2 + q3);

        double q4 = d;
        double q5 = (1.0d + 2.0d * t1 + c1) * Math.pow(d, 3) / 6.0d;
        double q6 = (5.0d - 2.0d * c1 + 28.0d * t1 - 3.0d * c1 * c1 + 8.0d * ep2 + 24.0d * t1 * t1)
                * Math.pow(d, 5) / 120.0d;
        double lon = lon0 + (q4 - q5 + q6) / cosFp;

        return new GeoPoint(Math.toDegrees(lon), Math.toDegrees(lat));
    }

    private double meridionalArc(double a, double e2, double lat) {
        return a * ((1.0d - e2 / 4.0d - 3.0d * Math.pow(e2, 2) / 64.0d - 5.0d * Math.pow(e2, 3) / 256.0d) * lat
                - (3.0d * e2 / 8.0d + 3.0d * Math.pow(e2, 2) / 32.0d + 45.0d * Math.pow(e2, 3) / 1024.0d) * Math.sin(2.0d * lat)
                + (15.0d * Math.pow(e2, 2) / 256.0d + 45.0d * Math.pow(e2, 3) / 1024.0d) * Math.sin(4.0d * lat)
                - (35.0d * Math.pow(e2, 3) / 3072.0d) * Math.sin(6.0d * lat));
    }

    private int scoreFromFrToken(String token) {
        String normalized = nvl(token).trim();
        if (isBlank(normalized)) {
            return 0;
        }
        String upper = normalized.toUpperCase(Locale.ROOT);
        if ("I2".equals(upper)) {
            return 10;
        }
        if (upper.contains("SEVERE") || upper.contains("HIGH") || normalized.contains("심각")) {
            return 8;
        }
        if (upper.contains("WARNING") || normalized.contains("경계")) {
            return 6;
        }
        if (upper.contains("CAUTION") || normalized.contains("주의")) {
            return 4;
        }
        if (upper.contains("INTEREST") || normalized.contains("관심")) {
            return 2;
        }

        Double numeric = parseNumeric(normalized);
        if (numeric == null) {
            return 0;
        }
        double value = numeric.doubleValue();
        if (value <= 0d || value == 255d || value == 9999d || value == -9999d) {
            return 0;
        }
        // KMA wildfire risk(fr) official ranges:
        // 0~25: interest, 25~50: caution, 50~75: warning, 75~100: severe, >100: not used.
        if (value < 25d) {
            return 2;
        }
        if (value < 50d) {
            return 4;
        }
        if (value < 75d) {
            return 6;
        }
        if (value <= 100d) {
            return 8;
        }
        return 0;
    }

    private int scoreFromFfToken(String token) {
        String normalized = nvl(token).trim();
        if (isBlank(normalized)) {
            return 0;
        }
        String upper = normalized.toUpperCase(Locale.ROOT);
        if ("I2".equals(upper)) {
            return 10;
        }
        if ("0".equals(upper) || "NONE".equals(upper) || "-".equals(upper)) {
            return 0;
        }
        Double numeric = parseNumeric(normalized);
        if (numeric != null) {
            double value = numeric.doubleValue();
            if (value <= 0d || value == 255d || value == 9999d || value == -9999d) {
                return 0;
            }
            return 10;
        }
        return 10;
    }

    private String wildfireGrade(int score) {
        if (score >= 10) return "DETECTED";
        if (score >= 8) return "SEVERE";
        if (score >= 6) return "WARNING";
        if (score >= 4) return "CAUTION";
        if (score >= 2) return "INTEREST";
        return "NONE";
    }

    private Double parseNumeric(String token) {
        try {
            return Double.valueOf(Double.parseDouble(token));
        } catch (Exception ignore) {
            return null;
        }
    }

    private int parseIntSafe(String value) {
        try {
            return Integer.parseInt(nvl(value).trim());
        } catch (Exception e) {
            return 0;
        }
    }

    private double parseDoubleSafe(String value) {
        try {
            return Double.parseDouble(nvl(value).trim());
        } catch (Exception e) {
            return Double.NaN;
        }
    }

    private String buildWildfireRegionKey(String regionCd, String regionNm, String districtNm) {
        String region = nvl(regionNm).trim();
        String district = nvl(districtNm).trim();
        // Prioritize 시/군/구 granularity whenever available.
        if (!isBlank(region) || !isBlank(district)) {
            return "NM:" + region + "|" + district;
        }
        String cd = nvl(regionCd).trim();
        if (!isBlank(cd)) {
            return "CD:" + cd;
        }
        return "";
    }

    private double mapDouble(Map<String, Object> row, String key) {
        if (row == null) {
            return Double.NaN;
        }
        Object value = row.get(key);
        if (value == null) {
            value = row.get(key.toUpperCase(Locale.ROOT));
        }
        if (value instanceof Number) {
            return ((Number) value).doubleValue();
        }
        if (value == null) {
            return Double.NaN;
        }
        try {
            return Double.parseDouble(String.valueOf(value));
        } catch (Exception e) {
            return Double.NaN;
        }
    }

    private double minValid(double a, double b, double c, double d) {
        double min = Double.POSITIVE_INFINITY;
        if (!Double.isNaN(a)) min = Math.min(min, a);
        if (!Double.isNaN(b)) min = Math.min(min, b);
        if (!Double.isNaN(c)) min = Math.min(min, c);
        if (!Double.isNaN(d)) min = Math.min(min, d);
        return min == Double.POSITIVE_INFINITY ? Double.NaN : min;
    }

    private double maxValid(double a, double b, double c, double d) {
        double max = Double.NEGATIVE_INFINITY;
        if (!Double.isNaN(a)) max = Math.max(max, a);
        if (!Double.isNaN(b)) max = Math.max(max, b);
        if (!Double.isNaN(c)) max = Math.max(max, c);
        if (!Double.isNaN(d)) max = Math.max(max, d);
        return max == Double.NEGATIVE_INFINITY ? Double.NaN : max;
    }

    private boolean isTimeoutException(Throwable e) {
        Throwable cursor = e;
        while (cursor != null) {
            if (cursor instanceof SocketTimeoutException) {
                return true;
            }
            cursor = cursor.getCause();
        }
        return false;
    }

    private String maskAuthKey(String url) {
        if (isBlank(url)) {
            return "";
        }
        int keyStart = url.indexOf("authKey=");
        if (keyStart < 0) {
            return url;
        }
        int valueStart = keyStart + "authKey=".length();
        int valueEnd = url.indexOf('&', valueStart);
        if (valueEnd < 0) {
            valueEnd = url.length();
        }
        return url.substring(0, valueStart) + "***" + url.substring(valueEnd);
    }

    private int resolveLookbackDays() {
        String raw = System.getProperty(LOOKBACK_DAYS_PROPERTY);
        if (isBlank(raw)) {
            return DEFAULT_LOOKBACK_DAYS;
        }
        try {
            int parsed = Integer.parseInt(raw.trim());
            if (parsed < 1 || parsed > 365) {
                LOGGER.warn("{} must be between 1 and 365. Using default {}.",
                        LOOKBACK_DAYS_PROPERTY, Integer.valueOf(DEFAULT_LOOKBACK_DAYS));
                return DEFAULT_LOOKBACK_DAYS;
            }
            return parsed;
        } catch (NumberFormatException e) {
            LOGGER.warn("Invalid {}='{}'. Using default {}.",
                    LOOKBACK_DAYS_PROPERTY, raw, Integer.valueOf(DEFAULT_LOOKBACK_DAYS));
            return DEFAULT_LOOKBACK_DAYS;
        }
    }

    private String resolveAuthKey() {
        String byProperty = System.getProperty("kma.auth.key");
        if (byProperty != null && !byProperty.trim().isEmpty()) {
            return byProperty.trim();
        }

        String byEnv = System.getenv("KMA_AUTH_KEY");
        if (byEnv != null && !byEnv.trim().isEmpty()) {
            return byEnv.trim();
        }

        throw new IllegalStateException("KMA auth key is not configured. Set -Dkma.auth.key or KMA_AUTH_KEY.");
    }

    private List<String[]> findMatchingAlerts(List<Map<String, String>> rawAlerts, String regionCd, String regionNm, String districtNm) {
        List<String[]> matched = new ArrayList<String[]>();

        for (Map<String, String> alert : rawAlerts) {
            String alertRegion = nvl(alert.get("regionNm"));
            String alertRegionCd = nvl(alert.get("regionCd"));
            String parentRegion = nvl(alert.get("parentRegion"));
            String normalized = normalizeRegionName(alertRegion);

            boolean isMatch = false;

            if (!isBlank(regionCd) && regionCd.equals(alertRegionCd)) {
                isMatch = true;
            }

            if (!isMatch && isMappedAlertMatch(alertRegionCd, alertRegion, regionNm, districtNm)) {
                isMatch = true;
            }

            if (!isMatch && !isBlank(regionNm)) {
                boolean regionMatched = false;
                if (parentRegion.contains(regionNm) || alertRegion.contains(regionNm)) {
                    regionMatched = true;
                }
                // 도 약칭(경북, 경남 등) → 전체 명칭(경상북도, 경상남도 등)으로 확장 매칭
                if (!regionMatched) {
                    String fullRegionNm = REGION_ALIASES.get(regionNm);
                    if (fullRegionNm != null
                            && (parentRegion.contains(fullRegionNm) || alertRegion.contains(fullRegionNm))) {
                        regionMatched = true;
                    }
                }

                if (regionMatched && isBlank(districtNm)) {
                    isMatch = true;
                }

                if (regionMatched && !isBlank(districtNm)) {
                    if (alertRegion.contains(districtNm) || normalized.contains(districtNm)) {
                        isMatch = true;
                    }

                    String shortDistrict = districtNm.replaceAll("[시군구]$", "");
                    if (!isMatch && shortDistrict.length() >= 2
                            && (alertRegion.contains(shortDistrict) || normalized.contains(shortDistrict))) {
                        isMatch = true;
                    }
                }
            }

            if (isMatch) {
                matched.add(new String[] { alert.get("alertType"), alert.get("alertLevel") });
            }
        }

        return matched;
    }

    private boolean isMappedAlertMatch(String alertRegionCd, String alertRegionNm, String regionNm, String districtNm) {
        ensureAlertZoneLoaded();

        AlertZoneMapping mapping = null;
        if (!isBlank(alertRegionCd)) {
            mapping = alertZoneByCode.get(alertRegionCd.trim());
        }
        if (mapping == null && !isBlank(alertRegionNm)) {
            mapping = alertZoneByName.get(alertRegionNm.trim());
        }
        if (mapping == null) {
            return false;
        }

        String targetRegion = normalizeRegionUnit(regionNm);
        String mappedRegion = normalizeRegionUnit(mapping.regionNm);
        if (!isBlank(targetRegion) && !isBlank(mappedRegion)
                && !targetRegion.equals(mappedRegion)
                && !mappedRegion.contains(targetRegion)
                && !targetRegion.contains(mappedRegion)) {
            return false;
        }

        String zoneName = nvl(mapping.name).trim();
        String districtExpr = nvl(mapping.districtExpr).trim();
        if (districtExpr.isEmpty()) {
            districtExpr = resolveSpecialDistrictExpr(zoneName);
        }
        if (districtExpr.contains("전역")) {
            return true;
        }

        if (isBlank(districtNm)) {
            return true;
        }

        if (matchesDistrict(districtExpr, districtNm)) {
            return true;
        }

        if (matchesDistrict(zoneName, districtNm)) {
            return true;
        }
        if (matchesDistrict(normalizeRegionName(zoneName), districtNm)) {
            return true;
        }

        // If no district expression is provided and zone name equals parent region unit,
        // treat it as a region-wide alert.
        String zoneRegion = normalizeRegionUnit(zoneName);
        if (districtExpr.isEmpty() && !isBlank(zoneRegion) && zoneRegion.equals(mappedRegion)) {
            return true;
        }

        return false;
    }

    private String resolveSpecialDistrictExpr(String zoneName) {
        String key = nvl(zoneName).replaceAll("\\s+", "");
        return nvl(SPECIAL_ZONE_DISTRICT_EXPR.get(key));
    }

    private boolean matchesDistrict(String source, String districtNm) {
        String src = nvl(source).trim();
        String targetDistrict = nvl(districtNm).trim();
        if (isBlank(src) || isBlank(targetDistrict)) {
            return false;
        }
        if (src.contains(targetDistrict)) {
            return true;
        }
        String shortDistrict = targetDistrict.replaceAll("[시군구]$", "");
        return shortDistrict.length() >= 2 && src.contains(shortDistrict);
    }

    private String normalizeRegionUnit(String value) {
        String v = nvl(value).trim();
        for (String suffix : REGION_SUFFIXES) {
            if (v.endsWith(suffix)) {
                v = v.substring(0, v.length() - suffix.length());
                break;
            }
        }
        return v;
    }

    private synchronized void ensureAlertZoneLoaded() {
        if (alertZoneLoaded) {
            return;
        }

        try {
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> rows = sqlSession.selectList(NAMESPACE + "selectAlertZoneMappings");
            if (rows != null) {
                for (Map<String, Object> row : rows) {
                    String code = mapString(row, "code");
                    String name = mapString(row, "name");
                    String region = mapString(row, "regionNm");
                    String districts = mapString(row, "districtExpr");
                    if (isBlank(code) && isBlank(name)) {
                        continue;
                    }
                    AlertZoneMapping mapping = new AlertZoneMapping(code, name, region, districts);
                    if (!isBlank(code)) {
                        alertZoneByCode.put(code, mapping);
                    }
                    if (!isBlank(name)) {
                        alertZoneByName.put(name, mapping);
                    }
                }
            }
            LOGGER.info("Loaded weather alert zone mappings from DB: {} rows", Integer.valueOf(alertZoneByCode.size()));
        } catch (Exception e) {
            LOGGER.error("Failed to load weather alert zone mappings from DB", e);
        } finally {
            alertZoneLoaded = true;
        }
    }

    private String mapString(Map<String, Object> row, String key) {
        if (row == null) {
            return "";
        }
        Object value = row.get(key);
        if (value == null) {
            value = row.get(key.toUpperCase(Locale.ROOT));
        }
        if (value == null) {
            value = row.get(key.toLowerCase(Locale.ROOT));
        }
        return value == null ? "" : String.valueOf(value).trim();
    }

    private BufferedReader openAlertZoneReader() throws Exception {
        String configuredPath = resolveAlertZonePath();
        if (!isBlank(configuredPath)) {
            Path path = Paths.get(configuredPath);
            if (!Files.exists(path)) {
                LOGGER.warn("Alert zone mapping file not found (configured): {}", configuredPath);
                return null;
            }
            LOGGER.info("Using alert zone mapping file from filesystem: {}", configuredPath);
            return Files.newBufferedReader(path, StandardCharsets.UTF_8);
        }

        InputStream in = Thread.currentThread().getContextClassLoader().getResourceAsStream(ALERT_ZONE_CLASSPATH);
        if (in == null) {
            LOGGER.warn("Alert zone mapping file not found. Set {} or {} or add classpath resource: {}",
                    ALERT_ZONE_FILE_PROPERTY, ALERT_ZONE_FILE_ENV, ALERT_ZONE_CLASSPATH);
            return null;
        }
        LOGGER.info("Using alert zone mapping file from classpath: {}", ALERT_ZONE_CLASSPATH);
        return new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8));
    }

    private String resolveAlertZonePath() {
        if (!isBlank(alertZoneFile)) {
            return alertZoneFile.trim();
        }

        String byProperty = System.getProperty(ALERT_ZONE_FILE_PROPERTY);
        if (!isBlank(byProperty)) {
            return byProperty.trim();
        }

        String byEnv = System.getenv(ALERT_ZONE_FILE_ENV);
        if (!isBlank(byEnv)) {
            return byEnv.trim();
        }

        return "";
    }

    private List<String> parseCsvLine(String line) {
        List<String> out = new ArrayList<String>();
        StringBuilder sb = new StringBuilder();
        boolean inQuotes = false;

        for (int i = 0; i < line.length(); i++) {
            char ch = line.charAt(i);
            if (ch == '"') {
                inQuotes = !inQuotes;
                continue;
            }
            if (ch == ',' && !inQuotes) {
                out.add(sb.toString());
                sb.setLength(0);
                continue;
            }
            sb.append(ch);
        }
        out.add(sb.toString());
        return out;
    }

    private static final class GeoPoint {
        private final double lon;
        private final double lat;

        private GeoPoint(double lon, double lat) {
            this.lon = lon;
            this.lat = lat;
        }
    }

    private static final class WildfireScore {
        private final double score;
        private final String grade;
        private final String tm;

        private WildfireScore(double score, String grade, String tm) {
            this.score = score;
            this.grade = grade;
            this.tm = tm == null ? "" : tm;
        }
    }

    private static final class WildfireComputationResult {
        private final Map<String, WildfireScore> regionScoreByRegionKey = new HashMap<String, WildfireScore>();
        private String frSourceTm = "";
        private String ffSourceTm = "";
    }

    private static final class WildfireGridData {
        private final int nx;
        private final int ny;
        private final List<String> values;
        private final double minLon;
        private final double maxLon;
        private final double minLat;
        private final double maxLat;
        private final String tm;
        private final String sourceType;

        private WildfireGridData(int nx, int ny, List<String> values,
                                 double minLon, double maxLon, double minLat, double maxLat,
                                 String tm, String sourceType) {
            this.nx = nx;
            this.ny = ny;
            this.values = values;
            this.minLon = minLon;
            this.maxLon = maxLon;
            this.minLat = minLat;
            this.maxLat = maxLat;
            this.tm = tm == null ? "" : tm;
            this.sourceType = sourceType == null ? "" : sourceType;
        }

        private String tokenAt(double lon, double lat) {
            if (values == null || values.isEmpty() || nx <= 0 || ny <= 0 || maxLon <= minLon || maxLat <= minLat) {
                return "";
            }
            String[] candidates = new String[] {
                    tokenAtInternal(lon, lat, false, false),
                    tokenAtInternal(lon, lat, true, false),
                    tokenAtInternal(lon, lat, false, true),
                    tokenAtInternal(lon, lat, true, true)
            };
            for (String token : candidates) {
                if (!isLikelyNoDataToken(token)) {
                    return token;
                }
            }
            return candidates[0] == null ? "" : candidates[0];
        }

        private String tokenAtInternal(double lon, double lat, boolean flipX, boolean flipY) {
            double xRatio = flipX
                    ? (maxLon - lon) / (maxLon - minLon)
                    : (lon - minLon) / (maxLon - minLon);
            double yRatio = flipY
                    ? (lat - minLat) / (maxLat - minLat)
                    : (maxLat - lat) / (maxLat - minLat);

            int x = clamp((int) Math.round(xRatio * (nx - 1)), 0, nx - 1);
            int y = clamp((int) Math.round(yRatio * (ny - 1)), 0, ny - 1);
            int idx = y * nx + x;
            if (idx < 0 || idx >= values.size()) {
                return "";
            }
            return values.get(idx);
        }

        private boolean isLikelyNoDataToken(String token) {
            String normalized = token == null ? "" : token.trim();
            if (normalized.isEmpty()) {
                return true;
            }
            return "9999".equals(normalized)
                    || "-9999".equals(normalized)
                    || "255".equals(normalized);
        }

        private int clamp(int value, int min, int max) {
            if (value < min) return min;
            if (value > max) return max;
            return value;
        }

    }

    private static final class AlertZoneMapping {
        private final String code;
        private final String name;
        private final String regionNm;
        private final String districtExpr;

        private AlertZoneMapping(String code, String name, String regionNm, String districtExpr) {
            this.code = code;
            this.name = name;
            this.regionNm = regionNm;
            this.districtExpr = districtExpr;
        }
    }

    private static final class MetAlertRecord {
        private final String regionCd;
        private final String warningCode;
        private final String levelCode;
        private final String commandCode;
        private final String issueDt;
        private final String effectDt;
        private final String inputDt;

        private MetAlertRecord(String regionCd, String warningCode, String levelCode, String commandCode,
                               String issueDt, String effectDt, String inputDt) {
            this.regionCd = regionCd;
            this.warningCode = warningCode;
            this.levelCode = levelCode;
            this.commandCode = commandCode;
            this.issueDt = issueDt;
            this.effectDt = effectDt;
            this.inputDt = inputDt;
        }

        private boolean isLaterThan(MetAlertRecord other) {
            int byInput = nvl(inputDt).compareTo(nvl(other.inputDt));
            if (byInput != 0) {
                return byInput > 0;
            }
            int byIssue = nvl(issueDt).compareTo(nvl(other.issueDt));
            if (byIssue != 0) {
                return byIssue > 0;
            }
            return nvl(effectDt).compareTo(nvl(other.effectDt)) > 0;
        }

        private static String nvl(String value) {
            return value == null ? "" : value;
        }
    }

    private String normalizeRegionName(String name) {
        String result = nvl(name);
        for (String suffix : SUFFIXES) {
            if (result.endsWith(suffix)) {
                result = result.substring(0, result.length() - suffix.length());
            }
        }
        return result.trim();
    }

    private Object[] calculateWeatherScore(List<String[]> alerts) {
        boolean hasTyphoon = false;
        for (String[] alert : alerts) {
            if ("태풍".equals(alert[0])) {
                hasTyphoon = true;
                break;
            }
        }

        Map<String, String[]> bestByType = new LinkedHashMap<String, String[]>();
        for (String[] alert : alerts) {
            String type = alert[0];
            String level = alert[1];

            if (hasTyphoon && "강풍".equals(type)) {
                continue;
            }

            Map<String, Integer> scoreMap = WEATHER_SCORES.get(type);
            if (scoreMap == null) {
                continue;
            }

            Integer score = scoreMap.get(level);
            if (score == null || score.intValue() == 0) {
                continue;
            }

            if (!bestByType.containsKey(type)) {
                bestByType.put(type, new String[] { type, level, String.valueOf(score) });
            } else {
                int existing = Integer.parseInt(bestByType.get(type)[2]);
                if (score.intValue() > existing) {
                    bestByType.put(type, new String[] { type, level, String.valueOf(score) });
                }
            }
        }

        double totalScore = 0.0d;
        List<String> applied = new ArrayList<String>();

        for (String[] best : bestByType.values()) {
            int score = Integer.parseInt(best[2]);
            totalScore += score;
            applied.add(best[0] + best[1] + "(" + score + ")");
        }

        return new Object[] { Double.valueOf(totalScore), String.join(", ", applied) };
    }

    // KMA API returns abbreviated levels ("주의", "경고") - normalize to full form
    private String normalizeAlertLevel(String raw) {
        if ("1".equals(raw)) return "예비";
        if ("2".equals(raw)) return "주의보";
        if ("3".equals(raw)) return "경보";
        if ("주의".equals(raw)) return "주의보";
        if ("경고".equals(raw)) return "경보";
        return raw;
    }

    private String normalizeWarningType(String codeOrName) {
        if ("T".equals(codeOrName)) return "태풍";
        if ("H".equals(codeOrName)) return "호우";
        if ("V".equals(codeOrName)) return "풍랑";
        if ("S".equals(codeOrName)) return "대설";
        if ("D".equals(codeOrName)) return "건조";
        if ("W".equals(codeOrName)) return "강풍";
        if ("C".equals(codeOrName)) return "한파";
        if ("O".equals(codeOrName)) return "폭염";
        if ("Y".equals(codeOrName)) return "황사";
        if ("F".equals(codeOrName)) return "안개";
        return codeOrName;
    }

    private String normalizeAlertCommand(String codeOrName) {
        if ("1".equals(codeOrName)) return "발표";
        if ("2".equals(codeOrName)) return "대치";
        if ("3".equals(codeOrName)) return "해제";
        if ("4".equals(codeOrName)) return "대치해제";
        if ("5".equals(codeOrName)) return "연장";
        if ("6".equals(codeOrName)) return "변경";
        if ("7".equals(codeOrName)) return "변경해제";
        return codeOrName;
    }

    private boolean isActiveCommand(String commandCode) {
        return "1".equals(commandCode) || "2".equals(commandCode) || "5".equals(commandCode) || "6".equals(commandCode);
    }

    private String nvl(String value) {
        return value == null ? "" : value;
    }

    private boolean isBlank(String value) {
        return value == null || value.trim().isEmpty();
    }
}
