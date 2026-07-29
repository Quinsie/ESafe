import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ApiError, apiRequest } from "./api";
import { formatKst } from "./home";
import type { ProfileRuntime } from "./profile";
import { AppLink } from "./router";

type EvidenceStatus = "SUFFICIENT" | "INSUFFICIENT" | "CONFLICT";
type WorkStatus =
  | "QUEUED"
  | "RUNNING"
  | "WAITING_APPROVAL"
  | "COMPLETED"
  | "ON_HOLD"
  | "DISCARDED"
  | "FAILED";

interface CaseContext {
  caseId: string;
  caseNumber: string;
  title: string;
  caseType: string;
  status: string;
  regionName: string | null;
  updatedAt: string;
}

interface EvidenceItem {
  evidenceItemId: string;
  documentId: string;
  documentTitle: string;
  documentFamily: string;
  issuingAgency: string | null;
  documentNumber: string | null;
  publishedAt: string | null;
  revision: string | null;
  authorityLevel: number;
  privacyStatus: string;
  evidenceGroup: "OFFICIAL" | "PAST_INCIDENT" | "OTHER_REGION";
  rank: number;
  fusedScore: number;
  currentStatus: string;
  selectionReason: string;
  excerpt: string;
  locator: string;
  pageOrSection: string | null;
  headingPath: string[];
}

interface Citation {
  citationId: string;
  evidenceItemId: string;
  supportType: string;
  quote: string;
  locator: string;
  documentTitle: string;
  issuingAgency: string | null;
  documentNumber: string | null;
  publishedAt: string | null;
}

interface RecommendationAction {
  recommendationActionId: string;
  ordinal: number;
  title: string;
  description: string;
  dueGuidance: string | null;
  evidenceStatus: EvidenceStatus;
  warning: string | null;
  status: string;
  workItemId: string | null;
  workItemStatus: WorkStatus | null;
  citations: Citation[];
}

interface Recommendation {
  recommendationId: string;
  version: number;
  status: string;
  generationMode: string;
  situationSummary: string;
  requiredChecks: string[];
  uncertainties: string[];
  conflicts: string[];
  warning: string | null;
  generationVersion: string;
  createdAt: string;
  actions: RecommendationAction[];
}

interface CaseEvidenceData {
  case: CaseContext;
  retrievalState: "NOT_RUN" | "COMPLETED";
  evidenceStatus: EvidenceStatus;
  warning: string | null;
  bundle: {
    evidenceBundleId: string;
    version: number;
    indexVersionId: string | null;
    indexStatus: string | null;
    indexedDocumentCount: number;
    indexedChunkCount: number;
    candidateCount: number;
    selectedCount: number;
    directCitationCount: number;
    retrievalVersion: string;
    createdAt: string;
  } | null;
  officialEvidence: EvidenceItem[];
  similarIncidents: EvidenceItem[];
  otherRegionReferences: EvidenceItem[];
  recommendation: Recommendation | null;
}

interface ChecklistItem {
  checklistItemId: string;
  ordinal: number;
  label: string;
  status: "PENDING" | "DONE" | "SKIPPED";
  note: string | null;
  completedAt: string | null;
  updatedAt: string;
}

interface WorkItem {
  workItemId: string;
  caseId: string | null;
  recommendationActionId: string | null;
  workType: string;
  status: WorkStatus;
  priority: "NORMAL" | "HIGH" | "URGENT";
  title: string;
  dueAt: string | null;
  progress: number;
  errorClass: string | null;
  retryCount: number;
  version: number;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  updatedAt: string;
  checklist: ChecklistItem[];
}

interface WorkItemsData {
  summary: {
    total: number;
    open: number;
    waitingApproval: number;
    completed: number;
  };
  items: WorkItem[];
}

interface ClosureReviewData {
  caseId: string;
  caseNumber: string;
  title: string;
  status: string;
  sourceStatus: string;
  openedAt: string;
  updatedAt: string;
  sourceResolvedAt: string | null;
  closedAt: string | null;
  closeReason: string | null;
  evidenceStatus: EvidenceStatus;
  evidenceWarning: string | null;
  workSummary: {
    incomplete: number;
    completed: number;
    discarded: number;
  };
  incompleteWorkItems: Array<{
    workItemId: string;
    title: string;
    status: WorkStatus;
    priority: "NORMAL" | "HIGH" | "URGENT";
    progress: number;
    updatedAt: string;
  }>;
  completedClosure: {
    caseClosureId: string;
    version: number;
    summary: string;
    createdAt: string;
  } | null;
  closurePolicy: "PENDING_USER_DECISION";
}

interface TimelineData {
  items: Array<{
    occurredAt: string;
    entryType: "SIGNAL_RAW" | "AUDIT" | "WORK_ITEM";
    entryId: string;
    category: string;
    title: string;
  }>;
  total: number;
}

