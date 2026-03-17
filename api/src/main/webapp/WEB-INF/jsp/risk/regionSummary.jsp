<%@ page contentType="text/html; charset=UTF-8" pageEncoding="UTF-8"%>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core"%>
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>지역별 현황 - KESCO 전기재해위험지수 관리시스템</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.2/font/bootstrap-icons.css">
    <link rel="stylesheet" href="<c:url value='/resources/css/risk-common.css'/>">
    <script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
</head>
<body>
    <jsp:include page="include/header.jsp"/>
    <div class="layout-wrapper">
        <jsp:include page="include/sidebar.jsp"/>
        <main class="main-content">
            <h2 class="page-title">지역별 현황</h2>

            <div class="search-box">
                <div class="search-row">
                    <label>시도</label>
                    <select id="filterRegion"><option value="">전체</option></select>

                    <label>구군</label>
                    <select id="filterDistrict"><option value="">전체</option></select>

                    <button type="button" id="btnSearch" class="btn btn-primary">조회</button>
                    <button type="button" id="btnDownloadRegionExcel" class="btn">(D+E) 엑셀 다운로드</button>
                </div>
            </div>

            <div class="grid-section">
                <h3>시도별 요약</h3>
                <div id="sbGridRegion" style="width:100%; max-height:300px; overflow-y:auto;"></div>
            </div>

            <div class="grid-section">
                <div class="grid-info">
                    총 <strong id="totalCount">0</strong>개 구군
                </div>
                <h3>구군별 상세</h3>
                <div id="sbGridDistrict" style="width:100%; max-height:450px; overflow-y:auto;"></div>
            </div>
        </main>
    </div>
    <jsp:include page="include/footer.jsp"/>
    <script src="<c:url value='/resources/js/risk-common.js'/>"></script>
    <script src="<c:url value='/resources/js/risk-region-summary.js'/>"></script>
</body>
</html>
