package egovframework.com.risk.web;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URLEncoder;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Base64;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.time.temporal.ChronoUnit;
import javax.annotation.PostConstruct;
import javax.annotation.Resource;
import javax.net.ssl.HttpsURLConnection;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import egovframework.com.risk.service.RiskWeatherService;
import egovframework.com.risk.vo.RiskSearchVO;
import egovframework.com.risk.vo.RiskWeatherVO;

/**
 * 기상특보 조회 REST API (넥사크로 연동)
 */
@RestController
public class RiskWeatherController {

    private static final Logger LOGGER = LoggerFactory.getLogger(RiskWeatherController.class);
    private static final String KST_ZONE_ID = "Asia/Seoul";
    private static final DateTimeFormatter MAP_TM_FORMAT = DateTimeFormatter.ofPattern("yyyyMMddHHmm");
    private static final String DEFAULT_WRN_CODES = "W,R,C,D,O,N,V,T,S,Y,H,F";
    private static final String WRN_MAP_URL = "https://apihub-pub.kma.go.kr/api/typ03/cgi/wrn/nph-wrn7";
    private static final String GK2A_MAP_URL_KO = "https://apihub-pub.kma.go.kr/api/typ05/api/GK2A/LE1B/VI004/KO/image";
    private static final String GK2A_MAP_URL_EA = "https://apihub-pub.kma.go.kr/api/typ05/api/GK2A/LE1B/VI004/EA/image";
    private static final String WILDFIRE_MAP_URL = "https://apihub-pub.kma.go.kr/api/typ01/cgi-bin/sat/nph-sat_ana_img";
    private static final int MAP_TIME_LAG_MINUTES = 30;
    private static final int WILDFIRE_MIN_IMAGE_BYTES = 5000;
    private static final Set<String> ALLOWED_WRN_CODES = new LinkedHashSet<String>(Arrays.asList(
            "W", "R", "C", "D", "O", "N", "V", "T", "S", "Y", "H", "F"
    ));
    private static final WeatherMapPreset DEFAULT_MAP_PRESET = new WeatherMapPreset(127.7d, 36.1d, 300, 685);

    @Resource(name = "riskWeatherService")
    private RiskWeatherService riskWeatherService;

    private final Object mapCacheLock = new Object();
    private volatile CachedImage warningMapCache;
    private volatile CachedImage satelliteMapCache;
    private volatile CachedImage wildfireMapCache;

    @PostConstruct
    public void warmUpWeatherMapCaches() {
        refreshMapCachesNow(true, true, true);
    }

    @Scheduled(cron = "0 0 * * * *", zone = KST_ZONE_ID)
    public void scheduledRefreshWarningAndSatelliteMaps() {
        refreshMapCachesNow(true, true, false);
    }

    @Scheduled(cron = "0 0 9 * * *", zone = KST_ZONE_ID)
    public void scheduledRefreshWildfireMap() {
        refreshMapCachesNow(false, false, true);
    }

    public Map<String, Object> refreshMapCachesNow(boolean refreshWarning, boolean refreshSatellite, boolean refreshWildfire) {
        synchronized (mapCacheLock) {
            Map<String, Object> result = new HashMap<String, Object>();
            result.put("resultCode", "OK");

            if (refreshWarning) {
                ResponseEntity<byte[]> warning = fetchWarningMapImage(DEFAULT_WRN_CODES);
                boolean warningOk = isUsableImageResponse(warning);
                if (warningOk) {
                    warningMapCache = CachedImage.from(warning);
                }
                result.put("warningMapRefreshed", Boolean.valueOf(warningOk));
                LOGGER.info("weather map cache refresh - warning: {}", Boolean.valueOf(warningOk));
            }

            if (refreshSatellite) {
                ResponseEntity<byte[]> sat = fetchSatelliteMapImage();
                boolean satOk = isUsableImageResponse(sat);
                if (satOk) {
                    satelliteMapCache = CachedImage.from(sat);
                }
                result.put("satelliteMapRefreshed", Boolean.valueOf(satOk));
                LOGGER.info("weather map cache refresh - satellite: {}", Boolean.valueOf(satOk));
            }

            if (refreshWildfire) {
                ResponseEntity<byte[]> fire = fetchWildfireMapImage();
                boolean fireOk = isUsableImageResponse(fire) && !isLikelyPlaceholderResponse(fire);
                if (fireOk) {
                    wildfireMapCache = CachedImage.from(fire);
                }
                result.put("wildfireMapRefreshed", Boolean.valueOf(fireOk));
                LOGGER.info("weather map cache refresh - wildfire: {}", Boolean.valueOf(fireOk));
            }

            return result;
        }
    }

