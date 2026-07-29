import { useQuery } from "@tanstack/react-query";
import {
  AttributionControl,
  LngLatBounds,
  Map as MapLibreMap,
  NavigationControl,
  type StyleSpecification,
  setWorkerUrl,
} from "maplibre-gl";
import mapWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { ApiError, apiRequest } from "./api";
import { formatKst } from "./home";
import type { ProfileRuntime } from "./profile";
import { AppLink, navigateInternal } from "./router";

setWorkerUrl(mapWorkerUrl);

interface CaseItem {
  caseId: string;
  caseNumber: string;
  caseType: "FIRE" | "WEATHER_WARNING" | "DISASTER_MESSAGE";
  title: string;
  status: string;
  sourceStatus: string;
  monitoringPriority: "NORMAL" | "ATTENTION" | "URGENT";
  primaryRegion: { regionCode: string; name: string; fullName: string } | null;
  locationPrecision: string | null;
  sources: string[];
  signalCount: number;
  impactBuildingCount: number;
  highRiskBuildingCount: number;
  incidentBuildingCount: number;
  openWorkItemCount: number;
  relationCandidateCount: number;
  openedAt: string;
  updatedAt: string;
  sourceResolvedAt: string | null;
  isSimulated: boolean;
  scenarioId: string | null;
  version: number;
}

interface CaseListData {
  summary: {
    total: number;
    open: number;
    sourceResolvedReview: number;
    urgent: number;
    simulated: number;
  };
  items: CaseItem[];
  page: number;
  pageSize: number;
  total: number;
  dataAsOf: string | null;
}

interface CaseSignal {
  signalEventId: string;
  source: string;
  externalId: string;
  eventType: string;
  eventSubtype: string | null;
  severity: string | null;
  sourceStatus: string;
  title: string;
  summary: string | null;
  sourcePublishedAt: string | null;
  effectiveAt: string | null;
  expiresAt: string | null;
  address: string | null;
  regionCodes: string[];
  regionNames: string[];
  locationPrecision: string | null;
  isRelevant: boolean;
  version: number;
  updatedAt: string;
  linkType: string;
}

interface CaseDetailData extends CaseItem {
  normalizedAddress: string | null;
  location: { type: "Point"; coordinates: [number, number] } | null;
  closeReason: string | null;
  closedAt: string | null;
  impactScope: {
    impactScopeId: string;
    scopeType: "RADIUS" | "ADMIN_REGION";
    center: { type: "Point"; coordinates: [number, number] } | null;
    radiusM: number | null;
    regionCodes: string[];
    precisionWarning: string | null;
    ruleVersion: string;
    calculatedAt: string;
  } | null;
  workItemCount: number;
  signals: CaseSignal[];
  relations: Array<{
    caseRelationId: string;
    sourceCaseId: string;
    sourceCaseNumber: string;
    targetCaseId: string;
    targetCaseNumber: string;
    relationType: string;
    evidence: Record<string, unknown>;
    createdAt: string;
    resolvedAt: string | null;
  }>;
  riskReference: {
    referenceMonth: string;
    horizonDays: number;
    lineageVersion: string;
    isProbability: false;
  };
}

interface ImpactBuilding {
  buildingId: string;
  sourceBuildingKey: string;
  regionCode: string;
  name: string;
  roadAddress: string | null;
  lotAddress: string;
  centroid: [number, number];
  matchReason: "EXACT" | "RADIUS" | "ADMIN_REGION";
  distanceM: number | null;
  isIncidentBuilding: boolean;
  isHighRisk: boolean;
  priorityOrder: number;
  risk: {
    referenceMonth: string;
    horizonDays: number;
    finalScore: number;
    regionalRank: number;
    topPercentile: number;
    riskBand: string;
    lineageVersion: string;
    isProbability: false;
  };
}

