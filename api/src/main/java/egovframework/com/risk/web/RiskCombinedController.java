package egovframework.com.risk.web;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ConcurrentHashMap;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

import javax.annotation.Resource;
import javax.servlet.http.HttpServletResponse;

import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.CellStyle;
import org.apache.poi.ss.usermodel.HorizontalAlignment;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import egovframework.com.risk.service.RiskCombinedService;
import egovframework.com.risk.util.RiskMapPolygonResolver;
import egovframework.com.risk.vo.RiskCombinedVO;
import egovframework.com.risk.vo.RiskFacilityHistoryVO;
import egovframework.com.risk.vo.RiskSearchVO;

@RestController
public class RiskCombinedController {

    private static final String DEFAULT_MAP_BRANCH_NM = "광주전남본부직할";
    private static final int DEFAULT_MAP_BUILDING_MAX_ROWS = 20000;
    private static final int DEFAULT_MAP_BUILDING_POLYGON_MAX_ROWS = 1200;
    private static final int HARD_MAX_MAP_BUILDING_ROWS = 50000;
    private static final Pattern TRAILING_BUILDING_META =
            Pattern.compile("\\s+\\d{3,}\\s+\\d+\\s+(?:\\uC77C\\uBC18\\uAC74\\uCD95\\uBB3C|\\uC9D1\\uD569\\uAC74\\uCD95\\uBB3C)$");
    private static final Pattern MIDDLE_LOT_MARKER =
            Pattern.compile("\\s+\\d+\\s+\\uC77C\\uBC18\\s+");
    private static final Pattern MULTI_SPACE = Pattern.compile("\\s{2,}");
    private static final Pattern H2_INSERT_META_PATTERN = Pattern.compile(
            "^INSERT INTO TB_BUILDING_RISK .* VALUES \\('(?:[^']|'')*','(?:[^']|'')*','(?:[^']|'')*','((?:[^']|'')*)','((?:[^']|'')*)','(?:[^']|'')*','(?:[^']|'')*','(?:[^']|'')*','((?:[^']|'')*)'.*$"
    );
    private static volatile Map<String, String[]> h2MetaByAddr;

    @Resource(name = "riskCombinedService")
    private RiskCombinedService riskCombinedService;

    @RequestMapping("/selectCombinedList.do")
    public Map<String, Object> selectCombinedList(RiskSearchVO searchVO) {
        int totalCount = riskCombinedService.selectCombinedListCnt(searchVO);
        List<RiskCombinedVO> list = riskCombinedService.selectCombinedList(searchVO);
        normalizeAddr(list);

        Map<String, Object> result = new HashMap<String, Object>();
        result.put("resultCode", "OK");
        result.put("resultMsg", "?깃났");
        result.put("totalCount", totalCount);
        result.put("data", list);
        return result;
    }

    @RequestMapping("/selectCombinedDetail.do")
    public Map<String, Object> selectCombinedDetail(@RequestParam("bldgSeq") long bldgSeq) {
        RiskCombinedVO detail = riskCombinedService.selectCombinedDetail(bldgSeq);
        normalizeAddr(detail);
        applyBuildingMetaFallback(detail);
        List<RiskFacilityHistoryVO> facilityHistory = riskCombinedService.selectLatestFacilityHistory(bldgSeq);

        Map<String, Object> result = new HashMap<String, Object>();
        result.put("resultCode", "OK");
        result.put("resultMsg", "?깃났");
        result.put("data", detail);
        result.put("facilityHistory", facilityHistory);
        return result;
    }

    @RequestMapping("/selectFacilityHistoryDetail.do")
    public Map<String, Object> selectFacilityHistoryDetail(
            @RequestParam("facilityType") String facilityType,
            @RequestParam("histSeq") long histSeq) {
        Map<String, Object> detail = riskCombinedService.selectFacilityHistoryDetail(facilityType, histSeq);
        if (detail != null && detail.containsKey("addr")) {
            detail.put("addr", normalizeAddress(asString(detail.get("addr"))));
        }

        Map<String, Object> result = new HashMap<String, Object>();
        result.put("resultCode", "OK");
        result.put("resultMsg", "OK");
        result.put("data", detail);
        return result;
    }

