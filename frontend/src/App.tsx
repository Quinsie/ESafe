import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { type ApiEnvelope, ApiError, apiRequest } from "./api";
import type { ProfileRuntime } from "./profile";
import {
  AppLink,
  currentInternalLocation,
  navigateInternal,
  safeReturnTo,
  useInternalPath,
} from "./router";

interface SessionData {
  user: {
    userId: string;
    displayName: string;
  };
  expiresAt: string;
}

interface MetaData {
  profile: "LIVE" | "DEMO";
  profileBadge: string;
  version: string;
  commit: string;
}

const navigation = [
  { group: "OVERVIEW", label: "상황 브리핑", to: "/home" },
  { group: "OVERVIEW", label: "위험 지도", to: "/map" },
  { group: "OVERVIEW", label: "위험 분석", to: "/analysis" },
  { group: "OVERVIEW", label: "점검 계획", to: "/inspections" },
  { group: "OVERVIEW", label: "재난 대응", to: "/incidents" },
  { group: "WORKFLOW", label: "검토·승인", to: "/approvals" },
  { group: "WORKFLOW", label: "자동화 기록", to: "/automation" },
  { group: "WORKFLOW", label: "보고서·산출물", to: "/outputs" },
] as const;

const routeTitles: Record<string, string> = {
  "/map": "위험 지도",
  "/analysis": "위험 분석",
  "/inspections": "점검 계획",
  "/incidents": "재난 대응",
  "/approvals": "검토·승인",
  "/automation": "자동화 기록",
  "/outputs": "보고서·산출물",
};

function sessionQuery(runtime: ProfileRuntime) {
  return {
    queryKey: ["auth-session", runtime.profile],
    queryFn: () => apiRequest<SessionData>(runtime, "/auth/session"),
    retry: false,
    staleTime: 60_000,
  } as const;
}

function useRuntimeMeta(runtime: ProfileRuntime) {
  return useQuery({
    queryKey: ["runtime-meta", runtime.profile],
    queryFn: () => apiRequest<MetaData>(runtime, "/meta"),
  });
}

function AuthLoading({ runtime }: { runtime: ProfileRuntime }) {
  return (
    <main className="auth-page" aria-busy="true">
      <header className="auth-topbar">
        <strong>E-Safe / 로그인</strong>
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
        <strong>E-Safe / 로그인</strong>
        <div className="auth-topbar-meta">
          <span className={`profile-badge ${runtime.profile.toLowerCase()}`}>{runtime.badge}</span>
          <span>최초 진입 · 세션 만료 시 안전하게 복귀</span>
        </div>
      </header>
      <section className="auth-intro" aria-labelledby="auth-page-title">
        <h1 id="auth-page-title">로그인·세션 확인</h1>
        <p>인증 시작과 만료된 작업의 안전한 복귀를 지원합니다.</p>
      </section>
      <section className="login-card" aria-label="E-Safe 로그인">
        <div className="login-card-heading">
          <strong>E-Safe</strong>
          <p>한국전기안전공사 재난안전 관제</p>
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
        <p className="auth-state-copy">인증 중 · 인증 실패·잠김 · 세션 만료 상태를 안내합니다.</p>
      </section>
      <aside className="auth-help">
        인증은 업무 권한 확인이며 승인과는 다릅니다. 성공하면 요청한 업무 화면으로 이동합니다.
      </aside>
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
                  className="nav-item"
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

function BriefingScaffold({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const metrics = ["긴급 점검 필요", "위험 급상승", "24시간 내 조치", "검토·승인 대기"];
  return (
    <main className="page" id="main-content">
      <div className="page-heading">
        <div>
          <h1>오늘의 상황 브리핑</h1>
          <p>광주·전남 전기재해 위험과 오늘 필요한 예방 조치를 확인하세요.</p>
        </div>
        <fieldset className="page-filters">
          <legend className="sr-only">브리핑 기준</legend>
          <button type="button">광주·전남</button>
          <button type="button">오늘</button>
        </fieldset>
      </div>

      <section className="notice-card" aria-label="관제 준비 상태">
        <span className="status-pill neutral">준비 중</span>
        <div>
          <h2>기준 데이터와 관제 서비스를 연결하고 있습니다.</h2>
          <p>상태가 준비되면 실제 Case, 근거와 조치가 이 영역에 표시됩니다.</p>
        </div>
      </section>

      <section className="metric-grid" aria-label="핵심 현황">
        {metrics.map((label) => (
          <article className="metric-card" key={label}>
            <p>{label}</p>
            <strong>—</strong>
            <span>집계 전</span>
          </article>
        ))}
      </section>

      <div className="dashboard-grid">
        <section className="panel priority-panel">
          <div className="panel-heading">
            <div>
              <h2>우선 확인이 필요한 지역</h2>
              <p>전체 기준 데이터 적재 후 상대 위험순위와 핵심 근거를 표시합니다.</p>
            </div>
            <AppLink
              className="outline-action"
              currentPath={currentPath}
              runtime={runtime}
              to="/map"
            >
              위험지도 보기
            </AppLink>
          </div>
          <div className="empty-state">지역 위험도 준비 중</div>
        </section>
        <section className="panel task-panel">
          <div className="panel-heading">
            <h2>오늘 처리할 업무</h2>
          </div>
          <div className="empty-state">처리할 업무 집계 중</div>
        </section>
        <section className="panel change-panel">
          <div className="panel-heading">
            <h2>최근 위험 변화</h2>
          </div>
          <div className="empty-state compact">외부 신호 연결 전</div>
        </section>
        <section className="panel ai-panel">
          <div className="panel-heading">
            <h2>AI 작업 및 승인 현황</h2>
          </div>
          <div className="empty-state compact">대기 중인 작업 없음</div>
        </section>
      </div>
    </main>
  );
}

function SectionPlaceholder({ title }: { title: string }) {
  return (
    <main className="page" id="main-content">
      <div className="page-heading">
        <div>
          <h1>{title}</h1>
          <p>확정 화면과 데이터 계약에 따라 구현 중입니다.</p>
        </div>
      </div>
      <section className="panel route-placeholder">
        <span className="status-pill neutral">구현 중</span>
        <h2>{title} 모듈 준비 중</h2>
        <p>완료되지 않은 행동을 실제 기능처럼 표시하지 않습니다.</p>
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
  const meta = useRuntimeMeta(runtime);
  const logout = useMutation({
    mutationFn: () => apiRequest(runtime, "/auth/logout", { method: "POST" }),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ["auth-session", runtime.profile] });
      navigateInternal(runtime, "/login", true);
    },
  });
  const dataState = meta.isSuccess ? "데이터 정상" : meta.isError ? "연결 확인" : "연결 중";
  const title = routeTitles[currentPath];

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        본문으로 건너뛰기
      </a>
      <header className="topbar">
        <strong className="brand">E-Safe / 전기재해 예방 관제</strong>
        <div className="topbar-status">
          <span className={`profile-badge ${runtime.profile.toLowerCase()}`}>{runtime.badge}</span>
          <span className={`data-status ${meta.isError ? "is-warning" : ""}`}>{dataState}</span>
          <span className="as-of">기준 시각 —</span>
          <button className="notification-button" type="button">
            알림
          </button>
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
        <BriefingScaffold currentPath={currentPath} runtime={runtime} />
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