    /**
     * 당일 특보 현황
     * GET /selectWeatherAlertToday.do
     */
    @RequestMapping("/selectWeatherAlertToday.do")
    public Map<String, Object> selectWeatherAlertToday() {
        List<RiskWeatherVO> list = riskWeatherService.selectWeatherAlertToday();

        Map<String, Object> result = new HashMap<String, Object>();
        result.put("resultCode", "OK");
        result.put("resultMsg", "성공");
        result.put("totalCount", list.size());
        result.put("data", list);
        return result;
    }

    /**
     * 지역별 기상점수
     * GET /selectWeatherRiskScore.do
     */
    @RequestMapping("/selectWeatherRiskScore.do")
    public Map<String, Object> selectWeatherRiskScore(RiskSearchVO searchVO) {
        List<RiskWeatherVO> list = riskWeatherService.selectWeatherRiskScore(searchVO);

        Map<String, Object> result = new HashMap<String, Object>();
        result.put("resultCode", "OK");
        result.put("resultMsg", "성공");
        result.put("totalCount", list.size());
        result.put("data", list);
        return result;
    }

    /**
     * 특보 이력 (일자별)
     * GET /selectWeatherHistory.do
     */
    @RequestMapping("/selectWeatherHistory.do")
    public Map<String, Object> selectWeatherHistory(RiskSearchVO searchVO) {
        List<RiskWeatherVO> list = riskWeatherService.selectWeatherHistory(searchVO);

        Map<String, Object> result = new HashMap<String, Object>();
        result.put("resultCode", "OK");
        result.put("resultMsg", "성공");
        result.put("totalCount", list.size());
        result.put("data", list);
        return result;
    }

    /**
     * 蹂몃?/?ъ뾽??留ㅽ븨
     * GET /selectBranchHqMap.do
     */
    @RequestMapping("/selectBranchHqMap.do")
    public Map<String, Object> selectBranchHqMap() {
        List<Map<String, Object>> list = riskWeatherService.selectBranchHqMap();

        Map<String, Object> result = new HashMap<String, Object>();
        result.put("resultCode", "OK");
        result.put("resultMsg", "?깃났");
        result.put("totalCount", list.size());
        result.put("data", list);
        return result;
    }

    /**
     * KMA warning status map image proxy.
     * GET /weatherWarningMapImage.do?wrn=R|D|T|W|H...
     */
    @RequestMapping("/weatherWarningMapImage.do")
    public ResponseEntity<byte[]> weatherWarningMapImage(
            @RequestParam(value = "wrn", required = false) String wrn,
            @RequestParam(value = "force", required = false) String force) {
        String wrnCodes = resolveWrnCodes(wrn);
        boolean forceRefresh = isForceRefresh(force);
        boolean isDefaultRequest = DEFAULT_WRN_CODES.equals(wrnCodes);

        if (!forceRefresh && isDefaultRequest) {
            CachedImage cached = warningMapCache;
            if (cached != null) {
                return cached.toResponseEntity();
            }
        }

        ResponseEntity<byte[]> live = fetchWarningMapImage(wrnCodes);
        if (isDefaultRequest && isUsableImageResponse(live)) {
            warningMapCache = CachedImage.from(live);
        }
        return live;
    }

    /**
     * GK2A visible satellite image proxy.
     * GET /weatherSatelliteMapImage.do
     */
    @RequestMapping("/weatherSatelliteMapImage.do")
    public ResponseEntity<byte[]> weatherSatelliteMapImage(
            @RequestParam(value = "force", required = false) String force) {
        boolean forceRefresh = isForceRefresh(force);
        if (!forceRefresh) {
            CachedImage cached = satelliteMapCache;
            if (cached != null) {
                return cached.toResponseEntity();
            }
        }

        ResponseEntity<byte[]> live = fetchSatelliteMapImage();
        if (isUsableImageResponse(live)) {
            satelliteMapCache = CachedImage.from(live);
        }
        return live;
    }

