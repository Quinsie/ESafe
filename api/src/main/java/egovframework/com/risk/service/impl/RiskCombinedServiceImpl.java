package egovframework.com.risk.service.impl;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.Reader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Clob;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import javax.annotation.Resource;

import com.fasterxml.jackson.databind.ObjectMapper;
import egovframework.com.risk.service.RiskCombinedService;
import egovframework.com.risk.util.ProjectPathResolver;
import egovframework.com.risk.vo.RiskCombinedVO;
import egovframework.com.risk.vo.RiskFacilityHistoryVO;
import egovframework.com.risk.vo.RiskSearchVO;
import egovframework.rte.fdl.cmmn.EgovAbstractServiceImpl;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.stereotype.Service;

@Service("riskCombinedService")
public class RiskCombinedServiceImpl extends EgovAbstractServiceImpl implements RiskCombinedService {

    private static final String NAMESPACE = "RiskCombined.";
    private static final Path GENERAL_FACILITY_CSV = ProjectPathResolver.resolveFromProjectRoot(
            "\uC124\uBE44\uB370\uC774\uD130",
            "\uAD11\uC8FC\uC804\uB0A8 \uC77C\uBC18\uC6A9 \uC810\uAC80 \uB370\uC774\uD130_\uC815\uC81C.csv");
    private static final Path SELF_FACILITY_CSV = ProjectPathResolver.resolveFromProjectRoot(
            "\uC124\uBE44\uB370\uC774\uD130",
            "\uAD11\uC8FC\uC804\uB0A8 \uC790\uAC00\uC6A9 \uAC80\uC0AC \uB370\uC774\uD130_\uC815\uC81C.csv");
    private static final String COL_BRANCH = "\uC0AC\uC5C5\uC18C";
    private static final String COL_ADDR = "\uC8FC\uC18C";
    private static final String COL_KEPCO_CUST_NO = "\uD55C\uC804\uACE0\uAC1D\uBC88\uD638";
    private static final String COL_RESULT = "\uACB0\uACFC";
    private static final String COL_CHECK_DATE_GENERAL = "\uC810\uAC80\uC77C\uC790";
    private static final String COL_ORAL_NOTICE = "\uAD6C\uB450\uD1B5\uBCF4";
    private static final String COL_LINE_NO = "\uC120\uC2DD\uBC88\uD638";
    private static final String COL_CAPACITY = "\uC6A9\uB7C9";
    private static final String COL_CHECK_CYCLE = "\uC8FC\uAE30";
    private static final String COL_CONTRACT_TYPE = "\uACC4\uC57D\uC885\uBCC4";
    private static final String COL_LOT_ADDR = "\uC9C0\uBC88\uC8FC\uC18C";
    private static final String COL_ROAD_ADDR = "\uB3C4\uB85C\uBA85\uC8FC\uC18C";
    private static final String COL_CUST_NO = "\uACE0\uAC1D\uBC88\uD638";
    private static final String COL_CHECK_DATE_SELF = "\uAC80\uC0AC\uC77C";
    private static final String COL_DEFECT_CNT = "\uC9C0\uC801\uAC74\uC218";
    private static final String COL_MOTOR_TYPE = "\uC6D0\uB3D9\uAE30\uC885\uB958";
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final Map<String, String> facilityRawJsonCache = new ConcurrentHashMap<String, String>();

    @Resource(name = "sqlSession")
    private SqlSessionTemplate sqlSession;

    @Override
    public List<RiskCombinedVO> selectCombinedList(RiskSearchVO searchVO) {
        searchVO.calcFirstIndex();
        return sqlSession.selectList(NAMESPACE + "selectCombinedList", searchVO);
    }

    @Override
    public int selectCombinedListCnt(RiskSearchVO searchVO) {
        return sqlSession.selectOne(NAMESPACE + "selectCombinedListCnt", searchVO);
    }

    @Override
    public RiskCombinedVO selectCombinedDetail(long bldgSeq) {
        return sqlSession.selectOne(NAMESPACE + "selectCombinedDetail", bldgSeq);
    }

    @Override
    public List<RiskFacilityHistoryVO> selectLatestFacilityHistory(long bldgSeq) {
        return sqlSession.selectList(NAMESPACE + "selectLatestFacilityHistory", bldgSeq);
    }

    @Override
    public Map<String, Object> selectFacilityHistoryDetail(String facilityType, long histSeq) {
        Map<String, Object> params = new java.util.HashMap<String, Object>();
        params.put("facilityType", facilityType);
        params.put("histSeq", Long.valueOf(histSeq));
        Map<String, Object> detail = sqlSession.selectOne(NAMESPACE + "selectFacilityHistoryDetail", params);
        normalizeFacilityHistoryDetail(detail);
        return detail;
    }