const evidenceLabels: Record<EvidenceStatus, string> = {
  SUFFICIENT: "근거 충분",
  INSUFFICIENT: "근거 부족",
  CONFLICT: "근거 충돌",
};

const workStatusLabels: Record<WorkStatus, string> = {
  QUEUED: "대기",
  RUNNING: "진행 중",
  WAITING_APPROVAL: "승인 대기",
  COMPLETED: "완료",
  ON_HOLD: "보류",
  DISCARDED: "폐기",
  FAILED: "오류",
};

const priorityLabels = {
  NORMAL: "일반",
  HIGH: "높음",
  URGENT: "긴급",
} as const;

const transitions: Record<
  WorkStatus,
  Array<{ status: WorkStatus; label: string; destructive?: boolean }>
> = {
  QUEUED: [
    { status: "RUNNING", label: "과업 시작" },
    { status: "ON_HOLD", label: "보류" },
    { status: "DISCARDED", label: "폐기", destructive: true },
  ],
  RUNNING: [
    { status: "WAITING_APPROVAL", label: "승인 요청" },
    { status: "ON_HOLD", label: "보류" },
    { status: "FAILED", label: "오류 기록", destructive: true },
  ],
  WAITING_APPROVAL: [
    { status: "COMPLETED", label: "완료 승인" },
    { status: "ON_HOLD", label: "보류" },
    { status: "DISCARDED", label: "폐기", destructive: true },
  ],
  ON_HOLD: [
    { status: "RUNNING", label: "재개" },
    { status: "WAITING_APPROVAL", label: "승인 요청" },
    { status: "DISCARDED", label: "폐기", destructive: true },
  ],
  FAILED: [
    { status: "QUEUED", label: "재시도" },
    { status: "DISCARDED", label: "폐기", destructive: true },
  ],
  COMPLETED: [],
  DISCARDED: [],
};