    @RequestMapping("/selectGradeStats.do")
    public Map<String, Object> selectGradeStats() {
        List<RiskCombinedVO> list = riskCombinedService.selectGradeStats();

        Map<String, Object> result = new HashMap<String, Object>();
        result.put("resultCode", "OK");
        result.put("resultMsg", "?깃났");
        result.put("data", list);
        return result;
    }

    @RequestMapping("/selectHqSummary.do")
    public Map<String, Object> selectHqSummary() {
        List<RiskCombinedVO> list = riskCombinedService.selectHqSummary();

        Map<String, Object> result = new HashMap<String, Object>();
        result.put("resultCode", "OK");
        result.put("resultMsg", "?깃났");
        result.put("totalCount", list.size());
        result.put("data", list);
        return result;
    }

    @RequestMapping("/selectBranchSummary.do")
    public Map<String, Object> selectBranchSummary() {
        List<RiskCombinedVO> list = riskCombinedService.selectBranchSummary();

        Map<String, Object> result = new HashMap<String, Object>();
        result.put("resultCode", "OK");
        result.put("resultMsg", "?깃났");
        result.put("totalCount", list.size());
        result.put("data", list);
        return result;
    }

    @RequestMapping("/selectRegionSummary.do")
    public Map<String, Object> selectRegionSummary() {
        List<RiskCombinedVO> list = riskCombinedService.selectRegionSummary();

        Map<String, Object> result = new HashMap<String, Object>();
        result.put("resultCode", "OK");
        result.put("resultMsg", "?깃났");
        result.put("totalCount", list.size());
        result.put("data", list);
        return result;
    }

    @RequestMapping("/selectRegionDistrictSummary.do")
    public Map<String, Object> selectRegionDistrictSummary() {
        List<RiskCombinedVO> list = riskCombinedService.selectRegionDistrictSummary();

        Map<String, Object> result = new HashMap<String, Object>();
        result.put("resultCode", "OK");
        result.put("resultMsg", "?깃났");
        result.put("totalCount", list.size());
        result.put("data", list);
        return result;
    }

    @RequestMapping("/selectGradeChangedList.do")
    public Map<String, Object> selectGradeChangedList() {
        List<RiskCombinedVO> list = riskCombinedService.selectGradeChangedList();
        normalizeAddr(list);

        Map<String, Object> result = new HashMap<String, Object>();
        result.put("resultCode", "OK");
        result.put("resultMsg", "?깃났");
        result.put("totalCount", list.size());
        result.put("data", list);
        return result;
    }

    @RequestMapping("/selectRiskMapDistrictLayer.do")
    public Map<String, Object> selectRiskMapDistrictLayer(
            @RequestParam(value = "branchNm", required = false) String branchNm) {
        String targetBranchNm = normalizeMapBranchName(branchNm);
        List<Map<String, Object>> list = riskCombinedService.selectRiskMapDistrictLayer(targetBranchNm);
        normalizeRiskMapDistrictRows(list);

        Map<String, Object> result = new HashMap<String, Object>();
        result.put("resultCode", "OK");
        result.put("resultMsg", "OK");
        result.put("branchNm", targetBranchNm);
        result.put("totalCount", list.size());
        result.put("data", list);
        return result;
    }

