<%@ page contentType="text/html; charset=UTF-8" pageEncoding="UTF-8"%>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core"%>
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>일반용 설비 상세 - KESCO 전기재해위험지수 관리시스템</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.2/font/bootstrap-icons.css">
    <link rel="stylesheet" href="<c:url value='/resources/css/risk-common.css'/>">
    <script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
</head>
<body>
    <jsp:include page="include/header.jsp"/>
    <div class="layout-wrapper">
        <jsp:include page="include/sidebar.jsp"/>
        <main class="main-content" id="facilityDetailRoot" data-hist-seq="${histSeq}" data-facility-type="${facilityType}" data-bldg-seq="${bldgSeq}">
            <h2 class="page-title">일반용 설비 상세</h2>

            <div class="detail-section">
                <h3>기본 정보</h3>
                <div id="facilityDetailSummary" class="facility-detail-grid"></div>
            </div>

            <div class="detail-section">
                <h3>원본 샘플 전체 컬럼</h3>
                <div class="facility-raw-table-wrap">
                    <table class="detail-table" id="facilityRawTable">
                        <thead>
                            <tr><th style="width:220px;">컬럼명</th><th>값</th></tr>
                        </thead>
                        <tbody>
                            <tr><td colspan="2">데이터를 불러오는 중입니다.</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <div class="btn-area">
                <button type="button" class="btn btn-secondary" id="btnBackToBuilding">건물 상세로</button>
            </div>
        </main>
    </div>
    <jsp:include page="include/footer.jsp"/>
    <script src="<c:url value='/resources/js/risk-common.js'/>"></script>
    <script src="<c:url value='/resources/js/risk-facility-detail.js?v=20260304a'/>"></script>
</body>
</html>
