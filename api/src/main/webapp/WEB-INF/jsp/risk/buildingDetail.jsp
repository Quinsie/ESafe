<%@ page contentType="text/html; charset=UTF-8" pageEncoding="UTF-8"%>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core"%>
<%
    String vworldDomain = request.getServerName();
    int serverPort = request.getServerPort();
    if (serverPort != 80 && serverPort != 443) {
        vworldDomain += ":" + serverPort;
    }
    request.setAttribute("vworldDomain", vworldDomain);
%>
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>건물 상세 - KESCO 전기재해위험지수 관리시스템</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.2/font/bootstrap-icons.css">
    <link rel="stylesheet" href="<c:url value='/resources/css/risk-common.css'/>">
    <script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1"></script>
</head>
<body>
    <jsp:include page="include/header.jsp"/>
    <div class="layout-wrapper">
        <jsp:include page="include/sidebar.jsp"/>
        <main class="main-content">
            <h2 class="page-title">건물 상세</h2>

            <div class="detail-section">
                <h3 id="buildingName">-</h3>
                <table class="detail-table">
                    <tr><th>사업소</th><td id="branchNm">-</td><th>주소</th><td id="addr">-</td></tr>
                    <tr><th>지역</th><td id="regionNm">-</td><th>구군</th><td id="districtNm">-</td></tr>
                </table>
            </div>

            <div class="score-section">
                <h3>위험 점수 상세</h3>
                <div class="score-cards">
                    <div class="score-card"><div class="score-label">건물연령</div><div class="score-value" id="ageScore">-</div></div>
                    <div class="score-card"><div class="score-label">침수</div><div class="score-value" id="floodScore">-</div></div>
                    <div class="score-card"><div class="score-label">산사태</div><div class="score-value" id="landslideScore">-</div></div>
                    <div class="score-card"><div class="score-label">화재</div><div class="score-value" id="fireScore">-</div></div>
                    <div class="score-card"><div class="score-label">용도지구</div><div class="score-value" id="landUseScore">-</div></div>
                    <div class="score-card"><div class="score-label">설비점검</div><div class="score-value" id="facilityRiskScore">-</div></div>
                    <div class="score-card"><div class="score-label">기상</div><div class="score-value" id="weatherScore">-</div></div>
                    <div class="score-card"><div class="score-label">산불위험</div><div class="score-value" id="wildfireScore">-</div></div>
                    <div class="score-card card-total-score"><div class="score-label">종합</div><div class="score-value" id="combinedScore">-</div><div class="score-grade" id="combinedGrade">-</div></div>
                </div>
            </div>

            <div class="chart-row">
                <div class="chart-box risk-factor-box" style="max-width:480px;">
                    <h3>위험요소 분석</h3>
                    <canvas id="radarChart" height="320"></canvas>
                </div>
                <div class="chart-box building-insight-box">
                    <h3>건물/설비 정보 (추후 확장 영역)</h3>
                    <div class="insight-split-row">
                        <div id="buildingMapPlaceholder" class="map-placeholder">
                            지도 영역 Placeholder
                        </div>
                        <div class="insight-placeholder-grid">
                            <div class="insight-placeholder-item">
                                <span class="insight-label">건물 연령(실제)</span>
                                <span id="insightBuildingAge" class="insight-value">-</span>
                            </div>
                            <div class="insight-placeholder-item">
                                <span class="insight-label">건축물 구조명</span>
                                <span id="insightStructureName" class="insight-value">-</span>
                            </div>
                            <div class="insight-placeholder-item">
                                <span class="insight-label">주요용도명</span>
                                <span id="insightMainUseName" class="insight-value">-</span>
                            </div>
                            <div class="insight-placeholder-item">
                                <span class="insight-label">용도지구</span>
                                <span id="insightLandUseZone" class="insight-value">-</span>
                            </div>
                            <div class="insight-placeholder-item">
                                <span class="insight-label">보유 설비 수</span>
                                <span id="insightFacilityCount" class="insight-value">-</span>
                            </div>
                            <div class="insight-placeholder-item">
                                <span class="insight-label">위도/경도</span>
                                <span id="insightLatLon" class="insight-value">-</span>
                            </div>
                            <div class="insight-placeholder-item">
                                <span class="insight-label">최근 화재 발생일</span>
                                <span id="insightRecentFireDate" class="insight-value">-</span>
                            </div>
                            <div class="insight-placeholder-item">
                                <span class="insight-label">산사태 위험지와의 거리</span>
                                <span id="insightLandslideDistance" class="insight-value">-</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="detail-section">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">
                    <h3>설비 최근 이력</h3>
                    <div style="display:flex;align-items:center;gap:8px;">
                        <label for="facilityTypeFilter" style="font-weight:600;">설비 구분</label>
                        <select id="facilityTypeFilter" class="form-control" style="min-width:120px;">
                            <option value="GENERAL">일반용</option>
                            <option value="SELF">자가용</option>
                        </select>
                    </div>
                </div>
                <table class="detail-table facility-history-table">
                    <thead id="facilityHistoryHead"></thead>
                    <tbody id="facilityHistoryBody">
                        <tr><td colspan="8">데이터가 없습니다.</td></tr>
                    </tbody>
                </table>
            </div>

            <div class="detail-section">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:10px;">
                    <h3 style="margin:0;">AI 위험원인 설명</h3>
                    <button type="button" id="aiExplainBtn" class="btn btn-secondary">AI 위험원인 설명</button>
                </div>
                <div id="aiExplainContent" class="nationwide-brief-content">
                    'AI 위험원인 설명' 버튼을 누르면 이 건물의 위험 원인을 근거와 함께 분석해 설명합니다.
                </div>
            </div>

            <div class="detail-section">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:10px;">
                    <h3 style="margin:0;">유사 사고 사례 추천</h3>
                    <button type="button" id="aiSimilarBtn" class="btn btn-secondary">유사 사례 검색</button>
                </div>
                <div id="aiSimilarContent" class="nationwide-brief-content">
                    '유사 사례 검색' 버튼을 누르면 이 건물과 비슷한 과거 전기재해 사고 사례를 찾아 보여줍니다.
                </div>
            </div>

            <div class="btn-area">
                <button type="button" class="btn btn-secondary" onclick="history.back()">목록으로</button>
            </div>
        </main>
    </div>
    <jsp:include page="include/footer.jsp"/>
    <script src="<c:url value='/resources/js/risk-common.js'/>"></script>
    <script>var bldgSeq = ${bldgSeq};</script>
    <script>
        window.RISK_VWORLD_API_KEY = "<c:out value='${vworldApiKey}'/>";
        window.RISK_VWORLD_DOMAIN = "<c:out value='${vworldDomain}'/>";
    </script>
    <script src="https://map.vworld.kr/js/webglMapInit.js.do?version=3.0&apiKey=<c:out value='${vworldApiKey}'/>&domain=<c:out value='${vworldDomain}'/>"></script>
    <script src="<c:url value='/resources/js/risk-building-detail-map-adapter.js?v=20260309c'/>"></script>
    <script src="<c:url value='/resources/js/risk-building-detail.js?v=20260309c'/>"></script>
    <script>
        // ESafe LLM 사이드카 주소. 운영 전환 시 Java 프록시 URL로 바꾼다.
        window.ESAFE_LLM_BASE = "http://localhost:8800";
    </script>
    <script src="<c:url value='/resources/js/risk-ai-explain.js?v=20260527b'/>"></script>
</body>
</html>
