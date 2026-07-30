import { useMutation, useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useState } from "react";
import { ApiError, apiRequest } from "./api";
import type { ProfileRuntime } from "./profile";
import { AppLink, currentInternalLocation, navigateInternal, safeReturnTo } from "./router";
import { SldAnalysisPanel } from "./sld_analysis";

type StandaloneDocumentVariant = "REGION_ANALYSIS" | "BUILDING_ANALYSIS" | "INSPECTION_REQUEST";

function StandaloneDocumentButton({
  runtime,
  variant,
  targetId,
  className,
  children,
}: {
  runtime: ProfileRuntime;
  variant: StandaloneDocumentVariant;
  targetId: string;
  className: string;
  children: ReactNode;
}) {
  const create = useMutation({
    mutationFn: () =>
      apiRequest<{ documentDraftId: string }>(runtime, "/standalone-documents", {
        method: "POST",
        headers: { "Idempotency-Key": `standalone-document-${crypto.randomUUID()}` },
        body: JSON.stringify({ variant, targetId }),
      }),
    onSuccess: ({ data }) => navigateInternal(runtime, `/documents/${data.documentDraftId}/edit`),
  });
  return (
    <div className="standalone-document-action">
      <button
        className={className}
        disabled={create.isPending}
        onClick={() => create.mutate()}
        type="button"
      >
        {create.isPending ? "초안 만드는 중…" : children}
      </button>
      {create.isError ? (
        <small role="alert">
          {create.error instanceof ApiError
            ? `${create.error.message} (${create.error.code})`
            : "문서 초안을 만들지 못했습니다. 다시 시도해 주세요."}
        </small>
      ) : null}
    </div>
  );
}

interface RiskValue {
  finalScore: number;
  regionalRank: number;
  topPercentile: number;
  riskBand: string;
}

type RankingLevel = "SIDO" | "SIGUNGU" | "EUPMYEONDONG" | "BUILDING";

interface RiskRankingItem {
  entityType: "REGION" | "BUILDING";
  entityId: string;
  level: RankingLevel;
  name: string;
  fullName: string;
  regionName: string;
  rankingPosition: number;
  buildingCount: number;
  top1Count: number;
  top10Count: number;
  top10Share: number;
  scoreP99: number | null;
  finalScore: number | null;
  topPercentile: number | null;
  riskBand: string | null;
}

interface RiskRankingData {
  level: RankingLevel;
  rankingBasis: "TOP_10_BUILDING_COUNT" | "GWANGJU_JEONNAM_REGIONAL_RANK";
  items: RiskRankingItem[];
  pagination: { page: number; pageSize: number; total: number; totalPages: number };
}

interface RegionDetailData {
  regionCode: string;
  level: "SIDO" | "SIGUNGU" | "EUPMYEONDONG";
  name: string;
  fullName: string;
  parent: { regionCode: string; fullName: string } | null;
  center: [number, number];
  bounds: [number, number, number, number];
  riskReference: {
    referenceMonth: string;
    horizonDays: number;
    lineageVersion: string;
    isProbability: boolean;
    calculatedAt: string;
  };
  distribution: {
    buildingCount: number;
    top10Count: number;
    bands: { top1: number; high1To10: number; watch10To25: number; general: number };
    bandShares: { top1: number; high1To10: number; watch10To25: number; general: number };
    scoreStats: { minimum: number; median: number; p90: number; p99: number; maximum: number };
  };
  currentSignals: { activeCaseCount: number; urgentCaseCount: number; hasCurrentSignal: boolean };
  topBuildings: Array<{
    buildingId: string;
    name: string;
    roadAddress: string | null;
    lotAddress: string;
    risk: RiskValue;
  }>;
}

interface BuildingDetailData {
  buildingId: string;
  sourceBuildingKey: string;
  region: { regionCode: string; fullName: string };
  name: string;
  roadAddress: string | null;
  lotAddress: string;
  center: [number, number];
  geometryStatus: string;
  attributes: {
    mainUseName: string | null;
    mainStructure: string | null;
    buildingYear: number | null;
    buildingAge: number | null;
    approvalDate: string | null;
    floorsAbove: number | null;
    floorsBelow: number | null;
    grossFloorAreaM2: number | null;
    landUseName: string | null;
    registerType: string | null;
  };
  facilitySummary: {
    linkedFacilityCount: number;
    generalCount: number;
    selfCount: number;
    latestInspectionDate: string | null;
    candidateSourceCount: number;
  };
  risk: RiskValue & { sourceClass: string; manifestHash: string };
  currentSignals: { activeCaseCount: number; urgentCaseCount: number; hasCurrentSignal: boolean };
  quality: { buildingFlags: string[]; riskFlags: string[] };
}

const riskNames: Record<string, string> = {
  TOP_1: "최상위 위험",
  HIGH_1_10: "고위험",
  WATCH_10_25: "관심",
  GENERAL: "일반",
};

