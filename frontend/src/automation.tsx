import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { ApiError, apiRequest } from "./api";
import { formatKst } from "./home";
import type { ProfileRuntime } from "./profile";
import { AppLink, navigateInternal } from "./router";

interface AutomationActivity {
  occurredAt: string;
  entryType: "AUTOMATION_RUN" | "AUDIT_EVENT";
  entryId: string;
  status: "RUNNING" | "SUCCEEDED" | "FAILED" | "SKIPPED" | "RECORDED";
  category: string;
  triggerType: string | null;
  source: string | null;
  actor: { type: string; displayName: string | null };
  case: { caseId: string; caseNumber: string | null } | null;
  workItem: { workItemId: string; title: string | null } | null;
  run: {
    ruleVersion: string | null;
    inputVersion: string | null;
    outputVersion: string | null;
    retryCount: number;
    errorClass: string | null;
    finishedAt: string | null;
  } | null;
}

interface AutomationActivityData {
  summary: {
    todayActivity: number;
    waitingApproval: number;
    running: number;
    failedLast24h: number;
  };
  items: AutomationActivity[];
  page: number;
  pageSize: number;
  total: number;
  dataAsOf: string;
}

interface AutomationPolicyData {
  policyVersion: string;
  mutable: false;
  profile: "LIVE" | "DEMO";
  scope: {
    regions: Array<{ regionCode: string; name: string }>;
    weatherWarningTypes: "ALL";
    disasterMessageFilter: string;
  };
  schedule: {
    pollIntervalMinutes: number;
    jitterSeconds: { minimum: number; maximum: number };
    caseReflectionTargetMinutes: number;
    delayedAfterMinutes: number;
    outageAfterMinutes: number;
  };
  sources: Array<{
    source: string;
    enabled: boolean;
    mode: "LIVE" | "FIXTURE";
  }>;
  deterministicRules: {
    sameSourceUpdate: boolean;
    crossSourceFireWindowHours: number;
    crossSourceFireDistanceM: number;
    pointImpactDefaultRadiusM: number;
    allowedImpactRadiusM: number[];
    weatherImpactScope: string;
    highRiskTopPercentile: number;
    automaticMergeByLlm: false;
  };
  approvalBoundary: {
    singleUserSingleStage: boolean;
    decisions: string[];
    externalEffectWithoutApproval: false;
    actualEmailOrOfficialDispatch: false;
    sourceResolvedRequiresUserClose: true;
  };
  retry: {
    sourceSchemaBackoffMinutes: number[];
    automaticAiRetries: number;
    externalEffectRetries: number;
  };
  capabilities: Array<{ code: string; label: string; status: string }>;
}

interface ActivityFilters {
  status: string;
  entryType: string;
  source: string;
  hours: string;
  search: string;
}

const activityStatus: Record<string, string> = {
  RUNNING: "진행 중",
  SUCCEEDED: "완료",
  FAILED: "실패",
  SKIPPED: "건너뜀",
  RECORDED: "기록",
};

const sourceNames: Record<string, string> = {
  NFDS: "전국119상황실",
  KMA_WARNING: "기상특보",
  DISASTER_MESSAGE: "재난문자",
};

const categoryNames: Record<string, string> = {
  SIGNAL_POLL: "신호 수집",
  SIGNAL_INGESTED: "신호 수신",
  CASE_CREATED: "Case 생성",
  CASE_UPDATED: "Case 갱신",
  CASE_STATUS_CHANGED: "Case 상태 변경",
  SESSION_LOGIN_SUCCEEDED: "로그인",
  SESSION_LOGOUT: "로그아웃",
};

const capabilityStatus: Record<string, string> = {
  ACTIVE: "사용 중",
  READY_NOT_CONNECTED: "준비됨 · 연결 전",
  NOT_IMPLEMENTED: "미구현",
};

const initialFilters = (): ActivityFilters => {
  const params = new URLSearchParams(window.location.search);
  return {
    status: params.get("status") ?? "",
    entryType: params.get("entryType") ?? "",
    source: params.get("source") ?? "",
    hours: params.get("hours") ?? "24",
    search: params.get("q") ?? "",
  };
};

