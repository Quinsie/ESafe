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
    <title>전국 전기재해위험지도 - KESCO 전기재해위험지수 관리시스템</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.2/font/bootstrap-icons.css">
    <link rel="stylesheet" href="<c:url value='/resources/css/risk-common.css'/>">
    <script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
</head>
<body>
    <jsp:include page="include/header.jsp"/>
    <div class="layout-wrapper">
        <jsp:include page="include/sidebar.jsp"/>
        <main class="main-content">
            <h2 class="page-title">전국 전기재해위험지도</h2>

            <div class="nationwide-map-layout">
                <section class="nationwide-map-shell">
                    <h3 style="font-size:14px;margin-bottom:10px;color:#2c3e50;">전국 전기재해위험 지도 API 영역</h3>
                    <div class="nationwide-map-toolbar">
                        <div class="nationwide-map-meta">
                            <span id="nationwideMapSource">지도 엔진: VWorld 2D</span>
                            <span id="nationwideMapBranch">대상: 광주전남본부직할</span>
                        </div>
                        <div class="nationwide-map-actions">
                            <div class="nationwide-grade-filter" id="nationwideGradeFilter">
                                <label class="nationwide-grade-chip grade-safe">
                                    <input type="checkbox" value="A" checked>
                                    <span class="swatch"></span>
                                    <span>안전</span>
                                </label>
                                <label class="nationwide-grade-chip grade-interest">
                                    <input type="checkbox" value="B" checked>
                                    <span class="swatch"></span>
                                    <span>관심</span>
                                </label>
                                <label class="nationwide-grade-chip grade-caution">
                                    <input type="checkbox" value="C" checked>
                                    <span class="swatch"></span>
                                    <span>주의</span>
                                </label>
                                <label class="nationwide-grade-chip grade-warning">
                                    <input type="checkbox" value="D" checked>
                                    <span class="swatch"></span>
                                    <span>경고</span>
                                </label>
                                <label class="nationwide-grade-chip grade-danger">
                                    <input type="checkbox" value="E" checked>
                                    <span class="swatch"></span>
                                    <span>위험</span>
                                </label>
                            </div>
                            <button type="button" id="nationwideMapRefreshBtn" class="btn btn-secondary">레이어 새로고침</button>
                        </div>
                    </div>
                    <div class="nationwide-map-placeholder" id="nationwideMapPlaceholder">
                        <div id="nationwideMapCanvas" class="nationwide-map-canvas"></div>
                        <div id="nationwideMapStatus" class="nationwide-map-status"></div>
                    </div>
                </section>

                <aside class="nationwide-ranking-shell">
                    <div class="nationwide-ranking-header">
                        <div>
                            <h3>위험 건물 순위</h3>
                            <p>건물 주소 기준 상위 10곳</p>
                        </div>
                    </div>
                    <div class="nationwide-ranking-tabs" id="nationwideRankingTabs">
                        <button type="button" data-ranking-filter="warning">경고</button>
                        <button type="button" class="is-active" data-ranking-filter="danger">위험</button>
                    </div>
                    <div class="nationwide-ranking-list" id="nationwideRankingList">
                        <div class="nationwide-ranking-empty">지역 순위를 불러오는 중입니다.</div>
                    </div>
                </aside>
            </div>

            <div class="nationwide-brief-shell">
                <h3 style="font-size:14px;margin-bottom:10px;color:#2c3e50;">AI 브리핑 및 상황요약 보고서</h3>
                <div class="nationwide-brief-content" id="nationwideBriefingContent">
                    LLM API 연동 전 레이아웃입니다. 전국 전기재해위험 상황 요약/브리핑 텍스트가 이 영역에 표출됩니다.
                </div>
            </div>
        </main>
    </div>
    <jsp:include page="include/footer.jsp"/>
    <script src="<c:url value='/resources/js/risk-common.js'/>"></script>
    <script>
        window.RISK_VWORLD_API_KEY = "<c:out value='${vworldApiKey}'/>";
        window.RISK_VWORLD_DOMAIN = "<c:out value='${vworldDomain}'/>";
    </script>
    <script src="https://map.vworld.kr/js/vworldMapInit.js.do?version=2.0&apiKey=<c:out value='${vworldApiKey}'/>&domain=<c:out value='${vworldDomain}'/>"></script>
    <script src="<c:url value='/resources/js/risk-nationwide-risk-map.js?v=20260327f'/>"></script>
</body>
</html>