    @RequestMapping("/selectRiskMapBuildingLayer.do")
    public Map<String, Object> selectRiskMapBuildingLayer(
            @RequestParam(value = "branchNm", required = false) String branchNm,
            @RequestParam(value = "minLon", required = false) Double minLon,
            @RequestParam(value = "minLat", required = false) Double minLat,
            @RequestParam(value = "maxLon", required = false) Double maxLon,
            @RequestParam(value = "maxLat", required = false) Double maxLat,
            @RequestParam(value = "riskCdList", required = false) List<String> riskCdList,
            @RequestParam(value = "maxRows", required = false) Integer maxRows) {
        String targetBranchNm = normalizeMapBranchName(branchNm);
        Double[] bbox = normalizeViewportBbox(minLon, minLat, maxLon, maxLat);
        int targetMaxRows = normalizeMapBuildingMaxRows(maxRows);
        List<String> normalizedRiskCdList = normalizeRiskCdList(riskCdList);
        List<Map<String, Object>> list = riskCombinedService.selectRiskMapBuildingLayer(
                targetBranchNm,
                bbox[0],
                bbox[1],
                bbox[2],
                bbox[3],
                normalizedRiskCdList,
                Integer.valueOf(targetMaxRows));
        normalizeRiskMapBuildingRows(list);
        int totalCount = extractRiskMapBuildingTotalCount(list);
        int visibleCount = list.size();

        Map<String, Object> result = new HashMap<String, Object>();
        result.put("resultCode", "OK");
        result.put("resultMsg", "OK");
        result.put("branchNm", targetBranchNm);
        result.put("totalCount", totalCount);
        result.put("visibleCount", visibleCount);
        result.put("truncated", Boolean.valueOf(totalCount > visibleCount));
        result.put("maxRows", Integer.valueOf(targetMaxRows));
        result.put("data", list);
        return result;
    }

    @RequestMapping("/selectRiskMapBuildingPolygonLayer.do")
    public Map<String, Object> selectRiskMapBuildingPolygonLayer(
            @RequestParam(value = "branchNm", required = false) String branchNm,
            @RequestParam(value = "minLon", required = false) Double minLon,
            @RequestParam(value = "minLat", required = false) Double minLat,
            @RequestParam(value = "maxLon", required = false) Double maxLon,
            @RequestParam(value = "maxLat", required = false) Double maxLat,
            @RequestParam(value = "riskCdList", required = false) List<String> riskCdList,
            @RequestParam(value = "maxRows", required = false) Integer maxRows) {
        String targetBranchNm = normalizeMapBranchName(branchNm);
        Double[] bbox = normalizeViewportBbox(minLon, minLat, maxLon, maxLat);
        int targetMaxRows = normalizeMapBuildingPolygonMaxRows(maxRows);
        List<String> normalizedRiskCdList = normalizeRiskCdList(riskCdList);
        List<Map<String, Object>> list = riskCombinedService.selectRiskMapBuildingLayer(
                targetBranchNm,
                bbox[0],
                bbox[1],
                bbox[2],
                bbox[3],
                normalizedRiskCdList,
                Integer.valueOf(targetMaxRows));
        normalizeRiskMapBuildingRows(list);
        RiskMapPolygonResolver.attachPolygons(targetBranchNm, list, 160);
        int totalCount = extractRiskMapBuildingTotalCount(list);
        int visibleCount = list.size();

        Map<String, Object> result = new HashMap<String, Object>();
        result.put("resultCode", "OK");
        result.put("resultMsg", "OK");
        result.put("branchNm", targetBranchNm);
        result.put("totalCount", totalCount);
        result.put("visibleCount", visibleCount);
        result.put("truncated", Boolean.valueOf(totalCount > visibleCount));
        result.put("maxRows", Integer.valueOf(targetMaxRows));
        result.put("data", list);
        return result;
    }