interface ImpactData {
  summary: {
    impactBuildings: number;
    highRiskBuildings: number;
    incidentBuildings: number;
  };
  scope: {
    impactScopeId: string;
    scopeType: "RADIUS" | "ADMIN_REGION";
    radiusM: number | null;
    regionCodes: string[];
    precisionWarning: string | null;
  } | null;
  items: ImpactBuilding[];
  filters: {
    riskThreshold: number | null;
    incidentOnly: boolean;
    search: string | null;
    sort: string;
  };
  page: number;
  pageSize: number;
  total: number;
}

interface TimelineData {
  items: Array<{
    occurredAt: string;
    entryType: "SIGNAL_RAW" | "AUDIT" | "WORK_ITEM";
    entryId: string;
    category: string;
    title: string;
    detail: Record<string, unknown>;
  }>;
  page: number;
  pageSize: number;
  total: number;
}

interface MapProvider {
  id: "vworld" | "osm";
  name: string;
  urlTemplate: string;
  attribution: string;
}

interface MapConfigData {
  providers: MapProvider[];
  preferredProvider: "vworld" | "osm";
}

interface CaseFilters {
  status: string;
  caseType: string;
  source: string;
  region: string;
  search: string;
  sort: string;
}

const statusLabels: Record<string, string> = {
  DETECTED: "감지",
  ACTIVE: "대응 중",
  ON_HOLD: "보류",
  SOURCE_RESOLVED_REVIEW: "종료 확인",
  CLOSED: "종료",
  MERGED: "병합",
  UPDATED: "갱신",
  RESOLVED: "해제",
  CANCELLED: "취소",
  CANCELED: "취소",
  EXPIRED: "만료",
  UNKNOWN: "상태 확인 필요",
};

const typeLabels: Record<string, string> = {
  FIRE: "화재 출동",
  WEATHER_WARNING: "기상특보",
  DISASTER_MESSAGE: "재난문자",
};

const sourceLabels: Record<string, string> = {
  NFDS: "전국119상황실",
  KMA_WARNING: "기상특보",
  DISASTER_MESSAGE: "재난문자",
};

const priorityLabels: Record<string, string> = {
  URGENT: "긴급",
  ATTENTION: "주의",
  NORMAL: "일반",
};

const initialFilters = (): CaseFilters => {
  const params = new URLSearchParams(window.location.search);
  return {
    status: params.get("status") ?? "",
    caseType: params.get("caseType") ?? "",
    source: params.get("source") ?? "",
    region: params.get("region") ?? "",
    search: params.get("q") ?? "",
    sort: params.get("sort") ?? "priority",
  };
};

function setCaseListUrl(
  runtime: ProfileRuntime,
  filters: CaseFilters,
  page: number,
  selected: string | null,
) {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.caseType) params.set("caseType", filters.caseType);
  if (filters.source) params.set("source", filters.source);
  if (filters.region) params.set("region", filters.region);
  if (filters.search) params.set("q", filters.search);
  if (filters.sort !== "priority") params.set("sort", filters.sort);
  if (page > 1) params.set("page", String(page));
  if (selected) params.set("selected", selected);
  const query = params.toString();
  navigateInternal(runtime, `/cases${query ? `?${query}` : ""}`, true);
}

function caseListPath(filters: CaseFilters, page: number): string {
  const params = new URLSearchParams({
    page: String(page),
    pageSize: "20",
    sort: filters.sort,
  });
  if (filters.status) params.set("status", filters.status);
  if (filters.caseType) params.set("caseType", filters.caseType);
  if (filters.source) params.set("source", filters.source);
  if (filters.region) params.set("regionCode", filters.region);
  if (filters.search) params.set("search", filters.search);
  return `/cases?${params.toString()}`;
}

