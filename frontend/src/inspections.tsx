import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useMemo, useState } from "react";
import { ApiError, apiRequest } from "./api";
import type { ProfileRuntime } from "./profile";
import { AppLink, navigateInternal } from "./router";
import "./inspections.css";

type ScenarioType = "BALANCED" | "HIGH_RISK_FOCUSED" | "COVERAGE_EXPANDED";
type SimulationStatus =
  | "QUEUED"
  | "RUNNING"
  | "CALCULATED"
  | "APPROVAL_PENDING"
  | "APPROVED"
  | "ON_HOLD"
  | "DISCARDED"
  | "FAILED";
interface Options {
  regions: { regionCode: string; level: string; fullName: string }[];
  facilityTypes: string[];
  algorithmVersion: string;
  risk: { referenceMonth: string; horizonDays: number; scoreMeaning: string };
}
interface Scenario {
  inspectionScenarioId: string;
  scenarioType: ScenarioType;
  ordinal: number;
  status: string;
  candidateCount: number;
  selectedCount: number;
  excludedCount: number;
  candidateCoveragePercent: number;
  requiredDays: number;
  overCapacity: boolean;
  confirmable: boolean;
  explanation: {
    strategy: string;
    capacityExceededBy: number;
    coverageFormula: string;
    appliedFilters: { topPercentile: number; minimumScore: number };
  };
  selected: boolean;
  version: number;
}
interface Simulation {
  inspectionSimulationId: string;
  status: SimulationStatus;
  version: number;
  context: {
    regionCode: string | null;
    regionName: string | null;
    buildingId: string | null;
    buildingLabel: string | null;
    caseId: string | null;
    caseNumber: string | null;
  };
  conditions: {
    facilityTypes: string[];
    startDate: string;
    endDate: string;
    inclusiveDayCount: number;
    teamCount: number;
    dailyCapacityPerTeam: number;
    totalCapacity: number;
    topPercentile: number;
    minimumScore: number;
    expandedTopPercentile: number;
    expandedMinimumScore: number;
  };
  riskSnapshot: {
    referenceMonth: string;
    horizonDays: number;
    lineageVersion: string;
    isProbability: false;
  };
  algorithmVersion: string;
  selectedScenarioId: string | null;
  error: { code: string; message: string } | null;
  scenarios: Scenario[];
}
interface Target {
  inspectionTargetId: string;
  buildingId: string;
  buildingLabel: string;
  address: string;
  regionName: string;
  facilityType: string;
  finalScore: number;
  regionalRank: number;
  topPercentile: number;
  included: boolean;
  selectionOrder: number | null;
  teamNumber: number | null;
  selectionReason: string | null;
  exclusionReason: string | null;
}
interface Targets {
  inspectionScenarioId: string;
  scenarioType: ScenarioType;
  items: Target[];
  pagination: { page: number; pageSize: number; total: number; totalPages: number };
}

const scenarioLabels: Record<ScenarioType, string> = {
  BALANCED: "균형형",
  HIGH_RISK_FOCUSED: "고위험 집중형",
  COVERAGE_EXPANDED: "커버리지 확대형",
};
const statusLabels: Record<string, string> = {
  QUEUED: "계산 대기",
  RUNNING: "계산 중",
  CALCULATED: "계산 완료",
  APPROVAL_PENDING: "승인 대기",
  APPROVED: "승인",
  ON_HOLD: "보류",
  DISCARDED: "폐기",
  FAILED: "계산 실패",
};
function key(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}
function errorText(error: unknown) {
  return error instanceof ApiError ? error.message : "요청을 처리하지 못했습니다.";
}
function simulationQuery(runtime: ProfileRuntime, id: string) {
  return {
    queryKey: ["inspection-simulation", runtime.profile, id],
    queryFn: () => apiRequest<Simulation>(runtime, `/inspections/simulations/${id}`),
    refetchInterval: (query: { state: { data?: { data: Simulation } } }) =>
      ["QUEUED", "RUNNING"].includes(query.state.data?.data.status ?? "") ? 1200 : false,
  } as const;
}
function simulationId(path: string) {
  return (
    path.match(/^\/inspections\/simulations\/([0-9a-f-]+)\/(?:compare|targets)$/i)?.[1] ?? null
  );
}

function Heading({
  eyebrow,
  title,
  copy,
  status,
}: {
  eyebrow: string;
  title: string;
  copy: string;
  status?: string;
}) {
  return (
    <div className="page-heading inspection-heading">
      <div>
        <p className="eyebrow">점검 계획 / {eyebrow}</p>
        <h1>{title}</h1>
        <p>{copy}</p>
      </div>
      {status ? (
        <span className="status-pill success">{statusLabels[status] ?? status}</span>
      ) : null}
    </div>
  );
}

