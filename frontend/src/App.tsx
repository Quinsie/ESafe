import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, lazy, Suspense, useEffect, useState } from "react";
import { type ApiEnvelope, ApiError, apiRequest } from "./api";
import { formatKst, HomeDashboard, sourceSummaryLabel, useSourceHealth } from "./home";
import type { ProfileRuntime } from "./profile";
import {
  AppLink,
  currentInternalLocation,
  navigateInternal,
  safeReturnTo,
  useInternalPath,
} from "./router";

const RiskMap = lazy(() => import("./map").then((module) => ({ default: module.RiskMap })));
const SpatialAnalysis = lazy(() =>
  import("./analysis").then((module) => ({ default: module.SpatialAnalysis })),
);
const SimilarityAnalysis = lazy(() =>
  import("./similarity").then((module) => ({
    default: module.SimilarityAnalysis,
  })),
);
const CaseManagement = lazy(() =>
  import("./cases").then((module) => ({ default: module.CaseManagement })),
);
const CaseWorkflow = lazy(() =>
  import("./case_workflow").then((module) => ({ default: module.CaseWorkflow })),
);
const AutomationManagement = lazy(() =>
  import("./automation").then((module) => ({
    default: module.AutomationManagement,
  })),
);
const ApprovalManagement = lazy(() =>
  import("./approvals").then((module) => ({
    default: module.ApprovalManagement,
  })),
);
const DocumentManagement = lazy(() =>
  import("./documents").then((module) => ({
    default: module.DocumentManagement,
  })),
);
const InspectionPlanning = lazy(() =>
  import("./inspections").then((module) => ({
    default: module.InspectionPlanning,
  })),
);
const NotificationCenter = lazy(() =>
  import("./notifications").then((module) => ({
    default: module.NotificationCenter,
  })),
);

interface SessionData {
  user: {
    userId: string;
    displayName: string;
  };
  expiresAt: string;
}

const navigation = [
  { group: "OVERVIEW", label: "상황 브리핑", to: "/home" },
  { group: "OVERVIEW", label: "위험 지도", to: "/map" },
  { group: "OVERVIEW", label: "위험 분석", to: "/regions" },
  { group: "OVERVIEW", label: "점검 계획", to: "/inspections/simulations/new" },
  { group: "OVERVIEW", label: "재난 대응", to: "/cases" },
  { group: "WORKFLOW", label: "검토·승인", to: "/approvals" },
  { group: "WORKFLOW", label: "자동화 기록", to: "/automation/runs" },
  { group: "WORKFLOW", label: "보고서·산출물", to: "/artifacts" },
] as const;

const routeTitles: Record<string, string> = {
  "/map": "위험 지도",
  "/regions": "위험 분석",
  "/inspections/simulations/new": "점검 계획",
  "/cases": "재난 대응",
  "/approvals": "검토·승인",
  "/automation/runs": "자동화 기록",
  "/automation/policies": "자동화 운영 정책",
  "/artifacts": "보고서·산출물",
  "/similar/incidents": "과거 사고사례 검색",
  "/similar/facilities": "유사 위험시설 탐색",
  "/similar/compare": "후보 시설 비교",
  "/notifications": "알림",
};

function routeTitle(path: string): string | undefined {
  if (routeTitles[path]) {
    return routeTitles[path];
  }
  if (/^\/regions\/[^/]+\/report$/.test(path)) {
    return "지역 분석 보고서";
  }
  if (/^\/buildings\/[^/]+\/report$/.test(path)) {
    return "건물 분석 보고서";
  }
  if (/^\/regions\/[^/]+$/.test(path)) {
    return "지역 상세";
  }
  if (/^\/buildings\/[^/]+$/.test(path)) {
    return "건물 상세";
  }
  if (/^\/cases\/[^/]+/.test(path)) {
    return "Case 상세";
  }
  if (/^\/approvals\/[0-9a-f-]+$/i.test(path)) {
    return "검토·승인";
  }
  if (/^\/inspections\/simulations\/[0-9a-f-]+\/(?:compare|targets)$/i.test(path)) {
    return "점검 계획";
  }
  if (
    path === "/artifacts" ||
    /^\/cases\/[0-9a-f-]+\/documents\/new$/i.test(path) ||
    /^\/documents\/[0-9a-f-]+\/(?:edit|result)$/i.test(path)
  ) {
    return "문서·산출물";
  }
  return undefined;
}

function sessionQuery(runtime: ProfileRuntime) {
  return {
    queryKey: ["auth-session", runtime.profile],
    queryFn: () => apiRequest<SessionData>(runtime, "/auth/session"),
    retry: false,
    staleTime: 60_000,
  } as const;
}

