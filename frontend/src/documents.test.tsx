import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApprovalManagement } from "./approvals";
import { DocumentManagement } from "./documents";
import { resolveProfile } from "./profile";

const caseId = "00000000-0000-4000-8000-000000000701";
const documentId = "00000000-0000-4000-8000-000000000702";
const versionId = "00000000-0000-4000-8000-000000000703";
const approvalId = "00000000-0000-4000-8000-000000000704";

function response(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

function envelope(data: unknown) {
  return {
    data,
    meta: {
      requestId: "00000000-0000-4000-8000-000000000000",
      profile: "DEMO",
      asOf: "2026-07-29T07:00:00Z",
    },
    error: null,
  };
}

const payload = {
  schemaVersion: 1,
  caseId,
  caseNumber: "ES-20260729-000007",
  variant: "INCIDENT_REPORT",
  document: { title: "광주 북구 전기화재 상황보고", date: "2026-07-29", year: "2026", number: "" },
  author: { name: "", department: "", approver: "" },
  contact: { phone: "", email: "", block: "" },
  incident: {
    type: "FIRE",
    occurredAt: "2026-07-29 15:30",
    location: "광주광역시 북구",
    cause: "",
    summary: "배전반 연기 신고가 접수되었습니다.",
    detail: "현장 확인 중입니다.",
    damage: "",
    agencies: "",
  },
  facility: { name: "", address: "", use: "", risk: "", region: "", detail: "" },
  analysis: { result: "전원 차단 상태 확인이 필요합니다.", uncertainties: [], conflicts: [] },
  monitoring: { summary: "", signals: [] },
  response: {
    summary: "현장 안전 확인",
    priority: "",
    actions: ["전원 차단 상태 확인"],
    evidence: [],
    plan: [],
    recipients: [],
    coordination: "",
    approvalProcedure: "",
    reportingProcedure: "",
    reportingTiming: "",
    emergencyPlan: "",
  },
  evidence: { status: "INSUFFICIENT", references: [] },
  notice: {
    recipient: "",
    deliveryRoute: "",
    opening: "",
    grounds: [],
    request: [],
    deadline: "",
  },
  attachments: { items: [] },
  review: { warning: "공식 현행 직접 근거가 부족합니다." },
};

const reviewArtifacts = [
  {
    documentArtifactId: "00000000-0000-4000-8000-000000000711",
    format: "HWPX",
    stage: "REVIEW",
    status: "SUCCEEDED",
    attemptCount: 1,
    fileName: "review.hwpx",
    mimeType: "application/zip",
    sizeBytes: 12345,
    sha256: "1".repeat(64),
    errorCode: null,
    errorMessage: null,
    queuedAt: "2026-07-29T06:00:00Z",
    startedAt: "2026-07-29T06:00:01Z",
    finishedAt: "2026-07-29T06:00:02Z",
    downloadUrl: null,
  },
  {
    documentArtifactId: "00000000-0000-4000-8000-000000000712",
    format: "PDF",
    stage: "REVIEW",
    status: "SUCCEEDED",
    attemptCount: 1,
    fileName: "review.pdf",
    mimeType: "application/pdf",
    sizeBytes: 23456,
    sha256: "2".repeat(64),
    errorCode: null,
    errorMessage: null,
    queuedAt: "2026-07-29T06:00:00Z",
    startedAt: "2026-07-29T06:00:01Z",
    finishedAt: "2026-07-29T06:00:02Z",
    downloadUrl: null,
  },
];

const finalArtifacts = reviewArtifacts.map((artifact, index) => ({
  ...artifact,
  documentArtifactId: `00000000-0000-4000-8000-00000000072${index + 1}`,
  stage: "FINAL",
  fileName: `final.${artifact.format.toLowerCase()}`,
}));

function documentDetail(status = "DRAFT") {
  return {
    documentDraftId: documentId,
    documentVersionId: versionId,
    caseId,
    caseNumber: "ES-20260729-000007",
    family: "SITUATION_REPORT",
    variant: "INCIDENT_REPORT",
    title: payload.document.title,
    status,
    versionStatus: status,
    currentVersion: 1,
    lockVersion: 1,
    payload,
    evidenceStatus: "INSUFFICIENT",
    warning: payload.review.warning,
    missingAdministrativeFields: ["document.number", "author.name"],
    contentSha256: "a".repeat(64),
    template: { key: "incident-report", version: "1", sha256: "b".repeat(64) },
    warningAcknowledged: status === "APPROVED",
    approvalReason: status === "APPROVED" ? "상황 공유를 위해 승인합니다." : null,
    createdAt: "2026-07-29T06:00:00Z",
    updatedAt: "2026-07-29T06:00:02Z",
    versionCreatedAt: "2026-07-29T06:00:00Z",
    approvedAt: status === "APPROVED" ? "2026-07-29T06:10:00Z" : null,
    artifacts: status === "APPROVED" ? [...reviewArtifacts, ...finalArtifacts] : reviewArtifacts,
    manualDeliveries: [],
    versions: [
      {
        version: 1,
        status,
        evidenceStatus: "INSUFFICIENT",
        warning: payload.review.warning,
        contentSha256: "a".repeat(64),
        succeededArtifactCount: status === "APPROVED" ? 4 : 2,
        createdAt: "2026-07-29T06:00:00Z",
        approvedAt: status === "APPROVED" ? "2026-07-29T06:10:00Z" : null,
      },
    ],
  };
}

function renderRoute(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("document workspace", () => {
  it("shows the structured editor, evidence warning, and both review files", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response(envelope(documentDetail()))),
    );
    const runtime = resolveProfile("/demo/documents");
    renderRoute(
      <DocumentManagement currentPath={`/documents/${documentId}/edit`} runtime={runtime} />,
    );

    expect(await screen.findByRole("heading", { name: "사고·상황 보고서" })).toBeVisible();
    expect(screen.getByDisplayValue(payload.document.title)).toBeVisible();
    expect(screen.getByText("2개 미입력 · 승인 차단 안 함")).toBeVisible();
    expect(screen.getAllByRole("link", { name: "다운로드" })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "승인 요청 · COM-02" })).toBeEnabled();
  });

  it("records an external manual delivery fact without claiming it sent anything", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/manual-deliveries")) {
        return response(envelope({ externalDeliveryVerified: false }));
      }
      return response(envelope(documentDetail("APPROVED")));
    });
    vi.stubGlobal("fetch", fetchMock);
    const runtime = resolveProfile("/demo/documents");
    renderRoute(
      <DocumentManagement currentPath={`/documents/${documentId}/result`} runtime={runtime} />,
    );

    expect(await screen.findByRole("heading", { name: "승인 결과 및 최종 파일" })).toBeVisible();
    expect(
      screen.getByText(/시스템은 실제 이메일·기관 메일·전자공문을 보내지 않습니다/),
    ).toBeVisible();
    await userEvent.type(screen.getByLabelText("수신처"), "광주광역시 재난안전부서");
    await userEvent.click(screen.getByRole("button", { name: "수동 발송 사실 기록" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining(`/document-versions/${versionId}/manual-deliveries`),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("renders the server-filtered document library and selected detail", async () => {
    const detail = documentDetail("APPROVED");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/documents?")) {
          return response(
            envelope({
              items: [
                {
                  documentDraftId: documentId,
                  caseId,
                  caseNumber: detail.caseNumber,
                  family: detail.family,
                  variant: detail.variant,
                  title: detail.title,
                  status: detail.status,
                  currentVersion: 1,
                  evidenceStatus: detail.evidenceStatus,
                  warning: detail.warning,
                  succeededArtifactCount: 4,
                  createdAt: detail.createdAt,
                  updatedAt: detail.updatedAt,
                },
              ],
              pagination: { page: 1, pageSize: 20, total: 1, totalPages: 1 },
            }),
          );
        }
        return response(envelope(detail));
      }),
    );
    const runtime = resolveProfile("/demo/artifacts");
    renderRoute(<DocumentManagement currentPath="/artifacts" runtime={runtime} />);

    expect(await screen.findByRole("heading", { name: "산출물 보관함" })).toBeVisible();
    expect(await screen.findByText("수동 발송")).toBeVisible();
    expect(screen.getByRole("link", { name: "파일 다운로드" })).toHaveAttribute(
      "href",
      expect.stringContaining("/document-artifacts/"),
    );
  });
});

