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

function mapConfigEnvelope() {
  return envelope({
    providers: [
      {
        id: "osm",
        name: "OpenStreetMap",
        urlTemplate: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        attribution: "© OpenStreetMap contributors",
        priority: 2,
      },
    ],
    preferredProvider: "osm",
    fallbackActive: true,
    fallbackReason: "VWORLD_NOT_CONFIGURED",
    buildingZoom: { minimum: 14, maximum: 20 },
  });
}

function mapRegionsEnvelope(level: "SIDO" | "SIGUNGU" = "SIDO") {
  const features =
    level === "SIDO"
      ? [
          ["29", "광주광역시", 113000, 1130, 12000, [126.83, 35.15]],
          ["46", "전라남도", 104238, 1043, 9724, [126.4, 34.64]],
        ]
      : [["29170", "광주광역시 북구", 27585, 563, 5953, [126.91, 35.19]]];
  return envelope({
    type: "FeatureCollection",
    riskReference: {
      referenceMonth: "2026-03",
      horizonDays: 60,
      lineageVersion: "v27.1-focus-2026-03-60d",
      isProbability: false,
    },
    features: features.map(([code, name, count, top1, top10, center]) => ({
      type: "Feature",
      id: code,
      bbox: [126, 34, 127, 36],
      geometry: {
        type: "MultiPolygon",
        coordinates: [
          [
            [
              [126, 34],
              [127, 34],
              [127, 36],
              [126, 34],
            ],
          ],
        ],
      },
      properties: {
        regionCode: code,
        level,
        name,
        fullName: name,
        parentCode: level === "SIGUNGU" ? "29" : null,
        center,
        buildingCount: count,
        top1Count: top1,
        top10Count: top10,
        riskBands: { top1, high1To10: top10, watch10To25: 0, general: 0 },
        scoreMedian: 0.5,
        scoreP90: 0.8,
        scoreP99: 0.9,
        scoreMax: 0.97,
        activeCaseCount: 0,
        urgentCaseCount: 0,
        hasCurrentSignal: false,
      },
    })),
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
      if (url.endsWith("/map/config")) {
        return response(mapConfigEnvelope());
      }
      if (url.endsWith("/map/regions")) {
        return response(mapRegionsEnvelope());
      }
      if (url.includes("/map/districts")) {
        return response(mapRegionsEnvelope("SIGUNGU"));
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
      if (url.endsWith("/map/config")) {
        return response(mapConfigEnvelope());
      }
      if (url.endsWith("/map/regions")) {
        return response(mapRegionsEnvelope());
      }
      if (url.includes("/map/districts")) {
        return response(mapRegionsEnvelope("SIGUNGU"));
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

    expect(await screen.findByRole("heading", { name: "통합 위험지도" })).toBeVisible();
    expect(window.location.pathname).toBe("/demo/map");
    expect(window.location.search).toBe("?zoom=7&region=29");
    expect(fetchMock).toHaveBeenCalledWith(
      "/demo/api/v1/auth/login",
      expect.objectContaining({ credentials: "include", method: "POST" }),
    );
  });

  it("renders actual spatial map contracts instead of an unfinished route", async () => {
    installAuthenticatedFetch();
    renderApp("/demo/map");

    expect(await screen.findByRole("heading", { name: "통합 위험지도" })).toBeVisible();
    expect(
      screen.getByText("지도 렌더링을 지원하지 않는 환경입니다.", { exact: false }),
    ).toBeVisible();
    expect(await screen.findByText("광주광역시")).toBeVisible();
    expect(screen.queryByText("완료되지 않은 행동을 실제 기능처럼 표시하지 않습니다.")).toBeNull();
  });
});