function AuthLoading({ runtime }: { runtime: ProfileRuntime }) {
  return (
    <main className="auth-page" aria-busy="true">
      <header className="auth-topbar">
        <strong>E-Safe / 전기재해 예방 관제</strong>
        <span className={`profile-badge ${runtime.profile.toLowerCase()}`}>{runtime.badge}</span>
      </header>
      <div className="auth-loading" role="status">
        세션을 확인하고 있습니다.
      </div>
    </main>
  );
}

function LoginPage({
  runtime,
  sessionExpired,
}: {
  runtime: ProfileRuntime;
  sessionExpired: boolean;
}) {
  const queryClient = useQueryClient();
  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const returnTo = safeReturnTo(new URLSearchParams(window.location.search).get("returnTo"));
  const login = useMutation({
    mutationFn: () =>
      apiRequest<SessionData>(runtime, "/auth/login", {
        method: "POST",
        body: JSON.stringify({ userId, password }),
      }),
    onSuccess: (session) => {
      queryClient.setQueryData<ApiEnvelope<SessionData>>(
        ["auth-session", runtime.profile],
        session,
      );
      setPassword("");
      navigateInternal(runtime, returnTo, true);
    },
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!login.isPending) {
      login.mutate();
    }
  };

  const errorMessage =
    login.error instanceof ApiError
      ? login.error.message
      : login.isError
        ? "로그인 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."
        : null;

  return (
    <main className="auth-page" id="main-content">
      <header className="auth-topbar">
        <strong>E-Safe / 전기재해 예방 관제</strong>
        <div className="auth-topbar-meta">
          <span className={`profile-badge ${runtime.profile.toLowerCase()}`}>{runtime.badge}</span>
          <span>광주·전남 관제 시스템</span>
        </div>
      </header>
      <div className="auth-workspace">
        <section className="auth-intro" aria-labelledby="auth-page-title">
          <span className="auth-eyebrow">ELECTRICAL SAFETY CONTROL</span>
          <h1 id="auth-page-title">
            전기재해 위험을
            <br />
            한곳에서 확인합니다.
          </h1>
          <p>
            실제 신호와 기준 위험도, 대응 근거와 승인 문서를 연결해 광주·전남의 관제 판단을
            지원합니다.
          </p>
          <div className="auth-capabilities">
            <span>24시간 신호 감시</span>
            <span>실제 건물 위험지도</span>
            <span>근거 기반 대응·문서</span>
          </div>
          <div className="auth-mode-card">
            <span className={`profile-badge ${runtime.profile.toLowerCase()}`}>
              {runtime.badge}
            </span>
            <div>
              <strong>
                {runtime.profile === "LIVE" ? "실시간 관제 환경" : "전체 기능 체험 환경"}
              </strong>
              <small>
                {runtime.profile === "LIVE"
                  ? "실제 외부 신호를 수집합니다."
                  : "통제 가능한 시나리오로 같은 처리 흐름을 재생합니다."}
              </small>
            </div>
          </div>
        </section>
        <section className="login-card" aria-label="E-Safe 로그인">
          <div className="login-card-heading">
            <span>사용자 인증</span>
            <strong>관제 시스템 로그인</strong>
            <p>공용 사용자 계정으로 업무 화면에 접속합니다.</p>
          </div>
          {sessionExpired ? (
            <div className="auth-notice" role="status">
              세션이 만료되었습니다. 다시 로그인하면 마지막 화면으로 돌아갑니다.
            </div>
          ) : null}
          <form onSubmit={submit}>
            <label htmlFor="user-id">사용자 ID</label>
            <input
              autoComplete="username"
              id="user-id"
              maxLength={128}
              onChange={(event) => setUserId(event.target.value)}
              placeholder="사용자 ID 입력"
              required
              value={userId}
            />
            <label htmlFor="password">비밀번호</label>
            <input
              autoComplete="current-password"
              id="password"
              maxLength={256}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="비밀번호 입력"
              required
              type="password"
              value={password}
            />
            {errorMessage ? (
              <div className="auth-error" role="alert">
                {errorMessage}
              </div>
            ) : null}
            <button className="login-button" disabled={login.isPending} type="submit">
              {login.isPending ? "확인 중…" : "로그인"}
            </button>
          </form>
          <p className="auth-state-copy">
            로그인 후 상황 브리핑으로 이동하며, 만료 시 현재 업무 위치를 보존합니다.
          </p>
        </section>
      </div>
    </main>
  );
}

