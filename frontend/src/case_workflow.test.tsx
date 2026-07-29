import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { resolveProfile } from "./profile";

const caseId = "00000000-0000-4000-8000-000000000301";
const workItemId = "00000000-0000-4000-8000-000000000801";
const checklistItemId = "00000000-0000-4000-8000-000000000901";
const approvalId = "00000000-0000-4000-8000-000000000401";

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
      asOf: "2026-07-29T05:00:00Z",
    },
    error: null,
  };
}

const evidence = {
  case: {
    caseId,
    caseNumber: "ES-20260729-000001",
    title: "광주 북구 공장 화재 출동",
    caseType: "FIRE",
    status: "ACTIVE",
    regionName: "광주광역시 북구",
    updatedAt: "2026-07-29T04:55:00Z",
  },
  retrievalState: "COMPLETED",
  evidenceStatus: "SUFFICIENT",
  warning: null,
  bundle: {
    evidenceBundleId: "00000000-0000-4000-8000-000000000701",
    version: 1,
    indexVersionId: "00000000-0000-4000-8000-000000000702",
    indexStatus: "ACTIVE",
    indexedDocumentCount: 241,
    indexedChunkCount: 14311,
    candidateCount: 77,
    selectedCount: 3,
    directCitationCount: 1,
    retrievalVersion: "hybrid-rff-v1",
    createdAt: "2026-07-29T04:50:00Z",
  },
  officialEvidence: [
    {
      evidenceItemId: "00000000-0000-4000-8000-000000000711",
      documentId: "00000000-0000-4000-8000-000000000712",
      documentTitle: "전기재해 대응 매뉴얼",
      documentFamily: "MANUAL",
      issuingAgency: "한국전기안전공사",
      documentNumber: null,
      publishedAt: "2026-04-01",
      revision: null,
      authorityLevel: 5,
      privacyStatus: "SAFE",
      evidenceGroup: "OFFICIAL",
      rank: 1,
      fusedScore: 0.08,
      currentStatus: "CURRENT",
      selectionReason: "공식 현행 대응 근거",
      excerpt: "현장 접근 전 전원 차단 여부와 소방 활동 안전 조건을 확인한다.",
      locator: "제3장 > 초동조치",
      pageOrSection: "제3장",
      headingPath: ["초동조치"],
    },
  ],
  similarIncidents: [],
  otherRegionReferences: [],
  recommendation: {
    recommendationId: "00000000-0000-4000-8000-000000000721",
    version: 1,
    status: "READY",
    generationMode: "SOLAR",
    situationSummary: "공장 화재 신호의 전기안전 초동 확인이 필요합니다.",
    requiredChecks: ["전원 차단 여부"],
    uncertainties: [],
    conflicts: [],
    warning: null,
    generationVersion: "recommendation-v1",
    createdAt: "2026-07-29T04:52:00Z",
    actions: [
      {
        recommendationActionId: "00000000-0000-4000-8000-000000000722",
        ordinal: 1,
        title: "전원 차단 상태 확인",
        description: "현장 안전 조건과 전원 차단 상태를 확인합니다.",
        dueGuidance: "즉시",
        evidenceStatus: "SUFFICIENT",
        warning: null,
        status: "READY",
        workItemId,
        workItemStatus: "RUNNING",
        citations: [
          {
            citationId: "00000000-0000-4000-8000-000000000723",
            evidenceItemId: "00000000-0000-4000-8000-000000000711",
            supportType: "DIRECT",
            quote: "현장 접근 전 전원 차단 여부를 확인한다.",
            locator: "제3장 > 초동조치",
            documentTitle: "전기재해 대응 매뉴얼",
            issuingAgency: "한국전기안전공사",
            documentNumber: null,
            publishedAt: "2026-04-01",
          },
        ],
      },
    ],
  },
};