    private ResponseEntity<byte[]> fetchSatelliteMapImage() {
        String authKey = resolveAuthKey();
        if (isBlank(authKey)) {
            return errorText("KMA auth key is not configured.", HttpStatus.INTERNAL_SERVER_ERROR);
        }

        // Prefer KO(한국영역) and fallback to EA if provider path differs by environment.
        ResponseEntity<byte[]> last = fetchSatelliteMapByBaseUrl(authKey, GK2A_MAP_URL_KO);
        if (isUsableImageResponse(last)) {
            return last;
        }
        last = fetchSatelliteMapByBaseUrl(authKey, GK2A_MAP_URL_EA);
        return last;
    }

    private ResponseEntity<byte[]> fetchSatelliteMapByBaseUrl(String authKey, String baseUrl) {
        LocalDateTime utcBase = LocalDateTime.now(ZoneOffset.UTC).minusMinutes(MAP_TIME_LAG_MINUTES);
        ResponseEntity<byte[]> last = null;
        for (int i = 0; i < 12; i++) {
            String date = formatObservationTime(utcBase.minusMinutes(i * 10L));
            String url = baseUrl
                    + "?date=" + date
                    + "&authKey=" + urlEncode(authKey);
            last = proxyRemoteImage(url, "satellite map");
            if (isUsableImageResponse(last)) {
                return last;
            }
        }

        // Fallback: try local-time based timestamp once in case provider expects KST.
        String localDate = resolveObservationTimeText();
        String fallbackUrl = baseUrl
                + "?date=" + localDate
                + "&authKey=" + urlEncode(authKey);
        return proxyRemoteImage(fallbackUrl, "satellite map");
    }

    /**
     * Satellite analysis (wildfire-focused) image proxy.
     * GET /weatherWildfireMapImage.do
     */
    @RequestMapping("/weatherWildfireMapImage.do")
    public ResponseEntity<byte[]> weatherWildfireMapImage(
            @RequestParam(value = "force", required = false) String force) {
        boolean forceRefresh = isForceRefresh(force);
        if (!forceRefresh) {
            CachedImage cached = wildfireMapCache;
            if (cached != null) {
                return cached.toResponseEntity();
            }
        }

        ResponseEntity<byte[]> live = fetchWildfireMapImage();
        if (isUsableImageResponse(live) && !isLikelyPlaceholderResponse(live)) {
            wildfireMapCache = CachedImage.from(live);
        }
        return live;
    }

    private ResponseEntity<byte[]> fetchWildfireMapImage() {
        String authKey = resolveAuthKey();
        if (isBlank(authKey)) {
            return errorText("KMA auth key is not configured.", HttpStatus.INTERNAL_SERVER_ERROR);
        }

        ResponseEntity<byte[]> last = null;
        List<String> tmCandidates = buildWildfireRiskTmCandidates();
        for (String tm : tmCandidates) {
            last = proxyRemoteImage(buildWildfireMapUrl(authKey, tm, "fr", "H1", "G"), "wildfire map");
            if (isUsableImageResponse(last) && !isLikelyPlaceholderResponse(last)) {
                return last;
            }
        }

        return errorText("No usable wildfire map image from KMA (err=-1 or empty).", HttpStatus.BAD_GATEWAY);
    }

    /**
     * KMA wildfire risk(obs=fr) is produced once per day at 00UTC (=09:00 KST).
     * Try latest KST 09:00 first, then backtrack by day.
     */
    private List<String> buildWildfireRiskTmCandidates() {
        List<String> candidates = new ArrayList<String>();
        LocalDateTime nowKst = LocalDateTime.now(ZoneId.of("Asia/Seoul"));
        LocalDateTime latestRun = nowKst.withHour(9).withMinute(0).withSecond(0).withNano(0);
        if (nowKst.isBefore(latestRun)) {
            latestRun = latestRun.minusDays(1);
        }
        for (int i = 0; i < 7; i++) {
            candidates.add(latestRun.minusDays(i).format(MAP_TM_FORMAT));
        }
        return candidates;
    }