function Sidebar({ currentPath, runtime }: { currentPath: string; runtime: ProfileRuntime }) {
  return (
    <aside className="sidebar" aria-label="주요 메뉴">
      {(["OVERVIEW", "WORKFLOW"] as const).map((group) => (
        <div className="nav-group" key={group}>
          <p className="nav-group-label">{group}</p>
          <nav>
            {navigation
              .filter((item) => item.group === group)
              .map((item) => (
                <AppLink
                  className={
                    item.to === "/regions" && currentPath.startsWith("/similar/")
                      ? "nav-item is-active"
                      : "nav-item"
                  }
                  currentPath={currentPath}
                  key={item.to}
                  runtime={runtime}
                  to={item.to}
                >
                  {item.label}
                </AppLink>
              ))}
          </nav>
        </div>
      ))}
    </aside>
  );
}

function SectionPlaceholder({ title }: { title: string }) {
  return (
    <main className="page" id="main-content">
      <div className="page-heading">
        <div>
          <h1>페이지를 찾을 수 없습니다</h1>
          <p>주소를 확인하거나 왼쪽 메뉴에서 다시 이동해 주세요.</p>
        </div>
      </div>
      <section className="panel not-found-panel">
        <span className="status-pill neutral">404</span>
        <h2>요청한 화면이 없습니다.</h2>
        <p>요청 화면: {title}</p>
      </section>
    </main>
  );
}

function AuthenticatedShell({
  currentPath,
  runtime,
  session,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
  session: ApiEnvelope<SessionData>;
}) {
  const queryClient = useQueryClient();
  const sourceHealth = useSourceHealth(runtime);
  const logout = useMutation({
    mutationFn: () => apiRequest(runtime, "/auth/logout", { method: "POST" }),
    onSuccess: () => {
      queryClient.removeQueries({
        queryKey: ["auth-session", runtime.profile],
      });
      navigateInternal(runtime, "/login", true);
    },
  });
  const sourceData = sourceHealth.data?.data;
  const dataState = sourceHealth.isError
    ? "수집 상태 확인 필요"
    : sourceSummaryLabel(runtime, sourceData);
  const sourceWarning = sourceHealth.isError || sourceData?.summary !== "HEALTHY";
  const title = routeTitle(currentPath);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        본문으로 건너뛰기
      </a>
      <header className="topbar">
        <strong className="brand">E-Safe / 전기재해 예방 관제</strong>
        <div className="topbar-status">
          <span className={`profile-badge ${runtime.profile.toLowerCase()}`}>{runtime.badge}</span>
          <span className={`data-status ${sourceWarning ? "is-warning" : ""}`}>{dataState}</span>
          <span className="as-of">기준 {formatKst(sourceData?.dataAsOf)}</span>
          <AppLink
            className="notification-button"
            currentPath={currentPath}
            runtime={runtime}
            to="/notifications"
          >
            알림
          </AppLink>
          <span className="signed-in-user">{session.data.user.displayName}</span>
          <button
            className="logout-button"
            disabled={logout.isPending}
            onClick={() => logout.mutate()}
            type="button"
          >
            로그아웃
          </button>
        </div>
      </header>
      <Sidebar currentPath={currentPath} runtime={runtime} />
      {currentPath === "/home" ? (
        <HomeDashboard currentPath={currentPath} runtime={runtime} />
      ) : currentPath === "/map" ? (
        <Suspense
          fallback={
            <main className="page" id="main-content">
              <div className="auth-loading" role="status">
                지도를 준비하고 있습니다.
              </div>
            </main>
          }
        >
          <RiskMap currentPath={currentPath} runtime={runtime} />
        </Suspense>
      ) : currentPath === "/regions" ||
        /^\/regions\/[^/]+(?:\/report)?$/.test(currentPath) ||
        /^\/buildings\/[^/]+(?:\/report)?$/.test(currentPath) ? (
        <Suspense
          fallback={
            <main className="page" id="main-content">
              <div className="auth-loading" role="status">
                분석 화면을 준비하고 있습니다.
              </div>
            </main>
          }
        >
          <SpatialAnalysis currentPath={currentPath} runtime={runtime} />
        </Suspense>
      ) : currentPath.startsWith("/similar/") ? (
        <Suspense
          fallback={
            <main className="page" id="main-content">
              <div className="auth-loading" role="status">
                유사분석 화면을 준비하고 있습니다.
              </div>
            </main>
          }
        >
          <SimilarityAnalysis currentPath={currentPath} runtime={runtime} />
        </Suspense>
      ) : currentPath === "/cases" || /^\/cases\/[0-9a-f-]+$/i.test(currentPath) ? (
        <Suspense
          fallback={
            <main className="page" id="main-content">
              <div className="auth-loading" role="status">
                재난 대응 화면을 준비하고 있습니다.
              </div>
            </main>
          }
        >
          <CaseManagement currentPath={currentPath} runtime={runtime} />
        </Suspense>
      ) : /^\/cases\/[0-9a-f-]+\/(?:evidence|close|tasks(?:\/[0-9a-f-]+)?)$/i.test(currentPath) ? (
        <Suspense
          fallback={
            <main className="page" id="main-content">
              <div className="auth-loading" role="status">
                Case 업무 화면을 준비하고 있습니다.
              </div>
            </main>
          }
        >
          <CaseWorkflow currentPath={currentPath} runtime={runtime} />
        </Suspense>
      ) : currentPath === "/automation/runs" || currentPath === "/automation/policies" ? (
        <Suspense
          fallback={
            <main className="page" id="main-content">
              <div className="auth-loading" role="status">
                자동화 화면을 준비하고 있습니다.
              </div>
            </main>
          }
        >
          <AutomationManagement currentPath={currentPath} runtime={runtime} />
        </Suspense>
      ) : currentPath === "/inspections/simulations/new" ||
        /^\/inspections\/simulations\/[0-9a-f-]+\/(?:compare|targets)$/i.test(currentPath) ? (
        <Suspense
          fallback={
            <main className="page" id="main-content">
              <div className="auth-loading" role="status">
                점검계획 화면을 준비하고 있습니다.
              </div>
            </main>
          }
        >
          <InspectionPlanning currentPath={currentPath} runtime={runtime} />
        </Suspense>
      ) : currentPath === "/approvals" || /^\/approvals\/[0-9a-f-]+$/i.test(currentPath) ? (
        <Suspense
          fallback={
            <main className="page" id="main-content">
              <div className="auth-loading" role="status">
                검토·승인 화면을 준비하고 있습니다.
              </div>
            </main>
          }
        >
          <ApprovalManagement currentPath={currentPath} runtime={runtime} />
        </Suspense>
      ) : currentPath === "/artifacts" ||
        /^\/cases\/[0-9a-f-]+\/documents\/new$/i.test(currentPath) ||
        /^\/documents\/[0-9a-f-]+\/(?:edit|result)$/i.test(currentPath) ? (
        <Suspense
          fallback={
            <main className="page" id="main-content">
              <div className="auth-loading" role="status">
                문서 화면을 준비하고 있습니다.
              </div>
            </main>
          }
        >
          <DocumentManagement currentPath={currentPath} runtime={runtime} />
        </Suspense>
      ) : currentPath === "/notifications" ? (
        <Suspense
          fallback={
            <main className="page" id="main-content">
              <div className="auth-loading" role="status">
                알림 센터를 준비하고 있습니다.
              </div>
            </main>
          }
        >
          <NotificationCenter currentPath={currentPath} runtime={runtime} />
        </Suspense>
      ) : title ? (
        <SectionPlaceholder title={title} />
      ) : (
        <SectionPlaceholder title="페이지를 찾을 수 없음" />
      )}
    </div>
  );
}