    @Override
    public List<RiskCombinedVO> selectGradeStats() {
        return sqlSession.selectList(NAMESPACE + "selectGradeStats");
    }

    @Override
    public List<RiskCombinedVO> selectHqSummary() {
        return sqlSession.selectList(NAMESPACE + "selectHqSummary");
    }

    @Override
    public List<RiskCombinedVO> selectBranchSummary() {
        return sqlSession.selectList(NAMESPACE + "selectBranchSummary");
    }

    @Override
    public List<RiskCombinedVO> selectRegionSummary() {
        return sqlSession.selectList(NAMESPACE + "selectRegionSummary");
    }

    @Override
    public List<RiskCombinedVO> selectRegionDistrictSummary() {
        return sqlSession.selectList(NAMESPACE + "selectRegionDistrictSummary");
    }

    @Override
    public List<RiskCombinedVO> selectGradeChangedList() {
        return sqlSession.selectList(NAMESPACE + "selectGradeChangedList");
    }

    @Override
    public List<Map<String, Object>> selectDangerBuildingExportList(RiskSearchVO searchVO) {
        return sqlSession.selectList(NAMESPACE + "selectDangerBuildingExportList", searchVO);
    }

    @Override
    public List<Map<String, Object>> selectRiskMapDistrictLayer(String branchNm) {
        Map<String, Object> params = new java.util.HashMap<String, Object>();
        params.put("branchNm", branchNm);
        return sqlSession.selectList(NAMESPACE + "selectRiskMapDistrictLayer", params);
    }

    @Override
    public List<Map<String, Object>> selectRiskMapBuildingLayer(
            String branchNm,
            Double minLon,
            Double minLat,
            Double maxLon,
            Double maxLat,
            List<String> riskCdList,
            Integer maxRows) {
        Map<String, Object> params = new java.util.HashMap<String, Object>();
        params.put("branchNm", branchNm);
        params.put("minLon", minLon);
        params.put("minLat", minLat);
        params.put("maxLon", maxLon);
        params.put("maxLat", maxLat);
        params.put("riskCdList", riskCdList);
        params.put("maxRows", maxRows);
        return sqlSession.selectList(NAMESPACE + "selectRiskMapBuildingLayer", params);
    }

    private void normalizeFacilityHistoryDetail(Map<String, Object> detail) {
        if (detail == null || detail.isEmpty()) {
            return;
        }

        putNormalized(detail, "facilityType", "FACILITYTYPE");
        putNormalized(detail, "histSeq", "HISTSEQ");
        putNormalized(detail, "bldgSeq", "BLDGSEQ");
        putNormalized(detail, "branchNm", "BRANCHNM");
        putNormalized(detail, "addr", "ADDR");
        putNormalized(detail, "kepcoCustNo", "KEPCOCUSTNO");
        putNormalized(detail, "resultText", "RESULTTEXT");
        putNormalized(detail, "oralNoticeYn", "ORALNOTICEYN");
        putNormalized(detail, "failDetail", "FAILDETAIL");
        putNormalized(detail, "lineNo", "LINENO");
        putNormalized(detail, "capacity", "CAPACITY");
        putNormalized(detail, "checkCycle", "CHECKCYCLE");
        putNormalized(detail, "contractType", "CONTRACTTYPE");
        putNormalized(detail, "defectCnt", "DEFECTCNT");
        putNormalized(detail, "motorType", "MOTORTYPE");
        putNormalized(detail, "checkDt", "CHECKDT");

        Object rawJson = detail.get("rawJson");
        if (rawJson == null) {
            rawJson = detail.get("RAWJSON");
        }

        if (rawJson instanceof Clob) {
            String clobText = readClob((Clob) rawJson);
            detail.put("rawJson", clobText);
            detail.put("RAWJSON", clobText);
            return;
        }

        if (rawJson != null) {
            String raw = String.valueOf(rawJson);
            detail.put("rawJson", raw);
            detail.put("RAWJSON", raw);
            return;
        }

        String fallbackRawJson = resolveRawJsonFromSource(detail);
        detail.put("rawJson", fallbackRawJson);
        detail.put("RAWJSON", fallbackRawJson);
    }

    private void putNormalized(Map<String, Object> detail, String normalizedKey, String upperKey) {
        if (detail.containsKey(normalizedKey) && detail.get(normalizedKey) != null) {
            return;
        }
        if (detail.containsKey(upperKey)) {
            detail.put(normalizedKey, detail.get(upperKey));
        }
    }

    private String readClob(Clob clob) {
        if (clob == null) {
            return null;
        }
        try (Reader reader = clob.getCharacterStream()) {
            StringBuilder sb = new StringBuilder();
            char[] buffer = new char[2048];
            int read;
            while ((read = reader.read(buffer)) != -1) {
                sb.append(buffer, 0, read);
            }
            return sb.toString();
        } catch (SQLException e) {
            throw new IllegalStateException("Failed to read CLOB from facility history detail", e);
        } catch (IOException e) {
            throw new IllegalStateException("Failed to read CLOB stream from facility history detail", e);
        }
    }

