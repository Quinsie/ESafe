<%@ page contentType="text/html; charset=UTF-8" pageEncoding="UTF-8"%>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core"%>
<%@ taglib prefix="sec" uri="http://www.springframework.org/security/tags" %>
<nav class="top-nav">
    <c:if test="${not empty _csrf}">
        <input type="hidden" id="_csrfToken" value="${_csrf.token}"/>
        <input type="hidden" id="_csrfHeader" value="${_csrf.headerName}"/>
    </c:if>
    <div class="nav-brand">
        <strong>KESCO</strong> 전기재해위험지수 관리시스템
    </div>
    <div class="nav-right" style="display:flex;gap:12px;align-items:center;">
        <span class="nav-info" id="currentTime"></span>
        <sec:authorize access="isAuthenticated()">
            <span class="nav-info"><sec:authentication property="name"/>님</span>
            <form action="<c:url value='/logout.do'/>" method="post" style="margin:0;">
                <c:if test="${not empty _csrf}">
                    <input type="hidden" name="${_csrf.parameterName}" value="${_csrf.token}"/>
                </c:if>
                <button type="submit" class="btn btn-sm">로그아웃</button>
            </form>
        </sec:authorize>
    </div>
</nav>
