import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, apiRequest } from "./api";
import { formatKst } from "./home";
import type { ProfileRuntime } from "./profile";
import { AppLink } from "./router";
import "./documents.css";

type EvidenceStatus = "SUFFICIENT" | "INSUFFICIENT" | "CONFLICT";
type ApprovalStatus = "APPROVAL_PENDING" | "APPROVED" | "ON_HOLD" | "DISCARDED" | "SUPERSEDED";
type Decision = "APPROVED" | "ON_HOLD" | "DISCARDED";

interface ApprovalListItem {
  approvalRequestId: string;
  caseId: string | null;
  caseNumber: string | null;
  caseTitle: string | null;
  targetType: string;
  targetVersion: number;
  title: string;
  status: ApprovalStatus;
  evidenceStatus: EvidenceStatus | null;
  warning: string | null;
  requestedAt: string;
  decidedAt: string | null;
  version: number;
}

interface ApprovalListData {
  items: ApprovalListItem[];
  page: number;
  pageSize: number;
  total: number;
}

interface ApprovalCitation {
  citationId: string;
  evidenceItemId: string;
  supportType: string;
  quote: string;
  locator: string;
  documentTitle: string;
  issuingAgency: string | null;
}

interface ApprovalAction {
  recommendationActionId: string;
  ordinal: number;
  title: string;
  description: string;
  dueGuidance: string | null;
  evidenceStatus: EvidenceStatus;
  warning: string | null;
  status: string;
  checklist: string[];
  citations: ApprovalCitation[];
  workItemId: string | null;
  workItemStatus: string | null;
}

interface ApprovalDocumentArtifact {
  documentArtifactId: string;
  format: "HWPX" | "PDF";
  stage: "REVIEW" | "FINAL";
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  attemptCount: number;
  fileName: string | null;
  mimeType: string | null;
  sizeBytes: number | null;
  sha256: string | null;
  errorCode: string | null;
  errorMessage: string | null;
}

interface ApprovalDocument {
  documentDraftId: string;
  documentVersionId: string;
  caseId: string | null;
  family: string;
  variant: string;
  title: string;
  draftStatus: string;
  currentVersion: number;
  draftLockVersion: number;
  version: number;
  versionStatus: string;
  payload: {
    document?: { title?: string; date?: string; number?: string };
    incident?: { occurredAt?: string; location?: string; summary?: string; detail?: string };
    analysis?: { result?: string };
    response?: { summary?: string; actions?: string[] };
  };
  evidenceStatus: EvidenceStatus;
  warning: string | null;
  contentSha256: string;
  approvedAt: string | null;
  artifacts: ApprovalDocumentArtifact[];
}
interface ApprovalInspection {
  inspectionSimulationId: string;
  inspectionScenarioId: string;
  scenarioType: "BALANCED" | "HIGH_RISK_FOCUSED" | "COVERAGE_EXPANDED";
  status: string;
  version: number;
  regionName: string | null;
  startDate: string;
  endDate: string;
  inclusiveDayCount: number;
  teamCount: number;
  dailyCapacityPerTeam: number;
  totalCapacity: number;
  candidateCount: number;
  selectedCount: number;
  excludedCount: number;
  candidateCoveragePercent: number;
  requiredDays: number;
  overCapacity: boolean;
  confirmable: boolean;
  referenceMonth: string;
  horizonDays: number;
  lineageVersion: string;
  algorithmVersion: string;
  explanation: { strategy: string; coverageFormula: string };
  teams: {
    teamNumber: number;
    targetCount: number;
    firstOrder: number;
    lastOrder: number;
  }[];
  sampleTargets: {
    buildingId: string;
    buildingLabel: string;
    selectionOrder: number;
    teamNumber: number;
    finalScore: number;
    regionName: string;
    facilityType: string;
  }[];
}

