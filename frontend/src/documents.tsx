import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, apiRequest } from "./api";
import { formatKst } from "./home";
import type { ProfileRuntime } from "./profile";
import { AppLink, navigateInternal } from "./router";
import "./documents.css";

type DocumentVariant =
  | "INCIDENT_REPORT"
  | "CRISIS_ASSESSMENT"
  | "BASIC_NOTICE"
  | "BASIC_PLAN"
  | "REGION_ANALYSIS"
  | "BUILDING_ANALYSIS"
  | "INSPECTION_REQUEST";
type DocumentFamily = "SITUATION_REPORT" | "OFFICIAL_NOTICE" | "RESPONSE_PLAN";
type DocumentStatus = "DRAFT" | "APPROVAL_PENDING" | "APPROVED" | "ON_HOLD" | "DISCARDED";
type EvidenceStatus = "SUFFICIENT" | "INSUFFICIENT" | "CONFLICT";
type ArtifactStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
type ArtifactFormat = "HWPX" | "PDF";
type ArtifactStage = "REVIEW" | "FINAL";

interface DocumentPayload {
  schemaVersion: 1;
  caseId: string | null;
  caseNumber: string;
  variant: DocumentVariant;
  document: { title: string; date: string; year: string; number: string };
  author: { name: string; department: string; approver: string };
  contact: { phone: string; email: string; block: string };
  incident: {
    type: string;
    occurredAt: string;
    location: string;
    cause: string;
    summary: string;
    detail: string;
    damage: string;
    agencies: string;
  };
  facility: {
    name: string;
    address: string;
    use: string;
    risk: string;
    region: string;
    detail: string;
  };
  analysis: { result: string; uncertainties: string[]; conflicts: string[] };
  monitoring: { summary: string; signals: string[] };
  response: {
    summary: string;
    priority: string;
    actions: string[];
    evidence: string[];
    plan: string[];
    recipients: string[];
    coordination: string;
    approvalProcedure: string;
    reportingProcedure: string;
    reportingTiming: string;
    emergencyPlan: string;
  };
  evidence: { status: EvidenceStatus; references: string[] };
  notice: {
    recipient: string;
    deliveryRoute: string;
    opening: string;
    grounds: string[];
    request: string[];
    deadline: string;
  };
  attachments: { items: string[] };
  review: { warning: string };
}

interface DocumentArtifact {
  documentArtifactId: string;
  format: ArtifactFormat;
  stage: ArtifactStage;
  status: ArtifactStatus;
  attemptCount: number;
  fileName: string | null;
  mimeType: string | null;
  sizeBytes: number | null;
  sha256: string | null;
  errorCode: string | null;
  errorMessage: string | null;
  queuedAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  downloadUrl: string | null;
}

interface ManualDelivery {
  documentManualDeliveryId: string;
  recipient: string;
  deliveredAt: string;
  method: string;
  memo: string | null;
  recordedBy: string;
  recordedAt: string;
  externalDeliveryVerified: false;
}

interface DocumentVersionSummary {
  version: number;
  status: string;
  evidenceStatus: EvidenceStatus;
  warning: string | null;
  contentSha256: string;
  succeededArtifactCount: number;
  createdAt: string;
  approvedAt: string | null;
}

interface DocumentDetailData {
  documentDraftId: string;
  documentVersionId: string;
  caseId: string | null;
  caseNumber: string | null;
  family: DocumentFamily;
  variant: DocumentVariant;
  title: string;
  status: DocumentStatus;
  versionStatus: string;
  currentVersion: number;
  lockVersion: number;
  payload: DocumentPayload;
  evidenceStatus: EvidenceStatus;
  warning: string | null;
  missingAdministrativeFields: string[];
  contentSha256: string;
  template: { key: string; version: string; sha256: string };
  warningAcknowledged: boolean;
  approvalReason: string | null;
  createdAt: string;
  updatedAt: string;
  versionCreatedAt: string;
  approvedAt: string | null;
  artifacts: DocumentArtifact[];
  manualDeliveries: ManualDelivery[];
  versions: DocumentVersionSummary[];
  reused?: boolean;
}

interface DocumentListItem {
  documentDraftId: string;
  caseId: string | null;
  caseNumber: string | null;
  family: DocumentFamily;
  variant: DocumentVariant;
  title: string;
  status: DocumentStatus;
  currentVersion: number;
  evidenceStatus: EvidenceStatus;
  warning: string | null;
  succeededArtifactCount: number;
  createdAt: string;
  updatedAt: string;
}

interface DocumentLibraryData {
  items: DocumentListItem[];
  pagination: {
    page: number;
    pageSize: number;
    total: number;
    totalPages: number;
  };
}

interface CaseSummary {
  caseId: string;
  caseNumber: string;
  title: string;
  primaryRegion: { fullName: string } | null;
}

interface ApprovalRequestData {
  approvalRequestId: string;
  status: string;
  reused: boolean;
}

const variantLabels: Record<DocumentVariant, string> = {
  INCIDENT_REPORT: "사고·상황 보고서",
  CRISIS_ASSESSMENT: "위기상황판단",
  BASIC_NOTICE: "한국전기안전공사 공문",
  BASIC_PLAN: "대응 계획서",
  REGION_ANALYSIS: "지역 위험 분석 보고서",
  BUILDING_ANALYSIS: "건물 위험 분석 보고서",
  INSPECTION_REQUEST: "현장점검 요청 공문",
};

const familyLabels: Record<DocumentFamily, string> = {
  SITUATION_REPORT: "보고서",
  OFFICIAL_NOTICE: "공문",
  RESPONSE_PLAN: "계획서",
};

const statusLabels: Record<DocumentStatus, string> = {
  DRAFT: "작성 중",
  APPROVAL_PENDING: "승인 대기",
  APPROVED: "승인",
  ON_HOLD: "보류",
  DISCARDED: "폐기",
};

