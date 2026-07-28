import { useQuery } from "@tanstack/react-query";
import { ApiError, apiRequest } from "./api";
import type { ProfileRuntime } from "./profile";
import { AppLink } from "./router";

export interface BriefingData {
  headline: {
    state: "NO_ACTIVE_CASES" | "ACTION_REQUIRED";
    title: string;
    description: string;
    caseId: string | null;
  };
  metrics: {
    urgentCases: number;
    activeCases: number;
    dueWithin24Hours: number;
    waitingApproval: number;
    sourceResolvedReview: number;
  };
  riskReference: {
    importId: string;
    sourceVersion: string;
    lineageVersion: string;
    referenceMonth: string;
    horizonDays: number;
    buildingCount: number;
    top1Count: number;
    top10Count: number;
    calculatedAt: string;
  };
  priorityRegions: Array<{
    regionCode: string;
    name: string;
    fullName: string;
    buildingCount: number;
    top1Count: number;
    top10Count: number;
    top10Share: number;
    scoreP99: number | null;
  }>;
  recentCases: Array<{
    caseId: string;
    caseNumber: string;
    title: string;
    caseType: string;
    status: string;
    monitoringPriority: string;
    primaryRegionCode: string | null;
    updatedAt: string;
    isSimulated: boolean;
  }>;
  dataAsOf: string;
}

export interface TaskSummaryData {
  counts: {
    queued: number;
    running: number;
    waitingApproval: number;
    onHold: number;
    failed: number;
  };
  items: Array<{
    workItemId: string;
    caseId: string | null;
    workType: string;
    status: string;
    priority: string;
    title: string;
    dueAt: string | null;
    progress: number;
    retryCount: number;
    errorClass: string | null;
    updatedAt: string;
  }>;
  dataAsOf: string | null;
}

export interface SourceHealthData {
  summary: "HEALTHY" | "DELAYED" | "OUTAGE" | "DISABLED";
  sources: Array<{
    source: "NFDS" | "KMA_WARNING" | "DISASTER_MESSAGE";
    executionMode: "EXTERNAL" | "FIXTURE";
    enabled: boolean;
    status: "HEALTHY" | "DELAYED" | "OUTAGE" | "DISABLED";
    lastAttemptAt: string | null;
    lastSuccessAt: string | null;
    lastFailureAt: string | null;
    consecutiveFailures: number;
    nextPollAt: string | null;
    backoffUntil: string | null;
    parserVersion: string;
    contractVersion: string;
    updatedAt: string;
  }>;
  dataAsOf: string | null;
}

const sourceNames = {
  NFDS: "전국119상황실",
  KMA_WARNING: "기상특보",
  DISASTER_MESSAGE: "재난문자",
} as const;

const statusNames: Record<string, string> = {
  DETECTED: "감지",
  ACTIVE: "대응 중",
  ON_HOLD: "보류",
  SOURCE_RESOLVED_REVIEW: "종료 확인",
  QUEUED: "대기",
  RUNNING: "처리 중",
  WAITING_APPROVAL: "승인 대기",
  FAILED: "실패",
};