export function App({ runtime }: { runtime: ProfileRuntime }) {
  const currentPath = useInternalPath(runtime);
  const session = useQuery(sessionQuery(runtime));

  useEffect(() => {
    const moveToLogin = () => {
      if (currentPath === "/login") {
        return;
      }
      const returnTo = currentInternalLocation(runtime);
      navigateInternal(runtime, `/login?returnTo=${encodeURIComponent(returnTo)}`, true);
    };
    window.addEventListener("esafe-session-expired", moveToLogin);
    if (session.error instanceof ApiError && session.error.status === 401) {
      moveToLogin();
    }
    return () => window.removeEventListener("esafe-session-expired", moveToLogin);
  }, [currentPath, runtime, session.error]);

  useEffect(() => {
    if (session.isSuccess && currentPath === "/login") {
      const returnTo = safeReturnTo(new URLSearchParams(window.location.search).get("returnTo"));
      navigateInternal(runtime, returnTo, true);
    }
  }, [currentPath, runtime, session.isSuccess]);

  if (session.isLoading) {
    return <AuthLoading runtime={runtime} />;
  }
  if (!session.isSuccess || currentPath === "/login") {
    const expired = session.error instanceof ApiError && session.error.code === "SESSION_EXPIRED";
    return <LoginPage runtime={runtime} sessionExpired={expired} />;
  }
  return <AuthenticatedShell currentPath={currentPath} runtime={runtime} session={session.data} />;
}
