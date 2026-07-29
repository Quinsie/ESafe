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
function regionDetailEnvelope() {
  return envelope({
    regionCode: "29170",
    level: "SIGUNGU",
    name: "북구",
    fullName: "광주광역시 북구",
    parent: { regionCode: "29", fullName: "광주광역시" },
    center: [126.91, 35.19],
    bounds: [126.7, 35.0, 127.1, 35.3],
    riskReference: {
      referenceMonth: "2026-03",
      horizonDays: 60,
      lineageVersion: "v27.1-focus-2026-03-60d",
      isProbability: false,
      calculatedAt: "2026-07-29T00:00:00Z",
    },
    distribution: {
      buildingCount: 27585,
      top10Count: 5953,
      bands: { top1: 563, high1To10: 5390, watch10To25: 4100, general: 17532 },
      bandShares: { top1: 2.04, high1To10: 19.54, watch10To25: 14.86, general: 63.56 },
      scoreStats: { minimum: 0.1, median: 0.5, p90: 0.8, p99: 0.969365, maximum: 0.99 },
    },
    currentSignals: { activeCaseCount: 0, urgentCaseCount: 0, hasCurrentSignal: false },
    topBuildings: [
      {
        buildingId: "00000000-0000-4000-8000-000000000001",
        name: "문흥동 공간아파트",
        roadAddress: "광주광역시 북구 문흥동 996-2",
        lotAddress: "광주광역시 북구 문흥동 996-2",
        risk: { finalScore: 0.99, regionalRank: 1, topPercentile: 0.01, riskBand: "TOP_1" },
      },
    ],
  });
}

function buildingDetailEnvelope() {
  return envelope({
    buildingId: "00000000-0000-4000-8000-000000000001",
    sourceBuildingKey: "30104609",
    region: { regionCode: "29170", fullName: "광주광역시 북구" },
    name: "문흥동 공간아파트",
    roadAddress: "광주광역시 북구 문흥동 996-2",
    lotAddress: "광주광역시 북구 문흥동 996-2",
    center: [126.91, 35.19],
    geometryStatus: "MATCHED",
    attributes: {
      mainUseName: "공동주택",
      mainStructure: "철근콘크리트",
      buildingYear: 1998,
      buildingAge: 28,
      approvalDate: "1998-05-01",
      floorsAbove: 15,
      floorsBelow: 1,
      grossFloorAreaM2: 12345.6,
      landUseName: "제2종일반주거지역",
      registerType: "일반건축물",
    },
    facilitySummary: {
      linkedFacilityCount: 3,
      generalCount: 2,
      selfCount: 1,
      latestInspectionDate: "2026-05-10",
      candidateSourceCount: 4,
    },
    risk: {
      finalScore: 0.99,
      regionalRank: 1,
      topPercentile: 0.01,
      riskBand: "TOP_1",
      sourceClass: "ORIG",
      manifestHash: "abcdef0123456789abcdef0123456789",
    },
    currentSignals: { activeCaseCount: 0, urgentCaseCount: 0, hasCurrentSignal: false },
    quality: { buildingFlags: [], riskFlags: [] },
  });
}

