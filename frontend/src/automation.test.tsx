import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { resolveProfile } from "./profile";

function response(data: unknown): Response {
  return { ok: true, status: 200, json: async () => data } as Response;
}

function envelope(data: unknown) {
  return {
    data,
    meta: {
      requestId: "00000000-0000-4000-8000-000000000000",
      profile: "DEMO",
      asOf: "2026-07-29T03:00:00Z",
    },
    error: null,
  };
}

const activity = {
  summary: {
    todayActivity: 12,
    waitingApproval: 2,
    running: 1,
    failedLast24h: 0,
  },
  items: [
    {
      occurredAt: "2026-07-29T02:30:00Z",
      entryType: "AUTOMATION_RUN",
      entryId: "00000000-0000-4000-8000-000000000801",
      status: "SUCCEEDED",
      category: "SIGNAL_POLL",
      triggerType: "SCHEDULED",
      source: "NFDS",
      actor: { type: "SYSTEM", displayName: null },
      case: {
        caseId: "00000000-0000-4000-8000-000000000301",
        caseNumber: "ES-20260729-000001",
      },
      workItem: null,
      run: {
        ruleVersion: "signal-poll-v1",
        inputVersion: null,
        outputVersion: "response-v1",
        retryCount: 0,
        errorClass: null,
        finishedAt: "2026-07-29T02:30:02Z",
      },
    },
  ],
  page: 1,
  pageSize: 20,
  total: 1,
  dataAsOf: "2026-07-29T02:30:02Z",
};

const policies = {
  policyVersion: "automation-policy-v1",
  mutable: false,
  profile: "DEMO",
  scope: {
    regions: [
      { regionCode: "29", name: "광주광역시" },
      { regionCode: "46", name: "전라남도" },
    ],
    weatherWarningTypes: "ALL",
    disasterMessageFilter: "ELECTRICAL_AND_NATURAL_HAZARD_V1",
  },
  schedule: {
    pollIntervalMinutes: 10,
    jitterSeconds: { minimum: 0, maximum: 60 },
    caseReflectionTargetMinutes: 2,
    delayedAfterMinutes: 30,
    outageAfterMinutes: 60,
  },
  sources: [
    { source: "NFDS", enabled: true, mode: "FIXTURE" },
    { source: "KMA_WARNING", enabled: true, mode: "FIXTURE" },
    { source: "DISASTER_MESSAGE", enabled: true, mode: "FIXTURE" },
  ],
  deterministicRules: {
    sameSourceUpdate: true,
    crossSourceFireWindowHours: 2,
    crossSourceFireDistanceM: 500,
    pointImpactDefaultRadiusM: 1000,
    allowedImpactRadiusM: [500, 1000, 3000, 5000],
    weatherImpactScope: "ADMIN_REGION",
    highRiskTopPercentile: 10,
    automaticMergeByLlm: false,
  },
  approvalBoundary: {
    singleUserSingleStage: true,
    decisions: ["APPROVED", "ON_HOLD", "DISCARDED"],
    externalEffectWithoutApproval: false,
    actualEmailOrOfficialDispatch: false,
    sourceResolvedRequiresUserClose: true,
  },
  retry: {
    sourceSchemaBackoffMinutes: [20, 40, 80],
    automaticAiRetries: 1,
    externalEffectRetries: 0,
  },
  capabilities: [
    {
      code: "SIGNAL_INGESTION",
      label: "외부 신호 수집·원문 보존",
      status: "ACTIVE",
    },
    {
      code: "CASE_IMPACT",
      label: "Case 영향 범위·건물 계산",
      status: "READY_NOT_CONNECTED",
    },
    {
      code: "DOCUMENT_OUTPUT",
      label: "HWPX·PDF 생성",
      status: "NOT_IMPLEMENTED",
    },
  ],
};

function installFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
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
      if (url.includes("/automation/runs?")) {
        return response(envelope(activity));
      }
      if (url.endsWith("/automation/policies")) {
        return response(envelope(policies));
      }
      throw new Error(`unexpected request: ${url}`);
    }),
  );
}

function renderApp(pathname: string) {
  window.history.replaceState({}, "", pathname);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
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

describe("automation screens", () => {
  it("renders AUT-01B from sanitized run and audit contracts", async () => {
    installFetch();
    renderApp("/demo/automation/runs");

    expect(await screen.findByRole("heading", { name: "자동화 실행·감사 기록" })).toBeVisible();
    expect(await screen.findByText("12")).toBeVisible();
    expect(screen.getAllByText("신호 수집").length).toBeGreaterThan(0);
    expect(screen.getAllByText("전국119상황실").length).toBeGreaterThan(0);
    expect(screen.getByText("signal-poll-v1")).toBeVisible();
    expect(screen.getByRole("link", { name: "ES-20260729-000001 보기" })).toHaveAttribute(
      "href",
      "/demo/cases/00000000-0000-4000-8000-000000000301",
    );
  });

  it("renders AUT-02B as a read-only truthful policy view", async () => {
    installFetch();
    renderApp("/demo/automation/policies");

    expect(await screen.findByRole("heading", { name: "자동화 운영 정책" })).toBeVisible();
    expect(await screen.findByText("읽기 전용 운영 계약")).toBeVisible();
    expect(screen.getAllByText("체험 데이터").length).toBeGreaterThan(0);
    expect(screen.getByText("준비됨 · 연결 전")).toBeVisible();
    expect(screen.getByText("미구현")).toBeVisible();
    expect(screen.queryByRole("button", { name: /저장|적용|변경/ })).not.toBeInTheDocument();
  });
});
