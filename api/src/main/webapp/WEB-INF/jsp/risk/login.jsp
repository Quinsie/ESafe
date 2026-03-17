<%@ page contentType="text/html; charset=UTF-8" pageEncoding="UTF-8"%>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core"%>
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>로그인 - KESCO 전기재해위험지수 관리시스템</title>
    <link rel="stylesheet" href="<c:url value='/resources/css/risk-common.css'/>">
</head>
<body>
<main class="main-content" style="max-width:420px;margin:60px auto;">
    <h2 class="page-title">로그인</h2>
    <c:if test="${param.error eq 'Y'}">
        <div style="color:#b91c1c;margin-bottom:10px;">아이디 또는 비밀번호가 올바르지 않습니다.</div>
    </c:if>
    <c:if test="${param.logout eq 'Y'}">
        <div style="color:#166534;margin-bottom:10px;">로그아웃되었습니다.</div>
    </c:if>
    <form action="<c:url value='/perform_login.do'/>" method="post">
        <c:if test="${not empty _csrf}">
            <input type="hidden" name="${_csrf.parameterName}" value="${_csrf.token}">
        </c:if>
        <div style="margin-bottom:10px;">
            <label for="username">아이디</label>
            <input id="username" name="username" type="text" style="width:100%;padding:8px;">
        </div>
        <div style="margin-bottom:16px;">
            <label for="password">비밀번호</label>
            <input id="password" name="password" type="password" style="width:100%;padding:8px;">
        </div>
        <button type="submit" class="btn btn-primary" style="width:100%;">로그인</button>
    </form>
</main>
</body>
</html>