const workItem = {
  workItemId,
  caseId,
  recommendationActionId: "00000000-0000-4000-8000-000000000722",
  workType: "FIELD_CHECK",
  status: "RUNNING",
  priority: "URGENT",
  title: "전원 차단 상태 확인",
  dueAt: null,
  progress: 50,
  errorClass: null,
  retryCount: 0,
  version: 1,
  createdAt: "2026-07-29T04:53:00Z",
  startedAt: "2026-07-29T04:54:00Z",
  completedAt: null,
  updatedAt: "2026-07-29T04:54:00Z",
  checklist: [
    {
      checklistItemId,
      ordinal: 1,
      label: "현장 전원 차단 여부 확인",
      status: "PENDING",
      note: null,
      completedAt: null,
      updatedAt: "2026-07-29T04:54:00Z",
    },
  ],
};

function installFetch({
  recommendationInitiallyMissing = false,
}: {
  recommendationInitiallyMissing?: boolean;
} = {}) {
  let evidenceReads = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/auth/session")) {
        return response(
          envelope({
            user: { userId: "user", displayName: "사용자" },
            expiresAt: "2026-07-29T12:00:00Z",
          }),
        );
      }
      if (url.endsWith("/sources/health")) {
        return response(envelope({ summary: "HEALTHY", dataAsOf: null, sources: [] }));
      }
      if (url.endsWith(`/cases/${caseId}/recommendations/generate`)) {
        return response(
          envelope({
            caseId,
            taskId: "00000000-0000-4000-8000-000000000799",
            status: "QUEUED",
            reused: false,
          }),
          202,
        );
      }
      if (
        url.endsWith(
          `/recommendations/${evidence.recommendation.recommendationId}/approval-requests`,
        )
      ) {
        return response(
          envelope({
            approvalRequestId: approvalId,
            recommendationId: evidence.recommendation.recommendationId,
            version: 1,
            status: "APPROVAL_PENDING",
            reused: false,
          }),
          201,
        );
      }
      if (url.endsWith(`/cases/${caseId}/evidence`)) {
        evidenceReads += 1;
        return response(
          envelope({
            ...evidence,
            recommendation:
              recommendationInitiallyMissing && evidenceReads === 1
                ? null
                : evidence.recommendation,
          }),
        );
      }
      if (url.endsWith(`/cases/${caseId}/work-items`)) {
        return response(
          envelope({
            summary: { total: 1, open: 1, waitingApproval: 0, completed: 0 },
            items: [workItem],
          }),
        );
      }
      if (url.endsWith(`/work-items/${workItemId}`)) {
        return response(envelope(workItem));
      }
      if (url.endsWith(`/work-items/${workItemId}/checklist/${checklistItemId}`)) {
        const payload = JSON.parse(String(init?.body));
        return response(
          envelope({
            ...workItem,
            progress: payload.status === "DONE" ? 100 : 0,
            version: 2,
            checklist: [
              {
                ...workItem.checklist[0],
                status: payload.status,
                completedAt: payload.status === "DONE" ? "2026-07-29T05:00:00Z" : null,
              },
            ],
          }),
        );
      }
      if (url.endsWith(`/cases/${caseId}/closure-review`)) {
        return response(
          envelope({
            caseId,
            caseNumber: "ES-20260729-000001",
            title: "광주 북구 공장 화재 출동",
            status: "SOURCE_RESOLVED_REVIEW",
            sourceStatus: "RESOLVED",
            openedAt: "2026-07-29T04:00:00Z",
            updatedAt: "2026-07-29T05:00:00Z",
            sourceResolvedAt: "2026-07-29T04:58:00Z",
            closedAt: null,
            closeReason: null,
            evidenceStatus: "SUFFICIENT",
            evidenceWarning: null,
            workSummary: { incomplete: 1, completed: 2, discarded: 0 },
            incompleteWorkItems: [
              {
                workItemId,
                title: "전원 차단 상태 확인",
                status: "RUNNING",
                priority: "URGENT",
                progress: 50,
                updatedAt: "2026-07-29T04:54:00Z",
              },
            ],
            completedClosure: null,
            closurePolicy: "PENDING_USER_DECISION",
          }),
        );
      }
      if (url.includes(`/cases/${caseId}/timeline?`)) {
        return response(
          envelope({
            items: [
              {
                occurredAt: "2026-07-29T04:00:00Z",
                entryType: "SIGNAL_RAW",
                entryId: "00000000-0000-4000-8000-000000000991",
                category: "NFDS",
                title: "원천 응답 수신",
              },
            ],
            page: 1,
            pageSize: 20,
            total: 1,
          }),
        );
      }
      throw new Error(`unexpected request: ${url}`);
    }),
  );
}

