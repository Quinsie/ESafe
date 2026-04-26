package egovframework.com.risk.web;

import java.io.ByteArrayOutputStream;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URLEncoder;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.Base64;
import java.util.Iterator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.time.temporal.ChronoUnit;
import javax.annotation.PostConstruct;
import javax.annotation.Resource;
import javax.imageio.IIOImage;
import javax.imageio.ImageIO;
import javax.imageio.ImageReadParam;
import javax.imageio.ImageReader;
import javax.imageio.stream.ImageInputStream;
import javax.net.ssl.HttpsURLConnection;
import java.awt.image.BufferedImage;
import java.awt.image.Raster;
import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Font;
import java.awt.FontMetrics;
import java.awt.Graphics2D;
import java.awt.Rectangle;
import java.awt.RenderingHints;
import java.awt.geom.Path2D;

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
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.File;
import java.util.LinkedHashMap;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

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
    private static final int LANDSLIDE_TARGET_WIDTH = 900;
    private static final int LANDSLIDE_TARGET_HEIGHT = 620;
    private static final int LANDSLIDE_VIEW_MIN_SIZE = 256;
    private static final int LANDSLIDE_VIEW_MAX_WIDTH = 1800;
    private static final int LANDSLIDE_VIEW_MAX_HEIGHT = 1200;
    private static final int LANDSLIDE_NO_DATA = Integer.MAX_VALUE;
    private static final int LANDSLIDE_TILE_SIZE = 256;
    private static final int LANDSLIDE_BASEMAP_ZOOM = 9;
    private static final double KOREA_2000_A = 6378137.0d;
    private static final double KOREA_2000_F = 1.0d / 298.257222101d;
    private static final double KOREA_2000_E2 = 2.0d * KOREA_2000_F - KOREA_2000_F * KOREA_2000_F;
    private static final double KOREA_2000_EP2 = KOREA_2000_E2 / (1.0d - KOREA_2000_E2);
    private static final double KOREA_2000_LAT0 = Math.toRadians(38.0d);
    private static final double KOREA_2000_LON0 = Math.toRadians(127.0d);
    private static final double KOREA_2000_FALSE_EASTING = 200000.0d;
    private static final double KOREA_2000_FALSE_NORTHING = 500000.0d;
    private static final double KOREA_2000_SCALE = 1.0d;
    private static final double KOREA_2000_M0 = meridionalArc(KOREA_2000_LAT0);
    private static final Color LANDSLIDE_PANEL_BG = new Color(14, 24, 35, 178);
    private static final Color LANDSLIDE_PANEL_BORDER = new Color(255, 255, 255, 68);
    private static final String VWORLD_SATELLITE_TILE_URL = "https://xdworld.vworld.kr/2d/Satellite/service/%d/%d/%d.jpeg";
    private static final String VWORLD_HYBRID_TILE_URL = "https://xdworld.vworld.kr/2d/Hybrid/service/%d/%d/%d.png";
    private static final String APPROX_RISK_GEOJSON_PATH = "res/jeonnam-risk-area/jeonnam-sig-approx-risk.geojson";
    private static final String APPROX_RISK_LINES_GEOJSON_PATH = "res/jeonnam-risk-area/jeonnam-sig-approx-risk-internal-lines.geojson";
    private static final List<LandslideRasterSpec> LANDSLIDE_RASTER_SPECS = Collections.unmodifiableList(Arrays.asList(
            new LandslideRasterSpec("29", "res/landslide/29/29.tif", "res/landslide/29/29.clr", "res/landslide/29/29.tfw"),
            new LandslideRasterSpec("46", "res/landslide/46/46.tif", "res/landslide/46/46.clr", "res/landslide/46/46.tfw"),
            new LandslideRasterSpec("52180", "res/landslide/52180/52180.tif", "res/landslide/52180/52180.clr", "res/landslide/52180/52180.tfw")
    ));
    private final ObjectMapper objectMapper = new ObjectMapper();
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
    private volatile CachedImage landslideMapCache;
    private volatile byte[] landslidePointLayerCache;

    @PostConstruct
    public void warmUpWeatherMapCaches() {
        Thread warmUpThread = new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    refreshMapCachesNow(true, true, true);
                } catch (Exception e) {
                    LOGGER.warn("weather map cache warm-up failed during startup", e);
                }
            }
        }, "risk-weather-map-warmup");
        warmUpThread.setDaemon(true);
        warmUpThread.start();
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

    public boolean refreshLandslideMapCache() {
        synchronized (mapCacheLock) {
            ResponseEntity<byte[]> landslide = fetchLandslideMapImage();
            boolean landslideOk = isUsableImageResponse(landslide);
            if (landslideOk) {
                landslideMapCache = CachedImage.from(landslide);
            }
            LOGGER.info("weather map cache refresh - landslide: {}", Boolean.valueOf(landslideOk));
            return landslideOk;
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

    /**
     * Local landslide risk map proxy.
     * GET /weatherLandslideMapImage.do
     */
    @RequestMapping("/weatherLandslideMapImage.do")
    public ResponseEntity<byte[]> weatherLandslideMapImage(
            @RequestParam(value = "force", required = false) String force) {
        boolean forceRefresh = isForceRefresh(force);
        if (!forceRefresh) {
            CachedImage cached = landslideMapCache;
            if (cached != null) {
                return cached.toResponseEntity();
            }
        }

        ResponseEntity<byte[]> live = fetchLandslideMapImage();
        if (isUsableImageResponse(live)) {
            landslideMapCache = CachedImage.from(live);
        }
        return live;
    }

    @RequestMapping("/weatherLandslidePointLayer.do")
    public ResponseEntity<byte[]> weatherLandslidePointLayer(
            @RequestParam(value = "force", required = false) String force) {
        boolean forceRefresh = isForceRefresh(force);
        if (!forceRefresh && landslidePointLayerCache != null) {
            return jsonResponse(landslidePointLayerCache);
        }

        try {
            byte[] payload = renderLandslidePointLayerJson();
            landslidePointLayerCache = payload;
            return jsonResponse(payload);
        } catch (Exception e) {
            LOGGER.warn("failed to render landslide point layer", e);
            return errorText("Failed to render landslide point layer: " + e.getMessage(), HttpStatus.INTERNAL_SERVER_ERROR);
        }
    }

    @RequestMapping("/weatherLandslideOverlayImage.do")
    public ResponseEntity<byte[]> weatherLandslideOverlayImage(
            @RequestParam(value = "force", required = false) String force,
            @RequestParam(value = "west", required = false) Double west,
            @RequestParam(value = "south", required = false) Double south,
            @RequestParam(value = "east", required = false) Double east,
            @RequestParam(value = "north", required = false) Double north,
            @RequestParam(value = "width", required = false) Integer width,
            @RequestParam(value = "height", required = false) Integer height) {
        try {
            GeoBounds requestedBounds = resolveRequestedGeoBounds(west, south, east, north);
            byte[] payload = requestedBounds == null
                    ? renderLandslideOverlayImage()
                    : renderLandslideOverlayImage(requestedBounds, width, height);
            HttpHeaders headers = new HttpHeaders();
            headers.setCacheControl("no-store, no-cache, must-revalidate, max-age=0");
            headers.setPragma("no-cache");
            headers.setExpires(0L);
            headers.setContentType(MediaType.IMAGE_PNG);
            return new ResponseEntity<byte[]>(payload, headers, HttpStatus.OK);
        } catch (Exception e) {
            LOGGER.warn("failed to render landslide overlay image", e);
            return errorText("Failed to render landslide overlay image: " + e.getMessage(), HttpStatus.INTERNAL_SERVER_ERROR);
        }
    }

    @RequestMapping("/weatherLandslideOverlayMeta.do")
    public ResponseEntity<byte[]> weatherLandslideOverlayMeta() {
        try {
            byte[] payload = renderLandslideOverlayMeta();
            return jsonResponse(payload);
        } catch (Exception e) {
            LOGGER.warn("failed to render landslide overlay meta", e);
            return errorText("Failed to render landslide overlay meta: " + e.getMessage(), HttpStatus.INTERNAL_SERVER_ERROR);
        }
    }

    @RequestMapping("/jeonnamApproxRiskGeoJson.do")
    public ResponseEntity<String> jeonnamApproxRiskGeoJson() {
        return fileJsonTextResponse(APPROX_RISK_GEOJSON_PATH);
    }

    @RequestMapping("/jeonnamApproxRiskLineGeoJson.do")
    public ResponseEntity<String> jeonnamApproxRiskLineGeoJson() {
        return fileJsonTextResponse(APPROX_RISK_LINES_GEOJSON_PATH);
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

    private ResponseEntity<byte[]> jsonResponse(byte[] payload) {
        HttpHeaders headers = new HttpHeaders();
        headers.setCacheControl("no-store, no-cache, must-revalidate, max-age=0");
        headers.setPragma("no-cache");
        headers.setExpires(0L);
        headers.setContentType(MediaType.APPLICATION_JSON);
        return new ResponseEntity<byte[]>(payload, headers, HttpStatus.OK);
    }

    private ResponseEntity<byte[]> fileJsonResponse(String relativePath) {
        try {
            File file = resolveDataFile(relativePath);
            if (!file.exists()) {
                return errorText("File not found: " + relativePath, HttpStatus.NOT_FOUND);
            }
            return jsonResponse(java.nio.file.Files.readAllBytes(file.toPath()));
        } catch (Exception e) {
            LOGGER.warn("failed to read json file {}", relativePath, e);
            return errorText("Failed to read file: " + relativePath, HttpStatus.INTERNAL_SERVER_ERROR);
        }
    }

    private ResponseEntity<String> fileJsonTextResponse(String relativePath) {
        try {
            File file = resolveDataFile(relativePath);
            if (!file.exists()) {
                return errorTextString("File not found: " + relativePath, HttpStatus.NOT_FOUND);
            }

            String payload = new String(java.nio.file.Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8);
            HttpHeaders headers = new HttpHeaders();
            headers.setCacheControl("no-store, no-cache, must-revalidate, max-age=0");
            headers.setPragma("no-cache");
            headers.setExpires(0L);
            headers.setContentType(new MediaType("application", "json", StandardCharsets.UTF_8));
            return new ResponseEntity<String>(payload, headers, HttpStatus.OK);
        } catch (Exception e) {
            LOGGER.warn("failed to read json text file {}", relativePath, e);
            return errorTextString("Failed to read file: " + relativePath, HttpStatus.INTERNAL_SERVER_ERROR);
        }
    }

    private ResponseEntity<byte[]> fetchLandslideMapImage() {
        try {
            byte[] payload = renderLandslideMapImage();
            HttpHeaders headers = new HttpHeaders();
            headers.setCacheControl("no-store, no-cache, must-revalidate, max-age=0");
            headers.setPragma("no-cache");
            headers.setExpires(0L);
            headers.setContentType(MediaType.IMAGE_PNG);
            return new ResponseEntity<byte[]>(payload, headers, HttpStatus.OK);
        } catch (Exception e) {
            LOGGER.warn("failed to render landslide map image", e);
            return errorText("Failed to render landslide map image: " + e.getMessage(), HttpStatus.INTERNAL_SERVER_ERROR);
        }
    }

    private byte[] renderLandslideMapImage() throws IOException {
        List<LandslideLayer> layers = new ArrayList<LandslideLayer>();
        for (LandslideRasterSpec spec : LANDSLIDE_RASTER_SPECS) {
            LandslideLayer layer = loadLandslideLayer(spec);
            if (layer != null) {
                layers.add(layer);
            }
        }
        if (layers.isEmpty()) {
            throw new IOException("No landslide raster resources found.");
        }

        Bounds unionBounds = mergeBounds(layers);
        CanvasSize canvas = resolveLandslideCanvasSize(unionBounds);
        BufferedImage merged = new BufferedImage(canvas.width, canvas.height, BufferedImage.TYPE_INT_ARGB);
        GeoBounds geoBounds = mergeGeoBounds(layers);

        drawLandslideBaseMap(merged, geoBounds, canvas);

        for (LandslideLayer layer : layers) {
            drawLandslideLayer(merged, layer, unionBounds, canvas);
        }
        drawLandslideOverlay(merged, geoBounds, canvas);
        drawLandslideLegend(merged, canvas);
        drawLandslideTimestamp(merged, canvas);

        ByteArrayOutputStream output = new ByteArrayOutputStream();
        ImageIO.write(merged, "png", output);
        return output.toByteArray();
    }

    private byte[] renderLandslideOverlayImage() throws IOException {
        List<LandslideLayer> layers = new ArrayList<LandslideLayer>();
        for (LandslideRasterSpec spec : LANDSLIDE_RASTER_SPECS) {
            LandslideLayer layer = loadLandslideLayer(spec);
            if (layer != null) {
                layers.add(layer);
            }
        }
        if (layers.isEmpty()) {
            throw new IOException("No landslide raster resources found.");
        }

        Bounds unionBounds = mergeBounds(layers);
        CanvasSize canvas = resolveLandslideCanvasSize(unionBounds);
        BufferedImage merged = new BufferedImage(canvas.width, canvas.height, BufferedImage.TYPE_INT_ARGB);
        GeoBounds geoBounds = mergeGeoBounds(layers);

        for (LandslideLayer layer : layers) {
            drawLandslideLayer(merged, layer, unionBounds, canvas);
        }
        drawLandslideOverlay(merged, geoBounds, canvas);

        ByteArrayOutputStream output = new ByteArrayOutputStream();
        ImageIO.write(merged, "png", output);
        return output.toByteArray();
    }

    private byte[] renderLandslideOverlayImage(GeoBounds requestedBounds, Integer requestedWidth, Integer requestedHeight) throws IOException {
        int width = clampInt(requestedWidth == null ? LANDSLIDE_TARGET_WIDTH : requestedWidth.intValue(), LANDSLIDE_VIEW_MIN_SIZE, LANDSLIDE_VIEW_MAX_WIDTH);
        int height = clampInt(requestedHeight == null ? LANDSLIDE_TARGET_HEIGHT : requestedHeight.intValue(), LANDSLIDE_VIEW_MIN_SIZE, LANDSLIDE_VIEW_MAX_HEIGHT);
        CanvasSize canvas = new CanvasSize(width, height, 1.0d);
        BufferedImage merged = new BufferedImage(canvas.width, canvas.height, BufferedImage.TYPE_INT_ARGB);

        for (LandslideRasterSpec spec : LANDSLIDE_RASTER_SPECS) {
            drawLandslideLayerForGeoBounds(merged, spec, requestedBounds, canvas);
        }
        drawLandslideOverlay(merged, requestedBounds, canvas);

        ByteArrayOutputStream output = new ByteArrayOutputStream();
        ImageIO.write(merged, "png", output);
        return output.toByteArray();
    }

    private GeoBounds resolveRequestedGeoBounds(Double west, Double south, Double east, Double north) {
        if (west == null || south == null || east == null || north == null) {
            return null;
        }
        double w = west.doubleValue();
        double s = south.doubleValue();
        double e = east.doubleValue();
        double n = north.doubleValue();
        if (!Double.isFinite(w) || !Double.isFinite(s) || !Double.isFinite(e) || !Double.isFinite(n)) {
            return null;
        }
        if (e <= w || n <= s) {
            return null;
        }
        return new GeoBounds(w, s, e, n);
    }

    private int clampInt(int value, int min, int max) {
        return Math.max(min, Math.min(max, value));
    }

    private byte[] renderLandslideOverlayMeta() throws IOException {
        List<LandslideLayer> layers = new ArrayList<LandslideLayer>();
        for (LandslideRasterSpec spec : LANDSLIDE_RASTER_SPECS) {
            LandslideLayer layer = loadLandslideLayer(spec);
            if (layer != null) {
                layers.add(layer);
            }
        }
        if (layers.isEmpty()) {
            throw new IOException("No landslide raster resources found.");
        }
        GeoBounds geoBounds = mergeGeoBounds(layers);
        String json = "{\"west\":" + formatCoord(geoBounds.west)
                + ",\"south\":" + formatCoord(geoBounds.south)
                + ",\"east\":" + formatCoord(geoBounds.east)
                + ",\"north\":" + formatCoord(geoBounds.north)
                + "}";
        return json.getBytes(StandardCharsets.UTF_8);
    }

    private byte[] renderLandslidePointLayerJson() throws IOException {
        List<LandslideLayer> layers = new ArrayList<LandslideLayer>();
        for (LandslideRasterSpec spec : LANDSLIDE_RASTER_SPECS) {
            LandslideLayer layer = loadLandslideLayer(spec);
            if (layer != null) {
                layers.add(layer);
            }
        }
        if (layers.isEmpty()) {
            throw new IOException("No landslide raster resources found.");
        }

        StringBuilder sb = new StringBuilder(2 * 1024 * 1024);
        sb.append("{\"points\":[");
        boolean first = true;
        for (LandslideLayer layer : layers) {
            first = appendLandslidePointFeatures(sb, layer, first);
        }
        sb.append("]}");
        return sb.toString().getBytes(StandardCharsets.UTF_8);
    }

    private boolean appendLandslidePointFeatures(StringBuilder sb, LandslideLayer layer, boolean firstFeature) {
        Raster raster = layer.raster;
        int width = raster.getWidth();
        int height = raster.getHeight();
        int sampleStep = resolveLandslidePointStep(width, height);
        boolean first = firstFeature;

        for (int y = 0; y < height; y += sampleStep) {
            for (int x = 0; x < width; x += sampleStep) {
                int value = raster.getSample(x, y, 0);
                Integer rgb = layer.colorMap.get(Integer.valueOf(value));
                if (rgb == null || value == LANDSLIDE_NO_DATA) {
                    continue;
                }

                double lon = layer.geoBounds.west + ((x + 0.5d) / Math.max(1.0d, width)) * (layer.geoBounds.east - layer.geoBounds.west);
                double lat = layer.geoBounds.north - ((y + 0.5d) / Math.max(1.0d, height)) * (layer.geoBounds.north - layer.geoBounds.south);

                if (!first) {
                    sb.append(',');
                }
                first = false;
                sb.append('[')
                  .append(formatCoord(lon)).append(',')
                  .append(formatCoord(lat)).append(',')
                  .append(value).append(']');
            }
        }
        return first;
    }

    private int resolveLandslidePointStep(int width, int height) {
        double pixelCount = width * (double) height;
        return Math.max(4, (int) Math.ceil(Math.sqrt(pixelCount / 12000.0d)));
    }

    private String formatCoord(double value) {
        return String.format(Locale.ROOT, "%.6f", value);
    }

    private LandslideLayer loadLandslideLayer(LandslideRasterSpec spec) throws IOException {
            File tifResource = resolveDataFile(spec.tifResourcePath);
            File clrResource = resolveDataFile(spec.clrResourcePath);
            File tfwResource = resolveDataFile(spec.tfwResourcePath);
            File xmlResource = resolveDataFile(spec.xmlResourcePath);
        if (!tifResource.exists() || !clrResource.exists() || !tfwResource.exists() || !xmlResource.exists()) {
            return null;
        }

        Map<Integer, Integer> colorMap = loadLandslideColorMap(clrResource);
        WorldFile worldFile = loadWorldFile(tfwResource);
        GeoBounds geoBounds = loadGeoBounds(xmlResource);
        try (InputStream tifStream = java.nio.file.Files.newInputStream(tifResource.toPath());
             ImageInputStream imageInput = ImageIO.createImageInputStream(tifStream)) {
            if (imageInput == null) {
                throw new IOException("Unable to open landslide raster stream");
            }

            Iterator<ImageReader> readers = ImageIO.getImageReaders(imageInput);
            if (!readers.hasNext()) {
                throw new IOException("No TIFF reader available for landslide raster");
            }

            ImageReader reader = readers.next();
            try {
                reader.setInput(imageInput, true, true);
                int sourceWidth = reader.getWidth(0);
                int sourceHeight = reader.getHeight(0);
                int sampling = resolveSubsampling(sourceWidth, sourceHeight);

                ImageReadParam param = reader.getDefaultReadParam();
                param.setSourceSubsampling(sampling, sampling, 0, 0);
                BufferedImage sourceImage = reader.read(0, param);
                if (sourceImage == null) {
                    throw new IOException("Unable to decode landslide raster image");
                }
                double sampledPixelWidth = worldFile.pixelWidth * sampling;
                double sampledPixelHeight = Math.abs(worldFile.pixelHeight) * sampling;
                double minX = worldFile.originX - (worldFile.pixelWidth / 2.0d);
                double maxY = worldFile.originY + (Math.abs(worldFile.pixelHeight) / 2.0d);
                double maxX = minX + sampledPixelWidth * sourceImage.getWidth();
                double minY = maxY - sampledPixelHeight * sourceImage.getHeight();
                Bounds projectedBounds = new Bounds(minX, minY, maxX, maxY);

                return new LandslideLayer(
                        spec.code,
                        sourceImage.getRaster(),
                        colorMap,
                        projectedBounds,
                        mergeGeoBounds(geoBounds, projectBoundsToGeoBounds(projectedBounds)),
                        sampledPixelWidth,
                        sampledPixelHeight
                );
            } finally {
                reader.dispose();
            }
        }
    }

    private int resolveSubsampling(int sourceWidth, int sourceHeight) {
        double widthRatio = sourceWidth / (double) LANDSLIDE_TARGET_WIDTH;
        double heightRatio = sourceHeight / (double) LANDSLIDE_TARGET_HEIGHT;
        return Math.max(1, (int) Math.ceil(Math.max(widthRatio, heightRatio)));
    }

    private void drawLandslideLayer(BufferedImage canvasImage, LandslideLayer layer, Bounds unionBounds, CanvasSize canvas) {
        Raster raster = layer.raster;
        int width = raster.getWidth();
        int height = raster.getHeight();
        int[] row = new int[width];

        for (int y = 0; y < height; y++) {
            raster.getSamples(0, y, width, 1, 0, row);
            double worldY = layer.bounds.maxY - ((y + 0.5d) * layer.pixelHeight);
            int canvasY = (int) Math.floor((unionBounds.maxY - worldY) * canvas.scale);
            if (canvasY < 0 || canvasY >= canvas.height) {
                continue;
            }
            for (int x = 0; x < width; x++) {
                int value = row[x];
                Integer rgb = layer.colorMap.get(Integer.valueOf(value));
                if (rgb == null || value == LANDSLIDE_NO_DATA) {
                    continue;
                }
                double worldX = layer.bounds.minX + ((x + 0.5d) * layer.pixelWidth);
                int canvasX = (int) Math.floor((worldX - unionBounds.minX) * canvas.scale);
                if (canvasX < 0 || canvasX >= canvas.width) {
                    continue;
                }
                canvasImage.setRGB(canvasX, canvasY, (resolveLandslideAlpha(value) << 24) | rgb.intValue());
            }
        }
    }

    private void drawLandslideLayerForGeoBounds(BufferedImage canvasImage, LandslideRasterSpec spec, GeoBounds requestedBounds, CanvasSize canvas) throws IOException {
        File tifResource = resolveDataFile(spec.tifResourcePath);
        File clrResource = resolveDataFile(spec.clrResourcePath);
        File tfwResource = resolveDataFile(spec.tfwResourcePath);
        if (!tifResource.exists() || !clrResource.exists() || !tfwResource.exists()) {
            return;
        }

        Map<Integer, Integer> colorMap = loadLandslideColorMap(clrResource);
        WorldFile worldFile = loadWorldFile(tfwResource);
        try (InputStream tifStream = java.nio.file.Files.newInputStream(tifResource.toPath());
             ImageInputStream imageInput = ImageIO.createImageInputStream(tifStream)) {
            if (imageInput == null) {
                throw new IOException("Unable to open landslide raster stream");
            }

            Iterator<ImageReader> readers = ImageIO.getImageReaders(imageInput);
            if (!readers.hasNext()) {
                throw new IOException("No TIFF reader available for landslide raster");
            }

            ImageReader reader = readers.next();
            try {
                reader.setInput(imageInput, true, true);
                int sourceWidth = reader.getWidth(0);
                int sourceHeight = reader.getHeight(0);
                Bounds projectedLayerBounds = resolveProjectedBounds(worldFile, sourceWidth, sourceHeight);
                Bounds projectedRequestBounds = projectGeoBoundsToProjectedBounds(requestedBounds);
                Bounds projectedIntersection = intersectProjectedBounds(projectedRequestBounds, projectedLayerBounds);
                if (projectedIntersection == null) {
                    return;
                }
                Rectangle sourceRegion = resolveLandslideSourceRegion(projectedIntersection, projectedLayerBounds, sourceWidth, sourceHeight);
                if (sourceRegion.width <= 0 || sourceRegion.height <= 0) {
                    return;
                }

                double projectedIntersectionWidth = Math.max(1e-9d, projectedIntersection.maxX - projectedIntersection.minX);
                double projectedIntersectionHeight = Math.max(1e-9d, projectedIntersection.maxY - projectedIntersection.minY);
                double projectedRequestWidth = Math.max(1e-9d, projectedRequestBounds.maxX - projectedRequestBounds.minX);
                double projectedRequestHeight = Math.max(1e-9d, projectedRequestBounds.maxY - projectedRequestBounds.minY);
                int targetWidth = Math.max(1, (int) Math.ceil(canvas.width * (projectedIntersectionWidth / projectedRequestWidth)));
                int targetHeight = Math.max(1, (int) Math.ceil(canvas.height * (projectedIntersectionHeight / projectedRequestHeight)));
                int sampling = Math.max(1, (int) Math.ceil(Math.max(sourceRegion.width / (double) targetWidth, sourceRegion.height / (double) targetHeight)));

                ImageReadParam param = reader.getDefaultReadParam();
                param.setSourceRegion(sourceRegion);
                param.setSourceSubsampling(sampling, sampling, 0, 0);
                BufferedImage sourceImage = reader.read(0, param);
                if (sourceImage == null) {
                    return;
                }

                drawSampledLandslideImage(canvasImage, sourceImage.getRaster(), colorMap, sourceRegion, sampling, projectedLayerBounds, requestedBounds, canvas, sourceWidth, sourceHeight);
            } finally {
                reader.dispose();
            }
        }
    }

    private Bounds intersectProjectedBounds(Bounds a, Bounds b) {
        double minX = Math.max(a.minX, b.minX);
        double minY = Math.max(a.minY, b.minY);
        double maxX = Math.min(a.maxX, b.maxX);
        double maxY = Math.min(a.maxY, b.maxY);
        if (maxX <= minX || maxY <= minY) {
            return null;
        }
        return new Bounds(minX, minY, maxX, maxY);
    }

    private Rectangle resolveLandslideSourceRegion(Bounds intersection, Bounds layerBounds, int sourceWidth, int sourceHeight) {
        double width = Math.max(1e-9d, layerBounds.maxX - layerBounds.minX);
        double height = Math.max(1e-9d, layerBounds.maxY - layerBounds.minY);
        int minX = clampInt((int) Math.floor((intersection.minX - layerBounds.minX) / width * sourceWidth), 0, sourceWidth - 1);
        int maxX = clampInt((int) Math.ceil((intersection.maxX - layerBounds.minX) / width * sourceWidth), minX + 1, sourceWidth);
        int minY = clampInt((int) Math.floor((layerBounds.maxY - intersection.maxY) / height * sourceHeight), 0, sourceHeight - 1);
        int maxY = clampInt((int) Math.ceil((layerBounds.maxY - intersection.minY) / height * sourceHeight), minY + 1, sourceHeight);
        return new Rectangle(minX, minY, maxX - minX, maxY - minY);
    }

    private void drawSampledLandslideImage(BufferedImage canvasImage, Raster raster, Map<Integer, Integer> colorMap,
            Rectangle sourceRegion, int sampling, Bounds projectedLayerBounds, GeoBounds requestedBounds,
            CanvasSize canvas, int sourceWidth, int sourceHeight) {
        int width = raster.getWidth();
        int height = raster.getHeight();
        int[] row = new int[width];
        double projectedWidth = Math.max(1e-9d, projectedLayerBounds.maxX - projectedLayerBounds.minX);
        double projectedHeight = Math.max(1e-9d, projectedLayerBounds.maxY - projectedLayerBounds.minY);
        double requestGeoWidth = Math.max(1e-9d, requestedBounds.east - requestedBounds.west);
        double requestGeoHeight = Math.max(1e-9d, requestedBounds.north - requestedBounds.south);

        Graphics2D g = canvasImage.createGraphics();
        try {
            for (int y = 0; y < height; y++) {
                raster.getSamples(0, y, width, 1, 0, row);
                double sourceY1 = sourceRegion.y + (y * sampling);
                double sourceY2 = Math.min(sourceHeight, sourceY1 + sampling);
                double projectedNorthY = projectedLayerBounds.maxY - (sourceY1 / Math.max(1.0d, sourceHeight)) * projectedHeight;
                double projectedSouthY = projectedLayerBounds.maxY - (sourceY2 / Math.max(1.0d, sourceHeight)) * projectedHeight;

                for (int x = 0; x < width; x++) {
                    int value = row[x];
                    Integer rgb = colorMap.get(Integer.valueOf(value));
                    if (rgb == null || value == LANDSLIDE_NO_DATA) {
                        continue;
                    }

                    double sourceX1 = sourceRegion.x + (x * sampling);
                    double sourceX2 = Math.min(sourceWidth, sourceX1 + sampling);
                    double projectedWestX = projectedLayerBounds.minX + (sourceX1 / Math.max(1.0d, sourceWidth)) * projectedWidth;
                    double projectedEastX = projectedLayerBounds.minX + (sourceX2 / Math.max(1.0d, sourceWidth)) * projectedWidth;
                    GeoPoint northWest = projectToGeo(projectedWestX, projectedNorthY);
                    GeoPoint northEast = projectToGeo(projectedEastX, projectedNorthY);
                    GeoPoint southWest = projectToGeo(projectedWestX, projectedSouthY);
                    GeoPoint southEast = projectToGeo(projectedEastX, projectedSouthY);
                    double westLon = min4(northWest.lon, northEast.lon, southWest.lon, southEast.lon);
                    double eastLon = max4(northWest.lon, northEast.lon, southWest.lon, southEast.lon);
                    double northLat = max4(northWest.lat, northEast.lat, southWest.lat, southEast.lat);
                    double southLat = min4(northWest.lat, northEast.lat, southWest.lat, southEast.lat);
                    int canvasY1 = (int) Math.floor((requestedBounds.north - northLat) / requestGeoHeight * canvas.height);
                    int canvasY2 = (int) Math.ceil((requestedBounds.north - southLat) / requestGeoHeight * canvas.height);
                    canvasY1 = clampInt(canvasY1, 0, canvas.height);
                    canvasY2 = clampInt(canvasY2, canvasY1 + 1, canvas.height);
                    if (canvasY1 >= canvas.height || canvasY2 <= 0) {
                        continue;
                    }
                    int canvasX1 = (int) Math.floor((westLon - requestedBounds.west) / requestGeoWidth * canvas.width);
                    int canvasX2 = (int) Math.ceil((eastLon - requestedBounds.west) / requestGeoWidth * canvas.width);
                    canvasX1 = clampInt(canvasX1, 0, canvas.width);
                    canvasX2 = clampInt(canvasX2, canvasX1 + 1, canvas.width);
                    if (canvasX1 >= canvas.width || canvasX2 <= 0) {
                        continue;
                    }
                    g.setColor(new Color((resolveLandslideAlpha(value) << 24) | rgb.intValue(), true));
                    g.fillRect(canvasX1, canvasY1, canvasX2 - canvasX1, canvasY2 - canvasY1);
                }
            }
        } finally {
            g.dispose();
        }
    }

    private GeoBounds mergeGeoBounds(GeoBounds a, GeoBounds b) {
        if (a == null) {
            return b;
        }
        if (b == null) {
            return a;
        }
        return new GeoBounds(
                Math.min(a.west, b.west),
                Math.min(a.south, b.south),
                Math.max(a.east, b.east),
                Math.max(a.north, b.north)
        );
    }

    private Bounds resolveProjectedBounds(WorldFile worldFile, int sourceWidth, int sourceHeight) {
        double minX = worldFile.originX - (worldFile.pixelWidth / 2.0d);
        double maxY = worldFile.originY + (Math.abs(worldFile.pixelHeight) / 2.0d);
        double maxX = minX + worldFile.pixelWidth * sourceWidth;
        double minY = maxY - Math.abs(worldFile.pixelHeight) * sourceHeight;
        return new Bounds(minX, minY, maxX, maxY);
    }

    private GeoBounds projectBoundsToGeoBounds(Bounds projectedBounds) {
        GeoPoint northWest = projectToGeo(projectedBounds.minX, projectedBounds.maxY);
        GeoPoint northEast = projectToGeo(projectedBounds.maxX, projectedBounds.maxY);
        GeoPoint southWest = projectToGeo(projectedBounds.minX, projectedBounds.minY);
        GeoPoint southEast = projectToGeo(projectedBounds.maxX, projectedBounds.minY);
        return new GeoBounds(
                min4(northWest.lon, northEast.lon, southWest.lon, southEast.lon),
                min4(northWest.lat, northEast.lat, southWest.lat, southEast.lat),
                max4(northWest.lon, northEast.lon, southWest.lon, southEast.lon),
                max4(northWest.lat, northEast.lat, southWest.lat, southEast.lat)
        );
    }

    private Bounds projectGeoBoundsToProjectedBounds(GeoBounds geoBounds) {
        ProjectedPoint northWest = geoToProjected(geoBounds.west, geoBounds.north);
        ProjectedPoint northEast = geoToProjected(geoBounds.east, geoBounds.north);
        ProjectedPoint southWest = geoToProjected(geoBounds.west, geoBounds.south);
        ProjectedPoint southEast = geoToProjected(geoBounds.east, geoBounds.south);
        return new Bounds(
                min4(northWest.x, northEast.x, southWest.x, southEast.x),
                min4(northWest.y, northEast.y, southWest.y, southEast.y),
                max4(northWest.x, northEast.x, southWest.x, southEast.x),
                max4(northWest.y, northEast.y, southWest.y, southEast.y)
        );
    }

    private static double meridionalArc(double lat) {
        return KOREA_2000_A * (
                (1.0d - KOREA_2000_E2 / 4.0d - 3.0d * Math.pow(KOREA_2000_E2, 2) / 64.0d - 5.0d * Math.pow(KOREA_2000_E2, 3) / 256.0d) * lat
                - (3.0d * KOREA_2000_E2 / 8.0d + 3.0d * Math.pow(KOREA_2000_E2, 2) / 32.0d + 45.0d * Math.pow(KOREA_2000_E2, 3) / 1024.0d) * Math.sin(2.0d * lat)
                + (15.0d * Math.pow(KOREA_2000_E2, 2) / 256.0d + 45.0d * Math.pow(KOREA_2000_E2, 3) / 1024.0d) * Math.sin(4.0d * lat)
                - (35.0d * Math.pow(KOREA_2000_E2, 3) / 3072.0d) * Math.sin(6.0d * lat)
        );
    }

    private GeoPoint projectToGeo(double x, double y) {
        double m = KOREA_2000_M0 + (y - KOREA_2000_FALSE_NORTHING) / KOREA_2000_SCALE;
        double mu = m / (KOREA_2000_A * (1.0d - KOREA_2000_E2 / 4.0d - 3.0d * Math.pow(KOREA_2000_E2, 2) / 64.0d - 5.0d * Math.pow(KOREA_2000_E2, 3) / 256.0d));
        double e1 = (1.0d - Math.sqrt(1.0d - KOREA_2000_E2)) / (1.0d + Math.sqrt(1.0d - KOREA_2000_E2));
        double j1 = 3.0d * e1 / 2.0d - 27.0d * Math.pow(e1, 3) / 32.0d;
        double j2 = 21.0d * Math.pow(e1, 2) / 16.0d - 55.0d * Math.pow(e1, 4) / 32.0d;
        double j3 = 151.0d * Math.pow(e1, 3) / 96.0d;
        double j4 = 1097.0d * Math.pow(e1, 4) / 512.0d;
        double fp = mu + j1 * Math.sin(2.0d * mu) + j2 * Math.sin(4.0d * mu) + j3 * Math.sin(6.0d * mu) + j4 * Math.sin(8.0d * mu);
        double sinFp = Math.sin(fp);
        double cosFp = Math.cos(fp);
        double tanFp = Math.tan(fp);
        double c1 = KOREA_2000_EP2 * cosFp * cosFp;
        double t1 = tanFp * tanFp;
        double n1 = KOREA_2000_A / Math.sqrt(1.0d - KOREA_2000_E2 * sinFp * sinFp);
        double r1 = KOREA_2000_A * (1.0d - KOREA_2000_E2) / Math.pow(1.0d - KOREA_2000_E2 * sinFp * sinFp, 1.5d);
        double d = (x - KOREA_2000_FALSE_EASTING) / (n1 * KOREA_2000_SCALE);
        double lat = fp - (n1 * tanFp / r1) * (
                d * d / 2.0d
                - (5.0d + 3.0d * t1 + 10.0d * c1 - 4.0d * c1 * c1 - 9.0d * KOREA_2000_EP2) * Math.pow(d, 4) / 24.0d
                + (61.0d + 90.0d * t1 + 298.0d * c1 + 45.0d * t1 * t1 - 252.0d * KOREA_2000_EP2 - 3.0d * c1 * c1) * Math.pow(d, 6) / 720.0d
        );
        double lon = KOREA_2000_LON0 + (
                d
                - (1.0d + 2.0d * t1 + c1) * Math.pow(d, 3) / 6.0d
                + (5.0d - 2.0d * c1 + 28.0d * t1 - 3.0d * c1 * c1 + 8.0d * KOREA_2000_EP2 + 24.0d * t1 * t1) * Math.pow(d, 5) / 120.0d
        ) / cosFp;
        return new GeoPoint(Math.toDegrees(lon), Math.toDegrees(lat));
    }

    private ProjectedPoint geoToProjected(double lon, double lat) {
        double latRad = Math.toRadians(lat);
        double lonRad = Math.toRadians(lon);
        double sinLat = Math.sin(latRad);
        double cosLat = Math.cos(latRad);
        double tanLat = Math.tan(latRad);
        double n = KOREA_2000_A / Math.sqrt(1.0d - KOREA_2000_E2 * sinLat * sinLat);
        double t = tanLat * tanLat;
        double c = KOREA_2000_EP2 * cosLat * cosLat;
        double aTerm = (lonRad - KOREA_2000_LON0) * cosLat;
        double m = meridionalArc(latRad);
        double x = KOREA_2000_FALSE_EASTING + KOREA_2000_SCALE * n * (
                aTerm
                + (1.0d - t + c) * Math.pow(aTerm, 3) / 6.0d
                + (5.0d - 18.0d * t + t * t + 72.0d * c - 58.0d * KOREA_2000_EP2) * Math.pow(aTerm, 5) / 120.0d
        );
        double y = KOREA_2000_FALSE_NORTHING + KOREA_2000_SCALE * (
                m - KOREA_2000_M0
                + n * tanLat * (
                        Math.pow(aTerm, 2) / 2.0d
                        + (5.0d - t + 9.0d * c + 4.0d * c * c) * Math.pow(aTerm, 4) / 24.0d
                        + (61.0d - 58.0d * t + t * t + 600.0d * c - 330.0d * KOREA_2000_EP2) * Math.pow(aTerm, 6) / 720.0d
                )
        );
        return new ProjectedPoint(x, y);
    }

    private double min4(double a, double b, double c, double d) {
        return Math.min(Math.min(a, b), Math.min(c, d));
    }

    private double max4(double a, double b, double c, double d) {
        return Math.max(Math.max(a, b), Math.max(c, d));
    }

    private int resolveLandslideAlpha(int value) {
        if (value <= 1) {
            return 182;
        }
        if (value == 2) {
            return 172;
        }
        if (value == 3) {
            return 156;
        }
        if (value == 4) {
            return 144;
        }
        return 134;
    }

    private void drawLandslideBaseMap(BufferedImage canvasImage, GeoBounds geoBounds, CanvasSize canvas) {
        Graphics2D g = canvasImage.createGraphics();
        try {
            g.setColor(new Color(230, 236, 242));
            g.fillRect(0, 0, canvas.width, canvas.height);

            drawTileLayer(g, geoBounds, canvas, VWORLD_SATELLITE_TILE_URL);
            drawTileLayer(g, geoBounds, canvas, VWORLD_HYBRID_TILE_URL);
        } catch (Exception e) {
            LOGGER.warn("failed to draw landslide basemap", e);
        } finally {
            g.dispose();
        }
    }

    private void drawTileLayer(Graphics2D g, GeoBounds geoBounds, CanvasSize canvas, String tileUrlPattern) {
        double minPixelX = lonToGlobalPixelX(geoBounds.west, LANDSLIDE_BASEMAP_ZOOM);
        double maxPixelX = lonToGlobalPixelX(geoBounds.east, LANDSLIDE_BASEMAP_ZOOM);
        double minPixelY = latToGlobalPixelY(geoBounds.north, LANDSLIDE_BASEMAP_ZOOM);
        double maxPixelY = latToGlobalPixelY(geoBounds.south, LANDSLIDE_BASEMAP_ZOOM);
        double pixelWidth = Math.max(1.0d, maxPixelX - minPixelX);
        double pixelHeight = Math.max(1.0d, maxPixelY - minPixelY);

        int minTileX = (int) Math.floor(minPixelX / LANDSLIDE_TILE_SIZE);
        int maxTileX = (int) Math.floor((maxPixelX - 1.0d) / LANDSLIDE_TILE_SIZE);
        int minTileY = (int) Math.floor(minPixelY / LANDSLIDE_TILE_SIZE);
        int maxTileY = (int) Math.floor((maxPixelY - 1.0d) / LANDSLIDE_TILE_SIZE);
        int tileCount = 1 << LANDSLIDE_BASEMAP_ZOOM;

        for (int tileX = minTileX; tileX <= maxTileX; tileX++) {
            for (int tileY = minTileY; tileY <= maxTileY; tileY++) {
                int wrappedX = wrapTileIndex(tileX, tileCount);
                if (tileY < 0 || tileY >= tileCount) {
                    continue;
                }

                BufferedImage tileImage = readRemoteTile(String.format(Locale.ROOT, tileUrlPattern, LANDSLIDE_BASEMAP_ZOOM, wrappedX, tileY));
                if (tileImage == null) {
                    continue;
                }

                double tileMinPixelX = tileX * LANDSLIDE_TILE_SIZE;
                double tileMaxPixelX = tileMinPixelX + LANDSLIDE_TILE_SIZE;
                double tileMinPixelY = tileY * LANDSLIDE_TILE_SIZE;
                double tileMaxPixelY = tileMinPixelY + LANDSLIDE_TILE_SIZE;

                int drawX1 = (int) Math.round((tileMinPixelX - minPixelX) / pixelWidth * canvas.width);
                int drawX2 = (int) Math.round((tileMaxPixelX - minPixelX) / pixelWidth * canvas.width);
                int drawY1 = (int) Math.round((tileMinPixelY - minPixelY) / pixelHeight * canvas.height);
                int drawY2 = (int) Math.round((tileMaxPixelY - minPixelY) / pixelHeight * canvas.height);

                g.drawImage(tileImage, drawX1, drawY1, drawX2, drawY2, 0, 0, tileImage.getWidth(), tileImage.getHeight(), null);
            }
        }
    }

    private BufferedImage readRemoteTile(String urlText) {
        try {
            return ImageIO.read(new URL(urlText));
        } catch (IOException e) {
            return null;
        }
    }

    private int wrapTileIndex(int value, int max) {
        int wrapped = value % max;
        return wrapped < 0 ? wrapped + max : wrapped;
    }

    private double lonToGlobalPixelX(double lon, int zoom) {
        double worldSize = LANDSLIDE_TILE_SIZE * Math.pow(2.0d, zoom);
        return ((lon + 180.0d) / 360.0d) * worldSize;
    }

    private double latToGlobalPixelY(double lat, int zoom) {
        double sinLat = Math.sin(Math.toRadians(lat));
        double worldSize = LANDSLIDE_TILE_SIZE * Math.pow(2.0d, zoom);
        double mercatorY = 0.5d - (Math.log((1.0d + sinLat) / (1.0d - sinLat)) / (4.0d * Math.PI));
        return mercatorY * worldSize;
    }

    private Map<Integer, Integer> loadLandslideColorMap(File clrResource) throws IOException {
        Map<Integer, Integer> colorMap = new HashMap<Integer, Integer>();
        try (InputStream input = java.nio.file.Files.newInputStream(clrResource.toPath())) {
            String text = new String(readAll(input), StandardCharsets.UTF_8);
            String[] lines = text.split("\\r?\\n");
            for (String line : lines) {
                String trimmed = line == null ? "" : line.trim();
                if (trimmed.isEmpty() || trimmed.startsWith("#")) {
                    continue;
                }
                String[] parts = trimmed.split("\\s+");
                if (parts.length < 4) {
                    continue;
                }
                int value = Integer.parseInt(parts[0]);
                int red = clampColor(parts[1]);
                int green = clampColor(parts[2]);
                int blue = clampColor(parts[3]);
                int rgb = (red << 16) | (green << 8) | blue;
                colorMap.put(Integer.valueOf(value), Integer.valueOf(rgb));
            }
        }
        return Collections.unmodifiableMap(colorMap);
    }

    private GeoBounds loadGeoBounds(File xmlResource) throws IOException {
        try (InputStream input = java.nio.file.Files.newInputStream(xmlResource.toPath())) {
            DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
            factory.setNamespaceAware(false);
            Document document = factory.newDocumentBuilder().parse(input);
            NodeList boxes = document.getElementsByTagName("GeoBndBox");
            if (boxes == null || boxes.getLength() == 0) {
                throw new IOException("GeoBndBox not found in " + xmlResource.getPath());
            }
            Element box = (Element) boxes.item(0);
            double west = parseGeoBoundValue(box, "westBL");
            double east = parseGeoBoundValue(box, "eastBL");
            double north = parseGeoBoundValue(box, "northBL");
            double south = parseGeoBoundValue(box, "southBL");
            return new GeoBounds(west, south, east, north);
        } catch (IOException e) {
            throw e;
        } catch (Exception e) {
            throw new IOException("Failed to parse landslide metadata: " + xmlResource.getPath(), e);
        }
    }

    private double parseGeoBoundValue(Element box, String tagName) throws IOException {
        NodeList nodes = box.getElementsByTagName(tagName);
        if (nodes == null || nodes.getLength() == 0) {
            throw new IOException("Missing " + tagName + " in landslide metadata");
        }
        return Double.parseDouble(nodes.item(0).getTextContent().trim());
    }

    private WorldFile loadWorldFile(File tfwResource) throws IOException {
        List<Double> values = new ArrayList<Double>();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(java.nio.file.Files.newInputStream(tfwResource.toPath()), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                String trimmed = line.trim();
                if (!trimmed.isEmpty()) {
                    values.add(Double.valueOf(Double.parseDouble(trimmed)));
                }
            }
        }
        if (values.size() < 6) {
            throw new IOException("Invalid world file: " + tfwResource.getPath());
        }
        return new WorldFile(
                values.get(0).doubleValue(),
                values.get(3).doubleValue(),
                values.get(4).doubleValue(),
                values.get(5).doubleValue()
        );
    }

    private Bounds mergeBounds(List<LandslideLayer> layers) {
        double minX = Double.POSITIVE_INFINITY;
        double minY = Double.POSITIVE_INFINITY;
        double maxX = Double.NEGATIVE_INFINITY;
        double maxY = Double.NEGATIVE_INFINITY;
        for (LandslideLayer layer : layers) {
            minX = Math.min(minX, layer.bounds.minX);
            minY = Math.min(minY, layer.bounds.minY);
            maxX = Math.max(maxX, layer.bounds.maxX);
            maxY = Math.max(maxY, layer.bounds.maxY);
        }
        return new Bounds(minX, minY, maxX, maxY);
    }

    private GeoBounds mergeGeoBounds(List<LandslideLayer> layers) {
        double west = Double.POSITIVE_INFINITY;
        double south = Double.POSITIVE_INFINITY;
        double east = Double.NEGATIVE_INFINITY;
        double north = Double.NEGATIVE_INFINITY;
        for (LandslideLayer layer : layers) {
            west = Math.min(west, layer.geoBounds.west);
            south = Math.min(south, layer.geoBounds.south);
            east = Math.max(east, layer.geoBounds.east);
            north = Math.max(north, layer.geoBounds.north);
        }
        return new GeoBounds(west, south, east, north);
    }

    private CanvasSize resolveLandslideCanvasSize(Bounds bounds) {
        double worldWidth = Math.max(1.0d, bounds.maxX - bounds.minX);
        double worldHeight = Math.max(1.0d, bounds.maxY - bounds.minY);
        double scale = Math.min(LANDSLIDE_TARGET_WIDTH / worldWidth, LANDSLIDE_TARGET_HEIGHT / worldHeight);
        int width = Math.max(1, (int) Math.round(worldWidth * scale));
        int height = Math.max(1, (int) Math.round(worldHeight * scale));
        return new CanvasSize(width, height, scale);
    }

    private void drawLandslideOverlay(BufferedImage canvasImage, GeoBounds geoBounds, CanvasSize canvas) {
        try {
            File polygonFile = resolveDataFile(APPROX_RISK_GEOJSON_PATH);
            File lineFile = resolveDataFile(APPROX_RISK_LINES_GEOJSON_PATH);
            if (!polygonFile.exists() || !lineFile.exists()) {
                return;
            }

            JsonNode polygonRoot = objectMapper.readTree(polygonFile);
            JsonNode lineRoot = objectMapper.readTree(lineFile);

            Graphics2D g = canvasImage.createGraphics();
            try {
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
                g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING, RenderingHints.VALUE_TEXT_ANTIALIAS_ON);

                drawInternalBoundaryLines(g, lineRoot.path("features"), geoBounds, canvas);
            } finally {
                g.dispose();
            }
        } catch (Exception e) {
            LOGGER.warn("failed to draw landslide overlay", e);
        }
    }

    private void drawLandslideLegend(BufferedImage canvasImage, CanvasSize canvas) {
        Graphics2D g = canvasImage.createGraphics();
        try {
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
            int panelWidth = 210;
            int panelHeight = 164;
            int x = canvas.width - panelWidth - 18;
            int y = canvas.height - panelHeight - 18;

            g.setColor(LANDSLIDE_PANEL_BG);
            g.fillRoundRect(x, y, panelWidth, panelHeight, 18, 18);
            g.setColor(LANDSLIDE_PANEL_BORDER);
            g.setStroke(new BasicStroke(1.0f));
            g.drawRoundRect(x, y, panelWidth, panelHeight, 18, 18);

            g.setFont(new Font("Malgun Gothic", Font.BOLD, 16));
            g.setColor(new Color(255, 255, 255, 232));
            g.drawString("산사태 위험등급", x + 16, y + 28);

            g.setFont(new Font("Malgun Gothic", Font.PLAIN, 12));
            String[] labels = new String[] {
                    "1등급 매우 높음",
                    "2등급 높음",
                    "3등급 보통",
                    "4등급 낮음",
                    "5등급 매우 낮음"
            };
            int[] colors = new int[] {
                    0xE53935,
                    0xFDD835,
                    0x43A047,
                    0x4FC3F7,
                    0x1E88E5
            };
            for (int i = 0; i < labels.length; i++) {
                int rowY = y + 50 + (i * 20);
                g.setColor(new Color(colors[i]));
                g.fillRoundRect(x + 16, rowY - 10, 18, 12, 5, 5);
                g.setColor(new Color(255, 255, 255, 222));
                g.drawString(labels[i], x + 42, rowY);
            }
        } finally {
            g.dispose();
        }
    }

    private void drawLandslideTimestamp(BufferedImage canvasImage, CanvasSize canvas) {
        Graphics2D g = canvasImage.createGraphics();
        try {
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
            String timestamp = "자료 기준: " + LocalDateTime.now(ZoneId.of(KST_ZONE_ID))
                    .format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"));
            String note = "자료: 산림청 산사태위험지도(광주/전남/정읍)";

            g.setFont(new Font("Malgun Gothic", Font.BOLD, 13));
            FontMetrics fm = g.getFontMetrics();
            int width = Math.max(fm.stringWidth(timestamp), fm.stringWidth(note)) + 28;
            int height = 50;
            int x = 18;
            int y = canvas.height - height - 18;

            g.setColor(LANDSLIDE_PANEL_BG);
            g.fillRoundRect(x, y, width, height, 16, 16);
            g.setColor(LANDSLIDE_PANEL_BORDER);
            g.drawRoundRect(x, y, width, height, 16, 16);

            g.setColor(new Color(255, 255, 255, 226));
            g.drawString(timestamp, x + 14, y + 21);
            g.setFont(new Font("Malgun Gothic", Font.PLAIN, 12));
            g.drawString(note, x + 14, y + 39);
        } finally {
            g.dispose();
        }
    }

    private void drawInternalBoundaryLines(Graphics2D g, JsonNode features, GeoBounds geoBounds, CanvasSize canvas) {
        for (JsonNode feature : features) {
            JsonNode properties = feature.path("properties");
            String regionNm = properties.path("regionNm").asText("");
            String lineType = properties.path("lineType").asText("");
            JsonNode geometry = feature.path("geometry");
            if (!"MultiLineString".equals(geometry.path("type").asText(""))) {
                continue;
            }

            if ("광주".equals(regionNm) && "outer-boundary".equals(lineType)) {
                continue;
            } else if ("광주".equals(regionNm)) {
                g.setColor(new Color(22, 33, 48, 170));
                g.setStroke(new BasicStroke(1.4f, BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
            } else {
                g.setColor(new Color(35, 46, 58, 120));
                g.setStroke(new BasicStroke(1.1f, BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
            }

            for (JsonNode line : geometry.path("coordinates")) {
                Path2D path = buildBoundaryPath(line, geoBounds, canvas, resolveBoundaryMinDistance(regionNm, lineType));
                if (path.getCurrentPoint() != null) {
                    g.setColor(new Color(255, 255, 255, 135));
                    g.setStroke(new BasicStroke(resolveBoundaryHaloWidth(regionNm, lineType), BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
                    g.draw(path);

                    if ("광주".equals(regionNm)) {
                        g.setColor(new Color(18, 30, 47, 190));
                        g.setStroke(new BasicStroke(1.8f, BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
                    } else {
                        g.setColor(new Color(27, 40, 53, 165));
                        g.setStroke(new BasicStroke(1.45f, BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
                    }
                    g.draw(path);
                }
            }
        }
    }

    private Path2D buildBoundaryPath(JsonNode line, GeoBounds geoBounds, CanvasSize canvas, double minDistancePx) {
        Path2D path = new Path2D.Double();
        boolean moved = false;
        double lastX = 0.0d;
        double lastY = 0.0d;
        for (JsonNode point : line) {
            if (point.size() < 2) {
                continue;
            }
            double lon = point.get(0).asDouble();
            double lat = point.get(1).asDouble();
            double x = (lon - geoBounds.west) / Math.max(1e-9d, geoBounds.east - geoBounds.west) * canvas.width;
            double y = (geoBounds.north - lat) / Math.max(1e-9d, geoBounds.north - geoBounds.south) * canvas.height;
            if (!moved) {
                path.moveTo(x, y);
                moved = true;
                lastX = x;
                lastY = y;
                continue;
            }

            double dx = x - lastX;
            double dy = y - lastY;
            if ((dx * dx) + (dy * dy) < (minDistancePx * minDistancePx)) {
                continue;
            }

            path.lineTo(x, y);
            lastX = x;
            lastY = y;
        }
        return path;
    }

    private double resolveBoundaryMinDistance(String regionNm, String lineType) {
        if ("광주".equals(regionNm)) {
            return 2.4d;
        }
        return 3.0d;
    }

    private float resolveBoundaryHaloWidth(String regionNm, String lineType) {
        if ("광주".equals(regionNm)) {
            return 3.9f;
        }
        return 3.2f;
    }

    private void drawRegionLabels(Graphics2D g, JsonNode features, GeoBounds geoBounds, CanvasSize canvas) {
        Map<String, LabelBounds> labelBounds = new LinkedHashMap<String, LabelBounds>();
        for (JsonNode feature : features) {
            String regionNm = feature.path("properties").path("regionNm").asText("");
            if (!"광주".equals(regionNm) && !"전남".equals(regionNm)) {
                continue;
            }
            collectPolygonBounds(feature.path("geometry"), labelBounds.computeIfAbsent(regionNm, key -> new LabelBounds()));
        }

        g.setFont(new Font("Malgun Gothic", Font.BOLD, 18));
        for (Map.Entry<String, LabelBounds> entry : labelBounds.entrySet()) {
            LabelBounds bounds = entry.getValue();
            if (!bounds.initialized) {
                continue;
            }
            double lon = (bounds.minLon + bounds.maxLon) / 2.0d;
            double lat = (bounds.minLat + bounds.maxLat) / 2.0d;
            int x = (int) Math.round((lon - geoBounds.west) / Math.max(1e-9d, geoBounds.east - geoBounds.west) * canvas.width);
            int y = (int) Math.round((geoBounds.north - lat) / Math.max(1e-9d, geoBounds.north - geoBounds.south) * canvas.height);
            String text = "광주".equals(entry.getKey()) ? "광주광역시" : "전라남도";
            g.setColor(new Color(255, 255, 255, 210));
            g.drawString(text, x - 2, y - 2);
            g.setColor(new Color(17, 24, 39, 210));
            g.drawString(text, x, y);
        }
    }

    private void drawDistrictLabels(Graphics2D g, JsonNode features, GeoBounds geoBounds, CanvasSize canvas) {
        g.setFont(new Font("Malgun Gothic", Font.BOLD, 12));
        for (JsonNode feature : features) {
            JsonNode properties = feature.path("properties");
            String districtNm = properties.path("districtNm").asText("");
            if (districtNm.isEmpty()) {
                continue;
            }

            LabelBounds bounds = new LabelBounds();
            collectPolygonBounds(feature.path("geometry"), bounds);
            if (!bounds.initialized) {
                continue;
            }

            double lon = (bounds.minLon + bounds.maxLon) / 2.0d;
            double lat = (bounds.minLat + bounds.maxLat) / 2.0d;
            int x = (int) Math.round((lon - geoBounds.west) / Math.max(1e-9d, geoBounds.east - geoBounds.west) * canvas.width);
            int y = (int) Math.round((geoBounds.north - lat) / Math.max(1e-9d, geoBounds.north - geoBounds.south) * canvas.height);

            g.setColor(new Color(255, 255, 255, 225));
            g.drawString(districtNm, x - 1, y - 1);
            g.drawString(districtNm, x + 1, y - 1);
            g.drawString(districtNm, x - 1, y + 1);
            g.drawString(districtNm, x + 1, y + 1);

            g.setColor(new Color(19, 27, 36, 220));
            g.drawString(districtNm, x, y);
        }
    }

    private void collectPolygonBounds(JsonNode geometry, LabelBounds bounds) {
        String type = geometry.path("type").asText("");
        if ("Polygon".equals(type)) {
            for (JsonNode ring : geometry.path("coordinates")) {
                collectPoints(ring, bounds);
            }
            return;
        }
        if ("MultiPolygon".equals(type)) {
            for (JsonNode polygon : geometry.path("coordinates")) {
                for (JsonNode ring : polygon) {
                    collectPoints(ring, bounds);
                }
            }
        }
    }

    private void collectPoints(JsonNode points, LabelBounds bounds) {
        for (JsonNode point : points) {
            if (point.size() < 2) {
                continue;
            }
            double lon = point.get(0).asDouble();
            double lat = point.get(1).asDouble();
            bounds.include(lon, lat);
        }
    }

    private File resolveProjectFile(String relativePath) {
        String projectRoot = System.getProperty("risk.project.root");
        if (isBlank(projectRoot)) {
            projectRoot = System.getenv("RISK_PROJECT_ROOT");
        }
        if (isBlank(projectRoot)) {
            projectRoot = new File(".").getAbsolutePath();
        }
        return new File(projectRoot, relativePath);
    }

    private File resolveDataFile(String relativePath) {
        return resolveProjectFile(relativePath);
    }

    private ResponseEntity<String> errorTextString(String message, HttpStatus status) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(new MediaType("text", "plain", StandardCharsets.UTF_8));
        headers.setCacheControl("no-store, no-cache, must-revalidate, max-age=0");
        headers.setPragma("no-cache");
        headers.setExpires(0L);
        return new ResponseEntity<String>(message, headers, status);
    }

    private int clampColor(String raw) {
        int value = Integer.parseInt(raw);
        return Math.max(0, Math.min(255, value));
    }

    private static final class LandslideRasterSpec {
        private final String code;
        private final String tifResourcePath;
        private final String clrResourcePath;
        private final String tfwResourcePath;
        private final String xmlResourcePath;

        private LandslideRasterSpec(String code, String tifResourcePath, String clrResourcePath, String tfwResourcePath) {
            this.code = code;
            this.tifResourcePath = tifResourcePath;
            this.clrResourcePath = clrResourcePath;
            this.tfwResourcePath = tfwResourcePath;
            this.xmlResourcePath = tifResourcePath + ".xml";
        }
    }

    private static final class WorldFile {
        private final double pixelWidth;
        private final double pixelHeight;
        private final double originX;
        private final double originY;

        private WorldFile(double pixelWidth, double pixelHeight, double originX, double originY) {
            this.pixelWidth = pixelWidth;
            this.pixelHeight = pixelHeight;
            this.originX = originX;
            this.originY = originY;
        }
    }

    private static final class Bounds {
        private final double minX;
        private final double minY;
        private final double maxX;
        private final double maxY;

        private Bounds(double minX, double minY, double maxX, double maxY) {
            this.minX = minX;
            this.minY = minY;
            this.maxX = maxX;
            this.maxY = maxY;
        }
    }

    private static final class GeoBounds {
        private final double west;
        private final double south;
        private final double east;
        private final double north;

        private GeoBounds(double west, double south, double east, double north) {
            this.west = west;
            this.south = south;
            this.east = east;
            this.north = north;
        }
    }

    private static final class GeoPoint {
        private final double lon;
        private final double lat;

        private GeoPoint(double lon, double lat) {
            this.lon = lon;
            this.lat = lat;
        }
    }

    private static final class ProjectedPoint {
        private final double x;
        private final double y;

        private ProjectedPoint(double x, double y) {
            this.x = x;
            this.y = y;
        }
    }

    private static final class CanvasSize {
        private final int width;
        private final int height;
        private final double scale;

        private CanvasSize(int width, int height, double scale) {
            this.width = width;
            this.height = height;
            this.scale = scale;
        }
    }

    private static final class LandslideLayer {
        private final String code;
        private final Raster raster;
        private final Map<Integer, Integer> colorMap;
        private final Bounds bounds;
        private final GeoBounds geoBounds;
        private final double pixelWidth;
        private final double pixelHeight;

        private LandslideLayer(String code, Raster raster, Map<Integer, Integer> colorMap, Bounds bounds, GeoBounds geoBounds, double pixelWidth, double pixelHeight) {
            this.code = code;
            this.raster = raster;
            this.colorMap = colorMap;
            this.bounds = bounds;
            this.geoBounds = geoBounds;
            this.pixelWidth = pixelWidth;
            this.pixelHeight = pixelHeight;
        }
    }

    private static final class LabelBounds {
        private double minLon;
        private double minLat;
        private double maxLon;
        private double maxLat;
        private boolean initialized;

        private void include(double lon, double lat) {
            if (!initialized) {
                minLon = maxLon = lon;
                minLat = maxLat = lat;
                initialized = true;
                return;
            }
            minLon = Math.min(minLon, lon);
            minLat = Math.min(minLat, lat);
            maxLon = Math.max(maxLon, lon);
            maxLat = Math.max(maxLat, lat);
        }
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