    private String resolveWrnCodes(String wrn) {
        if (isBlank(wrn)) {
            return DEFAULT_WRN_CODES;
        }

        Set<String> ordered = new LinkedHashSet<String>();
        String[] tokens = wrn.split(",");
        for (String token : tokens) {
            String normalized = token == null ? "" : token.trim().toUpperCase(Locale.ROOT);
            if (ALLOWED_WRN_CODES.contains(normalized)) {
                ordered.add(normalized);
            }
        }
        if (ordered.isEmpty()) {
            return DEFAULT_WRN_CODES;
        }
        return String.join(",", ordered);
    }

    private ResponseEntity<byte[]> fetchWarningMapImage(String wrnCodes) {
        String authKey = resolveAuthKey();
        if (isBlank(authKey)) {
            return errorText("KMA auth key is not configured.", HttpStatus.INTERNAL_SERVER_ERROR);
        }

        String tm = resolveObservationTimeText();
        String url = buildWarningMapUrl(authKey, DEFAULT_MAP_PRESET, tm, wrnCodes);
        return proxyRemoteImage(url, "weather warning map");
    }

    private boolean isForceRefresh(String force) {
        if (isBlank(force)) {
            return false;
        }
        String normalized = force.trim().toLowerCase(Locale.ROOT);
        return "1".equals(normalized) || "true".equals(normalized) || "y".equals(normalized) || "yes".equals(normalized);
    }

    private String buildWarningMapUrl(String authKey, WeatherMapPreset preset, String tm, String wrnCodes) {
        return WRN_MAP_URL
                + "?out=0&tmef=1&city=1&name=0"
                + "&tm=" + tm
                + "&lon=" + preset.lon
                + "&lat=" + preset.lat
                + "&range=" + preset.range
                + "&size=" + preset.size
                + "&wrn=" + wrnCodes + ","
                + "&authKey=" + urlEncode(authKey);
    }

    private String buildWildfireMapUrl(String authKey, String tm, String obs, String map, String sat) {
        return WILDFIRE_MAP_URL
                + "?obs=" + obs
                + "&tm=" + tm
                + "&size=600"
                + "&sat=" + sat
                + "&map=" + map
                + "&xp=-9999"
                + "&yp=-9999"
                + "&zoom=1.3"
                + "&scn=ko"
                + "&authKey=" + urlEncode(authKey);
    }

    private String resolveObservationTimeText() {
        LocalDateTime base = LocalDateTime.now().minusMinutes(MAP_TIME_LAG_MINUTES).truncatedTo(ChronoUnit.MINUTES);
        return formatObservationTime(base);
    }

    private String formatObservationTime(LocalDateTime base) {
        int flooredMinute = (base.getMinute() / 10) * 10;
        return base.withMinute(flooredMinute).withSecond(0).withNano(0).format(MAP_TM_FORMAT);
    }

