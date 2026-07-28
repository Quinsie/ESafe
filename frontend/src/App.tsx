import { useQuery } from "@tanstack/react-query";
import type { ProfileRuntime } from "./profile";
import { AppLink, useInternalPath } from "./router";

interface MetaResponse {
  data: {
    profile: "LIVE" | "DEMO";
    profileBadge: string;
    version: string;
    commit: string;
  };
}

const navigation = [
  { group: "OVERVIEW", label: "상황 브리핑", to: "/" },
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

function useRuntimeMeta(runtime: ProfileRuntime) {
  return useQuery({
    queryKey: ["runtime-meta", runtime.profile],
    queryFn: async (): Promise<MetaResponse> => {
      const response = await fetch(`${runtime.apiBase}/meta`, {
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error("runtime-meta-unavailable");
      }
      return response.json() as Promise<MetaResponse>;
    },
  });
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

export function App({ runtime }: { runtime: ProfileRuntime }) {
  const currentPath = useInternalPath(runtime);
  const meta = useRuntimeMeta(runtime);
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
        </div>
      </header>
      <Sidebar currentPath={currentPath} runtime={runtime} />
      {currentPath === "/" || !title ? (
        <BriefingScaffold currentPath={currentPath} runtime={runtime} />
      ) : (
        <SectionPlaceholder title={title} />
      )}
    </div>
  );
}