interface ApprovalDetailData {
  approvalRequestId: string;
  caseId: string | null;
  targetType: string;
  targetId: string;
  targetVersion: number;
  title: string;
  status: ApprovalStatus;
  contentSha256: string;
  contentMatches: boolean;
  evidenceStatus: EvidenceStatus | null;
  warning: string | null;
  requestedBy: string;
  requestedAt: string;
  decidedAt: string | null;
  version: number;
  case: {
    caseId: string;
    caseNumber: string;
    title: string;
    caseType: string;
    status: string;
    monitoringPriority: string;
    regionCode: string | null;
    regionName: string | null;
  } | null;
  recommendation: {
    recommendationId: string;
    version: number;
    status: string;
    situationSummary: string;
    requiredChecks: string[];
    uncertainties: string[];
    conflicts: string[];
    warning: string | null;
    evidenceStatus: EvidenceStatus;
    evidenceWarning: string | null;
    actions: ApprovalAction[];
  } | null;
  document: ApprovalDocument | null;
  inspection: ApprovalInspection | null;
  executionImpact: {
    workItemCount: number;
    externalEffect: boolean;
    summary: string;
  };
  decision: {
    approvalDecisionId: string;
    decision: Decision;
    decidedBy: string;
    reason: string;
    warningAcknowledged: boolean;
    contentSha256: string;
    decidedAt: string;
  } | null;
}

const approvalLabels: Record<ApprovalStatus, string> = {
  APPROVAL_PENDING: "승인 대기",
  APPROVED: "승인",
  ON_HOLD: "보류",
  DISCARDED: "폐기",
  SUPERSEDED: "이전 버전",
};

const decisionLabels: Record<Decision, string> = {
  APPROVED: "승인",
  ON_HOLD: "보류",
  DISCARDED: "폐기",
};

const evidenceLabels: Record<EvidenceStatus, string> = {
  SUFFICIENT: "근거 충분",
  INSUFFICIENT: "근거 부족",
  CONFLICT: "근거 충돌",
};

const documentFamilyLabels: Record<string, string> = {
  SITUATION_REPORT: "보고서",
  OFFICIAL_NOTICE: "공문",
  RESPONSE_PLAN: "계획서",
};

const documentVariantLabels: Record<string, string> = {
  INCIDENT_REPORT: "사고·상황 보고서",
  CRISIS_ASSESSMENT: "위기상황판단",
  BASIC_NOTICE: "한국전기안전공사 공문",
  BASIC_PLAN: "대응 계획서",
};

function statusClass(status: string): string {
  return status.toLowerCase().replaceAll("_", "-");
}