    @RequestMapping("/downloadDangerBuildingExcel.do")
    public void downloadDangerBuildingExcel(RiskSearchVO searchVO, HttpServletResponse response) throws Exception {
        List<Map<String, Object>> rows = riskCombinedService.selectDangerBuildingExportList(searchVO);

        Workbook workbook = new XSSFWorkbook();
        Sheet sheet = workbook.createSheet("D+E 嫄대Ъ紐⑸줉");

        CellStyle headerStyle = workbook.createCellStyle();
        headerStyle.setAlignment(HorizontalAlignment.CENTER);

        String[] headers = {
            "본부", "사업소", "건물명", "주소", "기본점수", "기본등급", "종합점수", "종합등급", "기상점수"
        };

        Row header = sheet.createRow(0);
        for (int i = 0; i < headers.length; i++) {
            Cell c = header.createCell(i);
            c.setCellValue(headers[i]);
            c.setCellStyle(headerStyle);
        }

        int r = 1;
        for (Map<String, Object> m : rows) {
            Row row = sheet.createRow(r++);
            row.createCell(0).setCellValue(toSafeExcelString(m.get("hqNm")));
            row.createCell(1).setCellValue(toSafeExcelString(m.get("branchNm")));
            row.createCell(2).setCellValue(toSafeExcelString(m.get("bldgNm")));
            row.createCell(3).setCellValue(toSafeExcelString(normalizeAddress(asString(m.get("addr")))));
            row.createCell(4).setCellValue(asDouble(m.get("baseScore")));
            row.createCell(5).setCellValue(toSafeExcelString(m.get("baseGrade")));
            row.createCell(6).setCellValue(asDouble(m.get("combinedScore")));
            row.createCell(7).setCellValue(toSafeExcelString(m.get("combinedGrade")));
            row.createCell(8).setCellValue(asDouble(m.get("weatherScore")));
        }

        for (int i = 0; i < headers.length; i++) {
            sheet.autoSizeColumn(i);
        }

        String fileName = "danger_buildings_" + System.currentTimeMillis() + ".xlsx";
        String encoded = URLEncoder.encode(fileName, "UTF-8").replaceAll("\\+", "%20");

        response.setContentType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
        response.setHeader("Content-Disposition", "attachment; filename*=UTF-8''" + encoded);

        workbook.write(response.getOutputStream());
        workbook.close();
        response.flushBuffer();
    }

    private String asString(Object v) {
        return v == null ? "" : String.valueOf(v);
    }

    private String normalizeMapBranchName(String branchNm) {
        if (branchNm == null) {
            return "\uAD11\uC8FC\uC804\uB0A8\uBCF8\uBD80\uC9C1\uD560";
        }
        String value = branchNm.trim();
        return value.isEmpty() ? "\uAD11\uC8FC\uC804\uB0A8\uBCF8\uBD80\uC9C1\uD560" : value;
    }

    private Double[] normalizeViewportBbox(Double minLon, Double minLat, Double maxLon, Double maxLat) {
        if (!isFiniteNumber(minLon) || !isFiniteNumber(minLat) || !isFiniteNumber(maxLon) || !isFiniteNumber(maxLat)) {
            return new Double[] { null, null, null, null };
        }

        double left = Math.min(minLon.doubleValue(), maxLon.doubleValue());
        double right = Math.max(minLon.doubleValue(), maxLon.doubleValue());
        double bottom = Math.min(minLat.doubleValue(), maxLat.doubleValue());
        double top = Math.max(minLat.doubleValue(), maxLat.doubleValue());
        return new Double[] {
                Double.valueOf(left),
                Double.valueOf(bottom),
                Double.valueOf(right),
                Double.valueOf(top)
        };
    }

    private boolean isFiniteNumber(Double value) {
        return value != null && !value.isNaN() && !value.isInfinite();
    }

    private int normalizeMapBuildingMaxRows(Integer maxRows) {
        if (maxRows == null) {
            return DEFAULT_MAP_BUILDING_MAX_ROWS;
        }
        int value = maxRows.intValue();
        if (value < 100) {
            return 100;
        }
        return Math.min(value, HARD_MAX_MAP_BUILDING_ROWS);
    }

    private int normalizeMapBuildingPolygonMaxRows(Integer maxRows) {
        if (maxRows == null) {
            return DEFAULT_MAP_BUILDING_POLYGON_MAX_ROWS;
        }
        int value = maxRows.intValue();
        if (value < 20) {
            return 20;
        }
        return Math.min(value, DEFAULT_MAP_BUILDING_MAX_ROWS);
    }