function queryError(error: Error | null): string {
  return error instanceof ApiError
    ? error.message
    : "자동화 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.";
}

function AutomationTabs({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  return (
    <nav className="automation-tabs" aria-label="자동화 메뉴">
      <AppLink
        className="automation-tab"
        currentPath={currentPath}
        runtime={runtime}
        to="/automation/runs"
      >
        실행·감사 기록
      </AppLink>
      <AppLink
        className="automation-tab"
        currentPath={currentPath}
        runtime={runtime}
        to="/automation/policies"
      >
        운영 정책
      </AppLink>
    </nav>
  );
}

function ActivityPage({ currentPath, runtime }: { currentPath: string; runtime: ProfileRuntime }) {
  const params = new URLSearchParams(window.location.search);
  const [draft, setDraft] = useState(initialFilters);
  const [filters, setFilters] = useState(initialFilters);
  const [page, setPage] = useState(Number(params.get("page") ?? 1) || 1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const query = new URLSearchParams({
    page: String(page),
    pageSize: "20",
    hours: filters.hours,
  });
  if (filters.status) query.set("status", filters.status);
  if (filters.entryType) query.set("entryType", filters.entryType);
  if (filters.source) query.set("source", filters.source);
  if (filters.search) query.set("search", filters.search);
  const activity = useQuery({
    queryKey: ["automation-activity", runtime.profile, filters, page],
    queryFn: () =>
      apiRequest<AutomationActivityData>(runtime, `/automation/runs?${query.toString()}`).then(
        (response) => response.data,
      ),
    placeholderData: (previous) => previous,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
  const selected =
    activity.data?.items.find((item) => item.entryId === selectedId) ??
    activity.data?.items[0] ??
    null;

  const updateLocation = (nextFilters: ActivityFilters, nextPage: number) => {
    const next = new URLSearchParams();
    if (nextFilters.status) next.set("status", nextFilters.status);
    if (nextFilters.entryType) next.set("entryType", nextFilters.entryType);
    if (nextFilters.source) next.set("source", nextFilters.source);
    if (nextFilters.hours !== "24") next.set("hours", nextFilters.hours);
    if (nextFilters.search) next.set("q", nextFilters.search);
    if (nextPage > 1) next.set("page", String(nextPage));
    navigateInternal(runtime, `/automation/runs${next.size ? `?${next}` : ""}`, true);
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setFilters(draft);
    setPage(1);
    setSelectedId(null);
    updateLocation(draft, 1);
  };
  const totalPages = Math.max(1, Math.ceil((activity.data?.total ?? 0) / 20));

  return (
    <main className="page automation-page" id="main-content">
      <div className="page-heading automation-heading">
        <div>
          <span className="eyebrow">AUT-01B</span>
          <h1>자동화 실행·감사 기록</h1>
          <p>수집 작업과 시스템·사용자 변경 이력을 시간순으로 확인합니다.</p>
        </div>
        <span className="automation-asof">기준 {formatKst(activity.data?.dataAsOf)}</span>
      </div>
      <AutomationTabs currentPath={currentPath} runtime={runtime} />
      {activity.isError ? (
        <div className="automation-state error" role="alert">
          {queryError(activity.error)}
        </div>
      ) : (
        <>
          <section className="automation-summary" aria-label="자동화 현황 요약">
            <article>
              <span>오늘 활동</span>
              <strong>{activity.data?.summary.todayActivity ?? "—"}</strong>
              <small>실행·감사 합계</small>
            </article>
            <article>
              <span>승인 대기</span>
              <strong>{activity.data?.summary.waitingApproval ?? "—"}</strong>
              <small>사용자 결정 필요</small>
            </article>
            <article>
              <span>진행 중</span>
              <strong>{activity.data?.summary.running ?? "—"}</strong>
              <small>현재 작업</small>
            </article>
            <article className={(activity.data?.summary.failedLast24h ?? 0) > 0 ? "warning" : ""}>
              <span>최근 24시간 실패</span>
              <strong>{activity.data?.summary.failedLast24h ?? "—"}</strong>
              <small>재확인 대상</small>
            </article>
          </section>
          <form className="automation-filters" onSubmit={submit}>
            <label>
              <span>기간</span>
              <select
                onChange={(event) => setDraft({ ...draft, hours: event.target.value })}
                value={draft.hours}
              >
                <option value="24">최근 24시간</option>
                <option value="168">최근 7일</option>
                <option value="720">최근 30일</option>
              </select>
            </label>
            <label>
              <span>유형</span>
              <select
                onChange={(event) => setDraft({ ...draft, entryType: event.target.value })}
                value={draft.entryType}
              >
                <option value="">전체</option>
                <option value="AUTOMATION_RUN">자동 실행</option>
                <option value="AUDIT_EVENT">감사 기록</option>
              </select>
            </label>
            <label>
              <span>상태</span>
              <select
                onChange={(event) => setDraft({ ...draft, status: event.target.value })}
                value={draft.status}
              >
                <option value="">전체</option>
                {Object.entries(activityStatus).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>신호 원천</span>
              <select
                onChange={(event) => setDraft({ ...draft, source: event.target.value })}
                value={draft.source}
              >
                <option value="">전체</option>
                {Object.entries(sourceNames).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="automation-search">
              <span>검색</span>
              <input
                maxLength={100}
                onChange={(event) => setDraft({ ...draft, search: event.target.value })}
                placeholder="작업·Case·기록 ID"
                value={draft.search}
              />
            </label>
            <button className="primary-action automation-submit" type="submit">
              조회
            </button>
          </form>
          <section className="automation-workspace">
            <div className="panel automation-list-panel">
              <div className="panel-heading">
                <div>
                  <h2>활동 타임라인</h2>
                  <span>총 {activity.data?.total ?? 0}건</span>
                </div>
                {activity.isFetching ? <span className="status-pill neutral">갱신 중</span> : null}
              </div>
              {activity.isLoading ? (
                <div className="automation-state" role="status">
                  기록을 불러오고 있습니다.
                </div>
              ) : activity.data?.items.length ? (
                <div className="automation-list">
                  <div className="automation-list-head" aria-hidden="true">
                    <span>시각</span>
                    <span>유형·작업</span>
                    <span>원천</span>
                    <span>상태</span>
                    <span>연결 대상</span>
                  </div>
                  {activity.data.items.map((item) => (
                    <button
                      className={`automation-row${selected?.entryId === item.entryId ? " selected" : ""}`}
                      key={item.entryId}
                      onClick={() => setSelectedId(item.entryId)}
                      type="button"
                    >
                      <time>{formatKst(item.occurredAt)}</time>
                      <span>
                        <strong>{categoryNames[item.category] ?? item.category}</strong>
                        <small>
                          {item.entryType === "AUTOMATION_RUN" ? "자동 실행" : "감사 기록"}
                        </small>
                      </span>
                      <span>{item.source ? (sourceNames[item.source] ?? item.source) : "—"}</span>
                      <span className={`automation-status ${item.status.toLowerCase()}`}>
                        {activityStatus[item.status] ?? item.status}
                      </span>
                      <span>{item.case?.caseNumber ?? item.workItem?.title ?? "—"}</span>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="automation-state">조건에 맞는 기록이 없습니다.</div>
              )}
              <div className="automation-pagination">
                <button
                  disabled={page <= 1}
                  onClick={() => {
                    const next = page - 1;
                    setPage(next);
                    setSelectedId(null);
                    updateLocation(filters, next);
                  }}
                  type="button"
                >
                  이전
                </button>
                <span>
                  {page} / {totalPages}
                </span>
                <button
                  disabled={page >= totalPages}
                  onClick={() => {
                    const next = page + 1;
                    setPage(next);
                    setSelectedId(null);
                    updateLocation(filters, next);
                  }}
                  type="button"
                >
                  다음
                </button>
              </div>
            </div>
            <aside className="panel automation-detail">
              <div className="panel-heading">
                <div>
                  <h2>기록 상세</h2>
                  <span>원문·비밀값은 표시하지 않습니다.</span>
                </div>
              </div>
              {selected ? (
                <>
                  <div className="automation-detail-title">
                    <span className={`automation-status ${selected.status.toLowerCase()}`}>
                      {activityStatus[selected.status] ?? selected.status}
                    </span>
                    <h3>{categoryNames[selected.category] ?? selected.category}</h3>
                    <code>{selected.entryId}</code>
                  </div>
                  <dl className="automation-detail-list">
                    <div>
                      <dt>발생 시각</dt>
                      <dd>{formatKst(selected.occurredAt)}</dd>
                    </div>
                    <div>
                      <dt>행위자</dt>
                      <dd>{selected.actor.displayName ?? selected.actor.type}</dd>
                    </div>
                    <div>
                      <dt>트리거</dt>
                      <dd>{selected.triggerType ?? "—"}</dd>
                    </div>
                    <div>
                      <dt>규칙 버전</dt>
                      <dd>{selected.run?.ruleVersion ?? "—"}</dd>
                    </div>
                    <div>
                      <dt>재시도</dt>
                      <dd>{selected.run ? `${selected.run.retryCount}회` : "—"}</dd>
                    </div>
                    <div>
                      <dt>완료 시각</dt>
                      <dd>{formatKst(selected.run?.finishedAt)}</dd>
                    </div>
                  </dl>
                  {selected.run?.errorClass ? (
                    <div className="automation-error-box">
                      <strong>오류 유형</strong>
                      <span>{selected.run.errorClass}</span>
                    </div>
                  ) : null}
                  {selected.case ? (
                    <AppLink
                      className="automation-linked-action"
                      currentPath={currentPath}
                      runtime={runtime}
                      to={`/cases/${selected.case.caseId}`}
                    >
                      {selected.case.caseNumber ?? "연결 Case"} 보기
                    </AppLink>
                  ) : null}
                </>
              ) : (
                <div className="automation-state">왼쪽에서 기록을 선택하세요.</div>
              )}
            </aside>
          </section>
        </>
      )}
    </main>
  );
}

function PolicyPage({ currentPath, runtime }: { currentPath: string; runtime: ProfileRuntime }) {
  const policies = useQuery({
    queryKey: ["automation-policies", runtime.profile],
    queryFn: () =>
      apiRequest<AutomationPolicyData>(runtime, "/automation/policies").then(
        (response) => response.data,
      ),
    staleTime: 60_000,
  });
  const data = policies.data;
  return (
    <main className="page automation-page" id="main-content">
      <div className="page-heading">
        <div>
          <span className="eyebrow">AUT-02B</span>
          <h1>자동화 운영 정책</h1>
          <p>현재 배포에 적용된 범위·결정 규칙·승인 경계를 확인합니다.</p>
        </div>
        {data ? <span className="status-pill neutral">{data.policyVersion}</span> : null}
      </div>
      <AutomationTabs currentPath={currentPath} runtime={runtime} />
      {policies.isLoading ? (
        <div className="automation-state" role="status">
          정책을 불러오고 있습니다.
        </div>
      ) : policies.isError || !data ? (
        <div className="automation-state error" role="alert">
          {queryError(policies.error)}
        </div>
      ) : (
        <>
          <div className="automation-readonly">
            <strong>읽기 전용 운영 계약</strong>
            <span>
              이 화면에서는 정책을 변경하지 않습니다. 변경은 검증된 코드·설정 배포로만 적용됩니다.
            </span>
          </div>
          <section className="automation-policy-grid">
            <article className="panel automation-policy-card">
              <div className="panel-heading">
                <div>
                  <h2>신호 수집</h2>
                  <span>{data.profile === "LIVE" ? "실제 원천 연결" : "원천형 fixture"}</span>
                </div>
              </div>
              <ul className="automation-source-list">
                {data.sources.map((source) => (
                  <li key={source.source}>
                    <span className={`source-dot ${source.enabled ? "on" : "off"}`} />
                    <span>
                      <strong>{sourceNames[source.source] ?? source.source}</strong>
                      <small>{source.mode === "LIVE" ? "실시간 연동" : "체험 데이터"}</small>
                    </span>
                    <b>{source.enabled ? "사용" : "중단"}</b>
                  </li>
                ))}
              </ul>
              <dl className="automation-policy-values">
                <div>
                  <dt>수집 주기</dt>
                  <dd>{data.schedule.pollIntervalMinutes}분 + 지터</dd>
                </div>
                <div>
                  <dt>지연·장애</dt>
                  <dd>
                    {data.schedule.delayedAfterMinutes}분 / {data.schedule.outageAfterMinutes}분
                  </dd>
                </div>
                <div>
                  <dt>관할</dt>
                  <dd>{data.scope.regions.map((region) => region.name).join(" · ")}</dd>
                </div>
              </dl>
            </article>
            <article className="panel automation-policy-card">
              <div className="panel-heading">
                <div>
                  <h2>결정적 Case·영향 규칙</h2>
                  <span>LLM 단독 병합 금지</span>
                </div>
              </div>
              <dl className="automation-policy-values prominent">
                <div>
                  <dt>교차 화재 연결</dt>
                  <dd>
                    {data.deterministicRules.crossSourceFireWindowHours}시간 ·{" "}
                    {data.deterministicRules.crossSourceFireDistanceM}m
                  </dd>
                </div>
                <div>
                  <dt>지점 기본 영향</dt>
                  <dd>{data.deterministicRules.pointImpactDefaultRadiusM.toLocaleString()}m</dd>
                </div>
                <div>
                  <dt>기상 영향 범위</dt>
                  <dd>행정구역</dd>
                </div>
                <div>
                  <dt>우선 위험 건물</dt>
                  <dd>상위 {data.deterministicRules.highRiskTopPercentile}%</dd>
                </div>
                <div>
                  <dt>허용 반경</dt>
                  <dd>
                    {data.deterministicRules.allowedImpactRadiusM
                      .map((radius) => `${radius / 1000}km`)
                      .join(" · ")}
                  </dd>
                </div>
              </dl>
            </article>
            <article className="panel automation-policy-card">
              <div className="panel-heading">
                <div>
                  <h2>승인 경계·재시도</h2>
                  <span>외부 효과는 사용자 결정 뒤 수행</span>
                </div>
              </div>
              <dl className="automation-policy-values prominent">
                <div>
                  <dt>사용자 결정</dt>
                  <dd>승인 · 보류 · 폐기</dd>
                </div>
                <div>
                  <dt>원천 종료</dt>
                  <dd>사용자 확인 후 Case 종료</dd>
                </div>
                <div>
                  <dt>스키마 오류 재시도</dt>
                  <dd>{data.retry.sourceSchemaBackoffMinutes.join(" · ")}분</dd>
                </div>
                <div>
                  <dt>AI 자동 재시도</dt>
                  <dd>{data.retry.automaticAiRetries}회</dd>
                </div>
                <div>
                  <dt>메일·전자공문</dt>
                  <dd>자동 발송 없음</dd>
                </div>
              </dl>
            </article>
            <article className="panel automation-policy-card capability-card">
              <div className="panel-heading">
                <div>
                  <h2>현재 구현 상태</h2>
                  <span>배포 기능을 과장하지 않는 상태 표시</span>
                </div>
              </div>
              <ul className="automation-capabilities">
                {data.capabilities.map((capability) => (
                  <li key={capability.code}>
                    <span>{capability.label}</span>
                    <strong className={capability.status.toLowerCase()}>
                      {capabilityStatus[capability.status] ?? capability.status}
                    </strong>
                  </li>
                ))}
              </ul>
            </article>
          </section>
        </>
      )}
    </main>
  );
}

export function AutomationManagement({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  return currentPath === "/automation/policies" ? (
    <PolicyPage currentPath={currentPath} runtime={runtime} />
  ) : (
    <ActivityPage currentPath={currentPath} runtime={runtime} />
  );
}