function queryMessage(error: Error | null, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function idempotencyKey(scope: string): string {
  return `${scope}-${crypto.randomUUID()}`;
}

function statusClass(status: string): string {
  return status.toLowerCase().replaceAll("_", "-");
}

function WorkflowState({ error = false, message }: { error?: boolean; message: string }) {
  return (
    <main className="page workflow-page" id="main-content">
      <div className={`workflow-state${error ? " error" : ""}`} role={error ? "alert" : "status"}>
        {message}
      </div>
    </main>
  );
}

function EvidencePill({ status }: { status: EvidenceStatus }) {
  return <span className={`evidence-status ${statusClass(status)}`}>{evidenceLabels[status]}</span>;
}

function WorkPill({ status }: { status: WorkStatus }) {
  return (
    <span className={`workflow-work-status ${statusClass(status)}`}>
      {workStatusLabels[status]}
    </span>
  );
}

function EvidenceCard({ item }: { item: EvidenceItem }) {
  return (
    <article className="evidence-card">
      <div className="evidence-card-heading">
        <div>
          <strong>{item.documentTitle}</strong>
          <p>
            {item.issuingAgency ?? "발행기관 미확인"}
            {item.documentNumber ? ` · ${item.documentNumber}` : ""}
            {item.publishedAt ? ` · ${item.publishedAt}` : ""}
          </p>
        </div>
        <span>#{item.rank}</span>
      </div>
      <blockquote>{item.excerpt}</blockquote>
      <dl>
        <div>
          <dt>인용 위치</dt>
          <dd>{item.locator}</dd>
        </div>
        <div>
          <dt>선정 근거</dt>
          <dd>{item.selectionReason}</dd>
        </div>
      </dl>
    </article>
  );
}

function EvidenceGroup({
  description,
  empty,
  items,
  title,
}: {
  description: string;
  empty: string;
  items: EvidenceItem[];
  title: string;
}) {
  return (
    <section className="panel evidence-group">
      <div className="workflow-section-heading">
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        <span>{items.length}건</span>
      </div>
      {items.length ? (
        <div className="evidence-card-list">
          {items.map((item) => (
            <EvidenceCard item={item} key={item.evidenceItemId} />
          ))}
        </div>
      ) : (
        <div className="workflow-empty">{empty}</div>
      )}
    </section>
  );
}

function CaseEvidence({
  caseId,
  currentPath,
  runtime,
}: {
  caseId: string;
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const queryClient = useQueryClient();
  const [retrieving, setRetrieving] = useState(false);
  const previousBundleId = useRef<string | null>(null);
  const evidence = useQuery({
    queryKey: ["case-evidence", runtime.profile, caseId],
    queryFn: () =>
      apiRequest<CaseEvidenceData>(runtime, `/cases/${caseId}/evidence`).then(
        (result) => result.data,
      ),
    staleTime: 15_000,
    refetchInterval: retrieving ? 2_000 : false,
  });
  const retrieve = useMutation({
    mutationFn: () =>
      apiRequest<{ caseId: string; taskId: string; status: string; reused: boolean }>(
        runtime,
        `/cases/${caseId}/evidence/retrieve`,
        {
          method: "POST",
          headers: { "Idempotency-Key": idempotencyKey("evidence") },
        },
      ),
    onMutate: () => {
      previousBundleId.current = evidence.data?.bundle?.evidenceBundleId ?? null;
      setRetrieving(true);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["case-evidence", runtime.profile, caseId],
      });
    },
    onError: () => setRetrieving(false),
  });

  useEffect(() => {
    if (!retrieving || !evidence.data) return;
    const currentBundleId = evidence.data.bundle?.evidenceBundleId ?? null;
    const completedNewRun =
      evidence.data.retrievalState === "COMPLETED" &&
      (previousBundleId.current === null || currentBundleId !== previousBundleId.current);
    if (completedNewRun) setRetrieving(false);
  }, [evidence.data, retrieving]);

  if (evidence.isLoading)
    return <WorkflowState message="근거 기반 대응 절차를 준비하고 있습니다." />;
  if (evidence.isError || !evidence.data) {
    return (
      <WorkflowState
        error
        message={queryMessage(evidence.error, "Case 근거를 불러오지 못했습니다.")}
      />
    );
  }

  const data = evidence.data;
  const actions = data.recommendation?.actions ?? [];
  const completedActions = actions.filter(
    (action) => action.workItemStatus === "COMPLETED" || action.status === "COMPLETED",
  ).length;
  const directActions = actions.filter((action) => action.citations.length > 0).length;
  const citationCoverage = actions.length ? Math.round((directActions / actions.length) * 100) : 0;
  const steps = [
    { label: "신호 확인", state: "complete" },
    {
      label: "근거 검색",
      state: data.retrievalState === "COMPLETED" ? "complete" : "current",
    },
    {
      label: "대응안 확인",
      state: data.recommendation
        ? "complete"
        : data.retrievalState === "COMPLETED"
          ? "current"
          : "next",
    },
    {
      label: "수행과업",
      state: actions.some((action) => action.workItemId) ? "current" : "next",
    },
    { label: "결과 보고", state: data.case.status === "CLOSED" ? "complete" : "next" },
  ];

  return (
    <main className="page workflow-page" id="main-content">
      <AppLink
        className="analysis-back"
        currentPath={currentPath}
        runtime={runtime}
        to={`/cases/${caseId}`}
      >
        ‹ 통합 상황판으로 돌아가기
      </AppLink>
      <div className="page-heading workflow-heading">
        <div>
          <p className="case-breadcrumb">재난 대응 / 근거 기반 대응 절차</p>
          <h1>근거 기반 대응 절차</h1>
          <p>
            {data.case.caseNumber} · {data.case.title} · {data.case.regionName ?? "지역 확인 필요"}
          </p>
        </div>
        <EvidencePill status={data.evidenceStatus} />
      </div>

      <section className="workflow-summary">
        <article>
          <span>검색 상태</span>
          <strong>
            {retrieving ? "갱신 중" : data.retrievalState === "COMPLETED" ? "검색 완료" : "검색 전"}
          </strong>
        </article>
        <article>
          <span>선택 근거</span>
          <strong>{data.bundle?.selectedCount ?? 0}건</strong>
        </article>
        <article>
          <span>공식 근거</span>
          <strong>{data.officialEvidence.length}건</strong>
        </article>
        <article>
          <span>제안 행동</span>
          <strong>{actions.length}건</strong>
        </article>
        <article>
          <span>직접 인용 충족률</span>
          <strong>{actions.length ? `${citationCoverage}%` : "계산 전"}</strong>
        </article>
      </section>

      <section className="panel workflow-step-panel">
        <div className="workflow-section-heading">
          <div>
            <h2>대응 절차</h2>
            <p>실제 Case 처리 상태에 따라 다음 단계가 열립니다.</p>
          </div>
          <button
            className="workflow-primary-action"
            disabled={retrieve.isPending || retrieving}
            onClick={() => retrieve.mutate()}
            type="button"
          >
            {retrieve.isPending || retrieving
              ? "근거 검색 갱신 중…"
              : data.retrievalState === "COMPLETED"
                ? "근거 다시 검색"
                : "근거 검색 시작"}
          </button>
        </div>
        <ol className="workflow-steps">
          {steps.map((step, index) => (
            <li className={step.state} key={step.label}>
              <span>{index + 1}</span>
              <strong>{step.label}</strong>
              <small>
                {step.state === "complete"
                  ? "완료"
                  : step.state === "current"
                    ? "현재 단계"
                    : "대기"}
              </small>
            </li>
          ))}
        </ol>
        {data.warning ? (
          <div className={`evidence-warning ${statusClass(data.evidenceStatus)}`} role="status">
            <strong>{evidenceLabels[data.evidenceStatus]}</strong>
            <span>{data.warning}</span>
          </div>
        ) : null}
        {retrieve.isError ? (
          <div className="workflow-inline-error" role="alert">
            {queryMessage(retrieve.error, "근거 검색 작업을 시작하지 못했습니다.")}
          </div>
        ) : null}
      </section>

      <div className="evidence-grid">
        <EvidenceGroup
          description="현재 대응을 직접 뒷받침하는 공식·현행 문서입니다."
          empty="선택된 공식 근거가 없습니다. 근거 부족 경고를 유지합니다."
          items={data.officialEvidence}
          title="공식 현행 근거"
        />
        <EvidenceGroup
          description="과거 대응을 참고하기 위한 사례이며 현재 지침을 대신하지 않습니다."
          empty="선택된 과거 사고사례가 없습니다."
          items={data.similarIncidents}
          title="과거 사고사례"
        />
      </div>
      <EvidenceGroup
        description="광주·전남 외 문서는 보조 참고로만 사용합니다."
        empty="선택된 타 지역 보조자료가 없습니다."
        items={data.otherRegionReferences}
        title="타 지역 보조자료"
      />

      <section className="panel recommendation-panel">
        <div className="workflow-section-heading">
          <div>
            <h2>대응 제안과 수행과업</h2>
            <p>각 행동은 직접 인용과 경고를 분리해 표시합니다.</p>
          </div>
          <span>
            {completedActions}/{actions.length} 완료
          </span>
        </div>
        {!data.recommendation ? (
          <div className="workflow-empty">
            구조화된 대응 제안이 아직 생성되지 않았습니다. 검색 근거만으로 자동 조치를 실행하지
            않습니다.
          </div>
        ) : (
          <>
            <div className="recommendation-summary">
              <strong>{data.recommendation.situationSummary}</strong>
              {data.recommendation.warning ? <span>{data.recommendation.warning}</span> : null}
            </div>
            <ol className="recommendation-actions">
              {actions.map((action) => (
                <li key={action.recommendationActionId}>
                  <span>{action.ordinal}</span>
                  <div>
                    <div className="recommendation-action-title">
                      <strong>{action.title}</strong>
                      <EvidencePill status={action.evidenceStatus} />
                    </div>
                    <p>{action.description}</p>
                    {action.warning ? (
                      <small className="action-warning">{action.warning}</small>
                    ) : null}
                    <div className="action-citations">
                      {action.citations.length ? (
                        action.citations.map((citation) => (
                          <span key={citation.citationId}>
                            {citation.documentTitle} · {citation.locator}
                          </span>
                        ))
                      ) : (
                        <span className="missing">직접 연결된 인용 없음</span>
                      )}
                    </div>
                  </div>
                  {action.workItemId ? (
                    <AppLink
                      className="workflow-action-link"
                      currentPath={currentPath}
                      runtime={runtime}
                      to={`/cases/${caseId}/tasks/${action.workItemId}`}
                    >
                      과업 열기
                    </AppLink>
                  ) : (
                    <span className="action-not-created">과업 미생성</span>
                  )}
                </li>
              ))}
            </ol>
          </>
        )}
        <div className="workflow-next-actions">
          <AppLink
            className="workflow-action-link"
            currentPath={currentPath}
            runtime={runtime}
            to={`/cases/${caseId}/tasks`}
          >
            전체 수행과업
          </AppLink>
          <AppLink
            className="workflow-action-link"
            currentPath={currentPath}
            runtime={runtime}
            to={`/cases/${caseId}/close`}
          >
            상황 종료 검토
          </AppLink>
        </div>
      </section>
    </main>
  );
}