const evidenceLabels: Record<EvidenceStatus, string> = {
  SUFFICIENT: "근거 충분",
  INSUFFICIENT: "근거 부족",
  CONFLICT: "근거 충돌",
};

const artifactStatusLabels: Record<ArtifactStatus, string> = {
  QUEUED: "생성 대기",
  RUNNING: "생성 중",
  SUCCEEDED: "생성 완료",
  FAILED: "생성 실패",
};

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function idempotencyKey(scope: string): string {
  return `${scope}-${crypto.randomUUID()}`;
}

function statusClass(status: string): string {
  return status.toLowerCase().replaceAll("_", "-");
}

function formatBytes(value: number | null): string {
  if (value === null) return "크기 확인 전";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function lines(value: string): string[] {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function localDateTimeValue(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function artifactHref(runtime: ProfileRuntime, artifact: DocumentArtifact): string {
  return `${runtime.apiBase}/document-artifacts/${artifact.documentArtifactId}/download`;
}

function pollDocument(data: DocumentDetailData | undefined): number | false {
  return data?.artifacts.some((item) => item.status === "QUEUED" || item.status === "RUNNING")
    ? 2_000
    : false;
}

function DocumentState({ error = false, message }: { error?: boolean; message: string }) {
  return (
    <main className="page" id="main-content">
      <div className={`auth-loading${error ? " document-state-error" : ""}`} role="status">
        {message}
      </div>
    </main>
  );
}

function ArtifactBadge({ artifact }: { artifact: DocumentArtifact }) {
  return (
    <span className={`document-artifact-status ${statusClass(artifact.status)}`}>
      {artifactStatusLabels[artifact.status]}
    </span>
  );
}

function NewDocument({
  caseId,
  currentPath,
  runtime,
}: {
  caseId: string;
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const [variant, setVariant] = useState<DocumentVariant>("INCIDENT_REPORT");
  const caseQuery = useQuery({
    queryKey: ["case-detail", runtime.profile, caseId],
    queryFn: () =>
      apiRequest<CaseSummary>(runtime, `/cases/${caseId}`).then((result) => result.data),
    staleTime: 15_000,
  });
  const create = useMutation({
    mutationFn: () =>
      apiRequest<DocumentDetailData>(runtime, `/cases/${caseId}/documents`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey("document-create") },
        body: JSON.stringify({ variant }),
      }).then((result) => result.data),
    onSuccess: (document) => {
      navigateInternal(runtime, `/documents/${document.documentDraftId}/edit`);
    },
  });
  return (
    <main className="page document-page" id="main-content">
      <AppLink
        className="analysis-back"
        currentPath={currentPath}
        runtime={runtime}
        to={`/cases/${caseId}`}
      >
        ‹ Case 통합 상황판으로 돌아가기
      </AppLink>
      <div className="page-heading document-heading">
        <div>
          <p className="case-breadcrumb">산출물 / 새 문서</p>
          <h1>문서 초안 만들기</h1>
          <p>Case 사실과 현재 근거를 구조화 초안으로 가져옵니다.</p>
        </div>
        <span className="document-count">4개 문서 계열</span>
      </div>
      <section className="panel document-case-summary">
        <span>연결 Case</span>
        <strong>{caseQuery.data?.caseNumber ?? caseId}</strong>
        <p>{caseQuery.data?.title ?? "Case 정보를 확인하고 있습니다."}</p>
        <small>{caseQuery.data?.primaryRegion?.fullName ?? "지역 확인 필요"}</small>
      </section>
      <section className="document-variant-grid" aria-label="문서 종류 선택">
        {(Object.keys(variantLabels) as DocumentVariant[]).map((item) => (
          <button
            aria-pressed={variant === item}
            className={variant === item ? "selected" : ""}
            key={item}
            onClick={() => setVariant(item)}
            type="button"
          >
            <span>
              {
                familyLabels[
                  item === "BASIC_NOTICE"
                    ? "OFFICIAL_NOTICE"
                    : item === "BASIC_PLAN"
                      ? "RESPONSE_PLAN"
                      : "SITUATION_REPORT"
                ]
              }
            </span>
            <strong>{variantLabels[item]}</strong>
            <small>
              {item === "BASIC_NOTICE"
                ? "한국전기안전공사 발신 협조 요청"
                : item === "BASIC_PLAN"
                  ? "대응 단계와 보고 절차 정리"
                  : "사건 사실·분석·근거·대응 기록"}
            </small>
          </button>
        ))}
      </section>
      <section className="panel document-create-boundary">
        <div>
          <strong>초안 생성 경계</strong>
          <p>
            근거가 부족해도 경고가 있는 초안을 만듭니다. 작성자·승인자·문서번호·개인 연락처는 비워
            두며 사용자가 직접 입력합니다.
          </p>
        </div>
        <button
          className="document-primary-button"
          disabled={create.isPending}
          onClick={() => create.mutate()}
          type="button"
        >
          {create.isPending ? "초안 준비 중…" : `${variantLabels[variant]} 시작`}
        </button>
      </section>
      {create.isError ? (
        <div className="workflow-inline-error" role="alert">
          {errorMessage(create.error, "문서 초안을 만들지 못했습니다.")}
        </div>
      ) : null}
    </main>
  );
}

function DocumentEditor({ documentId, runtime }: { documentId: string; runtime: ProfileRuntime }) {
  const queryClient = useQueryClient();
  const [payload, setPayload] = useState<DocumentPayload | null>(null);
  const loadedContentHash = useRef<string | null>(null);
  const saveKey = useRef<string | null>(null);
  const approvalKey = useRef<string | null>(null);
  const document = useQuery({
    queryKey: ["document", runtime.profile, documentId],
    queryFn: () =>
      apiRequest<DocumentDetailData>(runtime, `/documents/${documentId}`).then(
        (result) => result.data,
      ),
    staleTime: 3_000,
    refetchInterval: (query) => pollDocument(query.state.data),
  });
  useEffect(() => {
    if (document.data && loadedContentHash.current !== document.data.contentSha256) {
      loadedContentHash.current = document.data.contentSha256;
      setPayload(document.data.payload);
    }
  }, [document.data]);

  const save = useMutation({
    mutationFn: (nextPayload: DocumentPayload) => {
      saveKey.current ??= idempotencyKey("document-save");
      return apiRequest<DocumentDetailData>(runtime, `/documents/${documentId}`, {
        method: "PUT",
        headers: { "Idempotency-Key": saveKey.current },
        body: JSON.stringify({
          expectedVersion: document.data?.currentVersion,
          payload: nextPayload,
        }),
      }).then((result) => result.data);
    },
    onSuccess: (result) => {
      saveKey.current = null;
      queryClient.setQueryData(["document", runtime.profile, documentId], result);
      setPayload(result.payload);
      void queryClient.invalidateQueries({ queryKey: ["documents", runtime.profile] });
    },
  });
  const requestApproval = useMutation({
    mutationFn: () => {
      approvalKey.current ??= idempotencyKey("document-approval-request");
      return apiRequest<ApprovalRequestData>(
        runtime,
        `/documents/${documentId}/approval-requests`,
        {
          method: "POST",
          headers: { "Idempotency-Key": approvalKey.current },
        },
      ).then((result) => result.data);
    },
    onSuccess: (result) => {
      approvalKey.current = null;
      navigateInternal(runtime, `/approvals/${result.approvalRequestId}`);
    },
  });

  if (document.isLoading || payload === null) {
    return <DocumentState message="문서 구조와 검토용 파일을 준비하고 있습니다." />;
  }
  if (document.isError || !document.data) {
    return (
      <DocumentState
        error
        message={errorMessage(document.error, "문서 초안을 불러오지 못했습니다.")}
      />
    );
  }
  const data = document.data;
  const editable = data.status === "DRAFT" || data.status === "ON_HOLD";
  const dirty = JSON.stringify(payload) !== JSON.stringify(data.payload);
  const reviewArtifacts = data.artifacts.filter((item) => item.stage === "REVIEW");
  const reviewReady =
    reviewArtifacts.length === 2 && reviewArtifacts.every((item) => item.status === "SUCCEEDED");
  const update = (next: DocumentPayload) => setPayload(next);
  const savePayload = () => {
    if (editable && dirty && !save.isPending) save.mutate(payload);
  };
  return (
    <main className="page document-page document-editor-page" id="main-content">
      <div className="page-heading document-heading">
        <div>
          <p className="case-breadcrumb">산출물 / 대외 문서 초안 / OUT-01B</p>
          <h1>{variantLabels[data.variant]}</h1>
          <p>구조화 항목을 편집하면 같은 입력으로 검토 HWPX와 PDF를 생성합니다.</p>
        </div>
        <div className="document-heading-status">
          <span className={`document-status ${statusClass(data.status)}`}>
            {statusLabels[data.status]}
          </span>
          <span className={dirty ? "document-unsaved" : "document-saved"}>
            {dirty ? "저장하지 않은 변경" : `v${data.currentVersion} 저장됨`}
          </span>
        </div>
      </div>
      <section className="panel document-context-strip">
        <div>
          <span>Case</span>
          <strong>{data.caseNumber ?? data.caseId ?? "연결 없음"}</strong>
        </div>
        <div>
          <span>문서 계열</span>
          <strong>{familyLabels[data.family]}</strong>
        </div>
        <div>
          <span>근거 상태</span>
          <strong className={statusClass(data.evidenceStatus)}>
            {evidenceLabels[data.evidenceStatus]}
          </strong>
        </div>
        <div>
          <span>템플릿</span>
          <strong>{data.template.version}</strong>
        </div>
      </section>
      {data.warning ? (
        <div
          className={`document-evidence-warning ${statusClass(data.evidenceStatus)}`}
          role="status"
        >
          <strong>{evidenceLabels[data.evidenceStatus]}</strong>
          <span>{data.warning} · 검토본에는 경고가 표시되며 승인 시 명시적 확인이 필요합니다.</span>
        </div>
      ) : null}
      <div className="document-editor-layout">
        <section className="panel document-form-panel">
          <div className="document-form-heading">
            <div>
              <h2>문서 작성</h2>
              <p>빈 행정·인적정보는 자동 추정하지 않습니다.</p>
            </div>
            <div className="document-variant-tabs">
              <span className="active">{variantLabels[data.variant]}</span>
            </div>
          </div>
          <fieldset disabled={!editable || save.isPending}>
            <legend>기본 정보</legend>
            <div className="document-field-grid">
              <label className="wide">
                <span>제목</span>
                <input
                  maxLength={500}
                  onChange={(event) =>
                    update({
                      ...payload,
                      document: { ...payload.document, title: event.target.value },
                    })
                  }
                  value={payload.document.title}
                />
              </label>
              <label>
                <span>문서번호</span>
                <input
                  maxLength={500}
                  onChange={(event) =>
                    update({
                      ...payload,
                      document: { ...payload.document, number: event.target.value },
                    })
                  }
                  placeholder="사용자 입력"
                  value={payload.document.number}
                />
              </label>
              <label>
                <span>작성일</span>
                <input
                  maxLength={500}
                  onChange={(event) =>
                    update({
                      ...payload,
                      document: { ...payload.document, date: event.target.value },
                    })
                  }
                  value={payload.document.date}
                />
              </label>
              <label>
                <span>작성자</span>
                <input
                  maxLength={500}
                  onChange={(event) =>
                    update({ ...payload, author: { ...payload.author, name: event.target.value } })
                  }
                  placeholder="사용자 입력"
                  value={payload.author.name}
                />
              </label>
              <label>
                <span>부서</span>
                <input
                  maxLength={500}
                  onChange={(event) =>
                    update({
                      ...payload,
                      author: { ...payload.author, department: event.target.value },
                    })
                  }
                  placeholder="사용자 입력"
                  value={payload.author.department}
                />
              </label>
              <label>
                <span>승인자</span>
                <input
                  maxLength={500}
                  onChange={(event) =>
                    update({
                      ...payload,
                      author: { ...payload.author, approver: event.target.value },
                    })
                  }
                  placeholder="사용자 입력"
                  value={payload.author.approver}
                />
              </label>
              <label>
                <span>전화번호</span>
                <input
                  maxLength={500}
                  onChange={(event) =>
                    update({
                      ...payload,
                      contact: { ...payload.contact, phone: event.target.value },
                    })
                  }
                  placeholder="사용자 입력"
                  value={payload.contact.phone}
                />
              </label>
              <label>
                <span>이메일</span>
                <input
                  maxLength={500}
                  onChange={(event) =>
                    update({
                      ...payload,
                      contact: { ...payload.contact, email: event.target.value },
                    })
                  }
                  placeholder="사용자 입력"
                  value={payload.contact.email}
                />
              </label>
            </div>
          </fieldset>
          {data.variant === "BASIC_NOTICE" ? (
            <fieldset disabled={!editable || save.isPending}>
              <legend>공문 발송 설정</legend>
              <div className="document-field-grid">
                <label>
                  <span>수신기관</span>
                  <input
                    maxLength={500}
                    onChange={(event) =>
                      update({
                        ...payload,
                        notice: { ...payload.notice, recipient: event.target.value },
                      })
                    }
                    placeholder="사용자가 확인한 기관명"
                    value={payload.notice.recipient}
                  />
                </label>
                <label>
                  <span>회신기한</span>
                  <input
                    maxLength={500}
                    onChange={(event) =>
                      update({
                        ...payload,
                        notice: { ...payload.notice, deadline: event.target.value },
                      })
                    }
                    value={payload.notice.deadline}
                  />
                </label>
                <label className="wide">
                  <span>도입 문구</span>
                  <textarea
                    maxLength={8000}
                    onChange={(event) =>
                      update({
                        ...payload,
                        notice: { ...payload.notice, opening: event.target.value },
                      })
                    }
                    rows={3}
                    value={payload.notice.opening}
                  />
                </label>
                <label className="wide">
                  <span>요청사항 · 한 줄에 한 항목</span>
                  <textarea
                    maxLength={8000}
                    onChange={(event) =>
                      update({
                        ...payload,
                        notice: { ...payload.notice, request: lines(event.target.value) },
                      })
                    }
                    rows={4}
                    value={payload.notice.request.join("\n")}
                  />
                </label>
              </div>
            </fieldset>
          ) : null}
          <fieldset disabled={!editable || save.isPending}>
            <legend>상황·분석</legend>
            <div className="document-field-grid">
              <label>
                <span>발생·기준시각</span>
                <input
                  maxLength={500}
                  onChange={(event) =>
                    update({
                      ...payload,
                      incident: { ...payload.incident, occurredAt: event.target.value },
                    })
                  }
                  value={payload.incident.occurredAt}
                />
              </label>
              <label>
                <span>위치</span>
                <input
                  maxLength={500}
                  onChange={(event) =>
                    update({
                      ...payload,
                      incident: { ...payload.incident, location: event.target.value },
                    })
                  }
                  value={payload.incident.location}
                />
              </label>
              <label className="wide">
                <span>상황 요약</span>
                <textarea
                  maxLength={8000}
                  onChange={(event) =>
                    update({
                      ...payload,
                      incident: { ...payload.incident, summary: event.target.value },
                    })
                  }
                  rows={4}
                  value={payload.incident.summary}
                />
              </label>
              <label className="wide">
                <span>분석 결과</span>
                <textarea
                  maxLength={8000}
                  onChange={(event) =>
                    update({
                      ...payload,
                      analysis: { ...payload.analysis, result: event.target.value },
                    })
                  }
                  rows={5}
                  value={payload.analysis.result}
                />
              </label>
              <label className="wide">
                <span>세부 내용</span>
                <textarea
                  maxLength={8000}
                  onChange={(event) =>
                    update({
                      ...payload,
                      incident: { ...payload.incident, detail: event.target.value },
                    })
                  }
                  rows={5}
                  value={payload.incident.detail}
                />
              </label>
            </div>
          </fieldset>
          <fieldset disabled={!editable || save.isPending}>
            <legend>대응 내용</legend>
            <div className="document-field-grid">
              <label className="wide">
                <span>대응 요약</span>
                <textarea
                  maxLength={8000}
                  onChange={(event) =>
                    update({
                      ...payload,
                      response: { ...payload.response, summary: event.target.value },
                    })
                  }
                  rows={4}
                  value={payload.response.summary}
                />
              </label>
              <label className="wide">
                <span>대응 항목 · 한 줄에 한 항목</span>
                <textarea
                  maxLength={8000}
                  onChange={(event) =>
                    update({
                      ...payload,
                      response: { ...payload.response, actions: lines(event.target.value) },
                    })
                  }
                  rows={5}
                  value={payload.response.actions.join("\n")}
                />
              </label>
              <label className="wide">
                <span>기관 협조·조정</span>
                <textarea
                  maxLength={8000}
                  onChange={(event) =>
                    update({
                      ...payload,
                      response: { ...payload.response, coordination: event.target.value },
                    })
                  }
                  rows={3}
                  value={payload.response.coordination}
                />
              </label>
            </div>
          </fieldset>
          <div className="document-form-footer">
            <span>
              마지막 서버 저장 {formatKst(data.updatedAt)} · 내용 해시{" "}
              {data.contentSha256.slice(0, 10)}…
            </span>
            <button
              className="outline-action"
              disabled={!editable || !dirty || save.isPending}
              onClick={savePayload}
              type="button"
            >
              {save.isPending ? "저장 중…" : "새 버전으로 저장"}
            </button>
          </div>
          {save.isError ? (
            <div className="workflow-inline-error" role="alert">
              {errorMessage(save.error, "문서 변경사항을 저장하지 못했습니다.")}
            </div>
          ) : null}
        </section>
        <aside className="document-editor-aside">
          <section className="panel document-readiness">
            <div className="document-panel-title">
              <h2>검토 준비 상태</h2>
              <span>{reviewReady ? "검토본 완료" : "생성 확인 중"}</span>
            </div>
            <ul>
              <li className="ok">
                <strong>구조화 본문</strong>
                <span>v{data.currentVersion} 서버 저장</span>
              </li>
              <li className={data.evidenceStatus === "SUFFICIENT" ? "ok" : "warning"}>
                <strong>근거 상태</strong>
                <span>{evidenceLabels[data.evidenceStatus]}</span>
              </li>
              <li className={data.missingAdministrativeFields.length ? "warning" : "ok"}>
                <strong>행정정보</strong>
                <span>
                  {data.missingAdministrativeFields.length
                    ? `${data.missingAdministrativeFields.length}개 미입력 · 승인 차단 안 함`
                    : "입력 완료"}
                </span>
              </li>
              {reviewArtifacts.map((artifact) => (
                <li
                  className={
                    artifact.status === "SUCCEEDED"
                      ? "ok"
                      : artifact.status === "FAILED"
                        ? "error"
                        : "pending"
                  }
                  key={artifact.documentArtifactId}
                >
                  <strong>검토 {artifact.format}</strong>
                  <span>{artifactStatusLabels[artifact.status]}</span>
                </li>
              ))}
            </ul>
          </section>
          <section className="panel document-artifact-card">
            <div className="document-panel-title">
              <h2>검토용 파일</h2>
              <span>REVIEW</span>
            </div>
            {reviewArtifacts.map((artifact) => (
              <div className="document-artifact-row" key={artifact.documentArtifactId}>
                <b>{artifact.format}</b>
                <div>
                  <strong>{artifact.fileName ?? `${artifact.format} 생성 중`}</strong>
                  <small>
                    {formatBytes(artifact.sizeBytes)} · 시도 {artifact.attemptCount}회
                  </small>
                </div>
                {artifact.status === "SUCCEEDED" ? (
                  <a href={artifactHref(runtime, artifact)}>다운로드</a>
                ) : (
                  <ArtifactBadge artifact={artifact} />
                )}
              </div>
            ))}
          </section>
          <section className="panel document-approval-card">
            <h2>사용자 승인 요청</h2>
            <p>
              승인 전에는 현재 버전의 내용과 근거 상태를 잠급니다. 외부 전송은 실행되지 않습니다.
            </p>
            <button
              className="document-primary-button"
              disabled={!editable || dirty || !reviewReady || requestApproval.isPending}
              onClick={() => requestApproval.mutate()}
              type="button"
            >
              {requestApproval.isPending ? "승인 요청 중…" : "승인 요청 · COM-02"}
            </button>
            {dirty ? <small>먼저 변경사항을 저장해 주세요.</small> : null}
            {requestApproval.isError ? (
              <div className="workflow-inline-error" role="alert">
                {errorMessage(requestApproval.error, "승인 요청을 만들지 못했습니다.")}
              </div>
            ) : null}
          </section>
        </aside>
      </div>
    </main>
  );
}

function DocumentResult({
  currentPath,
  documentId,
  runtime,
}: {
  currentPath: string;
  documentId: string;
  runtime: ProfileRuntime;
}) {
  const queryClient = useQueryClient();
  const [recipient, setRecipient] = useState("");
  const [deliveredAt, setDeliveredAt] = useState(localDateTimeValue);
  const [method, setMethod] = useState("EMAIL");
  const [memo, setMemo] = useState("");
  const deliveryKey = useRef<string | null>(null);
  const cloneKey = useRef<string | null>(null);
  const document = useQuery({
    queryKey: ["document", runtime.profile, documentId],
    queryFn: () =>
      apiRequest<DocumentDetailData>(runtime, `/documents/${documentId}`).then(
        (result) => result.data,
      ),
    staleTime: 3_000,
    refetchInterval: (query) => pollDocument(query.state.data),
  });
  const retry = useMutation({
    mutationFn: (artifactId: string) =>
      apiRequest(runtime, `/document-artifacts/${artifactId}/retry`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey("document-artifact-retry") },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["document", runtime.profile, documentId],
      });
    },
  });
  const delivery = useMutation({
    mutationFn: (documentVersionId: string) => {
      deliveryKey.current ??= idempotencyKey("document-manual-delivery");
      return apiRequest(runtime, `/document-versions/${documentVersionId}/manual-deliveries`, {
        method: "POST",
        headers: { "Idempotency-Key": deliveryKey.current },
        body: JSON.stringify({
          recipient,
          deliveredAt: new Date(deliveredAt).toISOString(),
          method,
          memo: memo.trim() || null,
        }),
      });
    },
    onSuccess: () => {
      deliveryKey.current = null;
      setMemo("");
      void queryClient.invalidateQueries({
        queryKey: ["document", runtime.profile, documentId],
      });
    },
  });
  const clone = useMutation({
    mutationFn: () => {
      cloneKey.current ??= idempotencyKey("document-clone");
      return apiRequest<DocumentDetailData>(runtime, `/documents/${documentId}/clone`, {
        method: "POST",
        headers: { "Idempotency-Key": cloneKey.current },
      }).then((result) => result.data);
    },
    onSuccess: () => {
      cloneKey.current = null;
      navigateInternal(runtime, `/documents/${documentId}/edit`);
    },
  });
  if (document.isLoading) {
    return <DocumentState message="승인 결과와 최종 파일을 확인하고 있습니다." />;
  }
  if (document.isError || !document.data) {
    return (
      <DocumentState
        error
        message={errorMessage(document.error, "문서 결과를 불러오지 못했습니다.")}
      />
    );
  }
  const data = document.data;
  const finalArtifacts = data.artifacts.filter((item) => item.stage === "FINAL");
  const finalReady =
    finalArtifacts.length === 2 && finalArtifacts.every((item) => item.status === "SUCCEEDED");
  const submitDelivery = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (finalReady && recipient.trim() && !delivery.isPending) {
      delivery.mutate(data.documentVersionId);
    }
  };
  return (
    <main className="page document-page document-result-page" id="main-content">
      <div className="page-heading document-heading">
        <div>
          <p className="case-breadcrumb">산출물 / 승인 결과 및 실행 / OUT-02B</p>
          <h1>승인 결과 및 최종 파일</h1>
          <p>승인 범위와 최종 산출물을 확인하고 시스템 밖 전달 사실을 기록합니다.</p>
        </div>
        <span className={`document-status ${statusClass(data.status)}`}>
          {statusLabels[data.status]}
        </span>
      </div>
      <section className="panel document-decision-summary">
        <div>
          <span>결정</span>
          <strong>{statusLabels[data.status]}</strong>
        </div>
        <div>
          <span>승인시각</span>
          <strong>{formatKst(data.approvedAt)}</strong>
        </div>
        <div>
          <span>결정 사유</span>
          <strong>{data.approvalReason ?? "결정 사유 확인 필요"}</strong>
        </div>
        <p>승인본은 잠겨 있으며 수정하려면 새 초안을 복제해 다시 승인해야 합니다.</p>
      </section>
      <div className="document-result-grid">
        <section className="panel document-final-panel">
          <div className="document-panel-title">
            <h2>최종 산출물</h2>
            <span>{finalReady ? "생성 완료" : "형식별 상태 확인"}</span>
          </div>
          {finalArtifacts.length ? (
            <div className="document-final-files">
              {finalArtifacts.map((artifact) => (
                <article key={artifact.documentArtifactId}>
                  <b>{artifact.format}</b>
                  <div>
                    <strong>{artifact.fileName ?? `${artifact.format} 최종본`}</strong>
                    <span>
                      FINAL · {formatBytes(artifact.sizeBytes)} · 시도 {artifact.attemptCount}회
                    </span>
                    {artifact.errorMessage ? <small>{artifact.errorMessage}</small> : null}
                  </div>
                  {artifact.status === "SUCCEEDED" ? (
                    <a href={artifactHref(runtime, artifact)}>다운로드</a>
                  ) : artifact.status === "FAILED" ? (
                    <button
                      disabled={retry.isPending}
                      onClick={() => retry.mutate(artifact.documentArtifactId)}
                      type="button"
                    >
                      재시도
                    </button>
                  ) : (
                    <ArtifactBadge artifact={artifact} />
                  )}
                </article>
              ))}
            </div>
          ) : (
            <div className="workflow-empty">
              {data.status === "APPROVED"
                ? "FINAL HWPX·PDF 생성 작업을 확인하고 있습니다."
                : "승인된 문서에만 FINAL 파일이 생성됩니다."}
            </div>
          )}
          {retry.isError ? (
            <div className="workflow-inline-error" role="alert">
              {errorMessage(retry.error, "문서 산출물 재시도를 시작하지 못했습니다.")}
            </div>
          ) : null}
          <div className="document-file-verification">
            <span className={finalArtifacts.some((item) => item.format === "HWPX") ? "ok" : ""}>
              HWPX package·XML 검증
            </span>
            <span className={finalArtifacts.some((item) => item.format === "PDF") ? "ok" : ""}>
              PDF signature·font 검증
            </span>
            <span className={data.warningAcknowledged ? "ok" : ""}>근거 경고 결정 이력 보존</span>
          </div>
        </section>
        <section className="panel document-delivery-panel">
          <div className="document-panel-title">
            <h2>수동 발송 기록</h2>
            <span>{data.manualDeliveries.length}건 기록</span>
          </div>
          <p className="document-delivery-boundary">
            시스템은 실제 이메일·기관 메일·전자공문을 보내지 않습니다. 아래 기록은 사용자가 시스템
            밖에서 전달했다고 남긴 이력이며 수신 성공 증명이 아닙니다.
          </p>
          <form onSubmit={submitDelivery}>
            <label>
              <span>수신처</span>
              <input
                maxLength={500}
                onChange={(event) => setRecipient(event.target.value)}
                placeholder="기관 또는 수신처 입력"
                required
                value={recipient}
              />
            </label>
            <div className="document-delivery-fields">
              <label>
                <span>전달시각</span>
                <input
                  onChange={(event) => setDeliveredAt(event.target.value)}
                  required
                  type="datetime-local"
                  value={deliveredAt}
                />
              </label>
              <label>
                <span>방법</span>
                <select onChange={(event) => setMethod(event.target.value)} value={method}>
                  <option value="EMAIL">이메일</option>
                  <option value="MESSENGER">메신저</option>
                  <option value="E_DOCUMENT">전자문서</option>
                  <option value="IN_PERSON">대면 전달</option>
                  <option value="OTHER">기타</option>
                </select>
              </label>
            </div>
            <label>
              <span>메모</span>
              <textarea
                maxLength={2000}
                onChange={(event) => setMemo(event.target.value)}
                rows={3}
                value={memo}
              />
            </label>
            <button
              className="document-primary-button"
              disabled={!finalReady || !recipient.trim() || delivery.isPending}
              type="submit"
            >
              {delivery.isPending ? "기록 중…" : "수동 발송 사실 기록"}
            </button>
          </form>
          {delivery.isError ? (
            <div className="workflow-inline-error" role="alert">
              {errorMessage(delivery.error, "수동 발송 기록을 저장하지 못했습니다.")}
            </div>
          ) : null}
          {data.manualDeliveries.length ? (
            <ol className="document-delivery-history">
              {data.manualDeliveries.map((item) => (
                <li key={item.documentManualDeliveryId}>
                  <strong>{item.recipient}</strong>
                  <span>
                    {formatKst(item.deliveredAt)} · {item.method} · {item.recordedBy}
                  </span>
                  <small>사용자 수동 기록 · 외부 수신 성공 미검증</small>
                </li>
              ))}
            </ol>
          ) : null}
        </section>
      </div>
      <section className="panel document-result-history">
        <div className="document-panel-title">
          <h2>실행·감사 요약</h2>
          <span>불변 버전 v{data.currentVersion}</span>
        </div>
        <ol>
          <li>
            <span>1</span>
            <div>
              <strong>문서 버전 저장</strong>
              <small>{formatKst(data.versionCreatedAt)}</small>
            </div>
          </li>
          <li>
            <span>2</span>
            <div>
              <strong>사용자 결정</strong>
              <small>{formatKst(data.approvedAt)}</small>
            </div>
          </li>
          <li>
            <span>3</span>
            <div>
              <strong>FINAL HWPX·PDF</strong>
              <small>{finalReady ? "생성 완료" : "형식별 상태 확인 중"}</small>
            </div>
          </li>
          <li>
            <span>4</span>
            <div>
              <strong>수동 발송 기록</strong>
              <small>
                {data.manualDeliveries.length ? `${data.manualDeliveries.length}건` : "대기"}
              </small>
            </div>
          </li>
        </ol>
        <div className="document-result-actions">
          <AppLink
            className="outline-action"
            currentPath={currentPath}
            runtime={runtime}
            to="/artifacts"
          >
            산출물 보관함 열기
          </AppLink>
          {data.status === "APPROVED" || data.status === "DISCARDED" ? (
            <button
              className="document-secondary-button"
              disabled={clone.isPending}
              onClick={() => clone.mutate()}
              type="button"
            >
              {clone.isPending ? "복제 중…" : "새 초안으로 복제"}
            </button>
          ) : null}
        </div>
      </section>
    </main>
  );
}