describe("document approval", () => {
  it("uses the document decision contract and routes approval to final files", async () => {
    const approved = {
      approvalRequestId: approvalId,
      caseId,
      targetType: "DOCUMENT_DRAFT",
      targetId: documentId,
      targetVersion: 1,
      title: payload.document.title,
      status: "APPROVED",
      contentSha256: "a".repeat(64),
      contentMatches: true,
      evidenceStatus: "INSUFFICIENT",
      warning: payload.review.warning,
      requestedBy: "사용자",
      requestedAt: "2026-07-29T06:05:00Z",
      decidedAt: "2026-07-29T06:10:00Z",
      version: 2,
      case: {
        caseId,
        caseNumber: "ES-20260729-000007",
        title: "광주 북구 전기화재",
        caseType: "FIRE",
        status: "ACTIVE",
        monitoringPriority: "ATTENTION",
        regionCode: "29170",
        regionName: "광주광역시 북구",
      },
      recommendation: null,
      document: {
        ...documentDetail("APPROVED"),
        draftStatus: "APPROVED",
        draftLockVersion: 2,
        version: 1,
      },
      executionImpact: {
        workItemCount: 0,
        externalEffect: false,
        summary: "승인하면 FINAL HWPX·PDF 생성을 시작합니다.",
      },
      decision: {
        approvalDecisionId: "00000000-0000-4000-8000-000000000705",
        decision: "APPROVED",
        decidedBy: "사용자",
        reason: "상황 공유를 위해 승인합니다.",
        warningAcknowledged: true,
        contentSha256: "a".repeat(64),
        decidedAt: "2026-07-29T06:10:00Z",
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response(envelope(approved))),
    );
    const runtime = resolveProfile("/demo/approvals");
    renderRoute(<ApprovalManagement currentPath={`/approvals/${approvalId}`} runtime={runtime} />);

    expect(await screen.findByRole("heading", { name: /승인 대상 문서/ })).toBeVisible();
    expect(screen.getByText(/외부 전송은 승인 후에도 자동 실행하지 않습니다/)).toBeVisible();
    expect(screen.getByRole("link", { name: "최종 문서·전달 기록 열기" })).toHaveAttribute(
      "href",
      `/demo/documents/${documentId}/result`,
    );
  });
});