function WorkItemList({
  caseId,
  currentPath,
  runtime,
}: {
  caseId: string;
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const workItems = useQuery({
    queryKey: ["case-work-items", runtime.profile, caseId],
    queryFn: () =>
      apiRequest<WorkItemsData>(runtime, `/cases/${caseId}/work-items`).then(
        (result) => result.data,
      ),
    staleTime: 10_000,
  });
  if (workItems.isLoading) return <WorkflowState message="단계별 수행과업을 준비하고 있습니다." />;
  if (workItems.isError || !workItems.data) {
    return (
      <WorkflowState
        error
        message={queryMessage(workItems.error, "수행과업을 불러오지 못했습니다.")}
      />
    );
  }
  return (
    <main className="page workflow-page" id="main-content">
      <AppLink
        className="analysis-back"
        currentPath={currentPath}
        runtime={runtime}
        to={`/cases/${caseId}/evidence`}
      >
        ‹ 대응 절차로 돌아가기
      </AppLink>
      <div className="page-heading workflow-heading">
        <div>
          <p className="case-breadcrumb">재난 대응 / 단계별 수행과업</p>
          <h1>단계별 수행과업</h1>
          <p>체크리스트와 실제 수행 단위의 상태를 기록합니다.</p>
        </div>
        <span className="workflow-work-status running">
          진행 과업 {workItems.data.summary.open}건
        </span>
      </div>
      <section className="workflow-summary">
        <article>
          <span>전체</span>
          <strong>{workItems.data.summary.total}건</strong>
        </article>
        <article>
          <span>미완료</span>
          <strong>{workItems.data.summary.open}건</strong>
        </article>
        <article>
          <span>승인 대기</span>
          <strong>{workItems.data.summary.waitingApproval}건</strong>
        </article>
        <article>
          <span>완료</span>
          <strong>{workItems.data.summary.completed}건</strong>
        </article>
      </section>
      <section className="panel work-list-panel">
        <div className="workflow-section-heading">
          <div>
            <h2>Case 수행과업</h2>
            <p>우선순위와 생성 순서에 따라 표시합니다.</p>
          </div>
        </div>
        {!workItems.data.items.length ? (
          <div className="workflow-empty">
            생성된 수행과업이 없습니다. 대응 제안이 준비되면 행동별 과업을 연결합니다.
          </div>
        ) : (
          <ol className="work-item-list">
            {workItems.data.items.map((item) => (
              <li key={item.workItemId}>
                <span className={`work-priority ${item.priority.toLowerCase()}`}>
                  {priorityLabels[item.priority]}
                </span>
                <div>
                  <strong>{item.title}</strong>
                  <p>
                    {item.workType} · 체크리스트{" "}
                    {item.checklist.filter((entry) => entry.status === "DONE").length}/
                    {item.checklist.length} · 갱신 {formatKst(item.updatedAt)}
                  </p>
                  <div className="work-progress">
                    <span style={{ width: `${item.progress}%` }} />
                  </div>
                </div>
                <WorkPill status={item.status} />
                <AppLink
                  className="workflow-action-link"
                  currentPath={currentPath}
                  runtime={runtime}
                  to={`/cases/${caseId}/tasks/${item.workItemId}`}
                >
                  상세 열기
                </AppLink>
              </li>
            ))}
          </ol>
        )}
      </section>
      <div className="workflow-next-actions">
        <AppLink
          className="workflow-action-link"
          currentPath={currentPath}
          runtime={runtime}
          to={`/cases/${caseId}`}
        >
          통합 상황판
        </AppLink>
        <AppLink
          className="workflow-action-link"
          currentPath={currentPath}
          runtime={runtime}
          to={`/cases/${caseId}/close`}
        >
          상황 종료 검토
        </AppLink>
      </div>
    </main>
  );
}

function WorkItemDetail({
  caseId,
  currentPath,
  runtime,
  workItemId,
}: {
  caseId: string;
  currentPath: string;
  runtime: ProfileRuntime;
  workItemId: string;
}) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const detail = useQuery({
    queryKey: ["work-item", runtime.profile, workItemId],
    queryFn: () =>
      apiRequest<WorkItem>(runtime, `/work-items/${workItemId}`).then((result) => result.data),
    staleTime: 5_000,
  });
  const refresh = (item: WorkItem) => {
    queryClient.setQueryData(["work-item", runtime.profile, workItemId], item);
    void queryClient.invalidateQueries({
      queryKey: ["case-work-items", runtime.profile, caseId],
    });
    setReason("");
  };
  const transition = useMutation({
    mutationFn: ({ targetStatus }: { targetStatus: WorkStatus }) => {
      if (!detail.data) throw new Error("업무 상태가 준비되지 않았습니다.");
      return apiRequest<WorkItem>(runtime, `/work-items/${workItemId}/status`, {
        method: "PATCH",
        headers: { "Idempotency-Key": idempotencyKey("work-status") },
        body: JSON.stringify({
          expectedVersion: detail.data.version,
          targetStatus,
          reason,
        }),
      }).then((result) => result.data);
    },
    onSuccess: refresh,
  });
  const checklist = useMutation({
    mutationFn: ({
      checklistItemId,
      status,
    }: {
      checklistItemId: string;
      status: ChecklistItem["status"];
    }) => {
      if (!detail.data) throw new Error("업무 상태가 준비되지 않았습니다.");
      return apiRequest<WorkItem>(
        runtime,
        `/work-items/${workItemId}/checklist/${checklistItemId}`,
        {
          method: "PATCH",
          headers: { "Idempotency-Key": idempotencyKey("checklist") },
          body: JSON.stringify({
            expectedWorkVersion: detail.data.version,
            status,
            note: null,
          }),
        },
      ).then((result) => result.data);
    },
    onSuccess: refresh,
  });

  if (detail.isLoading) return <WorkflowState message="수행과업 상세를 준비하고 있습니다." />;
  if (detail.isError || !detail.data) {
    return (
      <WorkflowState
        error
        message={queryMessage(detail.error, "수행과업을 불러오지 못했습니다.")}
      />
    );
  }
  const item = detail.data;
  const allowed = transitions[item.status];
  const done = item.checklist.filter((entry) => entry.status === "DONE").length;
  const locked = item.status === "COMPLETED" || item.status === "DISCARDED";

  const requestTransition = (targetStatus: WorkStatus, destructive: boolean) => {
    if (!reason.trim()) return;
    if (destructive && !window.confirm("현재 내용과 이력은 보존됩니다. 이 상태로 기록할까요?")) {
      return;
    }
    transition.mutate({ targetStatus });
  };

  return (
    <main className="page workflow-page" id="main-content">
      <AppLink
        className="analysis-back"
        currentPath={currentPath}
        runtime={runtime}
        to={`/cases/${caseId}/tasks`}
      >
        ‹ 수행과업 목록으로 돌아가기
      </AppLink>
      <div className="page-heading workflow-heading">
        <div>
          <p className="case-breadcrumb">재난 대응 / 수행과업 상세</p>
          <h1>단계별 수행과업 상세</h1>
          <p>{item.title}</p>
        </div>
        <WorkPill status={item.status} />
      </div>
      <section className="workflow-summary">
        <article>
          <span>현재 과업</span>
          <strong>{item.title}</strong>
        </article>
        <article>
          <span>우선순위</span>
          <strong>{priorityLabels[item.priority]}</strong>
        </article>
        <article>
          <span>완료 기한</span>
          <strong>{item.dueAt ? formatKst(item.dueAt) : "미지정"}</strong>
        </article>
        <article>
          <span>체크 진행</span>
          <strong>
            {done}/{item.checklist.length}
          </strong>
        </article>
      </section>
      <div className="work-detail-grid">
        <section className="panel work-checklist-panel">
          <div className="workflow-section-heading">
            <div>
              <h2>수행 정보와 체크리스트</h2>
              <p>변경은 즉시 저장되며 감사 이력에 남습니다.</p>
            </div>
            <span>{item.progress}% 진행</span>
          </div>
          <div className="work-progress large">
            <span style={{ width: `${item.progress}%` }} />
          </div>
          {!item.checklist.length ? (
            <div className="workflow-empty">등록된 체크리스트가 없습니다.</div>
          ) : (
            <ol className="work-checklist">
              {item.checklist.map((entry) => (
                <li className={statusClass(entry.status)} key={entry.checklistItemId}>
                  <button
                    aria-label={`${entry.label} ${entry.status === "DONE" ? "미완료로 변경" : "완료로 변경"}`}
                    disabled={locked || checklist.isPending}
                    onClick={() =>
                      checklist.mutate({
                        checklistItemId: entry.checklistItemId,
                        status: entry.status === "DONE" ? "PENDING" : "DONE",
                      })
                    }
                    type="button"
                  >
                    {entry.status === "DONE" ? "✓" : entry.status === "SKIPPED" ? "−" : ""}
                  </button>
                  <div>
                    <strong>{entry.label}</strong>
                    <p>{entry.note ?? "별도 메모 없음"}</p>
                  </div>
                  <span>
                    {entry.status === "DONE"
                      ? "완료"
                      : entry.status === "SKIPPED"
                        ? "제외"
                        : "진행 필요"}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </section>
        <aside className="panel work-control-panel">
          <div className="workflow-section-heading">
            <div>
              <h2>수행 제어</h2>
              <p>실행 전 사유를 기록합니다.</p>
            </div>
          </div>
          <div className={`work-current-state ${statusClass(item.status)}`}>
            <span>현재 상태</span>
            <strong>{workStatusLabels[item.status]}</strong>
            <small>마지막 갱신 {formatKst(item.updatedAt)}</small>
          </div>
          {allowed.length ? (
            <>
              <label htmlFor="work-transition-reason">처리 사유</label>
              <textarea
                id="work-transition-reason"
                maxLength={1000}
                onChange={(event) => setReason(event.target.value)}
                placeholder="상태 변경 근거를 입력하세요."
                rows={4}
                value={reason}
              />
              <div className="work-transition-actions">
                {allowed.map((action) => (
                  <button
                    className={action.destructive ? "danger" : "primary"}
                    disabled={!reason.trim() || transition.isPending}
                    key={action.status}
                    onClick={() => requestTransition(action.status, Boolean(action.destructive))}
                    type="button"
                  >
                    {action.label}
                  </button>
                ))}
              </div>
            </>
          ) : (
            <div className="workflow-empty">이 과업은 잠겨 있으며 추가 상태 변경이 없습니다.</div>
          )}
          {transition.isError || checklist.isError ? (
            <div className="workflow-inline-error" role="alert">
              {queryMessage(
                transition.error ?? checklist.error,
                "변경을 저장하지 못했습니다. 최신 상태를 다시 확인해 주세요.",
              )}
            </div>
          ) : null}
          <AppLink
            className="workflow-secondary-link"
            currentPath={currentPath}
            runtime={runtime}
            to="/automation/runs"
          >
            감사·자동화 이력 확인
          </AppLink>
        </aside>
      </div>
    </main>
  );
}

function CaseClosure({
  caseId,
  currentPath,
  runtime,
}: {
  caseId: string;
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const review = useQuery({
    queryKey: ["case-closure-review", runtime.profile, caseId],
    queryFn: () =>
      apiRequest<ClosureReviewData>(runtime, `/cases/${caseId}/closure-review`).then(
        (result) => result.data,
      ),
    staleTime: 10_000,
  });
  const timeline = useQuery({
    queryKey: ["case-timeline", runtime.profile, caseId, "closure"],
    queryFn: () =>
      apiRequest<TimelineData>(runtime, `/cases/${caseId}/timeline?page=1&pageSize=20`).then(
        (result) => result.data,
      ),
    staleTime: 15_000,
  });
  if (review.isLoading) return <WorkflowState message="상황 종료 조건을 검토하고 있습니다." />;
  if (review.isError || !review.data) {
    return (
      <WorkflowState
        error
        message={queryMessage(review.error, "상황 종료 검토 정보를 불러오지 못했습니다.")}
      />
    );
  }
  const data = review.data;
  const isClosed = data.status === "CLOSED";
  const checks = [
    {
      label: "원천 종료·해제 확인",
      done: Boolean(data.sourceResolvedAt) || data.sourceStatus === "RESOLVED",
      detail: data.sourceResolvedAt
        ? `원천 종료 ${formatKst(data.sourceResolvedAt)}`
        : `현재 원천 상태 ${data.sourceStatus}`,
    },
    {
      label: "미완료 수행과업 확인",
      done: data.workSummary.incomplete === 0,
      detail: `미완료 ${data.workSummary.incomplete}건 · 완료 ${data.workSummary.completed}건 · 폐기 ${data.workSummary.discarded}건`,
    },
    {
      label: "대응 근거 상태 확인",
      done: data.evidenceStatus === "SUFFICIENT",
      detail: evidenceLabels[data.evidenceStatus],
    },
  ];
  const completedChecks = checks.filter((check) => check.done).length;

  return (
    <main className="page workflow-page" id="main-content">
      <AppLink
        className="analysis-back"
        currentPath={currentPath}
        runtime={runtime}
        to={`/cases/${caseId}`}
      >
        ‹ 통합 상황판으로 돌아가기
      </AppLink>
      <div className="page-heading workflow-heading">
        <div>
          <p className="case-breadcrumb">재난 대응 / 상황 종료 검토</p>
          <h1>상황 종료·결과 요약</h1>
          <p>
            {data.caseNumber} · {data.title}
          </p>
        </div>
        <span className={`workflow-work-status ${isClosed ? "completed" : "on-hold"}`}>
          {isClosed ? "종료 완료" : "종료 검토 중"}
        </span>
      </div>
      <section className="workflow-summary">
        <article>
          <span>대응 경과</span>
          <strong>{formatKst(data.openedAt)}</strong>
        </article>
        <article>
          <span>완료 과업</span>
          <strong>{data.workSummary.completed}건</strong>
        </article>
        <article>
          <span>미완료 과업</span>
          <strong>{data.workSummary.incomplete}건</strong>
        </article>
        <article>
          <span>근거 상태</span>
          <strong>{evidenceLabels[data.evidenceStatus]}</strong>
        </article>
        <article>
          <span>Case 상태</span>
          <strong>{data.status}</strong>
        </article>
      </section>
      <div className="closure-grid">
        <section className="panel closure-timeline-panel">
          <div className="workflow-section-heading">
            <div>
              <h2>사건 타임라인</h2>
              <p>원천 수신과 사람의 처리 이력을 시간순으로 확인합니다.</p>
            </div>
            <span>{timeline.data?.total ?? 0}건</span>
          </div>
          {timeline.isLoading ? (
            <div className="workflow-empty">타임라인을 불러오고 있습니다.</div>
          ) : timeline.isError || !timeline.data ? (
            <div className="workflow-inline-error">
              {queryMessage(timeline.error, "타임라인을 불러오지 못했습니다.")}
            </div>
          ) : timeline.data.items.length ? (
            <ol className="closure-timeline">
              {timeline.data.items.map((entry, index) => (
                <li key={`${entry.entryType}-${entry.entryId}`}>
                  <span>{index + 1}</span>
                  <time>{formatKst(entry.occurredAt)}</time>
                  <div>
                    <strong>{entry.title}</strong>
                    <p>
                      {entry.entryType} · {entry.category}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <div className="workflow-empty">기록된 타임라인이 없습니다.</div>
          )}
        </section>
        <aside className="panel closure-check-panel">
          <div className="workflow-section-heading">
            <div>
              <h2>종료 전 확인</h2>
              <p>
                필수 확인 {checks.length}개 중 {completedChecks}개가 충족됐습니다.
              </p>
            </div>
            <span>
              {completedChecks}/{checks.length}
            </span>
          </div>
          <ol className="closure-checks">
            {checks.map((check) => (
              <li className={check.done ? "done" : "required"} key={check.label}>
                <span>{check.done ? "✓" : "!"}</span>
                <div>
                  <strong>{check.label}</strong>
                  <p>{check.detail}</p>
                </div>
                <small>{check.done ? "확인" : "확인 필요"}</small>
              </li>
            ))}
          </ol>
          {data.evidenceWarning ? (
            <div className={`evidence-warning ${statusClass(data.evidenceStatus)}`}>
              <strong>{evidenceLabels[data.evidenceStatus]}</strong>
              <span>{data.evidenceWarning}</span>
            </div>
          ) : null}
          {data.incompleteWorkItems.length ? (
            <div className="closure-incomplete">
              <strong>미완료 과업</strong>
              {data.incompleteWorkItems.map((item) => (
                <AppLink
                  className="workflow-action-link"
                  currentPath={currentPath}
                  key={item.workItemId}
                  runtime={runtime}
                  to={`/cases/${caseId}/tasks/${item.workItemId}`}
                >
                  {item.title} · {workStatusLabels[item.status]}
                </AppLink>
              ))}
            </div>
          ) : null}
          {isClosed && data.completedClosure ? (
            <div className="closure-complete">
              <strong>종료 결과</strong>
              <span>{data.completedClosure.summary}</span>
              <small>{formatKst(data.completedClosure.createdAt)}</small>
            </div>
          ) : (
            <div className="closure-policy-note">
              <strong>종료 실행 기준 확정 대기</strong>
              <span>
                미완료 과업이 남은 경우의 허용 여부를 확정한 뒤 실제 종료 버튼을 연결합니다.
                조회·검토·미완료 과업 이동은 현재 사용할 수 있습니다.
              </span>
            </div>
          )}
        </aside>
      </div>
      <section className="panel closure-next-actions">
        <div>
          <strong>후속 작업</strong>
          <span>종료 전 필요한 작업을 처리하거나 현재 상황판으로 돌아갈 수 있습니다.</span>
        </div>
        <AppLink
          className="workflow-action-link"
          currentPath={currentPath}
          runtime={runtime}
          to={`/cases/${caseId}/tasks`}
        >
          미완료 과업 처리
        </AppLink>
        <AppLink
          className="workflow-action-link"
          currentPath={currentPath}
          runtime={runtime}
          to={`/cases/${caseId}`}
        >
          상황판 복귀
        </AppLink>
      </section>
    </main>
  );
}

export function CaseWorkflow({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const evidenceMatch = currentPath.match(/^\/cases\/([0-9a-f-]+)\/evidence$/i);
  if (evidenceMatch) {
    return <CaseEvidence caseId={evidenceMatch[1]} currentPath={currentPath} runtime={runtime} />;
  }
  const taskMatch = currentPath.match(/^\/cases\/([0-9a-f-]+)\/tasks(?:\/([0-9a-f-]+))?$/i);
  if (taskMatch) {
    return taskMatch[2] ? (
      <WorkItemDetail
        caseId={taskMatch[1]}
        currentPath={currentPath}
        runtime={runtime}
        workItemId={taskMatch[2]}
      />
    ) : (
      <WorkItemList caseId={taskMatch[1]} currentPath={currentPath} runtime={runtime} />
    );
  }
  const closureMatch = currentPath.match(/^\/cases\/([0-9a-f-]+)\/close$/i);
  if (closureMatch) {
    return <CaseClosure caseId={closureMatch[1]} currentPath={currentPath} runtime={runtime} />;
  }
  return <WorkflowState error message="지원하지 않는 Case 업무 화면입니다." />;
}