function NewSimulation({ runtime }: { runtime: ProfileRuntime }) {
  const params = new URLSearchParams(window.location.search);
  const options = useQuery({
    queryKey: ["inspection-options", runtime.profile],
    queryFn: () => apiRequest<Options>(runtime, "/inspections/options"),
    staleTime: 300_000,
  });
  const today = new Date().toISOString().slice(0, 10);
  const later = new Date(Date.now() + 4 * 86_400_000).toISOString().slice(0, 10);
  const [region, setRegion] = useState(params.get("region") ?? "");
  const [facilities, setFacilities] = useState<string[]>([]);
  const [startDate, setStartDate] = useState(today);
  const [endDate, setEndDate] = useState(later);
  const [teams, setTeams] = useState(4);
  const [daily, setDaily] = useState(12);
  const [percentile, setPercentile] = useState(10);
  const [minimum, setMinimum] = useState(0.9);
  const days = Math.max(
    0,
    Math.floor((Date.parse(endDate) - Date.parse(startDate)) / 86_400_000) + 1,
  );
  const capacity = days * teams * daily;
  const create = useMutation({
    mutationFn: () =>
      apiRequest<{ inspectionSimulationId: string }>(runtime, "/inspections/simulations", {
        method: "POST",
        headers: { "Idempotency-Key": key("inspection-create") },
        body: JSON.stringify({
          regionCode: region || null,
          buildingId: params.get("building"),
          caseId: params.get("case"),
          facilityTypes: facilities,
          startDate,
          endDate,
          teamCount: teams,
          dailyCapacityPerTeam: daily,
          topPercentile: percentile,
          minimumScore: minimum,
        }),
      }),
    onSuccess: ({ data }) =>
      navigateInternal(runtime, `/inspections/simulations/${data.inspectionSimulationId}/compare`),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (days > 0 && !create.isPending) create.mutate();
  };
  return (
    <main className="page inspection-page" id="main-content">
      <Heading
        eyebrow="시뮬레이션 조건"
        title="점검 시뮬레이션"
        copy="실제 광주·전남 위험점수와 명시한 처리용량으로 세 실행안을 계산합니다."
      />
      <div className="inspection-form-grid">
        <form className="panel inspection-form" onSubmit={submit}>
          <h2>1. 조건 설정</h2>
          <div className="inspection-fields">
            <label>
              대상 지역
              <select value={region} onChange={(e) => setRegion(e.target.value)}>
                <option value="">광주·전남 전체</option>
                {options.data?.data.regions.map((item) => (
                  <option key={item.regionCode} value={item.regionCode}>
                    {item.fullName}
                  </option>
                ))}
              </select>
            </label>
            <label>
              시작일
              <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            </label>
            <label>
              종료일
              <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </label>
            <label className="wide">
              시설유형
              <select
                multiple
                value={facilities}
                onChange={(e) =>
                  setFacilities(Array.from(e.target.selectedOptions, (item) => item.value))
                }
              >
                {options.data?.data.facilityTypes.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
              <small>미선택 시 전체 시설유형</small>
            </label>
            <label>
              점검반 수
              <input
                min="1"
                max="100"
                type="number"
                value={teams}
                onChange={(e) => setTeams(Number(e.target.value))}
              />
            </label>
            <label>
              점검반당 1일 처리량
              <input
                min="1"
                max="500"
                type="number"
                value={daily}
                onChange={(e) => setDaily(Number(e.target.value))}
              />
            </label>
            <label>
              상위 위험 백분위
              <select value={percentile} onChange={(e) => setPercentile(Number(e.target.value))}>
                {[1, 5, 10, 25].map((item) => (
                  <option key={item} value={item}>
                    상위 {item}%
                  </option>
                ))}
              </select>
            </label>
            <label>
              최소 상대점수
              <input
                min="0"
                max="1"
                step="0.01"
                type="number"
                value={minimum}
                onChange={(e) => setMinimum(Number(e.target.value))}
              />
            </label>
          </div>
          <div className="inspection-source-note">
            2026-03 · 향후 60일 v27.1 `final_score` · 발생확률 아님
          </div>
        </form>
        <aside className="panel inspection-capacity">
          <h2>2. 실행 판단</h2>
          <div className="capacity-hero">
            <span>총 처리 가능</span>
            <strong>{capacity.toLocaleString()}개소</strong>
          </div>
          <dl>
            <div>
              <dt>포함 기간</dt>
              <dd>{days}일</dd>
            </div>
            <div>
              <dt>점검반</dt>
              <dd>{teams}개 반</dd>
            </div>
            <div>
              <dt>일 처리량</dt>
              <dd>{(teams * daily).toLocaleString()}개소</dd>
            </div>
          </dl>
          <p>후보 수와 선정 결과는 전체 기준 DB의 비동기 계산 후 확인합니다.</p>
          {create.isError ? <div className="panel-error">{errorText(create.error)}</div> : null}
          <button
            className="primary-action"
            disabled={days < 1 || create.isPending}
            onClick={() => create.mutate()}
            type="button"
          >
            {create.isPending ? "계산 요청 중…" : "조건 저장 및 시뮬레이션 실행"}
          </button>
        </aside>
      </div>
      <section className="panel inspection-context">
        <h2>전달된 분석 문맥</h2>
        <p>
          지역 {region || "전체"} · 건물 {params.get("building") ?? "없음"} · Case{" "}
          {params.get("case") ?? "없음"}
        </p>
      </section>
    </main>
  );
}

function Compare({
  currentPath,
  runtime,
  id,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
  id: string;
}) {
  const query = useQuery(simulationQuery(runtime, id));
  const qc = useQueryClient();
  const data = query.data?.data;
  const select = useMutation({
    mutationFn: (scenario: Scenario) =>
      apiRequest<Simulation>(runtime, `/inspections/simulations/${id}/selection`, {
        method: "POST",
        headers: { "Idempotency-Key": key("inspection-select") },
        body: JSON.stringify({
          scenarioId: scenario.inspectionScenarioId,
          expectedVersion: data?.version,
        }),
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["inspection-simulation", runtime.profile, id] }),
  });
  if (!data || ["QUEUED", "RUNNING"].includes(data.status))
    return (
      <main className="page inspection-page" id="main-content">
        <Heading
          eyebrow="시나리오 비교"
          title="점검 시나리오 결과 비교"
          copy="실제 대상 순서와 점검반 배분을 계산하고 있습니다."
          status={data?.status ?? "QUEUED"}
        />
        <section className="panel loading-panel" role="status">
          전체 기준 데이터를 계산 중입니다. 다른 화면을 사용해도 작업은 계속됩니다.
        </section>
      </main>
    );
  if (data.status === "FAILED")
    return (
      <main className="page inspection-page" id="main-content">
        <Heading
          eyebrow="시나리오 비교"
          title="계산을 완료하지 못했습니다"
          copy={data.error?.message ?? "점검 시뮬레이션 오류"}
          status="FAILED"
        />
        <AppLink
          className="secondary-action"
          currentPath={currentPath}
          runtime={runtime}
          to="/inspections/simulations/new"
        >
          조건 다시 입력
        </AppLink>
      </main>
    );
  const selected = data.scenarios.find((item) => item.selected);
  return (
    <main className="page inspection-page" id="main-content">
      <Heading
        eyebrow="시나리오 비교"
        title="점검 시나리오 결과 비교"
        copy="동일한 입력과 고정 위험 snapshot으로 계산한 세 실행안을 비교합니다."
        status={data.status}
      />
      <section className="panel condition-strip">
        <span>{data.context.regionName ?? "광주·전남 전체"}</span>
        <span>
          {data.conditions.teamCount}개 반 · 최대 {data.conditions.totalCapacity.toLocaleString()}
          개소
        </span>
        <span>
          상위 {data.conditions.topPercentile}% · 최소 {data.conditions.minimumScore.toFixed(3)}
        </span>
      </section>
      <div className="scenario-grid">
        {data.scenarios.map((item) => (
          <article
            className={`panel scenario-card ${item.selected ? "selected" : ""} ${!item.confirmable ? "blocked" : ""}`}
            key={item.inspectionScenarioId}
          >
            <div className="scenario-title">
              <span>{String.fromCharCode(65 + item.ordinal - 1)}</span>
              <h2>{scenarioLabels[item.scenarioType]}</h2>
              {item.selected ? <span className="status-pill success">선택</span> : null}
            </div>
            <div className="scenario-metrics">
              <div>
                <span>점검 대상</span>
                <strong>{item.selectedCount.toLocaleString()}개소</strong>
              </div>
              <div>
                <span>후보 충족률</span>
                <strong>{item.candidateCoveragePercent.toFixed(1)}%</strong>
              </div>
            </div>
            <p>{item.explanation.strategy}</p>
            <dl>
              <div>
                <dt>필요 기간</dt>
                <dd>{item.requiredDays}일</dd>
              </div>
              <div>
                <dt>제외 대상</dt>
                <dd>{item.excludedCount.toLocaleString()}개소</dd>
              </div>
            </dl>
            {item.overCapacity ? (
              <div className="capacity-warning">
                용량 {item.explanation.capacityExceededBy.toLocaleString()}개소 초과 · 조건 수정
                필요
              </div>
            ) : (
              <button
                disabled={select.isPending || item.selected}
                onClick={() => select.mutate(item)}
                type="button"
              >
                {item.selected ? "현재 선택안" : "이 시나리오 선택"}
              </button>
            )}
          </article>
        ))}
      </div>
      <section className="panel selected-bar">
        <div>
          <span>선택한 시나리오</span>
          <strong>{selected ? scenarioLabels[selected.scenarioType] : "선택 필요"}</strong>
        </div>
        <AppLink
          className="secondary-action"
          currentPath={currentPath}
          runtime={runtime}
          to="/inspections/simulations/new"
        >
          조건 수정
        </AppLink>
        <button
          className="primary-action"
          disabled={!selected}
          onClick={() => navigateInternal(runtime, `/inspections/simulations/${id}/targets`)}
          type="button"
        >
          선택안으로 대상 목록 검토
        </button>
      </section>
      {select.isError ? <div className="panel-error">{errorText(select.error)}</div> : null}
    </main>
  );
}

function TargetList({
  currentPath,
  runtime,
  id,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
  id: string;
}) {
  const sim = useQuery(simulationQuery(runtime, id));
  const data = sim.data?.data;
  const params = new URLSearchParams(window.location.search);
  const [include, setInclude] = useState(params.get("include") ?? "ALL");
  const [team, setTeam] = useState(params.get("team") ?? "");
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [page, setPage] = useState(Number(params.get("page") ?? 1));
  const targetParams = useMemo(() => {
    const p = new URLSearchParams({ include, page: String(page), pageSize: "20" });
    if (team) p.set("teamNumber", team);
    if (search) p.set("q", search);
    return p;
  }, [include, page, search, team]);
  const targets = useQuery({
    queryKey: ["inspection-targets", runtime.profile, id, targetParams.toString()],
    queryFn: () =>
      apiRequest<Targets>(runtime, `/inspections/simulations/${id}/targets?${targetParams}`),
    enabled: Boolean(data?.selectedScenarioId),
    placeholderData: (old) => old,
  });
  const approval = useMutation({
    mutationFn: () =>
      apiRequest<{ approvalRequestId: string }>(
        runtime,
        `/inspections/simulations/${id}/approval-requests`,
        { method: "POST", headers: { "Idempotency-Key": key("inspection-approval") } },
      ),
    onSuccess: ({ data: result }) =>
      navigateInternal(runtime, `/approvals/${result.approvalRequestId}`),
  });
  if (!data)
    return (
      <main className="page inspection-page" id="main-content">
        <section className="panel loading-panel">점검대상을 불러오고 있습니다.</section>
      </main>
    );
  const scenario = data.scenarios.find((item) => item.selected);
  if (!scenario)
    return (
      <main className="page inspection-page" id="main-content">
        <Heading
          eyebrow="우선 점검대상"
          title="선택된 시나리오가 없습니다"
          copy="비교 화면에서 확정 가능한 실행안을 선택해 주세요."
        />
        <AppLink
          className="primary-action"
          currentPath={currentPath}
          runtime={runtime}
          to={`/inspections/simulations/${id}/compare`}
        >
          비교 화면으로 이동
        </AppLink>
      </main>
    );
  const checks = [
    { label: "점검대상 존재", ok: scenario.selectedCount > 0 },
    { label: "용량 이내", ok: !scenario.overCapacity },
    { label: "익명 점검반 배분", ok: data.conditions.teamCount > 0 },
    { label: "고정 위험 snapshot", ok: !data.riskSnapshot.isProbability },
  ];
  return (
    <main className="page inspection-page" id="main-content">
      <Heading
        eyebrow="우선 점검대상"
        title="우선 점검대상 목록"
        copy="선정·제외 근거와 익명 점검반 배정을 검토하고 확정을 요청합니다."
        status={data.status}
      />
      <section className="panel target-summary">
        <div>
          <span>선택 시나리오</span>
          <strong>{scenarioLabels[scenario.scenarioType]}</strong>
        </div>
        <div>
          <span>포함 대상</span>
          <strong>{scenario.selectedCount.toLocaleString()}개소</strong>
        </div>
        <div>
          <span>제외 대상</span>
          <strong>{scenario.excludedCount.toLocaleString()}개소</strong>
        </div>
        <div>
          <span>점검반</span>
          <strong>{data.conditions.teamCount}개 반</strong>
        </div>
        <div>
          <span>후보 충족률</span>
          <strong>{scenario.candidateCoveragePercent.toFixed(1)}%</strong>
        </div>
      </section>
      <div className="target-layout">
        <section className="panel target-panel">
          <div className="target-filters">
            <select
              value={include}
              onChange={(e) => {
                setInclude(e.target.value);
                setPage(1);
              }}
            >
              <option value="ALL">전체 상태</option>
              <option value="INCLUDED">포함</option>
              <option value="EXCLUDED">제외</option>
            </select>
            <select
              value={team}
              onChange={(e) => {
                setTeam(e.target.value);
                setPage(1);
              }}
            >
              <option value="">전체 점검반</option>
              {Array.from({ length: data.conditions.teamCount }, (_, index) => index + 1).map(
                (teamNumber) => (
                  <option key={teamNumber} value={teamNumber}>
                    점검반 {teamNumber}
                  </option>
                ),
              )}
            </select>
            <input
              aria-label="시설명·지역 검색"
              placeholder="시설명·지역 검색"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          </div>
          <div className="target-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>상태</th>
                  <th>시설</th>
                  <th>지역·유형</th>
                  <th>상대점수</th>
                  <th>상위 백분위</th>
                  <th>점검반</th>
                  <th>근거</th>
                </tr>
              </thead>
              <tbody>
                {targets.data?.data.items.map((item) => (
                  <tr key={item.inspectionTargetId}>
                    <td>
                      <span className={`status-pill ${item.included ? "success" : "warning"}`}>
                        {item.included ? "포함" : "제외"}
                      </span>
                    </td>
                    <td>
                      <AppLink
                        className="table-link"
                        currentPath={currentPath}
                        runtime={runtime}
                        to={`/buildings/${item.buildingId}`}
                      >
                        {item.buildingLabel}
                      </AppLink>
                      <small>{item.address}</small>
                    </td>
                    <td>
                      {item.regionName}
                      <small>{item.facilityType}</small>
                    </td>
                    <td>{item.finalScore.toFixed(6)}</td>
                    <td>상위 {item.topPercentile.toFixed(2)}%</td>
                    <td>{item.teamNumber ? `점검반 ${item.teamNumber}` : "—"}</td>
                    <td>{item.selectionReason ?? item.exclusionReason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)} type="button">
              이전
            </button>
            <span>
              {page} / {targets.data?.data.pagination.totalPages || 1}
            </span>
            <button
              disabled={page >= (targets.data?.data.pagination.totalPages || 1)}
              onClick={() => setPage(page + 1)}
              type="button"
            >
              다음
            </button>
          </div>
        </section>
        <aside className="panel confirmation-panel">
          <h2>확정 전 검토</h2>
          {checks.map((item) => (
            <div className={`check-row ${item.ok ? "ok" : "bad"}`} key={item.label}>
              <span>{item.ok ? "✓" : "!"}</span>
              <strong>{item.label}</strong>
            </div>
          ))}
          <p>
            승인하면 점검반 {data.conditions.teamCount}개의 내부 수행과업을 만듭니다. 개인 담당자와
            외부 요청은 자동 생성하지 않습니다.
          </p>
          {approval.isError ? <div className="panel-error">{errorText(approval.error)}</div> : null}
          <button
            className="primary-action"
            disabled={
              !scenario.confirmable ||
              approval.isPending ||
              data.status === "APPROVAL_PENDING" ||
              data.status === "APPROVED"
            }
            onClick={() => approval.mutate()}
            type="button"
          >
            {data.status === "APPROVAL_PENDING"
              ? "승인 대기 중"
              : data.status === "APPROVED"
                ? "승인 완료"
                : "확정 요청 · 검토 승인으로 이동"}
          </button>
          <AppLink
            className="secondary-action"
            currentPath={currentPath}
            runtime={runtime}
            to={`/inspections/simulations/${id}/compare`}
          >
            시나리오 다시 비교
          </AppLink>
        </aside>
      </div>
    </main>
  );
}

export function InspectionPlanning({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  if (currentPath === "/inspections/simulations/new") return <NewSimulation runtime={runtime} />;
  const id = simulationId(currentPath);
  if (!id)
    return (
      <main className="page" id="main-content">
        <section className="panel">점검 시뮬레이션 경로를 찾을 수 없습니다.</section>
      </main>
    );
  return currentPath.endsWith("/compare") ? (
    <Compare currentPath={currentPath} id={id} runtime={runtime} />
  ) : (
    <TargetList currentPath={currentPath} id={id} runtime={runtime} />
  );
}