    private ResponseEntity<byte[]> proxyRemoteImage(String url, String imageName) {
        HttpsURLConnection conn = null;
        try {
            conn = (HttpsURLConnection) new URL(url).openConnection();
            conn.setRequestMethod("GET");
            conn.setConnectTimeout(10000);
            conn.setReadTimeout(20000);

            int status = conn.getResponseCode();
            byte[] payload;
            try (InputStream stream = status >= 200 && status < 300 ? conn.getInputStream() : conn.getErrorStream()) {
                payload = readAll(stream);
            }
            String contentType = conn.getContentType();
            payload = decodeIfBase64Image(payload);
            String detected = detectImageMediaType(payload);
            if (!isBlank(detected)) {
                contentType = detected;
            }

            HttpHeaders headers = new HttpHeaders();
            headers.setCacheControl("no-store, no-cache, must-revalidate, max-age=0");
            headers.setPragma("no-cache");
            headers.setExpires(0L);

            if (!isBlank(contentType)) {
                try {
                    headers.setContentType(MediaType.parseMediaType(contentType));
                } catch (Exception ignore) {
                    headers.setContentType(MediaType.APPLICATION_OCTET_STREAM);
                }
            } else {
                headers.setContentType(MediaType.APPLICATION_OCTET_STREAM);
            }

            HttpStatus responseStatus;
            try {
                responseStatus = HttpStatus.valueOf(status);
            } catch (Exception e) {
                responseStatus = HttpStatus.BAD_GATEWAY;
            }
            return new ResponseEntity<byte[]>(payload, headers, responseStatus);
        } catch (Exception e) {
            return errorText("Failed to load " + imageName + ": " + e.getMessage(), HttpStatus.BAD_GATEWAY);
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private boolean isUsableImageResponse(ResponseEntity<byte[]> response) {
        if (response == null) {
            return false;
        }
        int status = response.getStatusCodeValue();
        if (status < 200 || status >= 300) {
            return false;
        }
        byte[] payload = response.getBody();
        if (payload == null || payload.length == 0) {
            return false;
        }

        String detected = detectImageMediaType(payload);
        if (!isBlank(detected)) {
            return true;
        }

        String text = new String(payload, StandardCharsets.UTF_8).trim();
        if (isBlank(text) || "\"\"".equals(text) || "null".equalsIgnoreCase(text)) {
            return false;
        }
        String lowered = text.toLowerCase(Locale.ROOT);
        if (lowered.startsWith("err") || lowered.contains("err=") || lowered.contains("error")) {
            return false;
        }
        return false;
    }

    private boolean isLikelyPlaceholderResponse(ResponseEntity<byte[]> response) {
        if (!isUsableImageResponse(response)) {
            return true;
        }
        byte[] payload = response.getBody();
        if (payload == null || payload.length == 0) {
            return true;
        }
        byte[] decoded = decodeIfBase64Image(payload);
        String mediaType = detectImageMediaType(decoded);
        if (MediaType.IMAGE_PNG_VALUE.equals(mediaType) && decoded.length < WILDFIRE_MIN_IMAGE_BYTES) {
            return true;
        }
        if (isBlank(mediaType)) {
            String text = new String(decoded, StandardCharsets.UTF_8).trim().toLowerCase(Locale.ROOT);
            if (text.startsWith("err") || text.contains("err=") || text.contains("error")) {
                return true;
            }
        }
        return false;
    }

    private String resolveAuthKey() {
        String byProperty = System.getProperty("kma.auth.key");
        if (!isBlank(byProperty)) {
            return byProperty.trim();
        }

        String byEnv = System.getenv("KMA_AUTH_KEY");
        if (!isBlank(byEnv)) {
            return byEnv.trim();
        }
        return "";
    }

    private String urlEncode(String value) {
        try {
            return URLEncoder.encode(value, StandardCharsets.UTF_8.name());
        } catch (Exception e) {
            return value;
        }
    }

    private byte[] readAll(InputStream in) throws IOException {
        if (in == null) {
            return new byte[0];
        }

        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int len;
        while ((len = in.read(buf)) != -1) {
            out.write(buf, 0, len);
        }
        return out.toByteArray();
    }

    private byte[] decodeIfBase64Image(byte[] payload) {
        if (payload == null || payload.length == 0) {
            return payload;
        }
        if (startsWithPngSignature(payload)) {
            return payload;
        }

        String text = new String(payload, StandardCharsets.UTF_8).trim();
        while (text.startsWith("\"") && text.length() > 1) {
            text = text.substring(1);
        }
        while (text.endsWith("\"") && text.length() > 1) {
            text = text.substring(0, text.length() - 1);
        }
        if (text.startsWith("data:image")) {
            int comma = text.indexOf(',');
            if (comma > -1 && comma < text.length() - 1) {
                text = text.substring(comma + 1);
            }
        }
        text = text.replace("\\/", "/")
                .replace("\\n", "")
                .replace("\\r", "");
        text = text.replaceAll("\\s+", "");
        if (text.length() < 16) {
            return payload;
        }
        if (!(text.startsWith("iVBOR") || text.startsWith("R0lGOD") || text.startsWith("/9j/"))) {
            return payload;
        }
        String sanitized = text.replaceAll("[^A-Za-z0-9+/=]", "");
        try {
            byte[] decoded = decodeBase64Flexible(sanitized);
            if (decoded != null && decoded.length > 0) {
                return decoded;
            }
        } catch (Exception ignore) {
            // Keep original payload when decode fails.
        }
        return payload;
    }

    private byte[] decodeBase64Flexible(String text) {
        try {
            return Base64.getDecoder().decode(text);
        } catch (IllegalArgumentException e) {
            return Base64.getMimeDecoder().decode(text);
        }
    }

    private boolean startsWithPngSignature(byte[] payload) {
        return payload != null
                && payload.length >= 8
                && (payload[0] & 0xFF) == 0x89
                && payload[1] == 0x50
                && payload[2] == 0x4E
                && payload[3] == 0x47
                && payload[4] == 0x0D
                && payload[5] == 0x0A
                && payload[6] == 0x1A
                && payload[7] == 0x0A;
    }

    private String detectImageMediaType(byte[] payload) {
        if (payload == null || payload.length < 4) {
            return "";
        }
        if (startsWithPngSignature(payload)) {
            return MediaType.IMAGE_PNG_VALUE;
        }
        if (startsWithGifSignature(payload)) {
            return MediaType.IMAGE_GIF_VALUE;
        }
        if (startsWithJpegSignature(payload)) {
            return MediaType.IMAGE_JPEG_VALUE;
        }
        return "";
    }

    private boolean startsWithGifSignature(byte[] payload) {
        return payload != null
                && payload.length >= 6
                && payload[0] == 'G'
                && payload[1] == 'I'
                && payload[2] == 'F'
                && payload[3] == '8'
                && (payload[4] == '7' || payload[4] == '9')
                && payload[5] == 'a';
    }

    private boolean startsWithJpegSignature(byte[] payload) {
        return payload != null
                && payload.length >= 3
                && (payload[0] & 0xFF) == 0xFF
                && (payload[1] & 0xFF) == 0xD8
                && (payload[2] & 0xFF) == 0xFF;
    }

    private ResponseEntity<byte[]> errorText(String message, HttpStatus status) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.TEXT_PLAIN);
        return new ResponseEntity<byte[]>(message.getBytes(StandardCharsets.UTF_8), headers, status);
    }

