import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { resolveProfile } from "./profile";

const incidentId = "00000000-0000-4000-8000-000000000101";
const buildingId = "00000000-0000-4000-8000-000000000201";

function response(data: unknown): Response {
  return { ok: true, status: 200, json: async () => data } as Response;
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

const incident = {
  incidentId,
  reportedOn: "2025-08-10",
  title: "전남 나주시 공장 전기화재 사고",
  sourceFamily: "GENERAL",
  incidentType: "화재",
  region: { sidoName: "전라남도", sigunguName: "나주시" },
  facilityType: "공장",
  causeCategories: ["전기적 요인"],
  damageCategories: ["재산피해 보고"],
  actionCategories: ["현장 확인"],
  equipmentCategories: ["배전반"],
  evidenceQuality: {
    status: "DERIVED_STRUCTURED",
    label: "파생정보 구조화",
    historicalExampleOnly: true,
    qualityFlags: [],
  },
  conditionMatch: null,
};

const conditionMatch = {
  score: 100,
  isProbability: false,
  components: [
    {
      code: "FACILITY_USE",
      label: "시설 용도 조건",
      points: 60,
      maximum: 60,
      detail: "사례·건물 용도 분류 일치: 공장",
    },
    {
      code: "GEOGRAPHY",
      label: "지역 조건",
      points: 40,
      maximum: 40,
      detail: "같은 시·군·구",
    },
  ],
};

const candidate = {
  buildingId,
  name: "나주 혁신산단 제1공장",
  roadAddress: "전라남도 나주시 혁신산단로 1",
  lotAddress: "전라남도 나주시 빛가람동 1",
  region: { regionCode: "46170", fullName: "전라남도 나주시" },
  center: [126.71, 35.02],
  attributes: { mainUseName: "공장", mainStructure: "철골조", buildingYear: "2004" },
  conditionMatch,
  risk: {
    finalScore: 0.978,
    regionalRank: 12,
    topPercentile: 0.1,
    riskBand: "TOP_1",
    isProbability: false,
  },
  inspectionPriority: { level: "URGENT", basis: "기준 위험구간과 조건 정합도를 분리해 표시" },
  facilitySummary: { linkedFacilityCount: 2, latestInspectionDate: "2026-05-20" },
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
      if (url.endsWith("/map/regions")) {
        return response(
          envelope({ features: [{ properties: { regionCode: "46", fullName: "전라남도" } }] }),
        );
      }
      if (url.includes("parentCode=29")) return response(envelope({ features: [] }));
      if (url.includes("parentCode=46")) {
        return response(
          envelope({
            features: [{ properties: { regionCode: "46170", fullName: "전라남도 나주시" } }],
          }),
        );
      }
      if (url.includes("/similar/incidents?")) {
        return response(
          envelope({
            items: [incident],
            pagination: { page: 1, pageSize: 20, total: 197, totalPages: 10 },
            selection: { explicitRegion: null, case: null, building: null },
          }),
        );
      }
      if (url.includes("/similar/facilities?")) {
        return response(
          envelope({
            referenceIncident: incident,
            items: [candidate],
            pagination: { page: 1, pageSize: 20, total: 217238, totalPages: 10862 },
            ordering: ["조건 정합도 높은 순", "광주·전남 위험순위 높은 순", "건물 ID"],
          }),
        );
      }
      if (url.includes("/similar/compare?")) {
        return response(
          envelope({
            referenceIncident: incident,
            candidateBuilding: candidate,
            conditionMatch,
            inspectionPriority: {
              level: "URGENT",
              riskBand: "TOP_1",
              separateFromConditionMatch: true,
            },
            inspectionChecklist: [
              {
                code: "CHECK_FIRE",
                label: "배전반 과열 흔적 확인",
                basis: "과거 사례의 설비 분류",
              },
            ],
            evidence: {
              status: "INSUFFICIENT",
              warning: "공식 현행 근거가 아직 연결되지 않았습니다.",
              historicalExampleOnly: true,
              requiresOfficialEvidence: true,
            },
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

describe("similarity analysis screens", () => {
  it("renders SIM-01B from de-identified historical incident facts", async () => {
    installFetch();
    renderApp("/demo/similar/incidents");

    expect(await screen.findByRole("heading", { name: "과거 사고사례 검색" })).toBeVisible();
    expect((await screen.findAllByText("전남 나주시 공장 전기화재 사고")).length).toBeGreaterThan(
      0,
    );
    expect(screen.getByText("검색 결과 197건")).toBeVisible();
    expect(screen.getByText("과거 사례 참고")).toBeVisible();
    expect(screen.getByText("조건 정합도 · 발생확률 아님")).toBeVisible();
  });

  it("renders SIM-02B with actual candidate count, coordinates fallback, and separate risk", async () => {
    installFetch();
    renderApp(`/demo/similar/facilities?referenceIncident=${incidentId}`);

    expect(await screen.findByRole("heading", { name: "유사 위험시설 탐색 결과" })).toBeVisible();
    expect(screen.getByText("후보 217,238개 · 실제 건물")).toBeVisible();
    expect(screen.getByText("나주 혁신산단 제1공장")).toBeVisible();
    expect(screen.getByText("최상위 위험 · 12위")).toBeVisible();
    expect(
      screen.getByText("브라우저 지도 대신 오른쪽 실제 후보 목록을 사용합니다."),
    ).toBeVisible();
  });

  it("renders SIM-03B without conflating condition match and probability", async () => {
    installFetch();
    renderApp(
      `/demo/similar/compare?referenceIncident=${incidentId}&candidateBuilding=${buildingId}`,
    );

    expect(
      await screen.findByRole("heading", { name: "기준 사고사례와 후보 시설 비교" }),
    ).toBeVisible();
    expect(screen.getAllByText("조건 정합도 100점").length).toBeGreaterThan(0);
    expect(screen.getByText("발생확률 아님")).toBeVisible();
    expect(screen.getByText("근거 부족 · 검토 필요")).toBeVisible();
    expect(screen.getByText("배전반 과열 흔적 확인")).toBeVisible();
  });
});