function idempotencyKey(scope: string): string {
  return `${scope}-${crypto.randomUUID()}`;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function ApprovalState({ error = false, message }: { error?: boolean; message: string }) {
  return (
    <main className="page" id="main-content">
      <div className={`auth-loading${error ? " approval-load-error" : ""}`} role="status">
        {message}
      </div>
    </main>
  );
}

function ApprovalQueue({ currentPath, runtime }: { currentPath: string; runtime: ProfileRuntime }) {
  const approvals = useQuery({
    queryKey: ["approvals", runtime.profile],
    queryFn: () =>
      apiRequest<ApprovalListData>(runtime, "/approvals?pageSize=50").then((result) => result.data),
    staleTime: 10_000,
  });
  if (approvals.isLoading) {
    return <ApprovalState message="검토·승인 대기열을 준비하고 있습니다." />;
  }
  if (approvals.isError || !approvals.data) {
    return (
      <ApprovalState
        error
        message={errorMessage(approvals.error, "검토·승인 대기열을 불러오지 못했습니다.")}
      />
    );
  }
  const pending = approvals.data.items.filter((item) => item.status === "APPROVAL_PENDING").length;
  const held = approvals.data.items.filter((item) => item.status === "ON_HOLD").length;
  return (
    <main className="page approval-page" id="main-content">
      <div className="page-heading approval-heading">
        <div>
          <p className="case-breadcrumb">Workflow / 검토·승인</p>
          <h1>검토·승인</h1>
          <p>자동화가 준비한 설명을 확인하고 승인·보류·폐기를 기록합니다.</p>
        </div>
        <span className="approval-count">{pending}건 승인 대기</span>
      </div>
      <section className="workflow-summary">
        <article>
          <span>전체 요청</span>
          <strong>{approvals.data.total}건</strong>
        </article>
        <article>
          <span>승인 대기</span>
          <strong>{pending}건</strong>
        </article>
        <article>
          <span>보류</span>
          <strong>{held}건</strong>
        </article>
      </section>
      <section className="panel approval-queue-panel">
        <div className="workflow-section-heading">
          <div>
            <h2>결정 대기열</h2>
            <p>최근 요청과 이미 결정된 이력을 함께 표시합니다.</p>
          </div>
        </div>
        {approvals.data.items.length ? (
          <ol className="approval-list">
            {approvals.data.items.map((item) => (
              <li key={item.approvalRequestId}>
                <div>
                  <span className={`approval-status ${statusClass(item.status)}`}>
                    {approvalLabels[item.status]}
                  </span>
                  {item.evidenceStatus ? (
                    <span className={`evidence-status ${statusClass(item.evidenceStatus)}`}>
                      {evidenceLabels[item.evidenceStatus]}
                    </span>
                  ) : null}
                </div>
                <div>
                  <strong>{item.title}</strong>
                  <p>
                    {item.caseNumber ?? "Case 없음"} · {item.caseTitle ?? "대상 설명 없음"}
                  </p>
                  <small>요청 {formatKst(item.requestedAt)}</small>
                </div>
                <AppLink
                  className="workflow-action-link"
                  currentPath={currentPath}
                  runtime={runtime}
                  to={`/approvals/${item.approvalRequestId}`}
                >
                  설명 확인
                </AppLink>
              </li>
            ))}
          </ol>
        ) : (
          <div className="workflow-empty">현재 검토할 승인 요청이 없습니다.</div>
        )}
      </section>
    </main>
  );
}

function ApprovalDetail({
  approvalId,
  currentPath,
  runtime,
}: {
  approvalId: string;
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [warningAcknowledged, setWarningAcknowledged] = useState(false);
  const [discardReason, setDiscardReason] = useState("");
  const [discardReasonDetail, setDiscardReasonDetail] = useState("");
  const approval = useQuery({
    queryKey: ["approval", runtime.profile, approvalId],
    queryFn: () =>
      apiRequest<ApprovalDetailData>(runtime, `/approvals/${approvalId}`).then(
        (result) => result.data,
      ),
    staleTime: 5_000,
  });
  const decide = useMutation({
    mutationFn: ({ decision, expectedVersion }: { decision: Decision; expectedVersion: number }) =>
      apiRequest<ApprovalDetailData>(runtime, `/approvals/${approvalId}/decision`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey(`approval-${decision}`) },
        body: JSON.stringify({
          expectedVersion,
          decision,
          reason,
          warningAcknowledged,
          discardReason: decision === "DISCARDED" ? discardReason : undefined,
          discardReasonDetail:
            decision === "DISCARDED" && discardReason === "OTHER" ? discardReasonDetail : undefined,
        }),
      }).then((result) => result.data),
    onSuccess: (result) => {
      queryClient.setQueryData(["approval", runtime.profile, approvalId], result);
      void queryClient.invalidateQueries({
        queryKey: ["approvals", runtime.profile],
      });
    },
  });
  if (approval.isLoading) {
    return <ApprovalState message="승인 전 설명과 영향 범위를 준비하고 있습니다." />;
  }
  if (approval.isError || !approval.data) {
    return (
      <ApprovalState
        error
        message={errorMessage(approval.error, "승인 요청을 불러오지 못했습니다.")}
      />
    );
  }
  const data = approval.data;
  const warningRequired =
    data.evidenceStatus === "INSUFFICIENT" || data.evidenceStatus === "CONFLICT";
  const isDocument = data.targetType === "DOCUMENT_DRAFT" && data.document !== null;
  const isInspection = data.targetType === "INSPECTION_SCENARIO" && data.inspection !== null;
  const canDecide =
    data.status === "APPROVAL_PENDING" && data.contentMatches && reason.trim().length > 0;
  const canDiscard =
    canDecide &&
    (!isDocument ||
      (discardReason.length > 0 &&
        (discardReason !== "OTHER" || discardReasonDetail.trim().length > 0)));
  const submit = (decision: Decision) => {
    const discardMessage = isDocument
      ? "이 문서 버전을 폐기하시겠습니까?"
      : isInspection
        ? "이 점검계획을 폐기하시겠습니까?"
        : "이 대응안 버전을 폐기하시겠습니까?";
    if (decision === "DISCARDED" && !window.confirm(discardMessage)) {
      return;
    }
    decide.mutate({ decision, expectedVersion: data.version });
  };
  return (
    <main className="page approval-page" id="main-content">
      <AppLink
        className="analysis-back"
        currentPath={currentPath}
        runtime={runtime}
        to="/approvals"
      >
        ‹ 검토·승인 대기열로 돌아가기
      </AppLink>
      <div className="page-heading approval-heading">
        <div>
          <p className="case-breadcrumb">공통 / 설명·승인 / COM-02</p>
          <h1>승인 전 설명 확인</h1>
          <p>
            {isDocument
              ? "문서 버전·근거·산출물과 승인 후 실행 범위를 확인합니다."
              : isInspection
                ? "점검 대상·처리용량·익명 점검반 배분과 승인 후 내부 과업을 확인합니다."
                : "제안의 근거·영향·실행 범위를 확인한 뒤 사용자가 결정합니다."}
          </p>
        </div>
        <span className={`approval-status ${statusClass(data.status)}`}>
          {approvalLabels[data.status]}
        </span>
      </div>
      <div className="approval-layout">
        <div className="approval-explanation">
          <section className="panel approval-section">
            <h2>
              {isDocument
                ? "1. Case·문서 사실"
                : isInspection
                  ? "1. 점검계획 사실"
                  : "1. 감지 사실"}
            </h2>
            <strong>{data.case?.title ?? data.document?.title ?? data.title}</strong>
            <dl className="approval-facts">
              <div>
                <dt>Case</dt>
                <dd>{data.case?.caseNumber ?? "연결 Case 없음"}</dd>
              </div>
              <div>
                <dt>지역</dt>
                <dd>{data.inspection?.regionName ?? data.case?.regionName ?? "광주·전남 전체"}</dd>
              </div>
              <div>
                <dt>{isInspection ? "점검 기간" : "관제 우선상태"}</dt>
                <dd>
                  {isInspection
                    ? `${data.inspection?.startDate} ~ ${data.inspection?.endDate}`
                    : (data.case?.monitoringPriority ?? "해당 없음")}
                </dd>
              </div>
              <div>
                <dt>요청 시각</dt>
                <dd>{formatKst(data.requestedAt)}</dd>
              </div>
            </dl>
          </section>
          <section className="panel approval-section">
            <h2>2. 근거 데이터·규칙</h2>
            <div className="approval-evidence-heading">
              <span
                className={`evidence-status ${statusClass(isInspection ? "SUFFICIENT" : (data.evidenceStatus ?? "INSUFFICIENT"))}`}
              >
                {isInspection
                  ? "규칙·스냅샷 고정"
                  : data.evidenceStatus
                    ? evidenceLabels[data.evidenceStatus]
                    : "근거 상태 없음"}
              </span>
              <small>내용 해시 {data.contentSha256.slice(0, 12)}…</small>
            </div>
            <p>
              {isInspection
                ? `${data.inspection?.lineageVersion} 위험도와 ${data.inspection?.algorithmVersion} 결정 규칙으로 계산한 순서입니다. 발생확률이 아닙니다.`
                : (data.recommendation?.situationSummary ??
                  "현재 문서 버전의 내용, 근거 상태와 생성 산출물을 검토합니다.")}
            </p>
            {(data.warning ?? data.recommendation?.warning ?? data.document?.warning) ? (
              <div className="evidence-warning insufficient" role="status">
                <strong>확인 필요</strong>
                <span>
                  {data.warning ?? data.recommendation?.warning ?? data.document?.warning}
                </span>
              </div>
            ) : null}
            {!data.contentMatches ? (
              <div className="workflow-inline-error" role="alert">
                요청 당시 내용과 현재 내용이 다릅니다. 이 버전은 결정할 수 없습니다.
              </div>
            ) : null}
            {data.recommendation?.requiredChecks.length ? (
              <ul className="approval-checks">
                {data.recommendation.requiredChecks.map((check) => (
                  <li key={check}>{check}</li>
                ))}
              </ul>
            ) : null}
          </section>
          <section className="panel approval-section">
            <h2>
              {isDocument
                ? "3. 승인 대상 문서"
                : isInspection
                  ? "3. 확정할 점검대상·점검반"
                  : "3. 시스템이 준비한 작업"}
            </h2>
            {data.inspection ? (
              <div className="approval-inspection-review">
                <dl className="approval-facts">
                  <div>
                    <dt>실행안</dt>
                    <dd>
                      {data.inspection.scenarioType === "BALANCED"
                        ? "균형형"
                        : data.inspection.scenarioType === "HIGH_RISK_FOCUSED"
                          ? "고위험 집중형"
                          : "커버리지 확대형"}
                    </dd>
                  </div>
                  <div>
                    <dt>점검 대상</dt>
                    <dd>{data.inspection.selectedCount.toLocaleString()}개소</dd>
                  </div>
                  <div>
                    <dt>처리용량</dt>
                    <dd>{data.inspection.totalCapacity.toLocaleString()}개소</dd>
                  </div>
                  <div>
                    <dt>후보 충족률</dt>
                    <dd>{data.inspection.candidateCoveragePercent.toFixed(1)}%</dd>
                  </div>
                  <div>
                    <dt>기준 위험도</dt>
                    <dd>
                      {data.inspection.referenceMonth.slice(0, 7)} · {data.inspection.horizonDays}일
                    </dd>
                  </div>
                  <div>
                    <dt>계산 버전</dt>
                    <dd>{data.inspection.algorithmVersion}</dd>
                  </div>
                </dl>
                <p>{data.inspection.explanation.strategy}</p>
                <div className="approval-inspection-teams">
                  {data.inspection.teams.map((team) => (
                    <div key={team.teamNumber}>
                      <strong>점검반 {team.teamNumber}</strong>
                      <span>
                        {team.targetCount.toLocaleString()}개소 · 순번 {team.firstOrder}~
                        {team.lastOrder}
                      </span>
                    </div>
                  ))}
                </div>
                <ol className="approval-inspection-sample">
                  {data.inspection.sampleTargets.slice(0, 5).map((target) => (
                    <li key={target.buildingId}>
                      <span>{target.selectionOrder}</span>
                      <div>
                        <strong>{target.buildingLabel}</strong>
                        <small>
                          {target.regionName} · {target.facilityType} · 상대점수{" "}
                          {target.finalScore.toFixed(6)}
                        </small>
                      </div>
                    </li>
                  ))}
                </ol>
                <AppLink
                  className="workflow-action-link"
                  currentPath={currentPath}
                  runtime={runtime}
                  to={`/inspections/simulations/${data.inspection.inspectionSimulationId}/targets`}
                >
                  전체 점검대상 다시 확인
                </AppLink>
              </div>
            ) : data.recommendation ? (
              <ol className="approval-actions">
                {data.recommendation.actions.map((action) => (
                  <li key={action.recommendationActionId}>
                    <span>{action.ordinal}</span>
                    <div>
                      <strong>{action.title}</strong>
                      <p>{action.description}</p>
                      <ul>
                        {action.checklist.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                      <div className="approval-citations">
                        {action.citations.map((citation) => (
                          <details key={citation.citationId}>
                            <summary>
                              {citation.supportType === "DIRECT" ? "직접" : "참고"} ·{" "}
                              {citation.documentTitle} · {citation.locator}
                            </summary>
                            <blockquote>{citation.quote}</blockquote>
                          </details>
                        ))}
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            ) : data.document ? (
              <div className="approval-document-review">
                <dl className="approval-facts">
                  <div>
                    <dt>문서 계열</dt>
                    <dd>{documentFamilyLabels[data.document.family] ?? data.document.family}</dd>
                  </div>
                  <div>
                    <dt>문서 형식</dt>
                    <dd>{documentVariantLabels[data.document.variant] ?? data.document.variant}</dd>
                  </div>
                  <div>
                    <dt>고정 버전</dt>
                    <dd>v{data.document.version}</dd>
                  </div>
                  <div>
                    <dt>검토 산출물</dt>
                    <dd>
                      {
                        data.document.artifacts.filter((artifact) => artifact.stage === "REVIEW")
                          .length
                      }
                      건
                    </dd>
                  </div>
                </dl>
                <div className="approval-document-payload">
                  <div>
                    <strong>문서 제목</strong>
                    <span>{data.document.payload.document?.title ?? data.document.title}</span>
                  </div>
                  <div>
                    <strong>발생·기준시각</strong>
                    <span>{data.document.payload.incident?.occurredAt || "미입력"}</span>
                  </div>
                  <div>
                    <strong>위치</strong>
                    <span>{data.document.payload.incident?.location || "미입력"}</span>
                  </div>
                  <div>
                    <strong>상황 요약</strong>
                    <span>{data.document.payload.incident?.summary || "미입력"}</span>
                  </div>
                  <div>
                    <strong>분석 결과</strong>
                    <span>{data.document.payload.analysis?.result || "미입력"}</span>
                  </div>
                  <div>
                    <strong>대응 내용</strong>
                    <span>
                      {data.document.payload.response?.actions?.join(", ") ||
                        data.document.payload.response?.summary ||
                        "미입력"}
                    </span>
                  </div>
                </div>
                <div className="approval-document-files">
                  {data.document.artifacts
                    .filter((artifact) => artifact.stage === "REVIEW")
                    .map((artifact) => (
                      <a
                        href={`${runtime.apiBase}/document-artifacts/${artifact.documentArtifactId}/download`}
                        key={artifact.documentArtifactId}
                      >
                        {artifact.format} 검토본 · {artifact.status}
                      </a>
                    ))}
                </div>
              </div>
            ) : null}
            <strong className="approval-boundary">
              {isDocument
                ? "승인 전에는 최종본을 생성하지 않으며 외부 전송은 승인 후에도 자동 실행하지 않습니다."
                : isInspection
                  ? "승인 전에는 내부 점검과업을 만들지 않으며 승인 후에도 담당자 지정·외부 요청은 자동 실행하지 않습니다."
                  : "준비 단계이며 승인 전에는 과업·외부 연락·발송·상태 변경을 실행하지 않습니다."}
            </strong>
          </section>
          <section className="panel approval-section">
            <h2>5. 결정 이력</h2>
            <p>
              {formatKst(data.requestedAt)} · {data.requestedBy} · 승인 요청
            </p>
            {data.decision ? (
              <p>
                {formatKst(data.decision.decidedAt)} · {data.decision.decidedBy} ·{" "}
                {decisionLabels[data.decision.decision]} · {data.decision.reason}
              </p>
            ) : (
              <p>현재 승인 대기 · 결정 기록 없음</p>
            )}
            <AppLink
              className="workflow-action-link"
              currentPath={currentPath}
              runtime={runtime}
              to="/automation/runs"
            >
              자동화 기록 열기
            </AppLink>
          </section>
        </div>
        <aside className="approval-decision-column">
          <section className="panel approval-impact">
            <h2>4. 승인 시 실행·영향</h2>
            <p>
              {isDocument
                ? "FINAL HWPX·PDF 2건 생성 시작"
                : isInspection
                  ? `익명 점검반 내부 수행과업 ${data.executionImpact.workItemCount}건 생성`
                  : `내부 수행과업 ${data.executionImpact.workItemCount}건 생성`}
            </p>
            <p>외부 영향: 없음 · 외부 연락·문서 발송 자동 실행 안 함</p>
            <p>{data.executionImpact.summary}</p>
            <strong>APPROVAL BOUNDARY · 이 화면에서만 최종 결정</strong>
          </section>
          <section className="panel approval-decision-panel">
            <h2>사용자 결정</h2>
            {data.status === "APPROVAL_PENDING" ? (
              <>
                <p>결정 사유를 기록하고 근거 상태와 영향 범위를 확인하세요.</p>
                {warningRequired ? (
                  <label className="approval-acknowledgement">
                    <input
                      checked={warningAcknowledged}
                      onChange={(event) => setWarningAcknowledged(event.target.checked)}
                      type="checkbox"
                    />
                    근거 부족·충돌 경고와 실행 범위를 확인했습니다.
                  </label>
                ) : null}
                <label htmlFor="approval-reason">결정 사유</label>
                <textarea
                  id="approval-reason"
                  maxLength={1000}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="결정 사유 입력 (필수)"
                  rows={5}
                  value={reason}
                />
                {isDocument ? (
                  <>
                    <label htmlFor="document-discard-reason">문서 폐기 사유</label>
                    <select
                      id="document-discard-reason"
                      onChange={(event) => {
                        setDiscardReason(event.target.value);
                        if (event.target.value !== "OTHER") {
                          setDiscardReasonDetail("");
                        }
                      }}
                      value={discardReason}
                    >
                      <option value="">폐기할 때 선택</option>
                      <option value="FALSE_ALARM">오경보</option>
                      <option value="DUPLICATE">중복 문서</option>
                      <option value="NO_ACTION_REQUIRED">조치 불필요</option>
                      <option value="EVIDENCE_INAPPROPRIATE">근거 부적절</option>
                      <option value="OTHER">기타</option>
                    </select>
                    {discardReason === "OTHER" ? (
                      <textarea
                        aria-label="기타 폐기 사유"
                        maxLength={500}
                        onChange={(event) => setDiscardReasonDetail(event.target.value)}
                        placeholder="기타 폐기 사유를 입력하세요."
                        rows={3}
                        value={discardReasonDetail}
                      />
                    ) : null}
                  </>
                ) : null}
                {decide.isError ? (
                  <div className="workflow-inline-error" role="alert">
                    {errorMessage(decide.error, "결정을 저장하지 못했습니다.")}
                  </div>
                ) : null}
                <div className="approval-buttons">
                  <button
                    disabled={!canDecide || decide.isPending}
                    onClick={() => submit("ON_HOLD")}
                    type="button"
                  >
                    보류
                  </button>
                  <button
                    className="discard"
                    disabled={!canDiscard || decide.isPending}
                    onClick={() => submit("DISCARDED")}
                    type="button"
                  >
                    폐기
                  </button>
                  <button
                    className="approve"
                    disabled={
                      !canDecide || decide.isPending || (warningRequired && !warningAcknowledged)
                    }
                    onClick={() => submit("APPROVED")}
                    type="button"
                  >
                    {isDocument ? "승인하고 최종본 생성" : "승인하고 과업 생성"}
                  </button>
                </div>
              </>
            ) : (
              <div className={`approval-result ${statusClass(data.status)}`}>
                <strong>{approvalLabels[data.status]} 결정 완료</strong>
                <span>{data.decision?.reason ?? "결정 사유가 기록되었습니다."}</span>
                {data.status === "APPROVED" && isDocument ? (
                  <AppLink
                    className="workflow-action-link"
                    currentPath={currentPath}
                    runtime={runtime}
                    to={`/documents/${data.targetId}/result`}
                  >
                    최종 문서·전달 기록 열기
                  </AppLink>
                ) : data.status === "APPROVED" && data.caseId ? (
                  <AppLink
                    className="workflow-action-link"
                    currentPath={currentPath}
                    runtime={runtime}
                    to={`/cases/${data.caseId}/tasks`}
                  >
                    생성된 수행과업 열기
                  </AppLink>
                ) : null}
              </div>
            )}
          </section>
        </aside>
      </div>
    </main>
  );
}

export function ApprovalManagement({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const match = /^\/approvals\/([0-9a-f-]+)$/i.exec(currentPath);
  if (match) {
    return <ApprovalDetail approvalId={match[1]} currentPath={currentPath} runtime={runtime} />;
  }
  return <ApprovalQueue currentPath={currentPath} runtime={runtime} />;
}

export default ApprovalManagement;