    private boolean isBlank(String value) {
        return value == null || value.trim().isEmpty();
    }

    private static final class CachedImage {
        private final byte[] payload;
        private final String contentType;
        private final HttpStatus status;

        private CachedImage(byte[] payload, String contentType, HttpStatus status) {
            this.payload = payload == null ? new byte[0] : Arrays.copyOf(payload, payload.length);
            this.contentType = contentType;
            this.status = status == null ? HttpStatus.OK : status;
        }

        private static CachedImage from(ResponseEntity<byte[]> response) {
            byte[] body = response == null ? null : response.getBody();
            MediaType mediaType = response == null ? null : response.getHeaders().getContentType();
            String ct = mediaType == null ? MediaType.APPLICATION_OCTET_STREAM_VALUE : mediaType.toString();
            HttpStatus st = response == null ? HttpStatus.OK : response.getStatusCode();
            return new CachedImage(body, ct, st);
        }

        private ResponseEntity<byte[]> toResponseEntity() {
            HttpHeaders headers = new HttpHeaders();
            headers.setCacheControl("no-store, no-cache, must-revalidate, max-age=0");
            headers.setPragma("no-cache");
            headers.setExpires(0L);
            try {
                headers.setContentType(MediaType.parseMediaType(contentType));
            } catch (Exception ignore) {
                headers.setContentType(MediaType.APPLICATION_OCTET_STREAM);
            }
            return new ResponseEntity<byte[]>(Arrays.copyOf(payload, payload.length), headers, status);
        }
    }

    private static final class WeatherMapPreset {
        private final double lon;
        private final double lat;
        private final int range;
        private final int size;

        private WeatherMapPreset(double lon, double lat, int range, int size) {
            this.lon = lon;
            this.lat = lat;
            this.range = range;
            this.size = size;
        }
    }
}