function queryMessage(error: Error | null, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function CaseState({ error = false, message }: { error?: boolean; message: string }) {
  return (
    <main className="page case-page" id="main-content">
      <div className={`case-state${error ? " error" : ""}`} role={error ? "alert" : "status"}>
        {message}
      </div>
    </main>
  );
}

function PriorityPill({ priority }: { priority: string }) {
  return (
    <span className={`case-priority ${priority.toLowerCase()}`}>
      {priorityLabels[priority] ?? priority}
    </span>
  );
}

function StatusPill({ status }: { status: string }) {
  return (
    <span className={`case-status ${status.toLowerCase()}`}>{statusLabels[status] ?? status}</span>
  );
}

function CaseList({ currentPath, runtime }: { currentPath: string; runtime: ProfileRuntime }) {
  const params = new URLSearchParams(window.location.search);
  const [draft, setDraft] = useState(initialFilters);
  const [filters, setFilters] = useState(initialFilters);
  const [page, setPage] = useState(Number(params.get("page") ?? 1) || 1);
  const [selectedId, setSelectedId] = useState(params.get("selected"));
  const cases = useQuery({
    queryKey: ["cases", runtime.profile, filters, page],
    queryFn: () =>
      apiRequest<CaseListData>(runtime, caseListPath(filters, page)).then((result) => result.data),
    placeholderData: (previous) => previous,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
  const selected =
    cases.data?.items.find((item) => item.caseId === selectedId) ?? cases.data?.items[0];
  const selectedDetail = useQuery({
    queryKey: ["case-detail-preview", runtime.profile, selected?.caseId],
    queryFn: () =>
      apiRequest<CaseDetailData>(runtime, `/cases/${selected?.caseId}`).then(
        (result) => result.data,
      ),
    enabled: Boolean(selected?.caseId),
    staleTime: 15_000,
  });

  const applyFilters = (event: FormEvent) => {
    event.preventDefault();
    setFilters(draft);
    setPage(1);
    setSelectedId(null);
    setCaseListUrl(runtime, draft, 1, null);
  };
  const choose = (caseId: string) => {
    setSelectedId(caseId);
    setCaseListUrl(runtime, filters, page, caseId);
  };
  const changePage = (next: number) => {
    setPage(next);
    setSelectedId(null);
    setCaseListUrl(runtime, filters, next, null);
  };

  if (cases.isLoading) return <CaseState message="Case 목록을 불러오고 있습니다." />;
  if (cases.isError || !cases.data)
    return (
      <CaseState error message={queryMessage(cases.error, "Case 목록을 불러오지 못했습니다.")} />
    );
  const totalPages = Math.max(1, Math.ceil(cases.data.total / cases.data.pageSize));
  return (
    <main className="page case-page" id="main-content">
      <div className="page-heading case-heading">
        <div>
          <p className="case-breadcrumb">재난 대응 / 자동 감지 Case</p>
          <h1>자동 감지 재난 신호</h1>
          <p>실제 수집 신호와 결정 규칙으로 생성된 Case를 검토합니다.</p>
        </div>
        <span className="case-live-label">30초마다 목록 갱신</span>
      </div>
      <section className="case-summary" aria-label="Case 현황">
        <article>
          <span>전체 Case</span>
          <strong>{cases.data.summary.total.toLocaleString("ko-KR")}건</strong>
        </article>
        <article>
          <span>진행 중</span>
          <strong>{cases.data.summary.open.toLocaleString("ko-KR")}건</strong>
        </article>
        <article className="urgent">
          <span>긴급 관제</span>
          <strong>{cases.data.summary.urgent.toLocaleString("ko-KR")}건</strong>
        </article>
        <article className="review">
          <span>종료 확인</span>
          <strong>{cases.data.summary.sourceResolvedReview.toLocaleString("ko-KR")}건</strong>
        </article>
        <article>
          <span>기준 시각</span>
          <strong>{formatKst(cases.data.dataAsOf)}</strong>
        </article>
      </section>
      <div className="case-list-workspace">
        <section className="case-list-panel panel">
          <div className="case-section-heading">
            <div>
              <h2>Case 목록</h2>
              <p>선택한 Case의 원천·영향 건물·현재 상태를 오른쪽에서 확인합니다.</p>
            </div>
            <span>검색 결과 {cases.data.total.toLocaleString("ko-KR")}건</span>
          </div>
          <form className="case-filters" onSubmit={applyFilters}>
            <select
              aria-label="Case 상태"
              onChange={(event) => setDraft({ ...draft, status: event.target.value })}
              value={draft.status}
            >
              <option value="">상태 전체</option>
              <option value="ACTIVE">대응 중</option>
              <option value="ON_HOLD">보류</option>
              <option value="SOURCE_RESOLVED_REVIEW">종료 확인</option>
              <option value="CLOSED">종료</option>
            </select>
            <select
              aria-label="Case 유형"
              onChange={(event) => setDraft({ ...draft, caseType: event.target.value })}
              value={draft.caseType}
            >
              <option value="">유형 전체</option>
              <option value="FIRE">화재 출동</option>
              <option value="WEATHER_WARNING">기상특보</option>
              <option value="DISASTER_MESSAGE">재난문자</option>
            </select>
            <select
              aria-label="신호 원천"
              onChange={(event) => setDraft({ ...draft, source: event.target.value })}
              value={draft.source}
            >
              <option value="">원천 전체</option>
              <option value="NFDS">전국119상황실</option>
              <option value="KMA_WARNING">기상특보</option>
              <option value="DISASTER_MESSAGE">재난문자</option>
            </select>
            <input
              aria-label="Case 검색"
              maxLength={100}
              onChange={(event) => setDraft({ ...draft, search: event.target.value })}
              placeholder="Case 번호·제목·지역 검색"
              value={draft.search}
            />
            <button type="submit">검색</button>
          </form>
          <div className="case-list-header" aria-hidden="true">
            <span>우선</span>
            <span>Case</span>
            <span>영향</span>
            <span>원천</span>
            <span>상태</span>
          </div>
          {cases.data.items.length === 0 ? (
            <div className="case-empty">
              <strong>조건에 맞는 Case가 없습니다.</strong>
              <span>필터를 바꾸거나 다음 수집 주기를 확인하세요.</span>
            </div>
          ) : (
            <div className="case-rows">
              {cases.data.items.map((item) => (
                <button
                  className={
                    item.caseId === selected?.caseId
                      ? "case-row-button is-selected"
                      : "case-row-button"
                  }
                  key={item.caseId}
                  onClick={() => choose(item.caseId)}
                  type="button"
                >
                  <PriorityPill priority={item.monitoringPriority} />
                  <span className="case-row-main">
                    <strong>{item.title}</strong>
                    <small>
                      {item.caseNumber} · {item.primaryRegion?.fullName ?? "지역 확인 필요"} ·{" "}
                      {formatKst(item.updatedAt)}
                    </small>
                  </span>
                  <span className="case-impact-count">
                    <strong>{item.impactBuildingCount.toLocaleString("ko-KR")}개</strong>
                    <small>고위험 {item.highRiskBuildingCount.toLocaleString("ko-KR")}</small>
                  </span>
                  <span className="case-source-list">
                    {item.sources.map((source) => sourceLabels[source] ?? source).join(" · ") ||
                      "—"}
                  </span>
                  <StatusPill status={item.status} />
                </button>
              ))}
            </div>
          )}
          <div className="case-pagination">
            <span>
              {page} / {totalPages}페이지
            </span>
            <button disabled={page <= 1} onClick={() => changePage(page - 1)} type="button">
              이전
            </button>
            <button
              disabled={page >= totalPages}
              onClick={() => changePage(page + 1)}
              type="button"
            >
              다음
            </button>
          </div>
        </section>
        <aside className="case-preview panel">
          {!selected ? (
            <div className="case-empty">
              <strong>선택할 Case가 없습니다.</strong>
              <span>새 Case가 생성되면 이곳에서 상세 내용을 확인합니다.</span>
            </div>
          ) : selectedDetail.isLoading ? (
            <div className="case-preview-state">선택 Case를 확인하고 있습니다.</div>
          ) : selectedDetail.isError || !selectedDetail.data ? (
            <div className="case-preview-state error">
              {queryMessage(selectedDetail.error, "선택 Case를 불러오지 못했습니다.")}
            </div>
          ) : (
            <>
              <div className="case-preview-top">
                <div>
                  <span>{typeLabels[selectedDetail.data.caseType]}</span>
                  <h2>{selectedDetail.data.title}</h2>
                  <p>
                    {selectedDetail.data.caseNumber} ·{" "}
                    {selectedDetail.data.primaryRegion?.fullName ?? "지역 확인 필요"}
                  </p>
                </div>
                <PriorityPill priority={selectedDetail.data.monitoringPriority} />
              </div>
              <dl className="case-preview-facts">
                <div>
                  <dt>현재 상태</dt>
                  <dd>
                    <StatusPill status={selectedDetail.data.status} />
                  </dd>
                </div>
                <div>
                  <dt>원천 상태</dt>
                  <dd>
                    {statusLabels[selectedDetail.data.sourceStatus] ??
                      selectedDetail.data.sourceStatus}
                  </dd>
                </div>
                <div>
                  <dt>영향 건물</dt>
                  <dd>{selectedDetail.data.impactBuildingCount.toLocaleString("ko-KR")}개</dd>
                </div>
                <div>
                  <dt>고위험 건물</dt>
                  <dd>{selectedDetail.data.highRiskBuildingCount.toLocaleString("ko-KR")}개</dd>
                </div>
                <div>
                  <dt>미완료 업무</dt>
                  <dd>{selectedDetail.data.openWorkItemCount.toLocaleString("ko-KR")}건</dd>
                </div>
                <div>
                  <dt>최근 갱신</dt>
                  <dd>{formatKst(selectedDetail.data.updatedAt)}</dd>
                </div>
              </dl>
              <div className="case-source-box">
                <strong>연결된 원천</strong>
                {selectedDetail.data.signals.map((signal) => (
                  <div key={signal.signalEventId}>
                    <span>{sourceLabels[signal.source] ?? signal.source}</span>
                    <b>{signal.sourceStatus}</b>
                  </div>
                ))}
              </div>
              {selectedDetail.data.impactScope?.precisionWarning ? (
                <div className="case-warning">
                  위치 정밀도가 낮아 확인 가능한 최소 행정구역을 영향 범위로 사용했습니다.
                </div>
              ) : null}
              <AppLink
                className="primary-action case-open-action"
                currentPath={currentPath}
                runtime={runtime}
                to={`/cases/${selected.caseId}`}
              >
                Case 통합 상황판 열기
              </AppLink>
            </>
          )}
        </aside>
      </div>
    </main>
  );
}

function supportsWebGl(): boolean {
  return typeof navigator !== "undefined" && !navigator.userAgent.toLowerCase().includes("jsdom");
}

function impactStyle(
  provider: MapProvider,
  impact: ImpactBuilding[],
  location: [number, number] | null,
): StyleSpecification {
  const sources: StyleSpecification["sources"] = {
    basemap: {
      type: "raster",
      tiles: [provider.urlTemplate],
      tileSize: 256,
      attribution: provider.attribution,
    },
    impact: {
      type: "geojson",
      data: {
        type: "FeatureCollection",
        features: impact.map((item) => ({
          type: "Feature",
          id: item.buildingId,
          geometry: { type: "Point", coordinates: item.centroid },
          properties: {
            buildingId: item.buildingId,
            incident: item.isIncidentBuilding,
            highRisk: item.isHighRisk,
          },
        })),
      },
    },
  };
  if (location) {
    sources.caseLocation = {
      type: "geojson",
      data: {
        type: "Feature",
        geometry: { type: "Point", coordinates: location },
        properties: {},
      },
    };
  }
  const layers: StyleSpecification["layers"] = [
    { id: "basemap", type: "raster", source: "basemap" },
    {
      id: "impact-points",
      type: "circle",
      source: "impact",
      paint: {
        "circle-radius": ["case", ["get", "incident"], 11, 7],
        "circle-color": [
          "case",
          ["get", "incident"],
          "#d52229",
          ["get", "highRisk"],
          "#e56a00",
          "#2873bd",
        ],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 2,
      },
    },
  ];
  if (location) {
    layers.push({
      id: "case-location",
      type: "circle",
      source: "caseLocation",
      paint: {
        "circle-radius": 17,
        "circle-color": "rgba(213,34,41,0.16)",
        "circle-stroke-color": "#d52229",
        "circle-stroke-width": 3,
      },
    });
  }
  return { version: 8, sources, layers };
}

function ImpactMap({
  detail,
  impact,
  runtime,
}: {
  detail: CaseDetailData;
  impact: ImpactBuilding[];
  runtime: ProfileRuntime;
}) {
  const container = useRef<HTMLDivElement>(null);
  const config = useQuery({
    queryKey: ["map-config", runtime.profile],
    queryFn: () => apiRequest<MapConfigData>(runtime, "/map/config").then((result) => result.data),
    staleTime: 5 * 60_000,
  });
  const provider =
    config.data?.providers.find((item) => item.id === config.data?.preferredProvider) ??
    config.data?.providers[0];
  const enabled = supportsWebGl();
  const location = detail.location?.coordinates ?? null;

  useEffect(() => {
    if (!enabled || !provider || !container.current || (!location && impact.length === 0)) return;
    const center = location ?? impact[0].centroid;
    const map = new MapLibreMap({
      container: container.current,
      style: impactStyle(provider, impact, location),
      center,
      zoom: detail.impactScope?.scopeType === "ADMIN_REGION" ? 8 : 13,
      attributionControl: false,
    });
    map.addControl(new NavigationControl({ showCompass: false }), "top-left");
    map.addControl(
      new AttributionControl({
        compact: true,
        customAttribution: provider.attribution,
      }),
      "bottom-right",
    );
    map.on("load", () => {
      const bounds = new LngLatBounds();
      if (location) bounds.extend(location);
      for (const item of impact) bounds.extend(item.centroid);
      if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 55, maxZoom: 15, duration: 0 });
    });
    return () => map.remove();
  }, [detail.impactScope?.scopeType, enabled, impact, location, provider]);

  if (!location && impact.length === 0)
    return <div className="case-map-fallback">표시할 위치 또는 영향 건물이 없습니다.</div>;
  if (!enabled)
    return (
      <div className="case-map-fallback">
        브라우저 지도 대신 오른쪽의 실제 영향 건물 목록을 사용합니다.
      </div>
    );
  if (config.isError)
    return <div className="case-map-fallback">배경지도 설정을 불러오지 못했습니다.</div>;
  return <div className="case-map" ref={container} />;
}

function CaseDetail({
  caseId,
  currentPath,
  runtime,
}: {
  caseId: string;
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const detail = useQuery({
    queryKey: ["case-detail", runtime.profile, caseId],
    queryFn: () =>
      apiRequest<CaseDetailData>(runtime, `/cases/${caseId}`).then((result) => result.data),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
  const impact = useQuery({
    queryKey: ["case-impact", runtime.profile, caseId, 10],
    queryFn: () =>
      apiRequest<ImpactData>(
        runtime,
        `/cases/${caseId}/impact-buildings?page=1&pageSize=100&riskThreshold=10&sort=priority`,
      ).then((result) => result.data),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
  const timeline = useQuery({
    queryKey: ["case-timeline", runtime.profile, caseId],
    queryFn: () =>
      apiRequest<TimelineData>(runtime, `/cases/${caseId}/timeline?page=1&pageSize=20`).then(
        (result) => result.data,
      ),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  if (detail.isLoading) return <CaseState message="Case 통합 상황판을 준비하고 있습니다." />;
  if (detail.isError || !detail.data)
    return (
      <CaseState
        error
        message={queryMessage(detail.error, "Case 통합 상황판을 불러오지 못했습니다.")}
      />
    );
  const item = detail.data;
  const scopeLabel =
    item.impactScope?.scopeType === "RADIUS"
      ? `반경 ${(item.impactScope.radiusM ?? 0).toLocaleString("ko-KR")}m`
      : item.impactScope?.regionCodes.length
        ? `행정구역 ${item.impactScope.regionCodes.join(", ")}`
        : "영향 범위 미확정";
  return (
    <main className="page case-page case-detail-page" id="main-content">
      <AppLink className="analysis-back" currentPath={currentPath} runtime={runtime} to="/cases">
        ‹ Case 목록으로 돌아가기
      </AppLink>
      <div className="page-heading case-heading">
        <div>
          <p className="case-breadcrumb">재난 대응 / 초동대응 통합 상황판</p>
          <h1>{item.title}</h1>
          <p>
            {item.caseNumber} · {item.primaryRegion?.fullName ?? "지역 확인 필요"} · 최근 갱신{" "}
            {formatKst(item.updatedAt)}
          </p>
        </div>
        <div className="case-heading-badges">
          <PriorityPill priority={item.monitoringPriority} />
          <StatusPill status={item.status} />
        </div>
      </div>
      <section className="case-detail-summary">
        <article>
          <span>사건 유형</span>
          <strong>{typeLabels[item.caseType] ?? item.caseType}</strong>
        </article>
        <article>
          <span>현재 단계</span>
          <strong>{statusLabels[item.status] ?? item.status}</strong>
        </article>
        <article>
          <span>영향 범위</span>
          <strong>{scopeLabel}</strong>
        </article>
        <article>
          <span>영향 건물</span>
          <strong>{item.impactBuildingCount.toLocaleString("ko-KR")}개</strong>
        </article>
        <article>
          <span>미완료 업무</span>
          <strong>{item.openWorkItemCount.toLocaleString("ko-KR")}건</strong>
        </article>
      </section>
      {item.impactScope?.precisionWarning ? (
        <div className="case-warning case-detail-warning">
          위치 정밀도가 낮습니다. 표시 범위는 피해 예측이 아니라 관련 건물 확인을 위한 운영 검색
          범위입니다.
        </div>
      ) : null}
      <div className="case-detail-grid">
        <section className="panel case-map-panel">
          <div className="case-section-heading">
            <div>
              <h2>사건 위치·영향 건물</h2>
              <p>실제 배경지도와 현재 페이지의 실제 건물 좌표입니다.</p>
            </div>
            <div className="case-map-legend">
              <span className="incident">사건 건물</span>
              <span className="high">상위 10%</span>
              <span className="impact">영향 건물</span>
            </div>
          </div>
          {impact.isError ? (
            <div className="case-map-fallback">
              {queryMessage(impact.error, "영향 건물을 불러오지 못했습니다.")}
            </div>
          ) : (
            <ImpactMap detail={item} impact={impact.data?.items ?? []} runtime={runtime} />
          )}
        </section>
        <section className="panel case-impact-panel">
          <div className="case-section-heading">
            <div>
              <h2>관제 우선 건물</h2>
              <p>사건 건물 우선, 이후 고정 v27.1 점수 순입니다.</p>
            </div>
            <span>상위 10% 필터</span>
          </div>
          {impact.isLoading ? (
            <div className="case-inline-state">영향 건물을 확인하고 있습니다.</div>
          ) : impact.isError || !impact.data ? (
            <div className="case-inline-state error">
              {queryMessage(impact.error, "영향 건물을 불러오지 못했습니다.")}
            </div>
          ) : impact.data.items.length === 0 ? (
            <div className="case-empty">
              <strong>표시할 영향 건물이 없습니다.</strong>
              <span>위치 정밀도와 기준 건물 데이터 상태를 확인하세요.</span>
            </div>
          ) : (
            <ol className="case-impact-list">
              {impact.data.items.slice(0, 10).map((building) => (
                <li key={building.buildingId}>
                  <span>{building.priorityOrder}</span>
                  <div>
                    <strong>{building.name}</strong>
                    <small>{building.roadAddress ?? building.lotAddress}</small>
                  </div>
                  <div>
                    <b className="case-impact-basis">
                      {building.isIncidentBuilding
                        ? "사건 건물"
                        : `상위 ${building.risk.topPercentile.toFixed(2)}%`}
                    </b>
                    <small>
                      {building.distanceM === null
                        ? "행정구역 영향"
                        : `${building.distanceM.toLocaleString("ko-KR")}m`}
                    </small>
                  </div>
                  <AppLink
                    className="text-action"
                    currentPath={currentPath}
                    runtime={runtime}
                    to={`/buildings/${building.buildingId}`}
                  >
                    건물 분석
                  </AppLink>
                </li>
              ))}
            </ol>
          )}
          {impact.data ? (
            <p className="case-impact-caption">
              영향 {impact.data.summary.impactBuildings.toLocaleString("ko-KR")}개 · 고위험{" "}
              {impact.data.summary.highRiskBuildings.toLocaleString("ko-KR")}개 · 현재 필터{" "}
              {impact.data.total.toLocaleString("ko-KR")}개
            </p>
          ) : null}
        </section>
      </div>
      <div className="case-lower-grid">
        <section className="panel case-signal-panel">
          <div className="case-section-heading">
            <div>
              <h2>연결 신호·원천 상태</h2>
              <p>원천 ID와 최신 상태를 보존합니다.</p>
            </div>
            <span>{item.signals.length}개 신호</span>
          </div>
          {item.signals.map((signal) => (
            <article key={signal.signalEventId}>
              <div>
                <strong>{sourceLabels[signal.source] ?? signal.source}</strong>
                <span>{signal.externalId}</span>
              </div>
              <p>{signal.title}</p>
              <div>
                <StatusPill status={signal.sourceStatus} />
                <time>{formatKst(signal.sourcePublishedAt ?? signal.updatedAt)}</time>
              </div>
            </article>
          ))}
        </section>
        <section className="panel case-timeline-panel">
          <div className="case-section-heading">
            <div>
              <h2>Case 타임라인</h2>
              <p>원문 수신·결정·업무 이력을 시간순으로 확인합니다.</p>
            </div>
            <span>{timeline.data?.total ?? 0}건</span>
          </div>
          {timeline.isLoading ? (
            <div className="case-inline-state">타임라인을 불러오고 있습니다.</div>
          ) : timeline.isError || !timeline.data ? (
            <div className="case-inline-state error">
              {queryMessage(timeline.error, "타임라인을 불러오지 못했습니다.")}
            </div>
          ) : timeline.data.items.length === 0 ? (
            <div className="case-empty">
              <strong>기록된 타임라인이 없습니다.</strong>
            </div>
          ) : (
            <ol className="case-timeline">
              {timeline.data.items.slice(0, 8).map((entry) => (
                <li key={`${entry.entryType}-${entry.entryId}`}>
                  <span className={entry.entryType.toLowerCase()} />
                  <div>
                    <strong>{entry.title}</strong>
                    <small>
                      {entry.entryType} · {entry.category}
                    </small>
                  </div>
                  <time>{formatKst(entry.occurredAt)}</time>
                </li>
              ))}
            </ol>
          )}
        </section>
        <aside className="panel case-next-actions">
          <div className="case-contract-note">
            <strong>표시 기준</strong>
            <span>
              영향 범위는 신호와의 관련 범위입니다. 모델 고위험 여부와 서로 다른 정보이며,
              final_score는 발생확률이 아닙니다.
            </span>
          </div>
          <div className="case-contract-note">
            <strong>원천 상태와 Case 상태</strong>
            <span>
              원천이 해제되어도 Case는 자동 종료되지 않습니다. 종료 확인 상태에서 사용자가
              검토합니다.
            </span>
          </div>
        </aside>
      </div>
    </main>
  );
}

export function CaseManagement({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  if (currentPath === "/cases") return <CaseList currentPath={currentPath} runtime={runtime} />;
  const detailMatch = currentPath.match(/^\/cases\/([0-9a-f-]+)$/i);
  if (detailMatch)
    return <CaseDetail caseId={detailMatch[1]} currentPath={currentPath} runtime={runtime} />;
  return <CaseState error message="지원하지 않는 Case 화면입니다." />;
}