    private String resolveRawJsonFromSource(Map<String, Object> detail) {
        String facilityType = asString(detail.get("facilityType"));
        String histSeq = asString(detail.get("histSeq"));
        if (isBlank(facilityType) || isBlank(histSeq)) {
            return null;
        }

        String cacheKey = facilityType.toUpperCase() + ":" + histSeq;
        if (facilityRawJsonCache.containsKey(cacheKey)) {
            return facilityRawJsonCache.get(cacheKey);
        }

        String rawJson = "SELF".equalsIgnoreCase(facilityType)
                ? findSelfRawJson(detail)
                : findGeneralRawJson(detail);

        facilityRawJsonCache.put(cacheKey, rawJson);
        return rawJson;
    }

    private String findGeneralRawJson(Map<String, Object> detail) {
        return findRawJson(
                GENERAL_FACILITY_CSV,
                detail,
                new RowMatcher() {
                    @Override
                    public boolean matches(Map<String, String> row, Map<String, Object> d) {
                        if (!eq(normalizeText(row.get(COL_BRANCH)), normalizeText(asString(d.get("branchNm"))))) return false;
                        if (!eq(normalizeAddress(row.get(COL_ADDR)), normalizeAddress(asString(d.get("addr"))))) return false;
                        if (!eq(normalizeCustNo(row.get(COL_KEPCO_CUST_NO)), normalizeCustNo(asString(d.get("kepcoCustNo"))))) return false;
                        if (!eq(normalizeText(row.get(COL_RESULT)), normalizeText(asString(d.get("resultText"))))) return false;
                        if (!eq(normalizeDate(row.get(COL_CHECK_DATE_GENERAL)), normalizeDate(asString(d.get("checkDt"))))) return false;

                        String oralExpected = normalizeOralYn(asString(d.get("oralNoticeYn")));
                        if (!isBlank(oralExpected) && !eq(normalizeOralYn(row.get(COL_ORAL_NOTICE)), oralExpected)) return false;

                        String expectedLineNo = normalizeText(asString(d.get("lineNo")));
                        if (!isBlank(expectedLineNo) && !eq(normalizeText(row.get(COL_LINE_NO)), expectedLineNo)) return false;

                        String expectedCapacity = normalizeText(asString(d.get("capacity")));
                        if (!isBlank(expectedCapacity) && !eq(normalizeText(row.get(COL_CAPACITY)), expectedCapacity)) return false;

                        String expectedCycle = normalizeText(asString(d.get("checkCycle")));
                        if (!isBlank(expectedCycle) && !eq(normalizeText(row.get(COL_CHECK_CYCLE)), expectedCycle)) return false;

                        String expectedContract = normalizeText(asString(d.get("contractType")));
                        if (!isBlank(expectedContract) && !eq(normalizeText(row.get(COL_CONTRACT_TYPE)), expectedContract)) return false;
                        return true;
                    }
                });
    }

    private String findSelfRawJson(Map<String, Object> detail) {
        return findRawJson(
                SELF_FACILITY_CSV,
                detail,
                new RowMatcher() {
                    @Override
                    public boolean matches(Map<String, String> row, Map<String, Object> d) {
                        if (!eq(normalizeText(row.get(COL_BRANCH)), normalizeText(asString(d.get("branchNm"))))) return false;
                        if (!eq(
                                normalizeAddress(firstNonBlank(row.get(COL_LOT_ADDR), row.get(COL_ADDR), row.get(COL_ROAD_ADDR))),
                                normalizeAddress(asString(d.get("addr"))))) {
                            return false;
                        }
                        if (!eq(
                                normalizeCustNo(firstNonBlank(row.get(COL_CUST_NO), row.get(COL_KEPCO_CUST_NO))),
                                normalizeCustNo(asString(d.get("kepcoCustNo"))))) {
                            return false;
                        }
                        if (!eq(normalizeText(row.get(COL_RESULT)), normalizeText(asString(d.get("resultText"))))) return false;
                        if (!eq(
                                normalizeDate(firstNonBlank(row.get(COL_CHECK_DATE_SELF), row.get(COL_CHECK_DATE_GENERAL))),
                                normalizeDate(asString(d.get("checkDt"))))) {
                            return false;
                        }

                        String expectedDefectCnt = normalizeText(asString(d.get("defectCnt")));
                        if (!isBlank(expectedDefectCnt) && !eq(normalizeText(row.get(COL_DEFECT_CNT)), expectedDefectCnt)) return false;

                        String expectedMotorType = normalizeText(asString(d.get("motorType")));
                        if (!isBlank(expectedMotorType) && !eq(normalizeText(row.get(COL_MOTOR_TYPE)), expectedMotorType)) return false;
                        return true;
                    }
                });
    }