const bandRows = [
  { key: "top1", label: "최상위 위험 · 상위 1%", className: "top" },
  { key: "high1To10", label: "고위험 · 상위 1~10%", className: "high" },
  { key: "watch10To25", label: "관심 · 상위 10~25%", className: "watch" },
  { key: "general", label: "일반", className: "general" },
] as const;

function formatScore(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "—"
    : value.toLocaleString("ko-KR", { maximumFractionDigits: 6 });
}

function displayValue(value: string | number | null | undefined, suffix = ""): string {
  if (value === null || value === undefined || value === "") return "미등록";
  return `${typeof value === "number" ? value.toLocaleString("ko-KR") : value}${suffix}`;
}

function AnalysisLoading() {
  return (
    <main className="page analysis-page" id="main-content">
      <div className="analysis-state" role="status">
        분석 데이터를 불러오고 있습니다.
      </div>
    </main>
  );
}

function AnalysisError({ retry }: { retry: () => void }) {
  return (
    <main className="page analysis-page" id="main-content">
      <div className="analysis-state error" role="alert">
        <strong>분석 데이터를 불러오지 못했습니다.</strong>
        <button onClick={retry} type="button">
          다시 시도
        </button>
      </div>
    </main>
  );
}

function RegionIndex({ currentPath, runtime }: { currentPath: string; runtime: ProfileRuntime }) {
  const initialLevel = new URLSearchParams(window.location.search).get("level");
  const [level, setLevel] = useState<RankingLevel>(
    initialLevel === "SIDO" ||
      initialLevel === "SIGUNGU" ||
      initialLevel === "EUPMYEONDONG" ||
      initialLevel === "BUILDING"
      ? initialLevel
      : "SIGUNGU",
  );
  const [page, setPage] = useState(1);
  const rankings = useQuery({
    queryKey: ["analysis-risk-rankings", runtime.profile, level, page],
    queryFn: () =>
      apiRequest<RiskRankingData>(
        runtime,
        `/risk-rankings?level=${level}&page=${page}&pageSize=24`,
      ).then((result) => result.data),
    staleTime: 5 * 60_000,
    placeholderData: (previous) => previous,
  });
  if (rankings.isLoading) return <AnalysisLoading />;
  if (rankings.isError || !rankings.data)
    return <AnalysisError retry={() => void rankings.refetch()} />;
  const levelLabels: Record<RankingLevel, string> = {
    SIDO: "광역시·도",
    SIGUNGU: "시·군·구",
    EUPMYEONDONG: "읍·면·동",
    BUILDING: "건물",
  };
  return (
    <main className="page analysis-page" id="main-content">
      <div className="page-heading analysis-heading">
        <div>
          <h1>위험 분석</h1>
          <p>광주·전남의 광역시·도, 시·군·구, 읍·면·동과 건물 순위를 비교합니다.</p>
        </div>
        <AppLink className="outline-action" currentPath={currentPath} runtime={runtime} to="/map">
          통합 위험지도
        </AppLink>
      </div>
      <aside className="analysis-contract-note">
        v27.1 · 2026-03 · 향후 60일 상대점수입니다. 발생확률이나 실시간 재난점수가 아닙니다.
      </aside>
      <nav className="analysis-level-tabs" aria-label="위험 분석 단위">
        {(Object.keys(levelLabels) as RankingLevel[]).map((item) => (
          <button
            aria-pressed={level === item}
            className={level === item ? "is-active" : ""}
            key={item}
            onClick={() => {
              setLevel(item);
              setPage(1);
              const params = new URLSearchParams(window.location.search);
              params.set("level", item);
              window.history.replaceState({}, "", `${window.location.pathname}?${params}`);
            }}
            type="button"
          >
            {levelLabels[item]}
          </button>
        ))}
      </nav>
      <div className="analysis-ranking-basis">
        <strong>{levelLabels[level]} 위험 순위</strong>
        <span>
          {rankings.data.rankingBasis === "GWANGJU_JEONNAM_REGIONAL_RANK"
            ? "광주·전남 모델 순위"
            : "상위 10% 건물 수 기준"}
        </span>
      </div>
      <section className="region-index-grid" aria-label={`${levelLabels[level]} 위험 순위`}>
        {rankings.data.items.map((item) => {
          const isBuilding = item.entityType === "BUILDING";
          return (
            <article key={item.entityId}>
              <div className="region-index-rank">{item.rankingPosition}</div>
              <div>
                <h2>{item.fullName}</h2>
                <p>
                  {isBuilding
                    ? item.regionName
                    : `건물 ${item.buildingCount.toLocaleString("ko-KR")}개 · 상위 10% ${item.top10Count.toLocaleString("ko-KR")}개`}
                </p>
              </div>
              <dl>
                <div>
                  <dt>{isBuilding ? "위험구간" : "상위 10% 비중"}</dt>
                  <dd>
                    {isBuilding
                      ? riskNames[item.riskBand ?? "GENERAL"]
                      : `${item.top10Share.toFixed(1)}%`}
                  </dd>
                </div>
                <div>
                  <dt>{isBuilding ? "상위 백분위" : "p99 점수"}</dt>
                  <dd>
                    {isBuilding && item.topPercentile !== null
                      ? `상위 ${item.topPercentile.toFixed(2)}%`
                      : formatScore(item.scoreP99)}
                  </dd>
                </div>
                <div>
                  <dt>{isBuilding ? "상대점수" : "상위 1%"}</dt>
                  <dd>
                    {isBuilding
                      ? formatScore(item.finalScore)
                      : `${item.top1Count.toLocaleString("ko-KR")}개`}
                  </dd>
                </div>
              </dl>
              <AppLink
                className="primary-action"
                currentPath={currentPath}
                runtime={runtime}
                to={isBuilding ? `/buildings/${item.entityId}` : `/regions/${item.entityId}`}
              >
                {isBuilding ? "건물 분석 보기" : "지역 분석 보기"}
              </AppLink>
            </article>
          );
        })}
      </section>
      <div className="analysis-ranking-pagination">
        <button disabled={page <= 1} onClick={() => setPage(page - 1)} type="button">
          이전
        </button>
        <span>
          {rankings.data.pagination.page} / {rankings.data.pagination.totalPages || 1} · 총{" "}
          {rankings.data.pagination.total.toLocaleString("ko-KR")}개
        </span>
        <button
          disabled={page >= rankings.data.pagination.totalPages}
          onClick={() => setPage(page + 1)}
          type="button"
        >
          다음
        </button>
      </div>
    </main>
  );
}

