<%@ page contentType="text/html; charset=UTF-8" pageEncoding="UTF-8"%>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core"%>
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>대시보드 - KESCO 전기재해위험지수 관리시스템</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.2/font/bootstrap-icons.css">
    <link rel="stylesheet" href="<c:url value='/resources/css/risk-common.css'/>">
    <!-- SBGrid CSS (라이선스 확보 후 로컬 경로로 변경) -->
    <script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1"></script>
</head>
<body>
    <jsp:include page="include/header.jsp"/>
    <div class="layout-wrapper">
        <jsp:include page="include/sidebar.jsp"/>
        <main class="main-content">
            <h2 class="page-title">대시보드</h2>

            <!-- 요약 카드 -->
            <div class="summary-cards">
                <div class="card card-total">
                    <div class="card-label">총 건물수</div>
                    <div class="card-value" id="totalCount">-</div>
                </div>
                <div class="card card-danger">
                    <div class="card-label">위험 이상 (D+E)</div>
                    <div class="card-value" id="dangerCount">-</div>
                </div>
                <div class="card card-warning">
                    <div class="card-label">경고 (C)</div>
                    <div class="card-value" id="warningCount">-</div>
                </div>
                <div class="card card-weather">
                    <div class="card-label">당일 특보</div>
                    <div class="card-value" id="alertCount">-</div>
                </div>
            </div>

            <!-- 차트 영역 -->
            <div class="chart-row">
                <div class="chart-box">
                    <h3>등급 분포</h3>
                    <canvas id="gradeChart" height="250"></canvas>
                </div>
                <div class="chart-box">
                    <h3>본부별 위험건물</h3>
                    <canvas id="hqChart" height="250"></canvas>
                </div>
            </div>

        </main>
    </div>
    <jsp:include page="include/footer.jsp"/>
    <script src="<c:url value='/resources/js/risk-common.js'/>"></script>
    <script src="<c:url value='/resources/js/risk-dashboard.js'/>"></script>
</body>
</html>