    private List<String> normalizeRiskCdList(List<String> riskCdList) {
        if (riskCdList == null || riskCdList.isEmpty()) {
            return null;
        }
        List<String> result = new java.util.ArrayList<String>();
        for (String riskCd : riskCdList) {
            if (riskCd == null) {
                continue;
            }
            String value = riskCd.trim().toUpperCase();
            if (value.matches("[ABCDE]")) {
                result.add(value);
            }
        }
        return result.isEmpty() ? null : result;
    }

    private int extractRiskMapBuildingTotalCount(List<Map<String, Object>> rows) {
        if (rows == null || rows.isEmpty()) {
            return 0;
        }
        Object value = rows.get(0).get("totalMatchedCount");
        if (value == null) {
            value = rows.get(0).get("TOTALMATCHEDCOUNT");
        }
        return toInt(value, rows.size());
    }

    private int toInt(Object value, int defaultValue) {
        if (value == null) {
            return defaultValue;
        }
        if (value instanceof Number) {
            return ((Number) value).intValue();
        }
        try {
            return Integer.parseInt(String.valueOf(value));
        } catch (Exception e) {
            return defaultValue;
        }
    }

    private void normalizeAddressField(List<Map<String, Object>> rows) {
        if (rows == null) {
            return;
        }
        for (Map<String, Object> row : rows) {
            if (row == null) {
                continue;
            }
            if (row.containsKey("addr")) {
                row.put("addr", normalizeAddress(asString(row.get("addr"))));
            }
        }
    }

    private void normalizeRiskMapDistrictRows(List<Map<String, Object>> rows) {
        if (rows == null) {
            return;
        }
        for (Map<String, Object> row : rows) {
            if (row == null) {
                continue;
            }
            putAlias(row, "regionNm", "REGIONNM");
            putAlias(row, "districtNm", "DISTRICTNM");
            putAlias(row, "regionCd", "REGIONCD");
            putAlias(row, "bldgCnt", "BLDGCNT");
            putAlias(row, "avgScore", "AVGSCORE");
            putAlias(row, "maxScore", "MAXSCORE");
            putAlias(row, "centerLon", "CENTERLON");
            putAlias(row, "centerLat", "CENTERLAT");
            putAlias(row, "riskCd", "RISKCD");
            putAlias(row, "riskLabel", "RISKLABEL");
        }
    }

    private void normalizeRiskMapBuildingRows(List<Map<String, Object>> rows) {
        if (rows == null) {
            return;
        }
        for (Map<String, Object> row : rows) {
            if (row == null) {
                continue;
            }
            putAlias(row, "bldgSeq", "BLDGSEQ");
            putAlias(row, "branchNm", "BRANCHNM");
            putAlias(row, "regionNm", "REGIONNM");
            putAlias(row, "districtNm", "DISTRICTNM");
            putAlias(row, "regionCd", "REGIONCD");
            putAlias(row, "bldgNm", "BLDGNM");
            putAlias(row, "addr", "ADDR");
            putAlias(row, "lon", "LON");
            putAlias(row, "lat", "LAT");
            putAlias(row, "baseScore", "BASESCORE");
            putAlias(row, "baseGrade", "BASEGRADE");
            putAlias(row, "baseRiskCd", "BASERISKCD");
            putAlias(row, "totalScore", "TOTALSCORE");
            putAlias(row, "totalGrade", "TOTALGRADE");
            putAlias(row, "combinedScore", "COMBINEDSCORE");
            putAlias(row, "combinedGradeNm", "COMBINEDGRADENM");
            putAlias(row, "combinedRiskCd", "COMBINEDRISKCD");
            putAlias(row, "riskCd", "RISKCD");
            putAlias(row, "totalMatchedCount", "TOTALMATCHEDCOUNT");
            if (row.containsKey("addr")) {
                row.put("addr", normalizeAddress(asString(row.get("addr"))));
            }
        }
    }

    private void putAlias(Map<String, Object> row, String normalizedKey, String sourceKey) {
        if (row.containsKey(normalizedKey) && row.get(normalizedKey) != null) {
            return;
        }
        if (row.containsKey(sourceKey)) {
            row.put(normalizedKey, row.get(sourceKey));
        }
    }

