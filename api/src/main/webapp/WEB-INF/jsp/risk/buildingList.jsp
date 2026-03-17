<%@ page contentType="text/html; charset=UTF-8" pageEncoding="UTF-8"%>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core"%>
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>건물 목록 - KESCO 전기재해위험지수 관리시스템</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.2/font/bootstrap-icons.css">
    <link rel="stylesheet" href="<c:url value='/resources/css/risk-common.css'/>">
    <script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
</head>
<body>
    <jsp:include page="include/header.jsp"/>
    <div class="layout-wrapper">
        <jsp:include page="include/sidebar.jsp"/>
        <main class="main-content">
            <h2 class="page-title">건물 목록</h2>

            <!-- 검색 필터 -->
            <div class="search-box">
                <div class="search-row">
                    <label>본부</label>
                    <select id="searchHq"><option value="">전체</option></select>

                    <label>사업소</label>
                    <select id="searchBranch"><option value="">전체</option></select>

                    <label>시도</label>
                    <select id="searchRegion"><option value="">전체</option></select>

                    <label>구군</label>
                    <select id="searchDistrict"><option value="">전체</option></select>
                </div>
                <div class="search-row" style="margin-top:8px;">
                    <label>등급</label>
                    <select id="searchGrade">
                        <option value="">전체</option>
                        <option value="A">A (안전)</option>
                        <option value="B">B (관심)</option>
                        <option value="C">C (경고)</option>
                        <option value="D">D (위험)</option>
                        <option value="E">E (심각)</option>
                    </select>

                    <label>키워드</label>
                    <input type="text" id="searchKeyword" placeholder="건물명, 주소...">

                    <button type="button" id="btnSearch" class="btn btn-primary">검색</button>
                </div>
            </div>

            <!-- SBGrid 건물 목록 -->
            <div class="grid-section">
                <div class="grid-info">
                    총 <strong id="totalCount">0</strong>건
                </div>
                <div id="sbGridBuilding" style="width:100%; height:500px;"></div>
            </div>

            <!-- 페이징 -->
            <div class="paging-area" id="pagingArea"></div>
        </main>
    </div>
    <jsp:include page="include/footer.jsp"/>
    <script src="<c:url value='/resources/js/risk-common.js'/>"></script>
    <script src="<c:url value='/resources/js/risk-building-list.js'/>"></script>
</body>
</html>