    private String findRawJson(Path csvPath, Map<String, Object> detail, RowMatcher matcher) {
        if (!Files.exists(csvPath)) {
            return null;
        }

        try (BufferedReader reader = openFacilityCsv(csvPath)) {
            CsvRowReader csvReader = new CsvRowReader(reader);
            List<String> header = csvReader.readRow();
            if (header == null) {
                return null;
            }

            List<String> rowValues;
            while ((rowValues = csvReader.readRow()) != null) {
                Map<String, String> rowMap = toRowMap(header, rowValues);
                if (matcher.matches(rowMap, detail)) {
                    return OBJECT_MAPPER.writeValueAsString(rowMap);
                }
            }
        } catch (Exception ignore) {
        }
        return null;
    }

    private BufferedReader openFacilityCsv(Path path) throws IOException {
        IOException last = null;
        for (String encoding : new String[] {"UTF-8", "MS949"}) {
            try {
                return new BufferedReader(new InputStreamReader(Files.newInputStream(path), encoding));
            } catch (IOException e) {
                last = e;
            }
        }
        throw last == null ? new IOException("Failed to open CSV: " + path) : last;
    }

    private Map<String, String> toRowMap(List<String> header, List<String> values) {
        Map<String, String> rowMap = new LinkedHashMap<String, String>();
        for (int i = 0; i < header.size(); i++) {
            String key = normalizeHeader(header.get(i));
            String value = i < values.size() ? values.get(i) : "";
            rowMap.put(key, value);
        }
        return rowMap;
    }

    private String normalizeHeader(String value) {
        if (value == null) {
            return "";
        }
        return value.replace("\ufeff", "").replace("\r", "").trim();
    }

    private String normalizeText(String value) {
        if (value == null) {
            return "";
        }
        return value.trim().replace(",", " ").replaceAll("\\s+", " ");
    }

    private String normalizeAddress(String value) {
        return normalizeText(value);
    }

    private String normalizeCustNo(String value) {
        return normalizeText(value).replaceAll("\\.0$", "");
    }

    private String normalizeDate(String value) {
        String text = normalizeText(value);
        if (text.matches("\\d{8}")) {
            return text.substring(0, 4) + "-" + text.substring(4, 6) + "-" + text.substring(6, 8);
        }
        return text;
    }

    private String normalizeOralYn(String value) {
        String text = normalizeText(value);
        if ("Y".equalsIgnoreCase(text) || text.contains("\uC608")) {
            return "Y";
        }
        if ("N".equalsIgnoreCase(text) || text.contains("\uC544\uB2C8\uC624")) {
            return "N";
        }
        return text;
    }

    private boolean eq(String left, String right) {
        return normalizeText(left).equals(normalizeText(right));
    }

    private String firstNonBlank(String... values) {
        if (values == null) {
            return "";
        }
        for (String value : values) {
            if (!isBlank(value)) {
                return value;
            }
        }
        return "";
    }

    private String asString(Object value) {
        return value == null ? "" : String.valueOf(value);
    }

    private boolean isBlank(String value) {
        return value == null || value.trim().isEmpty();
    }

    private interface RowMatcher {
        boolean matches(Map<String, String> row, Map<String, Object> detail);
    }

    private static final class CsvRowReader {
        private final BufferedReader reader;

        private CsvRowReader(BufferedReader reader) {
            this.reader = reader;
        }

        private List<String> readRow() throws IOException {
            List<String> cells = new ArrayList<String>();
            StringBuilder sb = new StringBuilder();
            boolean inQuotes = false;
            boolean sawAny = false;

            while (true) {
                int raw = reader.read();
                if (raw == -1) {
                    if (!sawAny && sb.length() == 0 && cells.isEmpty()) {
                        return null;
                    }
                    cells.add(sb.toString());
                    return cells;
                }

                sawAny = true;
                char ch = (char) raw;

                if (ch == '"') {
                    if (inQuotes) {
                        reader.mark(1);
                        int next = reader.read();
                        if (next == '"') {
                            sb.append('"');
                        } else {
                            inQuotes = false;
                            if (next != -1) {
                                reader.reset();
                            }
                        }
                    } else {
                        inQuotes = true;
                    }
                    continue;
                }

                if (ch == ',' && !inQuotes) {
                    cells.add(sb.toString());
                    sb.setLength(0);
                    continue;
                }

                if ((ch == '\n' || ch == '\r') && !inQuotes) {
                    if (ch == '\r') {
                        reader.mark(1);
                        int next = reader.read();
                        if (next != '\n' && next != -1) {
                            reader.reset();
                        }
                    }
                    cells.add(sb.toString());
                    return cells;
                }

                sb.append(ch);
            }
        }
    }
}
