import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { resolveProfile } from "./profile";

const caseId = "00000000-0000-4000-8000-000000000301";
const approvalId = "00000000-0000-4000-8000-000000000401";
const recommendationId = "00000000-0000-4000-8000-000000000501";

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

const listItem = {
  approvalRequestId: approvalId,
  caseId,
  caseNumber: "ES-20260729-000001",
  caseTitle: "광주 북구 공장 화재 출동",
  targetType: "RECOMMENDATION",
  targetVersion: 1,
  title: "광주 북구 공장 화재 대응안",
  status: "APPROVAL_PENDING",
  evidenceStatus: "INSUFFICIENT",
  warning: "공식 현행 직접 근거가 부족합니다.",
  requestedAt: "2026-07-29T04:55:00Z",
  decidedAt: null,
  version: 1,
};

const detail = {
  ...listItem,
  targetId: recommendationId,
  contentSha256: "a".repeat(64),
  contentMatches: true,
  requestedBy: "사용자",
  case: {
    caseId,
    caseNumber: "ES-20260729-000001",
    title: "광주 북구 공장 화재 출동",
    caseType: "FIRE",
    status: "ACTIVE",
    monitoringPriority: "ATTENTION",
    regionCode: "29170",
    regionName: "광주광역시 북구",
  },
  recommendation: {
    recommendationId,
    version: 1,
    status: "APPROVAL_PENDING",
    situationSummary: "현장 전원 차단 여부와 접근 안전성을 우선 확인합니다.",
    requiredChecks: ["현장 통제선과 전원 차단 상태 확인"],
    uncertainties: ["발화 설비가 아직 특정되지 않았습니다."],
    conflicts: [],
    warning: "공식 현행 직접 근거가 부족합니다.",
    evidenceStatus: "INSUFFICIENT",
    evidenceWarning: "직접 근거 부족",
    actions: [
      {
        recommendationActionId: "00000000-0000-4000-8000-000000000511",
        ordinal: 1,
        title: "현장 전원 차단 상태 확인",
        description: "현장 안전 조건과 전원 차단 상태를 확인합니다.",
        dueGuidance: "즉시",
        evidenceStatus: "INSUFFICIENT",
        warning: "직접 근거 부족",
        status: "READY",
        checklist: ["통제선 확인", "차단기 상태 확인"],
        citations: [
          {
            citationId: "00000000-0000-4000-8000-000000000512",
            evidenceItemId: "00000000-0000-4000-8000-000000000513",
            supportType: "CONTEXT",
            quote: "현장 접근 전 안전 조건을 확인한다.",
            locator: "제2장 > 초동조치",
            documentTitle: "전기재해 대응 매뉴얼",
            issuingAgency: "한국전기안전공사",
          },
        ],
        workItemId: null,
        workItemStatus: null,
      },
    ],
  },
  executionImpact: {
    workItemCount: 1,
    externalEffect: false,
    summary: "승인하면 내부 수행과업만 생성합니다.",
  },
  decision: null,
};

function installFetch() {
  let decided = false;
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
      if (url.includes("/approvals?pageSize=50")) {
        return response(envelope({ items: [listItem], page: 1, pageSize: 50, total: 1 }));
      }
      if (url.endsWith(`/approvals/${approvalId}/decision`)) {
        const payload = JSON.parse(String(init?.body));
        decided = true;
        return response(
          envelope({
            ...detail,
            status: payload.decision,
            version: 2,
            decidedAt: "2026-07-29T05:10:00Z",
            recommendation: {
              ...detail.recommendation,
              status: payload.decision === "APPROVED" ? "READY" : "APPROVAL_PENDING",
              actions: detail.recommendation.actions.map((action) => ({
                ...action,
                status: payload.decision === "APPROVED" ? "ACCEPTED" : action.status,
                workItemId:
                  payload.decision === "APPROVED" ? "00000000-0000-4000-8000-000000000601" : null,
                workItemStatus: payload.decision === "APPROVED" ? "QUEUED" : null,
              })),
            },
            decision: {
              approvalDecisionId: "00000000-0000-4000-8000-000000000402",
              decision: payload.decision,
              decidedBy: "사용자",
              reason: payload.reason,
              warningAcknowledged: payload.warningAcknowledged,
              contentSha256: detail.contentSha256,
              decidedAt: "2026-07-29T05:10:00Z",
            },
          }),
        );
      }
      if (url.endsWith(`/approvals/${approvalId}`)) {
        return response(envelope(decided ? { ...detail, status: "APPROVED" } : detail));
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

describe("approval screens", () => {
  it("renders the approval queue and links to its explanation", async () => {
    installFetch();
    renderApp("/demo/approvals");

    expect(await screen.findByRole("heading", { name: "검토·승인" })).toBeVisible();
    expect(screen.getByText("광주 북구 공장 화재 대응안")).toBeVisible();
    expect(screen.getByText("근거 부족")).toBeVisible();
    expect(screen.getByRole("link", { name: "설명 확인" })).toHaveAttribute(
      "href",
      `/demo/approvals/${approvalId}`,
    );
  });

  it("requires the evidence warning acknowledgement before approval", async () => {
    installFetch();
    renderApp(`/demo/approvals/${approvalId}`);

    expect(await screen.findByRole("heading", { name: "승인 전 설명 확인" })).toBeVisible();
    expect(screen.getByText("현장 전원 차단 상태 확인")).toBeVisible();
    expect(screen.getByText("외부 영향: 없음 · 외부 연락·문서 발송 자동 실행 안 함")).toBeVisible();

    const approve = screen.getByRole("button", { name: "승인하고 과업 생성" });
    await userEvent.type(screen.getByLabelText("결정 사유"), "현장 확인 과업을 진행합니다.");
    expect(approve).toBeDisabled();

    await userEvent.click(
      screen.getByRole("checkbox", {
        name: "근거 부족·충돌 경고와 실행 범위를 확인했습니다.",
      }),
    );
    expect(approve).toBeEnabled();
    await userEvent.click(approve);

    expect(await screen.findByText("승인 결정 완료")).toBeVisible();
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining(`/approvals/${approvalId}/decision`),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          expectedVersion: 1,
          decision: "APPROVED",
          reason: "현장 확인 과업을 진행합니다.",
          warningAcknowledged: true,
        }),
      }),
    );
    expect(screen.getByRole("link", { name: "생성된 수행과업 열기" })).toHaveAttribute(
      "href",
      `/demo/cases/${caseId}/tasks`,
    );
  });
});
