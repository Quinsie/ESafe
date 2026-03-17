<%@ page contentType="text/html; charset=UTF-8" pageEncoding="UTF-8"%>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core"%>
<%@ taglib prefix="sec" uri="http://www.springframework.org/security/tags" %>
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>기상특보 - KESCO 전기재해위험지수 관리시스템</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.2/font/bootstrap-icons.css">
    <link rel="stylesheet" href="<c:url value='/resources/css/risk-common.css'/>">
    <script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
</head>
<body>
    <jsp:include page="include/header.jsp"/>
    <div class="layout-wrapper">
        <jsp:include page="include/sidebar.jsp"/>
        <main class="main-content">
            <h2 class="page-title">기상특보 현황
                <sec:authorize access="hasRole('ADMIN')">
                    <button type="button" id="btnRefresh" class="btn btn-sm btn-primary" style="margin-left:10px;">수동 갱신</button>
                </sec:authorize>
            </h2>

            <div class="grid-section weather-map-section">
                <div class="weather-map-header">
                    <h3>특보 현황 지도</h3>
                    <span id="weatherMapUpdatedAt" class="weather-map-updated"></span>
                </div>
                <div class="weather-map-grid">
                    <figure class="weather-map-card">
                        <figcaption>종합 지도</figcaption>
                        <div class="weather-map-frame">
                            <span class="weather-map-state">불러오는 중...</span>
                            <img id="weatherMapComposite" class="weather-map-image" data-map-kind="wrn" data-wrn="W,R,C,D,O,N,V,T,S,Y,H,F" alt="종합 특보 현황 지도">
                        </div>
                    </figure>
                    <figure class="weather-map-card">
                        <figcaption>위성지도</figcaption>
                        <div class="weather-map-frame">
                            <span class="weather-map-state">불러오는 중...</span>
                            <img id="weatherMapSatellite" class="weather-map-image" data-map-kind="gk2a" alt="위성지도">
                        </div>
                    </figure>
                    <figure class="weather-map-card">
                        <figcaption>산불위험지도</figcaption>
                        <div class="weather-map-frame">
                            <span class="weather-map-state">불러오는 중...</span>
                            <img id="weatherMapWildfire" class="weather-map-image" data-map-kind="wildfire" alt="산불위험지도">
                        </div>
                    </figure>
                </div>
            </div>

            <div class="grid-section">
                <h3>당일 발효 특보</h3>
                <div id="sbGridAlert" style="width:100%; max-height:400px; overflow-y:auto;"></div>
            </div>

            <div class="grid-section">
                <h3>지역별 기상 점수</h3>
                <div class="search-box" id="weatherScoreSearchBox">
                    <div class="search-row">
                        <label>본부</label>
                        <select id="weatherSearchHq"><option value="">전체</option></select>

                        <label>사업소</label>
                        <select id="weatherSearchBranch"><option value="">전체</option></select>

                        <label>시도</label>
                        <select id="weatherSearchRegion"><option value="">전체</option></select>

                        <label>시군구</label>
                        <select id="weatherSearchDistrict"><option value="">전체</option></select>

                        <button type="button" id="btnWeatherScoreSearch" class="btn btn-primary">검색</button>
                    </div>
                </div>
                <div id="sbGridScore" style="width:100%; max-height:400px; overflow-y:auto;"></div>
            </div>
        </main>
    </div>
    <jsp:include page="include/footer.jsp"/>
    <script src="<c:url value='/resources/js/risk-common.js?v=20260303_1'/>"></script>
    <script src="<c:url value='/resources/js/risk-weather.js?v=20260304_5'/>"></script>
</body>
</html>