function renderApp(pathname: string) {
  window.history.replaceState({}, "", pathname);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <App runtime={resolveProfile(pathname)} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("case workflow screens", () => {
  it("renders INC-03B with grouped evidence, exact locators, and cited actions", async () => {
    installFetch();
    renderApp(`/demo/cases/${caseId}/evidence`);

    expect(await screen.findByRole("heading", { name: "근거 기반 대응 절차" })).toBeVisible();
    expect(screen.getByText("전기재해 대응 매뉴얼")).toBeVisible();
    expect(screen.getByText("제3장 > 초동조치")).toBeVisible();
    expect(screen.getByText(/현장 접근 전 전원 차단 여부/)).toBeVisible();
    expect(screen.getByText("직접 인용 충족률")).toBeVisible();
    expect(screen.getByText("100%")).toBeVisible();
    expect(screen.getByRole("link", { name: "과업 열기" })).toHaveAttribute(
      "href",
      `/demo/cases/${caseId}/tasks/${workItemId}`,
    );
  });

  it("queues a recommendation after evidence retrieval and renders the result", async () => {
    installFetch({ recommendationInitiallyMissing: true });
    renderApp(`/demo/cases/${caseId}/evidence`);

    const generate = await screen.findByRole("button", {
      name: "대응안 생성",
    });
    await userEvent.click(generate);

    expect(
      await screen.findByText("공장 화재 신호의 전기안전 초동 확인이 필요합니다."),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "대응안 다시 생성" })).toBeVisible();
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining(`/cases/${caseId}/recommendations/generate`),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("requests recommendation approval and navigates to the explanation screen", async () => {
    installFetch();
    vi.stubGlobal("scrollTo", vi.fn());
    renderApp(`/demo/cases/${caseId}/evidence`);

    await userEvent.click(await screen.findByRole("button", { name: "대응안 검토·승인" }));

    await waitFor(() => {
      expect(window.location.pathname).toBe(`/demo/approvals/${approvalId}`);
    });
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining(
        `/recommendations/${evidence.recommendation.recommendationId}/approval-requests`,
      ),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("renders INC-04B and persists a checklist change through the workflow API", async () => {
    installFetch();
    renderApp(`/demo/cases/${caseId}/tasks/${workItemId}`);

    expect(await screen.findByRole("heading", { name: "단계별 수행과업 상세" })).toBeVisible();
    const button = screen.getByRole("button", {
      name: "현장 전원 차단 여부 확인 완료로 변경",
    });
    await userEvent.click(button);
    expect(await screen.findByText("완료")).toBeVisible();
  });

  it("renders INC-05B with real incomplete work and no premature close action", async () => {
    installFetch();
    renderApp(`/demo/cases/${caseId}/close`);

    expect(await screen.findByRole("heading", { name: "상황 종료·결과 요약" })).toBeVisible();
    expect(screen.getByText("원천 응답 수신")).toBeVisible();
    expect(screen.getByText("종료 실행 기준 확정 대기")).toBeVisible();
    expect(screen.getByRole("link", { name: /전원 차단 상태 확인/ })).toHaveAttribute(
      "href",
      `/demo/cases/${caseId}/tasks/${workItemId}`,
    );
    expect(screen.queryByRole("button", { name: /종료/ })).not.toBeInTheDocument();
  });
});