function RegionDetail({
  currentPath,
  runtime,
  regionCode,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
  regionCode: string;
}) {
  const region = useQuery({
    queryKey: ["analysis-region", runtime.profile, regionCode],
    queryFn: () =>
      apiRequest<RegionDetailData>(runtime, `/regions/${regionCode}`).then((result) => result.data),
    staleTime: 5 * 60_000,
  });
  if (region.isLoading) return <AnalysisLoading />;
  if (region.isError || !region.data) return <AnalysisError retry={() => void region.refetch()} />;
  const data = region.data;
  const returnTo = safeReturnTo(new URLSearchParams(window.location.search).get("returnTo"));
  const mapTarget =
    returnTo === "/home"
      ? `/map?level=district&region=${data.regionCode}&lng=${data.center[0]}&lat=${data.center[1]}&zoom=${data.level === "SIDO" ? 9 : 12.5}`
      : returnTo;
  const highRiskMapTarget = (() => {
    const [path, query = ""] = mapTarget.split("?", 2);
    const params = new URLSearchParams(query);
    params.set("level", "building");
    params.set("zoom", "16");
    return `${path}?${params.toString()}`;
  })();
  const currentLocation = currentInternalLocation(runtime);
  return (
    <main className="page analysis-page" id="main-content">
      <AppLink className="analysis-back" currentPath={currentPath} runtime={runtime} to={mapTarget}>
        ‹ 통합 위험지도로 돌아가기
      </AppLink>
      <div className="page-heading analysis-heading">
        <div>
          <h1>지역 상세</h1>
          <p>
            <strong>{data.fullName}</strong>
            {data.parent ? ` · ${data.parent.fullName}` : ""}
          </p>
        </div>
        <div className="analysis-heading-actions">
          <AppLink
            className="outline-action"
            currentPath={currentPath}
            runtime={runtime}
            to="/regions"
          >
            지역 목록
          </AppLink>
          <AppLink
            className="primary-action"
            currentPath={currentPath}
            runtime={runtime}
            to={highRiskMapTarget}
          >
            고위험 건물
          </AppLink>
        </div>
      </div>
      <aside className="analysis-contract-note">
        {data.riskReference.lineageVersion} · {data.riskReference.referenceMonth} · 향후{" "}
        {data.riskReference.horizonDays}일 상대점수. 실시간 신호는 기준점수를 변경하지 않습니다.
      </aside>
      <section className="analysis-metrics" aria-label="지역 핵심 지표">
        <article>
          <span>분석 건물</span>
          <strong>{data.distribution.buildingCount.toLocaleString("ko-KR")}개</strong>
          <small>모델 대상·폴리곤 정합 건물</small>
        </article>
        <article>
          <span>상위 10% 건물</span>
          <strong>{data.distribution.top10Count.toLocaleString("ko-KR")}개</strong>
          <small>
            {((data.distribution.top10Count / data.distribution.buildingCount) * 100).toFixed(1)}%
            집중
          </small>
        </article>
        <article>
          <span>p99 상대점수</span>
          <strong>{formatScore(data.distribution.scoreStats.p99)}</strong>
          <small>발생확률 아님</small>
        </article>
        <article className={data.currentSignals.hasCurrentSignal ? "signal" : ""}>
          <span>현재 관제 Case</span>
          <strong>{data.currentSignals.activeCaseCount.toLocaleString("ko-KR")}건</strong>
          <small>긴급 {data.currentSignals.urgentCaseCount.toLocaleString("ko-KR")}건</small>
        </article>
      </section>
      <div className="analysis-two-column">
        <section className="analysis-panel">
          <div className="analysis-panel-heading">
            <h2>지역 위험구간 분포</h2>
            <span>{data.distribution.buildingCount.toLocaleString("ko-KR")}개</span>
          </div>
          <div className="band-chart">
            {bandRows.map((row) => {
              const share = data.distribution.bandShares[row.key];
              return (
                <div className="band-row" key={row.key}>
                  <span>{row.label}</span>
                  <div>
                    <i className={row.className} style={{ width: `${Math.max(share, 0.5)}%` }} />
                  </div>
                  <b>{data.distribution.bands[row.key].toLocaleString("ko-KR")}개</b>
                  <em>{share.toFixed(2)}%</em>
                </div>
              );
            })}
          </div>
        </section>
        <section className="analysis-panel">
          <div className="analysis-panel-heading">
            <h2>상대점수 분포 기준</h2>
            <span>v27.1</span>
          </div>
          <dl className="score-stat-grid">
            <div>
              <dt>최소</dt>
              <dd>{formatScore(data.distribution.scoreStats.minimum)}</dd>
            </div>
            <div>
              <dt>중앙값</dt>
              <dd>{formatScore(data.distribution.scoreStats.median)}</dd>
            </div>
            <div>
              <dt>p90</dt>
              <dd>{formatScore(data.distribution.scoreStats.p90)}</dd>
            </div>
            <div>
              <dt>p99</dt>
              <dd>{formatScore(data.distribution.scoreStats.p99)}</dd>
            </div>
            <div>
              <dt>최대</dt>
              <dd>{formatScore(data.distribution.scoreStats.maximum)}</dd>
            </div>
          </dl>
          <p className="analysis-explanation">
            지역 간 점수 절대값을 위험확률로 비교하지 않고 광주·전남 전체 순위와 위험구간으로
            우선순위를 정합니다.
          </p>
        </section>
      </div>
      <section className="analysis-panel top-building-panel">
        <div className="analysis-panel-heading">
          <div>
            <h2>우선 확인 건물</h2>
            <p>광주·전남 순위 기준 지역 내 상위 10개입니다.</p>
          </div>
          <span>실제 기준 데이터</span>
        </div>
        <div className="analysis-table-wrap">
          <table className="analysis-table">
            <thead>
              <tr>
                <th>건물</th>
                <th>위험구간</th>
                <th>광주·전남 순위</th>
                <th>상위 백분위</th>
                <th>상세</th>
              </tr>
            </thead>
            <tbody>
              {data.topBuildings.map((building) => (
                <tr key={building.buildingId}>
                  <td>
                    <strong>{building.name}</strong>
                    <small>{building.roadAddress ?? building.lotAddress}</small>
                  </td>
                  <td>
                    <span className={`risk-pill ${building.risk.riskBand.toLowerCase()}`}>
                      {riskNames[building.risk.riskBand]}
                    </span>
                  </td>
                  <td>{building.risk.regionalRank.toLocaleString("ko-KR")}위</td>
                  <td>상위 {building.risk.topPercentile.toFixed(2)}%</td>
                  <td>
                    <AppLink
                      className="table-action"
                      currentPath={currentPath}
                      runtime={runtime}
                      to={`/buildings/${building.buildingId}?returnTo=${encodeURIComponent(currentLocation)}`}
                    >
                      분석 보기
                    </AppLink>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="analysis-actions">
        <div>
          <h2>분석 결과로 할 수 있는 작업</h2>
          <p>현재 지역과 기준 위험분포가 다음 작업의 초기 조건으로 전달됩니다.</p>
        </div>
        <div>
          <AppLink
            className="outline-action"
            currentPath={currentPath}
            runtime={runtime}
            to={`/inspections/simulations/new?region=${data.regionCode}`}
          >
            지역 점검 시뮬레이션
          </AppLink>
          <AppLink
            className="outline-action"
            currentPath={currentPath}
            runtime={runtime}
            to={`/similar/incidents?region=${data.regionCode}`}
          >
            지역 화재 사례 검색
          </AppLink>
          <AppLink
            className="primary-action"
            currentPath={currentPath}
            runtime={runtime}
            to={`/regions/${data.regionCode}/report`}
          >
            지역 분석 보고서
          </AppLink>
        </div>
      </section>
    </main>
  );
}

function BuildingDetail({
  currentPath,
  runtime,
  buildingId,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
  buildingId: string;
}) {
  const [showSldAnalysis, setShowSldAnalysis] = useState(false);
  const building = useQuery({
    queryKey: ["analysis-building", runtime.profile, buildingId],
    queryFn: () =>
      apiRequest<BuildingDetailData>(runtime, `/buildings/${buildingId}`).then(
        (result) => result.data,
      ),
    staleTime: 5 * 60_000,
  });
  if (building.isLoading) return <AnalysisLoading />;
  if (building.isError || !building.data)
    return <AnalysisError retry={() => void building.refetch()} />;
  const data = building.data;
  const requestedReturn = new URLSearchParams(window.location.search).get("returnTo");
  const returnTarget = requestedReturn
    ? safeReturnTo(requestedReturn)
    : `/regions/${data.region.regionCode}`;
  const attributeRows = [
    ["주용도", data.attributes.mainUseName],
    ["주구조", data.attributes.mainStructure],
    ["사용승인", data.attributes.approvalDate],
    ["건축연도", data.attributes.buildingYear],
    ["건물연령", data.attributes.buildingAge, "년"],
    ["지상층", data.attributes.floorsAbove, "층"],
    ["지하층", data.attributes.floorsBelow, "층"],
    ["연면적", data.attributes.grossFloorAreaM2, "㎡"],
    ["토지이용", data.attributes.landUseName],
    ["대장구분", data.attributes.registerType],
  ] as const;
  const qualityFlags = [...data.quality.buildingFlags, ...data.quality.riskFlags];
  return (
    <main className="page analysis-page" id="main-content">
      <AppLink
        className="analysis-back"
        currentPath={currentPath}
        runtime={runtime}
        to={returnTarget}
      >
        ‹ 이전 분석으로 돌아가기
      </AppLink>
      <div className="page-heading analysis-heading">
        <div>
          <h1>건물 상세</h1>
          <p>
            <strong>{data.name}</strong> · {data.roadAddress ?? data.lotAddress} ·{" "}
            {data.region.fullName}
          </p>
        </div>
        <div className="analysis-heading-actions">
          <button
            aria-expanded={showSldAnalysis}
            className="outline-action"
            onClick={() => setShowSldAnalysis((visible) => !visible)}
            type="button"
          >
            단선결선도 분석
          </button>
          <AppLink
            className="outline-action"
            currentPath={currentPath}
            runtime={runtime}
            to={`/map?level=building&region=${data.region.regionCode}&building=${data.buildingId}&lng=${data.center[0]}&lat=${data.center[1]}&zoom=17`}
          >
            지도에서 보기
          </AppLink>
          <AppLink
            className="primary-action"
            currentPath={currentPath}
            runtime={runtime}
            to={`/buildings/${data.buildingId}/report`}
          >
            건물 분석 보고서
          </AppLink>
        </div>
      </div>
      {showSldAnalysis ? <SldAnalysisPanel buildingId={buildingId} runtime={runtime} /> : null}
      <aside className="analysis-contract-note">
        기준 위험도는 v27.1 · 2026-03 · 향후 60일 광주·전남 상대순위입니다. 현재 신호는 기준점수를
        변경하지 않습니다.
      </aside>
      <section className="analysis-metrics building-metrics" aria-label="건물 핵심 지표">
        <article className={data.risk.riskBand === "TOP_1" ? "signal" : ""}>
          <span>위험구간</span>
          <strong>{riskNames[data.risk.riskBand]}</strong>
          <small>상위 {data.risk.topPercentile.toFixed(2)}%</small>
        </article>
        <article>
          <span>광주·전남 순위</span>
          <strong>{data.risk.regionalRank.toLocaleString("ko-KR")}위</strong>
          <small>217,238개 기준</small>
        </article>
        <article>
          <span>상대점수</span>
          <strong>{formatScore(data.risk.finalScore)}</strong>
          <small>발생확률 아님</small>
        </article>
        <article className={data.currentSignals.hasCurrentSignal ? "signal" : ""}>
          <span>100m 내 활성 Case</span>
          <strong>{data.currentSignals.activeCaseCount.toLocaleString("ko-KR")}건</strong>
          <small>긴급 {data.currentSignals.urgentCaseCount.toLocaleString("ko-KR")}건</small>
        </article>
      </section>
      <div className="analysis-two-column building-columns">
        <section className="analysis-panel">
          <div className="analysis-panel-heading">
            <h2>건축물 기준 정보</h2>
            <span>{data.geometryStatus}</span>
          </div>
          <dl className="building-attribute-grid">
            {attributeRows.map(([label, value, suffix]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{displayValue(value, suffix)}</dd>
              </div>
            ))}
          </dl>
        </section>
        <section className="analysis-panel">
          <div className="analysis-panel-heading">
            <h2>연결 설비·점검 정보</h2>
            <span>정규 연결</span>
          </div>
          <dl className="facility-summary">
            <div>
              <dt>연결 설비</dt>
              <dd>{data.facilitySummary.linkedFacilityCount.toLocaleString("ko-KR")}건</dd>
            </div>
            <div>
              <dt>일반용 설비</dt>
              <dd>{data.facilitySummary.generalCount.toLocaleString("ko-KR")}건</dd>
            </div>
            <div>
              <dt>자가용 설비</dt>
              <dd>{data.facilitySummary.selfCount.toLocaleString("ko-KR")}건</dd>
            </div>
            <div>
              <dt>최근 점검일</dt>
              <dd>{displayValue(data.facilitySummary.latestInspectionDate)}</dd>
            </div>
            <div>
              <dt>원천 후보</dt>
              <dd>{data.facilitySummary.candidateSourceCount.toLocaleString("ko-KR")}건</dd>
            </div>
          </dl>
        </section>
      </div>
      <div className="analysis-two-column building-columns">
        <section className="analysis-panel">
          <div className="analysis-panel-heading">
            <h2>위험도 해석</h2>
            <span>{data.risk.sourceClass}</span>
          </div>
          <p className="analysis-explanation">
            이 건물은 광주·전남 모델 대상 217,238개 중{" "}
            {data.risk.regionalRank.toLocaleString("ko-KR")}위이며 {riskNames[data.risk.riskBand]}{" "}
            구간입니다. 점수는 우선 확인 순서를 정하는 상대값이며 사고 발생확률이 아닙니다.
          </p>
          <AppLink
            className="text-action"
            currentPath={currentPath}
            runtime={runtime}
            to={`/regions/${data.region.regionCode}`}
          >
            {data.region.fullName} 지역 분포와 비교
          </AppLink>
        </section>
        <section className="analysis-panel">
          <div className="analysis-panel-heading">
            <h2>데이터 품질</h2>
            <span>{qualityFlags.length ? `${qualityFlags.length}개 표시` : "확인됨"}</span>
          </div>
          {qualityFlags.length ? (
            <ul className="quality-flags">
              {qualityFlags.map((flag) => (
                <li key={flag}>{flag}</li>
              ))}
            </ul>
          ) : (
            <p className="analysis-explanation">
              건물·위험도 기준 데이터에 별도 품질 경고가 없습니다.
            </p>
          )}
          <p className="lineage-copy">
            건물키 {data.sourceBuildingKey} · 계보 {data.risk.manifestHash.slice(0, 12)}…
          </p>
        </section>
      </div>
      <section className="analysis-actions">
        <div>
          <h2>분석 결과로 할 수 있는 작업</h2>
          <p>이 건물과 실제 기준정보가 다음 업무의 초기 조건으로 전달됩니다.</p>
        </div>
        <div>
          <AppLink
            className="outline-action"
            currentPath={currentPath}
            runtime={runtime}
            to={`/inspections/simulations/new?building=${data.buildingId}`}
          >
            점검 시뮬레이션
          </AppLink>
          <AppLink
            className="outline-action"
            currentPath={currentPath}
            runtime={runtime}
            to={`/similar/incidents?building=${data.buildingId}`}
          >
            유사 화재 검색
          </AppLink>
          <StandaloneDocumentButton
            className="outline-action"
            runtime={runtime}
            targetId={data.buildingId}
            variant="INSPECTION_REQUEST"
          >
            현장점검 요청 작성
          </StandaloneDocumentButton>
          <AppLink
            className="primary-action"
            currentPath={currentPath}
            runtime={runtime}
            to={`/buildings/${data.buildingId}/report`}
          >
            건물 분석 보고서
          </AppLink>
        </div>
      </section>
    </main>
  );
}

function ReportPreview({
  currentPath,
  runtime,
  kind,
  targetId,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
  kind: "region" | "building";
  targetId: string;
}) {
  const region = useQuery({
    queryKey: ["analysis-report-region", runtime.profile, targetId],
    queryFn: () =>
      apiRequest<RegionDetailData>(runtime, `/regions/${targetId}`).then((result) => result.data),
    enabled: kind === "region",
    staleTime: 5 * 60_000,
  });
  const building = useQuery({
    queryKey: ["analysis-report-building", runtime.profile, targetId],
    queryFn: () =>
      apiRequest<BuildingDetailData>(runtime, `/buildings/${targetId}`).then(
        (result) => result.data,
      ),
    enabled: kind === "building",
    staleTime: 5 * 60_000,
  });
  const activeQuery = kind === "region" ? region : building;
  if (activeQuery.isLoading) return <AnalysisLoading />;
  if (activeQuery.isError) return <AnalysisError retry={() => void activeQuery.refetch()} />;

  const regionData = kind === "region" ? region.data : undefined;
  const buildingData = kind === "building" ? building.data : undefined;
  if (!regionData && !buildingData)
    return <AnalysisError retry={() => void activeQuery.refetch()} />;

  const title = regionData
    ? `${regionData.fullName} 전기재해 예방 위험 분석 보고서`
    : `${buildingData?.name} 전기재해 예방 위험 분석 보고서`;
  const backTarget = regionData
    ? `/regions/${regionData.regionCode}`
    : `/buildings/${buildingData?.buildingId}`;
  const currentSignals = regionData?.currentSignals ?? buildingData?.currentSignals;
  return (
    <main className="page analysis-page report-page" id="main-content">
      <AppLink
        className="analysis-back"
        currentPath={currentPath}
        runtime={runtime}
        to={backTarget}
      >
        ‹ 분석 화면으로 돌아가기
      </AppLink>
      <div className="page-heading analysis-heading">
        <div>
          <h1>{regionData ? "지역 분석 보고서" : "건물 분석 보고서"}</h1>
          <p>실제 기준 데이터와 현재 관제 상태를 검토하고 문서 초안 범위를 확인합니다.</p>
        </div>
        <span className="evidence-badge insufficient">근거 부족 · 검토 필요</span>
      </div>
      <div className="report-layout">
        <article className="report-preview-card">
          <div className="analysis-panel-heading">
            <div>
              <h2>보고서 미리보기</h2>
              <p>v27.1 · 2026-03 · 향후 60일 광주·전남 상대위험 기준</p>
            </div>
            <span>검토용 초안</span>
          </div>
          <section className="report-paper" aria-label="분석 보고서 미리보기">
            <header>
              <p>한국전기안전공사 · 내부 업무용</p>
              <h2>{title}</h2>
              <dl>
                <div>
                  <dt>작성자</dt>
                  <dd>미입력</dd>
                </div>
                <div>
                  <dt>승인자</dt>
                  <dd>미입력</dd>
                </div>
                <div>
                  <dt>문서번호</dt>
                  <dd>미입력</dd>
                </div>
              </dl>
            </header>
            {regionData ? (
              <>
                <div className="report-kpis">
                  <div>
                    <span>분석 건물</span>
                    <strong>
                      {regionData.distribution.buildingCount.toLocaleString("ko-KR")}개
                    </strong>
                  </div>
                  <div>
                    <span>상위 10% 건물</span>
                    <strong>{regionData.distribution.top10Count.toLocaleString("ko-KR")}개</strong>
                  </div>
                  <div>
                    <span>p99 상대점수</span>
                    <strong>{formatScore(regionData.distribution.scoreStats.p99)}</strong>
                  </div>
                </div>
                <ReportSection number="01" title="분석 범위">
                  {regionData.fullName}의 모델 대상 건물{" "}
                  {regionData.distribution.buildingCount.toLocaleString("ko-KR")}개를 광주·전남 전체
                  순위와 네 위험구간으로 비교했습니다. 점수는 사고 발생확률이 아닙니다.
                </ReportSection>
                <ReportSection number="02" title="위험구간 분포">
                  최상위 위험 {regionData.distribution.bands.top1.toLocaleString("ko-KR")}개, 고위험{" "}
                  {regionData.distribution.bands.high1To10.toLocaleString("ko-KR")}개, 관심{" "}
                  {regionData.distribution.bands.watch10To25.toLocaleString("ko-KR")}개, 일반{" "}
                  {regionData.distribution.bands.general.toLocaleString("ko-KR")}개입니다.
                </ReportSection>
                <ReportSection number="03" title="우선 확인 대상">
                  {regionData.topBuildings.slice(0, 5).map((item) => (
                    <span className="report-list-item" key={item.buildingId}>
                      {item.name} · 광주·전남 {item.risk.regionalRank.toLocaleString("ko-KR")}위 ·{" "}
                      {riskNames[item.risk.riskBand]}
                    </span>
                  ))}
                </ReportSection>
              </>
            ) : buildingData ? (
              <>
                <div className="report-kpis">
                  <div>
                    <span>위험구간</span>
                    <strong>{riskNames[buildingData.risk.riskBand]}</strong>
                  </div>
                  <div>
                    <span>광주·전남 순위</span>
                    <strong>{buildingData.risk.regionalRank.toLocaleString("ko-KR")}위</strong>
                  </div>
                  <div>
                    <span>상대점수</span>
                    <strong>{formatScore(buildingData.risk.finalScore)}</strong>
                  </div>
                </div>
                <ReportSection number="01" title="대상 건물">
                  {buildingData.name} · {buildingData.roadAddress ?? buildingData.lotAddress} ·{" "}
                  {buildingData.region.fullName}
                </ReportSection>
                <ReportSection number="02" title="건축물·설비 현황">
                  주용도 {displayValue(buildingData.attributes.mainUseName)}, 주구조{" "}
                  {displayValue(buildingData.attributes.mainStructure)}, 건물연령{" "}
                  {displayValue(buildingData.attributes.buildingAge, "년")}, 연결 설비{" "}
                  {buildingData.facilitySummary.linkedFacilityCount.toLocaleString("ko-KR")}
                  건입니다.
                </ReportSection>
                <ReportSection number="03" title="우선 확인 항목">
                  <span className="report-list-item">
                    기준 위험구간과 현장 설비 현황의 일치 여부 확인
                  </span>
                  <span className="report-list-item">연결 설비 목록과 최근 점검 이력 확인</span>
                  {buildingData.facilitySummary.latestInspectionDate ? (
                    <span className="report-list-item">
                      최근 등록 점검일 {buildingData.facilitySummary.latestInspectionDate} 이후
                      변경사항 확인
                    </span>
                  ) : (
                    <span className="report-list-item warning">
                      최근 점검일 미등록 · 사용자 확인 필요
                    </span>
                  )}
                </ReportSection>
              </>
            ) : null}
            <ReportSection number="04" title="현재 관제 상태">
              {currentSignals?.hasCurrentSignal
                ? `연결된 활성 Case ${currentSignals.activeCaseCount.toLocaleString("ko-KR")}건, 긴급 ${currentSignals.urgentCaseCount.toLocaleString("ko-KR")}건을 별도 확인해야 합니다.`
                : "현재 연결된 관제 Case가 없습니다. 기준 위험도만으로 실상황이 발생했다고 해석하지 않습니다."}
            </ReportSection>
            <ReportSection number="05" title="대응 근거 상태">
              <span className="report-list-item warning">
                공식 매뉴얼·과거 사고 인용이 아직 연결되지 않아 대응 조치의 근거가 부족합니다. 근거
                연결 전에는 사실·분포 미리보기로만 사용합니다.
              </span>
            </ReportSection>
          </section>
        </article>
        <aside className="report-settings-card">
          <h2>문서 생성 계약</h2>
          <p>검토가 끝난 같은 승인 버전에서 두 형식을 함께 생성합니다.</p>
          <dl>
            <div>
              <dt>필수 출력</dt>
              <dd>HWPX + PDF</dd>
            </div>
            <div>
              <dt>문서 상태</dt>
              <dd>승인 전 검토용</dd>
            </div>
            <div>
              <dt>개인정보</dt>
              <dd>자동 추정 안 함</dd>
            </div>
            <div>
              <dt>작성자·승인자</dt>
              <dd>사용자 입력 전 빈칸</dd>
            </div>
            <div>
              <dt>보관 위치</dt>
              <dd>보고서·산출물</dd>
            </div>
          </dl>
          <div className="report-warning" role="status">
            근거가 부족해도 초안은 만들되 문서와 화면에 경고를 유지합니다. 허위 인용은 생성하지
            않습니다.
          </div>
          <StandaloneDocumentButton
            className="primary-action"
            runtime={runtime}
            targetId={targetId}
            variant={regionData ? "REGION_ANALYSIS" : "BUILDING_ANALYSIS"}
          >
            분석 보고서 초안 만들기
          </StandaloneDocumentButton>
          <AppLink
            className="outline-action"
            currentPath={currentPath}
            runtime={runtime}
            to="/artifacts"
          >
            문서·산출물 보관함 보기
          </AppLink>
          <small>재난 Case가 없어도 현재 분석 대상을 기준으로 독립 문서를 만듭니다.</small>
        </aside>
      </div>
    </main>
  );
}

function ReportSection({
  number,
  title,
  children,
}: {
  number: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="report-section">
      <h3>
        <span>{number}</span>
        {title}
      </h3>
      <div>{children}</div>
    </section>
  );
}
export function SpatialAnalysis({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  if (currentPath === "/regions")
    return <RegionIndex currentPath={currentPath} runtime={runtime} />;
  const regionReportMatch = currentPath.match(/^\/regions\/([^/]+)\/report$/);
  if (regionReportMatch)
    return (
      <ReportPreview
        currentPath={currentPath}
        kind="region"
        runtime={runtime}
        targetId={regionReportMatch[1]}
      />
    );
  const buildingReportMatch = currentPath.match(/^\/buildings\/([^/]+)\/report$/);
  if (buildingReportMatch)
    return (
      <ReportPreview
        currentPath={currentPath}
        kind="building"
        runtime={runtime}
        targetId={buildingReportMatch[1]}
      />
    );
  const regionMatch = currentPath.match(/^\/regions\/([^/]+)$/);
  if (regionMatch)
    return <RegionDetail currentPath={currentPath} runtime={runtime} regionCode={regionMatch[1]} />;
  const buildingMatch = currentPath.match(/^\/buildings\/([^/]+)$/);
  if (buildingMatch)
    return (
      <BuildingDetail buildingId={buildingMatch[1]} currentPath={currentPath} runtime={runtime} />
    );
  return null;
}
