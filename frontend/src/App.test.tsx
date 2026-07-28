import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { resolveProfile } from "./profile";

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
      asOf: "2026-07-29T00:00:00Z",
    },
    error: null,
  };
}

function sessionEnvelope() {
  return envelope({
    user: { userId: "user", displayName: "사용자" },
    expiresAt: "2026-07-29T12:00:00Z",
  });
}

function sourceEnvelope() {
  return envelope({
    summary: "HEALTHY",
    dataAsOf: "2026-07-29T00:00:00Z",
    sources: [
      {
        source: "NFDS",
        executionMode: "FIXTURE",
        enabled: true,
        status: "HEALTHY",
        lastAttemptAt: "2026-07-29T00:00:00Z",
        lastSuccessAt: "2026-07-29T00:00:00Z",
        lastFailureAt: null,
        consecutiveFailures: 0,
        nextPollAt: null,
        backoffUntil: null,
        parserVersion: "test",
        contractVersion: "test",
        updatedAt: "2026-07-29T00:00:00Z",
      },
    ],
  });
}

function briefingEnvelope() {
  return envelope({
    headline: {
      state: "NO_ACTIVE_CASES",
      title: "현재 확인된 광주·전남 관제 Case가 없습니다.",
      description: "수집원 상태를 함께 확인하세요.",
      caseId: null,
    },
    metrics: {
      urgentCases: 0,
      activeCases: 0,
      dueWithin24Hours: 0,
      waitingApproval: 0,
      sourceResolvedReview: 0,
    },
    riskReference: {
      importId: "test",
      sourceVersion: "test",
      lineageVersion: "v27.1-focus-2026-03-60d",
      referenceMonth: "2026-03",
      horizonDays: 60,
      buildingCount: 217238,
      top1Count: 2173,
      top10Count: 21724,
      calculatedAt: "2026-07-29T00:00:00Z",
    },
    priorityRegions: [
      {
        regionCode: "29170",
        name: "북구",
        fullName: "광주광역시 북구",
        buildingCount: 27585,
        top1Count: 563,
        top10Count: 5953,
        top10Share: 21.58,
        scoreP99: 0.969365,
      },
    ],
    recentCases: [],
    dataAsOf: "2026-07-29T00:00:00Z",
  });
}

function tasksEnvelope() {
  return envelope({
    counts: { queued: 0, running: 0, waitingApproval: 0, onHold: 0, failed: 0 },
    items: [],
    dataAsOf: null,
  });
}

function installAuthenticatedFetch(failedEndpoint?: string) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/auth/session")) {
        return response(sessionEnvelope());
      }
      if (failedEndpoint && url.endsWith(failedEndpoint)) {
        return response(
          { data: null, error: { code: "PANEL_FAILED", message: "패널 점검 필요" } },
          503,
        );
      }
      if (url.endsWith("/briefing")) {
        return response(briefingEnvelope());
      }
      if (url.endsWith("/tasks/summary")) {
        return response(tasksEnvelope());
      }
      if (url.endsWith("/sources/health")) {
        return response(sourceEnvelope());
      }
      throw new Error(`unexpected request: ${url}`);
    }),
  );
}

function renderApp(pathname = "/demo/home") {
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

describe("App authentication boundary", () => {
  it("renders actual H-01D panels only after session validation", async () => {
    installAuthenticatedFetch();
    renderApp();

    expect(screen.getByText("세션을 확인하고 있습니다.")).toBeVisible();
    expect(await screen.findByRole("heading", { name: "오늘의 상황 브리핑" })).toBeVisible();
    expect(screen.getByText("체험 데이터")).toBeVisible();
    expect(await screen.findByText("데이터 정상")).toBeVisible();
    expect(screen.getByText("217,238개", { exact: false })).toBeVisible();
    const priorityPanel = screen
      .getByRole("heading", { name: "우선 확인이 필요한 지역" })
      .closest("section");
    expect(priorityPanel).not.toBeNull();
    expect(within(priorityPanel as HTMLElement).getByText("북구")).toBeVisible();
  });

  it("keeps healthy panels visible when the task panel fails", async () => {
    installAuthenticatedFetch("/tasks/summary");
    renderApp();

    expect(await screen.findByText("패널 점검 필요")).toBeVisible();
    expect(screen.getByText("현재 확인된 광주·전남 관제 Case가 없습니다.")).toBeVisible();
    expect(screen.getByText("북구")).toBeVisible();
    expect(screen.getAllByText("데이터 정상").length).toBeGreaterThan(0);
  });

  it("redirects an anonymous route to AUTH-01 and preserves the full return location", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/auth/session")) {
        return response(
          { data: null, error: { code: "AUTH_REQUIRED", message: "로그인이 필요합니다." } },
          401,
        );
      }
      if (url.endsWith("/auth/login")) {
        return response(sessionEnvelope());
      }
      if (url.endsWith("/sources/health")) {
        return response(sourceEnvelope());
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderApp("/demo/map?zoom=7&region=29");

    expect(await screen.findByRole("heading", { name: "로그인·세션 확인" })).toBeVisible();
    await waitFor(() => {
      expect(window.location.pathname).toBe("/demo/login");
      expect(new URLSearchParams(window.location.search).get("returnTo")).toBe(
        "/map?zoom=7&region=29",
      );
    });

    await user.type(screen.getByLabelText("사용자 ID"), "user");
    await user.type(screen.getByLabelText("비밀번호"), "secret");
    await user.click(screen.getByRole("button", { name: "로그인" }));

    expect(await screen.findByRole("heading", { name: "위험 지도" })).toBeVisible();
    expect(window.location.pathname).toBe("/demo/map");
    expect(window.location.search).toBe("?zoom=7&region=29");
    expect(fetchMock).toHaveBeenCalledWith(
      "/demo/api/v1/auth/login",
      expect.objectContaining({ credentials: "include", method: "POST" }),
    );
  });

  it("labels unfinished authenticated routes honestly", async () => {
    installAuthenticatedFetch();
    renderApp("/demo/map");

    expect(await screen.findByRole("heading", { name: "위험 지도" })).toBeVisible();
    expect(screen.getByText("완료되지 않은 행동을 실제 기능처럼 표시하지 않습니다.")).toBeVisible();
  });
});
