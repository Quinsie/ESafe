<%@ page contentType="text/html; charset=UTF-8" pageEncoding="UTF-8"%>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core"%>
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>접근 거부</title>
    <link rel="stylesheet" href="<c:url value='/resources/css/risk-common.css'/>">
</head>
<body>
<main class="main-content" style="max-width:500px;margin:60px auto;">
    <h2 class="page-title">접근 권한이 없습니다.</h2>
    <p>요청하신 기능은 관리자 권한이 필요합니다.</p>
    <a class="btn btn-primary" href="<c:url value='/riskDashboard.do'/>">대시보드로 이동</a>
</main>
</body>
</html>