function demoScenariosEnvelope() {
  return envelope({
    items: [
      {
        scenarioId: "89ec1b9e-6dc2-5f49-95bf-971098c85101",
        code: "DS-01",
        name: "화재 전체 여정",
        description: "원천 화재부터 종료까지 재현합니다.",
        scenarioVersion: 1,
        stepCount: 3,
        steps: [
          {
            ordinal: 1,
            label: "광주 건물화재 신규 감지",
            source: "NFDS",
            sourceTime: "2026-07-29T10:00:00+09:00",
            kind: "FIXTURE",
          },
          {
            ordinal: 2,
            label: "동일 화재 대응상태 갱신",
            source: "NFDS",
            sourceTime: "2026-07-29T10:12:00+09:00",
            kind: "FIXTURE",
          },
          {
            ordinal: 3,
            label: "화재 원천 종료",
            source: "NFDS",
            sourceTime: "2026-07-29T11:05:00+09:00",
            kind: "FIXTURE",
          },
        ],
        playback: null,
      },
    ],
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
      if (url.endsWith("/demo/scenarios")) {
        return response(demoScenariosEnvelope());
      }
      if (url.endsWith("/tasks/summary")) {
        return response(tasksEnvelope());
      }
      if (url.endsWith("/sources/health")) {
        return response(sourceEnvelope());
      }
      if (url.endsWith("/regions/29170")) {
        return response(regionDetailEnvelope());
      }
      if (url.endsWith("/buildings/00000000-0000-4000-8000-000000000001")) {
        return response(buildingDetailEnvelope());
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
    expect(screen.getAllByText("체험 데이터").length).toBeGreaterThan(0);
    expect(await screen.findByText("데이터 정상")).toBeVisible();
    expect(screen.getByText("217,238개", { exact: false })).toBeVisible();
    const priorityPanel = screen
      .getByRole("heading", { name: "우선 확인이 필요한 지역" })
      .closest("section");
    expect(priorityPanel).not.toBeNull();
    expect(within(priorityPanel as HTMLElement).getByText("북구")).toBeVisible();
  });

  it("keeps the LIVE-shaped home and exposes DEMO controls in the sidebar", async () => {
    installAuthenticatedFetch();
    renderApp();

    expect(await screen.findByRole("heading", { name: "오늘의 상황 브리핑" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "실시간 상황 시나리오" })).not.toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "체험 시나리오 리모컨" })).toBeVisible();
    expect(screen.getByText("체험 리모컨")).toBeVisible();
    expect(screen.getByRole("link", { name: "체험 시나리오" })).toBeVisible();
    expect(screen.getByRole("button", { name: "시작" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "다음 단계" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "초기화" })).toBeEnabled();
  });

  it("opens scenario descriptions in the dedicated DEMO route", async () => {
    installAuthenticatedFetch();
    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("link", { name: "체험 시나리오" }));

    expect(await screen.findByRole("heading", { name: "체험 시나리오" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "화재 전체 여정" })).toBeVisible();
    expect(screen.getByText("광주 건물화재 신규 감지")).toBeVisible();
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

    expect(await screen.findByRole("heading", { name: /전기재해 위험을/ })).toBeVisible();
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

  it("renders REG-01C from the actual region contract without probability claims", async () => {
    installAuthenticatedFetch();
    renderApp("/demo/regions/29170");

    expect(await screen.findByRole("heading", { name: "지역 상세" })).toBeVisible();
    expect(screen.getByText("광주광역시 북구")).toBeVisible();
    expect(screen.getAllByText("27,585개").length).toBeGreaterThan(0);
    expect(screen.getAllByText("0.969365").length).toBeGreaterThan(0);
    expect(screen.getByText("문흥동 공간아파트")).toBeVisible();
    expect(screen.getAllByText("발생확률 아님").length).toBeGreaterThan(0);
  });

  it("renders REG-01B from the actual building and facility contract", async () => {
    installAuthenticatedFetch();
    renderApp("/demo/buildings/00000000-0000-4000-8000-000000000001");

    expect(await screen.findByRole("heading", { name: "건물 상세" })).toBeVisible();
    expect(screen.getAllByText("문흥동 공간아파트").length).toBeGreaterThan(0);
    expect(screen.getByText("최상위 위험")).toBeVisible();
    expect(screen.getByText("철근콘크리트")).toBeVisible();
    expect(screen.getByText("3건")).toBeVisible();
    expect(screen.getByText("건물·위험도 기준 데이터에 별도 품질 경고가 없습니다.")).toBeVisible();
  });

  it("renders REG-02B with actual regional facts and an evidence warning", async () => {
    installAuthenticatedFetch();
    renderApp("/demo/regions/29170/report");

    expect(await screen.findByRole("heading", { name: "지역 분석 보고서" })).toBeVisible();
    expect(screen.getByText("광주광역시 북구 전기재해 예방 위험 분석 보고서")).toBeVisible();
    expect(screen.getAllByText("27,585개").length).toBeGreaterThan(0);
    expect(screen.getByText("근거 부족 · 검토 필요")).toBeVisible();
    expect(screen.getByText("HWPX + PDF")).toBeVisible();
    expect(screen.getAllByText("미입력").length).toBe(3);
    expect(screen.getByRole("link", { name: "Case에서 문서 초안 만들기" })).toBeVisible();
    expect(screen.queryByText(/S7 문서 흐름/)).toBeNull();
  });

  it("renders BLD-02 without inventing inspection history or citations", async () => {
    installAuthenticatedFetch();
    renderApp("/demo/buildings/00000000-0000-4000-8000-000000000001/report");

    expect(await screen.findByRole("heading", { name: "건물 분석 보고서" })).toBeVisible();
    expect(screen.getByText("문흥동 공간아파트 전기재해 예방 위험 분석 보고서")).toBeVisible();
    expect(screen.getByText("광주·전남 순위")).toBeVisible();
    expect(screen.getByText(/최근 등록 점검일 2026-05-10/)).toBeVisible();
    expect(screen.getByText(/공식 매뉴얼·과거 사고 인용이 아직 연결되지 않아/)).toBeVisible();
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