function DocumentLibrary({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [family, setFamily] = useState("");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const params = new URLSearchParams({ page: String(page), pageSize: "20" });
  if (status) params.set("status", status);
  if (family) params.set("family", family);
  const documents = useQuery({
    queryKey: ["documents", runtime.profile, page, status, family],
    queryFn: () =>
      apiRequest<DocumentLibraryData>(runtime, `/documents?${params}`).then(
        (result) => result.data,
      ),
    staleTime: 10_000,
  });
  const selected = useQuery({
    queryKey: ["document", runtime.profile, selectedId],
    queryFn: () =>
      apiRequest<DocumentDetailData>(runtime, `/documents/${selectedId}`).then(
        (result) => result.data,
      ),
    enabled: selectedId !== null,
    staleTime: 5_000,
  });
  useEffect(() => {
    if (!selectedId && documents.data?.items[0]) {
      setSelectedId(documents.data.items[0].documentDraftId);
    }
  }, [documents.data, selectedId]);
  const visibleItems = useMemo(() => {
    const keyword = search.trim().toLocaleLowerCase("ko-KR");
    if (!keyword) return documents.data?.items ?? [];
    return (documents.data?.items ?? []).filter((item) =>
      `${item.title} ${item.caseNumber ?? ""}`.toLocaleLowerCase("ko-KR").includes(keyword),
    );
  }, [documents.data, search]);
  if (documents.isLoading) {
    return <DocumentState message="산출물 보관함을 준비하고 있습니다." />;
  }
  if (documents.isError || !documents.data) {
    return (
      <DocumentState
        error
        message={errorMessage(documents.error, "산출물 보관함을 불러오지 못했습니다.")}
      />
    );
  }
  const detail = selected.data;
  const preferredArtifact =
    detail?.artifacts.find(
      (item) => item.stage === "FINAL" && item.format === "PDF" && item.status === "SUCCEEDED",
    ) ??
    detail?.artifacts.find(
      (item) => item.stage === "REVIEW" && item.format === "PDF" && item.status === "SUCCEEDED",
    );
  return (
    <main className="page document-page document-library-page" id="main-content">
      <div className="page-heading document-heading">
        <div>
          <p className="case-breadcrumb">보고서·산출물 / 산출물 보관함 / DOC-01B</p>
          <h1>산출물 보관함</h1>
          <p>문서 버전·승인·HWPX/PDF·수동 발송 기록을 검색하고 열람합니다.</p>
        </div>
        <span className="document-count">총 {documents.data.pagination.total}건</span>
      </div>
      <section className="panel document-library-filters">
        <div>
          <strong>검색 및 필터</strong>
          <span>서버 상태·계열 필터와 현재 페이지 제목 검색을 조합합니다.</span>
        </div>
        <select
          aria-label="문서 계열"
          onChange={(event) => {
            setFamily(event.target.value);
            setPage(1);
            setSelectedId(null);
          }}
          value={family}
        >
          <option value="">계열 전체</option>
          <option value="SITUATION_REPORT">보고서</option>
          <option value="OFFICIAL_NOTICE">공문</option>
          <option value="RESPONSE_PLAN">계획서</option>
        </select>
        <select
          aria-label="문서 상태"
          onChange={(event) => {
            setStatus(event.target.value);
            setPage(1);
            setSelectedId(null);
          }}
          value={status}
        >
          <option value="">상태 전체</option>
          {(Object.keys(statusLabels) as DocumentStatus[]).map((item) => (
            <option key={item} value={item}>
              {statusLabels[item]}
            </option>
          ))}
        </select>
        <input
          aria-label="제목 또는 Case 검색"
          onChange={(event) => setSearch(event.target.value)}
          placeholder="제목·Case 번호 검색"
          value={search}
        />
        <button
          className="document-secondary-button"
          onClick={() => {
            setFamily("");
            setStatus("");
            setSearch("");
            setPage(1);
            setSelectedId(null);
          }}
          type="button"
        >
          초기화
        </button>
      </section>
      <div className="document-library-layout">
        <section className="panel document-library-list">
          <div className="document-panel-title">
            <div>
              <h2>문서 목록</h2>
              <span>현재 페이지 {visibleItems.length}건</span>
            </div>
          </div>
          <div className="document-list-head" aria-hidden="true">
            <span>계열</span>
            <span>제목·Case</span>
            <span>버전</span>
            <span>갱신</span>
            <span>파일</span>
            <span>상태</span>
          </div>
          {visibleItems.length ? (
            <div className="document-list-body">
              {visibleItems.map((item) => (
                <button
                  className={selectedId === item.documentDraftId ? "selected" : ""}
                  key={item.documentDraftId}
                  onClick={() => setSelectedId(item.documentDraftId)}
                  type="button"
                >
                  <span className={`document-family ${statusClass(item.family)}`}>
                    {familyLabels[item.family]}
                  </span>
                  <span>
                    <strong>{item.title}</strong>
                    <small>{item.caseNumber ?? "Case 연결 없음"}</small>
                  </span>
                  <span>v{item.currentVersion}</span>
                  <time>{formatKst(item.updatedAt)}</time>
                  <span>{item.succeededArtifactCount}개</span>
                  <span className={`document-status ${statusClass(item.status)}`}>
                    {statusLabels[item.status]}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <div className="workflow-empty">조건에 맞는 문서가 없습니다.</div>
          )}
          <div className="document-pagination">
            <span>
              {documents.data.pagination.total
                ? `${(page - 1) * 20 + 1}–${Math.min(page * 20, documents.data.pagination.total)} / ${documents.data.pagination.total}`
                : "0건"}
            </span>
            <div>
              <button disabled={page <= 1} onClick={() => setPage(page - 1)} type="button">
                이전
              </button>
              <b>{page}</b>
              <button
                disabled={page >= documents.data.pagination.totalPages}
                onClick={() => setPage(page + 1)}
                type="button"
              >
                다음
              </button>
            </div>
          </div>
        </section>
        <aside className="panel document-library-detail">
          {selected.isLoading ? (
            <div className="workflow-empty">선택 문서를 불러오고 있습니다.</div>
          ) : selected.isError || !detail ? (
            <div className="workflow-empty">
              {selectedId ? "선택 문서를 불러오지 못했습니다." : "문서를 선택해 주세요."}
            </div>
          ) : (
            <>
              <div className="document-panel-title">
                <h2>선택 문서</h2>
                <span className={`document-status ${statusClass(detail.status)}`}>
                  {statusLabels[detail.status]}
                </span>
              </div>
              <div className="document-selected-file">
                <b>{preferredArtifact?.format ?? familyLabels[detail.family]}</b>
                <div>
                  <strong>{detail.title}</strong>
                  <span>
                    v{detail.currentVersion} ·{" "}
                    {preferredArtifact
                      ? formatBytes(preferredArtifact.sizeBytes)
                      : "파일 생성 확인 중"}
                  </span>
                  <small>최근 갱신 {formatKst(detail.updatedAt)}</small>
                </div>
              </div>
              <dl className="document-selected-facts">
                <div>
                  <dt>계열</dt>
                  <dd>{variantLabels[detail.variant]}</dd>
                </div>
                <div>
                  <dt>Case</dt>
                  <dd>{detail.caseNumber ?? "연결 없음"}</dd>
                </div>
                <div>
                  <dt>근거</dt>
                  <dd>{evidenceLabels[detail.evidenceStatus]}</dd>
                </div>
                <div>
                  <dt>파일</dt>
                  <dd>{detail.artifacts.filter((item) => item.status === "SUCCEEDED").length}개</dd>
                </div>
                <div>
                  <dt>수동 발송</dt>
                  <dd>{detail.manualDeliveries.length}건</dd>
                </div>
                <div>
                  <dt>보존 버전</dt>
                  <dd>{detail.versions.length}개</dd>
                </div>
              </dl>
              <div className="document-library-actions">
                {preferredArtifact ? (
                  <a
                    className="document-primary-button"
                    href={artifactHref(runtime, preferredArtifact)}
                  >
                    파일 다운로드
                  </a>
                ) : null}
                <AppLink
                  className="document-secondary-link"
                  currentPath={currentPath}
                  runtime={runtime}
                  to={
                    detail.status === "DRAFT" || detail.status === "ON_HOLD"
                      ? `/documents/${detail.documentDraftId}/edit`
                      : `/documents/${detail.documentDraftId}/result`
                  }
                >
                  문서 열기
                </AppLink>
              </div>
              <AppLink
                className="document-audit-link"
                currentPath={currentPath}
                runtime={runtime}
                to="/automation/runs"
              >
                연결된 감사 이력 열기
              </AppLink>
            </>
          )}
        </aside>
      </div>
    </main>
  );
}

export function DocumentManagement({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const createMatch = /^\/cases\/([0-9a-f-]+)\/documents\/new$/i.exec(currentPath);
  if (createMatch) {
    return <NewDocument caseId={createMatch[1]} currentPath={currentPath} runtime={runtime} />;
  }
  const editMatch = /^\/documents\/([0-9a-f-]+)\/edit$/i.exec(currentPath);
  if (editMatch) {
    return <DocumentEditor documentId={editMatch[1]} runtime={runtime} />;
  }
  const resultMatch = /^\/documents\/([0-9a-f-]+)\/result$/i.exec(currentPath);
  if (resultMatch) {
    return (
      <DocumentResult currentPath={currentPath} documentId={resultMatch[1]} runtime={runtime} />
    );
  }
  return <DocumentLibrary currentPath={currentPath} runtime={runtime} />;
}

export default DocumentManagement;
