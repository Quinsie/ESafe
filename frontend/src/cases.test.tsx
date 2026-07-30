import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { resolveProfile } from "./profile";

const caseId = "00000000-0000-4000-8000-000000000301";
const buildingId = "00000000-0000-4000-8000-000000000401";
const signalId = "00000000-0000-4000-8000-000000000501";

function response(data: unknown): Response {
  return { ok: true, status: 200, json: async () => data } as Response;
}

function envelope(data: unknown) {
  return {
    data,
    meta: {
      requestId: "00000000-0000-4000-8000-000000000000",
      profile: "DEMO",
      asOf: "2026-07-29T02:00:00Z",
    },
    error: null,
  };
}

const caseItem = {
  caseId,
  caseNumber: "ES-20260729-000001",
  caseType: "FIRE",
  title: "광주 북구 공장 화재 출동",
  status: "ACTIVE",
  sourceStatus: "ACTIVE",
  monitoringPriority: "URGENT",
  primaryRegion: {
    regionCode: "29170",
    name: "북구",
    fullName: "광주광역시 북구",
  },
  locationPrecision: "ADDRESS",
  sources: ["NFDS"],
  signalCount: 1,
  impactBuildingCount: 905,
  highRiskBuildingCount: 88,
  incidentBuildingCount: 1,
  openWorkItemCount: 0,
  relationCandidateCount: 0,
  openedAt: "2026-07-29T01:10:00Z",
  updatedAt: "2026-07-29T01:20:00Z",
  sourceResolvedAt: null,
  isSimulated: true,
  scenarioId: "DEMO-FIRE-01",
  version: 1,
};

const signal = {
  signalEventId: signalId,
  source: "NFDS",
  externalId: "NFDS-20260729-001",
  eventType: "FIRE",
  eventSubtype: "공장",
  severity: "UNKNOWN",
  sourceStatus: "ACTIVE",
  title: "광주 북구 공장 화재 출동",
  summary: "소방 출동 신호",
  sourcePublishedAt: "2026-07-29T01:10:00Z",
  effectiveAt: "2026-07-29T01:10:00Z",
  expiresAt: null,
  address: "광주광역시 북구 첨단과기로 1",
  regionCodes: ["29170"],
  regionNames: ["광주광역시 북구"],
  locationPrecision: "ADDRESS",
  isRelevant: true,
  version: 1,
  updatedAt: "2026-07-29T01:20:00Z",
  linkType: "PRIMARY",
};

const caseDetail = {
  ...caseItem,
  normalizedAddress: "광주광역시 북구 첨단과기로 1",
  location: { type: "Point", coordinates: [126.86, 35.22] },
  closeReason: null,
  closedAt: null,
  impactScope: {
    impactScopeId: "00000000-0000-4000-8000-000000000601",
    scopeType: "RADIUS",
    center: { type: "Point", coordinates: [126.86, 35.22] },
    radiusM: 100,
    regionCodes: ["29170"],
    precisionWarning: null,
    ruleVersion: "case-impact-v3-fire-building-100m",
    calculatedAt: "2026-07-29T01:20:00Z",
  },
  workItemCount: 0,
  signals: [signal],
  relations: [],
  riskReference: {
    referenceMonth: "2026-03",
    horizonDays: 60,
    lineageVersion: "v27.1",
    isProbability: false,
  },
};

const impact = {
  summary: {
    impactBuildings: 2,
    highRiskBuildings: 2,
    incidentBuildings: 1,
  },
  scope: {
    impactScopeId: "00000000-0000-4000-8000-000000000601",
    scopeType: "RADIUS",
    radiusM: 100,
    regionCodes: ["29170"],
    precisionWarning: null,
  },
  items: [
    {
      buildingId,
      sourceBuildingKey: "BLDG-001",
      regionCode: "29170",
      name: "첨단산단 제1공장",
      roadAddress: "광주광역시 북구 첨단과기로 1",
      lotAddress: "광주광역시 북구 오룡동 1",
      centroid: [126.86, 35.22],
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [126.8599, 35.2199],
            [126.8601, 35.2199],
            [126.8601, 35.2201],
            [126.8599, 35.2201],
            [126.8599, 35.2199],
          ],
        ],
      },
      matchReason: "EXACT",
      distanceM: 0,
      isIncidentBuilding: true,
      isHighRisk: true,
      priorityOrder: 1,
      risk: {
        referenceMonth: "2026-03",
        horizonDays: 60,
        finalScore: 0.921,
        regionalRank: 612,
        topPercentile: 0.28,
        riskBand: "TOP_1",
        lineageVersion: "v27.1",
        isProbability: false,
      },
    },
    {
      buildingId: "00000000-0000-4000-8000-000000000402",
      sourceBuildingKey: "BLDG-002",
      regionCode: "29170",
      name: "첨단산단 제2공장",
      roadAddress: "광주광역시 북구 첨단과기로 3",
      lotAddress: "광주광역시 북구 오룡동 2",
      centroid: [126.861, 35.221],
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [126.8608, 35.2208],
            [126.8612, 35.2208],
            [126.8612, 35.2212],
            [126.8608, 35.2212],
            [126.8608, 35.2208],
          ],
        ],
      },
      matchReason: "RADIUS",
      distanceM: 40,
      isIncidentBuilding: false,
      isHighRisk: true,
      priorityOrder: 2,
      risk: {
        referenceMonth: "2026-03",
        horizonDays: 60,
        finalScore: 0.88,
        regionalRank: 1800,
        topPercentile: 0.83,
        riskBand: "TOP_1",
        lineageVersion: "v27.1",
        isProbability: false,
      },
    },
  ],
  filters: {
    riskThreshold: null,
    incidentOnly: false,
    search: null,
    sort: "distance",
  },
  page: 1,
  pageSize: 100,
  total: 2,
};

