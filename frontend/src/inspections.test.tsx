import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { resolveProfile } from "./profile";

const simulationId = "00000000-0000-4000-8000-000000000701";
const scenarioId = "00000000-0000-4000-8000-000000000702";
const approvalId = "00000000-0000-4000-8000-000000000703";
const buildingId = "00000000-0000-4000-8000-000000000704";

function envelope(data: unknown) {
  return {
    data,
    meta: { requestId: "test", profile: "DEMO", asOf: "2026-07-29T00:00:00Z" },
    error: null,
  };
}

function response(data: unknown): Response {
  return { ok: true, status: 200, json: async () => data } as Response;
}

const scenarios = [
  [scenarioId, "BALANCED", 1, 68, 40, 28, 58.8, false, true],
  ["00000000-0000-4000-8000-000000000705", "HIGH_RISK_FOCUSED", 2, 68, 40, 28, 58.8, false, true],
  ["00000000-0000-4000-8000-000000000706", "COVERAGE_EXPANDED", 3, 140, 140, 0, 100, true, false],
].map(([id, type, ordinal, candidates, selected, excluded, coverage, over, confirmable]) => ({
  inspectionScenarioId: id,
  scenarioType: type,
  ordinal,
  status: "CALCULATED",
  candidateCount: candidates,
  selectedCount: selected,
  excludedCount: excluded,
  candidateCoveragePercent: coverage,
  requiredDays: 2,
  overCapacity: over,
  confirmable,
  explanation: {
    strategy: `${type} 결정 규칙`,
    capacityExceededBy: over ? 100 : 0,
    coverageFormula: "selected / candidates * 100",
    appliedFilters: { topPercentile: 10, minimumScore: 0.9 },
  },
  selected: id === scenarioId,
  version: 1,
}));

const simulation = {
  inspectionSimulationId: simulationId,
  status: "CALCULATED",
  version: 2,
  context: {
    regionCode: "46170",
    regionName: "전라남도 나주시",
    buildingId: null,
    buildingLabel: null,
    caseId: null,
    caseNumber: null,
  },
  conditions: {
    facilityTypes: [],
    startDate: "2026-07-29",
    endDate: "2026-07-30",
    inclusiveDayCount: 2,
    teamCount: 2,
    dailyCapacityPerTeam: 10,
    totalCapacity: 40,
    topPercentile: 10,
    minimumScore: 0.9,
    expandedTopPercentile: 25,
    expandedMinimumScore: 0.85,
  },
  riskSnapshot: {
    referenceMonth: "2026-03-01",
    horizonDays: 60,
    lineageVersion: "v27.1-focus-2026-03-60d",
    isProbability: false,
  },
  algorithmVersion: "inspection-v1.0.0",
  selectedScenarioId: scenarioId,
  error: null,
  scenarios,
};

const approvalDetail = {
  approvalRequestId: approvalId,
  caseId: null,
  targetType: "INSPECTION_SCENARIO",
  targetId: scenarioId,
  targetVersion: 1,
  title: "점검계획 확정 · BALANCED · 40개소",
  status: "APPROVAL_PENDING",
  contentSha256: "a".repeat(64),
  contentMatches: true,
  evidenceStatus: null,
  warning: null,
  requestedBy: "사용자",
  requestedAt: "2026-07-29T00:00:00Z",
  decidedAt: null,
  version: 1,
  case: null,
  recommendation: null,
  document: null,
  inspection: {
    inspectionSimulationId: simulationId,
    inspectionScenarioId: scenarioId,
    scenarioType: "BALANCED",
    status: "APPROVAL_PENDING",
    version: 1,
    regionName: "전라남도 나주시",
    startDate: "2026-07-29",
    endDate: "2026-07-30",
    inclusiveDayCount: 2,
    teamCount: 2,
    dailyCapacityPerTeam: 10,
    totalCapacity: 40,
    candidateCount: 68,
    selectedCount: 40,
    excludedCount: 28,
    candidateCoveragePercent: 58.8,
    requiredDays: 2,
    overCapacity: false,
    confirmable: true,
    referenceMonth: "2026-03-01",
    horizonDays: 60,
    lineageVersion: "v27.1-focus-2026-03-60d",
    algorithmVersion: "inspection-v1.0.0",
    explanation: {
      strategy: "지역·시설유형 균형 순환",
      coverageFormula: "selected / candidates * 100",
    },
    teams: [
      { teamNumber: 1, targetCount: 20, firstOrder: 1, lastOrder: 39 },
      { teamNumber: 2, targetCount: 20, firstOrder: 2, lastOrder: 40 },
    ],
    sampleTargets: [
      {
        buildingId,
        buildingLabel: "나주 시험시설",
        selectionOrder: 1,
        teamNumber: 1,
        finalScore: 0.981234,
        regionName: "전라남도 나주시",
        facilityType: "공장",
      },
    ],
  },
  executionImpact: {
    workItemCount: 2,
    externalEffect: false,
    summary: "익명 점검반별 내부 과업만 생성합니다.",
  },
  decision: null,
};

function installFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/auth/session"))
        return response(
          envelope({
            user: { userId: "user", displayName: "사용자" },
            expiresAt: "2026-07-29T12:00:00Z",
          }),
        );
      if (url.endsWith("/sources/health"))
        return response(envelope({ summary: "HEALTHY", dataAsOf: null, sources: [] }));
      if (url.endsWith("/inspections/options"))
        return response(
          envelope({
            regions: [{ regionCode: "46170", level: "SIGUNGU", fullName: "전라남도 나주시" }],
            facilityTypes: ["공장"],
            algorithmVersion: "inspection-v1.0.0",
            risk: { referenceMonth: "2026-03", horizonDays: 60, scoreMeaning: "상대점수" },
          }),
        );
      if (url.endsWith("/inspections/simulations") && init?.method === "POST")
        return response(envelope({ inspectionSimulationId: simulationId, status: "QUEUED" }));
      if (url.endsWith(`/inspections/simulations/${simulationId}`))
        return response(envelope(simulation));
      if (url.includes(`/inspections/simulations/${simulationId}/targets?`))
        return response(
          envelope({
            inspectionScenarioId: scenarioId,
            scenarioType: "BALANCED",
            items: [
              {
                inspectionTargetId: "target",
                buildingId,
                buildingLabel: "나주 시험시설",
                address: "전라남도 나주시",
                regionName: "전라남도 나주시",
                facilityType: "공장",
                finalScore: 0.981234,
                regionalRank: 1,
                topPercentile: 0.01,
                included: true,
                selectionOrder: 1,
                teamNumber: 1,
                selectionReason: "균형형 우선순위",
                exclusionReason: null,
              },
            ],
            pagination: { page: 1, pageSize: 20, total: 1, totalPages: 1 },
          }),
        );
      if (url.endsWith(`/inspections/simulations/${simulationId}/approval-requests`))
        return response(envelope({ approvalRequestId: approvalId }));
      if (url.endsWith(`/approvals/${approvalId}`)) return response(envelope(approvalDetail));
      throw new Error(`unexpected request: ${url}`);
    }),
  );
}

function renderApp(path: string) {
  window.history.replaceState({}, "", path);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <App runtime={resolveProfile(path)} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("inspection planning", () => {
  it("submits real conditions and renders three calculated scenarios", async () => {
    installFetch();
    renderApp("/demo/inspections/simulations/new");
    expect(await screen.findByRole("heading", { name: "점검 시뮬레이션" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "조건 저장 및 시뮬레이션 실행" }));
    expect(
      await screen.findByRole("heading", { name: "점검 시나리오 결과 비교" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "균형형" })).toBeInTheDocument();
    expect(screen.getByText("고위험 집중형")).toBeInTheDocument();
    expect(screen.getByText("커버리지 확대형")).toBeInTheDocument();
    expect(screen.getByText(/용량 100개소 초과/)).toBeInTheDocument();
  });

  it("shows actual targets and carries the selected plan into common approval", async () => {
    installFetch();
    renderApp(`/demo/inspections/simulations/${simulationId}/targets`);
    expect(await screen.findByRole("heading", { name: "우선 점검대상 목록" })).toBeInTheDocument();
    expect(await screen.findByText("나주 시험시설")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "확정 요청 · 검토 승인으로 이동" }));
    expect(await screen.findByRole("heading", { name: "승인 전 설명 확인" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "1. 점검계획 사실" })).toBeInTheDocument();
    expect(screen.getByText("20개소 · 순번 1~20")).toBeInTheDocument();
    expect(screen.getByText("20개소 · 순번 21~40")).toBeInTheDocument();
    expect(screen.getByText(/익명 점검반 내부 수행과업 2건 생성/)).toBeInTheDocument();
    await waitFor(() => expect(window.location.pathname).toBe(`/demo/approvals/${approvalId}`));
  });
});