    private String toSafeExcelString(Object v) {
        String value = asString(v);
        if (value.isEmpty()) {
            return value;
        }

        char first = value.charAt(0);
        if (first == '=' || first == '+' || first == '-' || first == '@') {
            return "'" + value;
        }

        return value;
    }

    private double asDouble(Object v) {
        if (v == null) return 0.0d;
        if (v instanceof Number) return ((Number) v).doubleValue();
        try {
            return Double.parseDouble(String.valueOf(v));
        } catch (Exception e) {
            return 0.0d;
        }
    }

    private void normalizeAddr(List<RiskCombinedVO> list) {
        if (list == null) return;
        for (RiskCombinedVO vo : list) {
            normalizeAddr(vo);
        }
    }

    private void normalizeAddr(RiskCombinedVO vo) {
        if (vo == null) return;
        vo.setAddr(normalizeAddress(vo.getAddr()));
    }

    private void applyBuildingMetaFallback(RiskCombinedVO detail) {
        if (detail == null) return;

        if (isBlank(detail.getStructureName()) && !isBlank(detail.getA17())) {
            detail.setStructureName(detail.getA17());
        }
        if (isBlank(detail.getMainUseName()) && !isBlank(detail.getA19())) {
            detail.setMainUseName(detail.getA19());
        }
        if (!isBlank(detail.getStructureName()) && !isBlank(detail.getMainUseName())) {
            return;
        }

        String addrKey = normalizeAddress(detail.getAddr());
        if (isBlank(addrKey)) return;

        String[] meta = getH2MetaByAddr().get(addrKey);
        if (meta == null) return;

        if (isBlank(detail.getA17()) && !isBlank(meta[0])) detail.setA17(meta[0]);
        if (isBlank(detail.getA19()) && !isBlank(meta[1])) detail.setA19(meta[1]);
        if (isBlank(detail.getStructureName()) && !isBlank(meta[0])) detail.setStructureName(meta[0]);
        if (isBlank(detail.getMainUseName()) && !isBlank(meta[1])) detail.setMainUseName(meta[1]);
    }

    private Map<String, String[]> getH2MetaByAddr() {
        Map<String, String[]> cached = h2MetaByAddr;
        if (cached != null) return cached;

        synchronized (RiskCombinedController.class) {
            if (h2MetaByAddr != null) return h2MetaByAddr;

            Map<String, String[]> map = new ConcurrentHashMap<String, String[]>();
            InputStream is = getClass().getClassLoader().getResourceAsStream("egovframework/spring/data-h2.sql");
            if (is == null) {
                h2MetaByAddr = map;
                return map;
            }

            try (BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
                String line;
                while ((line = br.readLine()) != null) {
                    java.util.regex.Matcher m = H2_INSERT_META_PATTERN.matcher(line);
                    if (!m.matches()) continue;

                    String a17 = unescapeSql(m.group(1));
                    String a19 = unescapeSql(m.group(2));
                    String addr = normalizeAddress(unescapeSql(m.group(3)));
                    if (isBlank(addr)) continue;

                    if (!map.containsKey(addr)) {
                        map.put(addr, new String[] { a17, a19 });
                    }
                }
            } catch (Exception ignore) {
                // best effort fallback
            }

            h2MetaByAddr = map;
            return map;
        }
    }

    private String unescapeSql(String s) {
        if (s == null) return "";
        return s.replace("''", "'");
    }

    private boolean isBlank(String s) {
        return s == null || s.trim().isEmpty();
    }

    private String normalizeAddress(String rawAddr) {
        if (rawAddr == null) return null;

        String original = rawAddr.trim();
        if (original.isEmpty()) return original;

        String cleaned = TRAILING_BUILDING_META.matcher(original).replaceFirst("");
        cleaned = MIDDLE_LOT_MARKER.matcher(cleaned).replaceAll(" ");
        cleaned = MULTI_SPACE.matcher(cleaned).replaceAll(" ").trim();

        return cleaned.isEmpty() ? original : cleaned;
    }
}