export function useSourceHealth(runtime: ProfileRuntime) {
  return useQuery({
    queryKey: ["source-health", runtime.profile],
    queryFn: () => apiRequest<SourceHealthData>(runtime, "/sources/health"),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

function useBriefing(runtime: ProfileRuntime) {
  return useQuery({
    queryKey: ["home-briefing", runtime.profile],
    queryFn: () => apiRequest<BriefingData>(runtime, "/briefing"),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

function useTaskSummary(runtime: ProfileRuntime) {
  return useQuery({
    queryKey: ["task-summary", runtime.profile],
    queryFn: () => apiRequest<TaskSummaryData>(runtime, "/tasks/summary"),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}

export function formatKst(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export function sourceSummaryLabel(
  runtime: ProfileRuntime,
  sourceHealth: SourceHealthData | undefined,
): string {
  if (!sourceHealth) {
    return "수집 상태 확인 중";
  }
  const neverAttempted = sourceHealth.sources.every((source) => source.lastAttemptAt === null);
  if (neverAttempted) {
    return runtime.profile === "DEMO" ? "시나리오 대기" : "첫 수집 대기";
  }
  const labels = {
    HEALTHY: "데이터 정상",
    DELAYED: "수집 지연",
    OUTAGE: "수집 장애",
    DISABLED: runtime.profile === "DEMO" ? "시나리오 중지" : "외부 수집 중지",
  } as const;
  return labels[sourceHealth.summary];
}

function PanelMessage({ kind, message }: { kind: "loading" | "error"; message: string }) {
  return (
    <div className={`panel-message ${kind}`} role={kind === "error" ? "alert" : "status"}>
      {message}
    </div>
  );
}

function queryErrorMessage(error: Error | null): string {
  return error instanceof ApiError ? error.message : "이 패널의 데이터를 불러오지 못했습니다.";
}

function BriefingNotice({
  currentPath,
  data,
  runtime,
}: {
  currentPath: string;
  data: BriefingData;
  runtime: ProfileRuntime;
}) {
  const actionRequired = data.headline.state === "ACTION_REQUIRED";
  return (
    <section
      className={`notice-card ${actionRequired ? "is-urgent" : ""}`}
      aria-label="오늘의 관제 요약"
    >
      <span className={`status-pill ${actionRequired ? "urgent" : "neutral"}`}>
        {actionRequired ? "확인 필요" : "현재 Case 없음"}
      </span>
      <div className="notice-content">
        <h2>{data.headline.title}</h2>
        <p>{data.headline.description}</p>
        <p className="reference-caption">
          기준 위험도 {data.riskReference.referenceMonth} · 향후 {data.riskReference.horizonDays}일
          · 건물 {data.riskReference.buildingCount.toLocaleString("ko-KR")}개
        </p>
      </div>
      <div className="notice-actions">
        {data.headline.caseId ? (
          <AppLink
            className="primary-action"
            currentPath={currentPath}
            runtime={runtime}
            to={`/cases/${data.headline.caseId}`}
          >
            Case 확인
          </AppLink>
        ) : null}
        <AppLink className="outline-action" currentPath={currentPath} runtime={runtime} to="/map">
          위험지도 보기
        </AppLink>
      </div>
    </section>
  );
}

function MetricCards({ data }: { data: BriefingData }) {
  const metrics = [
    { label: "긴급 관제 Case", value: data.metrics.urgentCases, note: "현재 우선상태" },
    { label: "진행 중 Case", value: data.metrics.activeCases, note: "감지·대응·보류" },
    { label: "24시간 내 업무", value: data.metrics.dueWithin24Hours, note: "완료 필요" },
    { label: "검토·승인 대기", value: data.metrics.waitingApproval, note: "사용자 결정 필요" },
  ];
  return (
    <section className="metric-grid" aria-label="핵심 현황">
      {metrics.map((metric) => (
        <article className="metric-card" key={metric.label}>
          <p>{metric.label}</p>
          <strong>{metric.value.toLocaleString("ko-KR")}</strong>
          <span>{metric.note}</span>
        </article>
      ))}
    </section>
  );
}

function PriorityRegions({
  currentPath,
  data,
  runtime,
}: {
  currentPath: string;
  data: BriefingData;
  runtime: ProfileRuntime;
}) {
  return (
    <section className="panel priority-panel">
      <div className="panel-heading">
        <div>
          <h2>우선 확인이 필요한 지역</h2>
          <p>v27.1 기준 상위 10% 건물 수가 많은 순입니다.</p>
        </div>
        <AppLink className="outline-action" currentPath={currentPath} runtime={runtime} to="/map">
          전체 지도
        </AppLink>
      </div>
      <ol className="priority-list">
        {data.priorityRegions.map((region, index) => (
          <li key={region.regionCode}>
            <span className="region-rank">{index + 1}</span>
            <div>
              <strong>{region.name}</strong>
              <span>{region.fullName}</span>
            </div>
            <div className="region-metric">
              <strong>{region.top10Count.toLocaleString("ko-KR")}개</strong>
              <span>지역 건물의 {region.top10Share.toFixed(2)}%</span>
            </div>
            <AppLink
              className="text-action"
              currentPath={currentPath}
              runtime={runtime}
              to={`/regions/${region.regionCode}`}
            >
              지역 분석
            </AppLink>
          </li>
        ))}
      </ol>
    </section>
  );
}

function TaskPanel({
  currentPath,
  data,
  runtime,
}: {
  currentPath: string;
  data: TaskSummaryData;
  runtime: ProfileRuntime;
}) {
  return (
    <section className="panel task-panel">
      <div className="panel-heading">
        <div>
          <h2>오늘 처리할 업무</h2>
          <p>긴급도와 기한 순으로 최대 8건을 표시합니다.</p>
        </div>
      </div>
      {data.items.length === 0 ? (
        <div className="empty-state">현재 처리할 업무가 없습니다.</div>
      ) : (
        <ul className="task-list">
          {data.items.map((item) => (
            <li key={item.workItemId}>
              <div>
                <span className={`work-status status-${item.status.toLowerCase()}`}>
                  {statusNames[item.status] ?? item.status}
                </span>
                <strong>{item.title}</strong>
                <span>기한 {formatKst(item.dueAt)}</span>
              </div>
              <AppLink
                className="text-action"
                currentPath={currentPath}
                runtime={runtime}
                to={
                  item.caseId
                    ? `/cases/${item.caseId}/tasks/${item.workItemId}`
                    : "/automation/runs"
                }
              >
                열기
              </AppLink>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RecentCases({
  currentPath,
  data,
  runtime,
}: {
  currentPath: string;
  data: BriefingData;
  runtime: ProfileRuntime;
}) {
  return (
    <section className="panel change-panel">
      <div className="panel-heading">
        <div>
          <h2>최근 위험신호 Case</h2>
          <p>기준 위험점수와 별도로 수집된 관제 사건입니다.</p>
        </div>
      </div>
      {data.recentCases.length === 0 ? (
        <div className="empty-state compact">최근 위험신호 Case가 없습니다.</div>
      ) : (
        <ul className="recent-list">
          {data.recentCases.map((item) => (
            <li key={item.caseId}>
              <div>
                <strong>{item.title}</strong>
                <span>
                  {item.caseNumber} · {statusNames[item.status] ?? item.status} ·{" "}
                  {formatKst(item.updatedAt)}
                </span>
              </div>
              <AppLink
                className="text-action"
                currentPath={currentPath}
                runtime={runtime}
                to={`/cases/${item.caseId}`}
              >
                보기
              </AppLink>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function AutomationPanel({ data }: { data: TaskSummaryData }) {
  const values = [
    ["대기", data.counts.queued],
    ["처리 중", data.counts.running],
    ["승인 대기", data.counts.waitingApproval],
    ["실패", data.counts.failed],
  ] as const;
  return (
    <section className="panel ai-panel">
      <div className="panel-heading">
        <div>
          <h2>자동화 작업 현황</h2>
          <p>비동기 분석·근거·문서 작업 상태입니다.</p>
        </div>
      </div>
      <dl className="automation-counts">
        {values.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value.toLocaleString("ko-KR")}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function SourcePanel({ data, runtime }: { data: SourceHealthData; runtime: ProfileRuntime }) {
  return (
    <section className="source-panel" aria-label="수집원 상태">
      <div>
        <strong>수집원 상태</strong>
        <span>{sourceSummaryLabel(runtime, data)}</span>
      </div>
      <ul>
        {data.sources.map((source) => {
          const waiting = source.lastAttemptAt === null;
          const label = waiting
            ? runtime.profile === "DEMO"
              ? "시나리오 대기"
              : source.enabled
                ? "첫 수집 대기"
                : "중지"
            : source.status === "HEALTHY"
              ? "정상"
              : source.status === "DELAYED"
                ? "지연"
                : source.status === "OUTAGE"
                  ? "장애"
                  : "중지";
          return (
            <li key={source.source}>
              <span className={`source-dot source-${source.status.toLowerCase()}`} />
              <strong>{sourceNames[source.source]}</strong>
              <span>{label}</span>
              <time>{formatKst(source.lastSuccessAt)}</time>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function HomeDashboard({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const briefing = useBriefing(runtime);
  const tasks = useTaskSummary(runtime);
  const sources = useSourceHealth(runtime);
  return (
    <main className="page" id="main-content">
      <div className="page-heading">
        <div>
          <h1>오늘의 상황 브리핑</h1>
          <p>광주·전남 전기재해 위험과 오늘 필요한 예방 조치를 확인하세요.</p>
        </div>
        <fieldset className="briefing-basis">
          <legend className="sr-only">브리핑 기준</legend>
          <span>광주·전남</span>
          <span>2026-03 · 60일</span>
        </fieldset>
      </div>

      {briefing.isLoading ? (
        <PanelMessage kind="loading" message="관제 요약을 불러오고 있습니다." />
      ) : !briefing.isSuccess ? (
        <PanelMessage kind="error" message={queryErrorMessage(briefing.error)} />
      ) : (
        <>
          <BriefingNotice currentPath={currentPath} data={briefing.data.data} runtime={runtime} />
          <MetricCards data={briefing.data.data} />
        </>
      )}

      {sources.isLoading ? (
        <PanelMessage kind="loading" message="수집원 상태를 확인하고 있습니다." />
      ) : !sources.isSuccess ? (
        <PanelMessage kind="error" message={queryErrorMessage(sources.error)} />
      ) : (
        <SourcePanel data={sources.data.data} runtime={runtime} />
      )}

      <div className="dashboard-grid">
        {briefing.isLoading ? (
          <section className="panel priority-panel">
            <PanelMessage kind="loading" message="지역 집계 로딩 중" />
          </section>
        ) : !briefing.isSuccess ? (
          <section className="panel priority-panel">
            <PanelMessage kind="error" message="지역 집계를 불러오지 못했습니다." />
          </section>
        ) : (
          <PriorityRegions currentPath={currentPath} data={briefing.data.data} runtime={runtime} />
        )}

        {tasks.isLoading ? (
          <section className="panel task-panel">
            <PanelMessage kind="loading" message="업무 목록 로딩 중" />
          </section>
        ) : !tasks.isSuccess ? (
          <section className="panel task-panel">
            <PanelMessage kind="error" message={queryErrorMessage(tasks.error)} />
          </section>
        ) : (
          <TaskPanel currentPath={currentPath} data={tasks.data.data} runtime={runtime} />
        )}

        {briefing.isLoading ? (
          <section className="panel change-panel">
            <PanelMessage kind="loading" message="최근 Case 로딩 중" />
          </section>
        ) : !briefing.isSuccess ? (
          <section className="panel change-panel">
            <PanelMessage kind="error" message="최근 Case를 불러오지 못했습니다." />
          </section>
        ) : (
          <RecentCases currentPath={currentPath} data={briefing.data.data} runtime={runtime} />
        )}

        {tasks.isLoading ? (
          <section className="panel ai-panel">
            <PanelMessage kind="loading" message="자동화 상태 로딩 중" />
          </section>
        ) : !tasks.isSuccess ? (
          <section className="panel ai-panel">
            <PanelMessage kind="error" message="자동화 상태를 불러오지 못했습니다." />
          </section>
        ) : (
          <AutomationPanel data={tasks.data.data} />
        )}
      </div>
    </main>
  );
}