const timeline = {
  items: [
    {
      occurredAt: "2026-07-29T01:10:00Z",
      entryType: "SIGNAL_RAW",
      entryId: "00000000-0000-4000-8000-000000000701",
      category: "NFDS",
      title: "원천 응답 수신",
      detail: { rawPayloadHash: "sha256:test", rawPayloadVersion: 1 },
    },
    {
      occurredAt: "2026-07-29T01:20:00Z",
      entryType: "AUDIT",
      entryId: "00000000-0000-4000-8000-000000000702",
      category: "CASE_CREATED",
      title: "Case 생성",
      detail: { version: 1 },
    },
  ],
  page: 1,
  pageSize: 20,
  total: 2,
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
      if (url.endsWith("/map/config")) {
        return response(
          envelope({
            providers: [
              {
                id: "osm",
                name: "OpenStreetMap",
                urlTemplate: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                attribution: "© OpenStreetMap contributors",
              },
            ],
            preferredProvider: "osm",
          }),
        );
      }
      if (url.includes(`/cases/${caseId}/impact-buildings?`)) {
        return response(envelope(impact));
      }
      if (url.includes(`/cases/${caseId}/timeline?`)) {
        return response(envelope(timeline));
      }
      if (url.endsWith(`/cases/${caseId}`)) {
        return response(envelope(caseDetail));
      }
      if (url.includes("/cases?")) {
        return response(
          envelope({
            summary: {
              total: 1,
              open: 1,
              sourceResolvedReview: 0,
              urgent: 1,
              simulated: 1,
            },
            items: [caseItem],
            page: 1,
            pageSize: 20,
            total: 1,
            dataAsOf: "2026-07-29T01:20:00Z",
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

describe("case management screens", () => {
  it("renders INC-01B from paginated Case data and opens a truthful preview", async () => {
    installFetch();
    renderApp("/demo/cases");

    expect(await screen.findByRole("heading", { name: "자동 감지 재난 신호" })).toBeVisible();
    expect((await screen.findAllByText("광주 북구 공장 화재 출동")).length).toBeGreaterThan(0);
    expect(screen.getByText("검색 결과 1건")).toBeVisible();
    expect(screen.getAllByText("905개").length).toBeGreaterThan(0);
    expect(screen.getByText("고위험 88")).toBeVisible();
    expect(screen.getByRole("link", { name: "Case 통합 상황판 열기" })).toHaveAttribute(
      "href",
      `/demo/cases/${caseId}`,
    );
  });

  it("renders INC-02B with real impact, source, and timeline contracts", async () => {
    installFetch();
    renderApp(`/demo/cases/${caseId}`);

    expect(await screen.findByRole("heading", { name: "광주 북구 공장 화재 출동" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "사건 위치·영향 건물" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "화재 주변 건물" })).toBeVisible();
    expect(screen.getByText("첨단산단 제1공장")).toBeVisible();
    expect(screen.getByText("100m 주변 건물")).toBeVisible();
    expect(screen.getByText("반경 100m · 전체")).toBeVisible();
    expect(screen.getByText("원천 응답 수신")).toBeVisible();
    expect(
      screen.getByText("브라우저 지도 대신 오른쪽의 100m 이내 건물 목록을 사용합니다."),
    ).toBeVisible();
    expect(screen.getByText(/final_score는 발생확률이 아닙니다/)).toBeVisible();
    expect(screen.getByRole("link", { name: "근거 기반 대응 절차" })).toHaveAttribute(
      "href",
      `/demo/cases/${caseId}/evidence`,
    );
    expect(screen.getByRole("link", { name: "단계별 수행과업" })).toHaveAttribute(
      "href",
      `/demo/cases/${caseId}/tasks`,
    );
    expect(screen.getByRole("link", { name: "상황 종료 검토" })).toHaveAttribute(
      "href",
      `/demo/cases/${caseId}/close`,
    );
  });
});
