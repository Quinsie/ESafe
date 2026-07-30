import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useMemo, useState } from "react";
import { apiRequest } from "./api";
import { type NaverMapConfigData, type NaverPoint, NaverPointMap } from "./naver_maps";
import type { ProfileRuntime } from "./profile";
import { AppLink, navigateInternal } from "./router";

interface MatchComponent {
  code: string;
  label: string;
  points: number;
  maximum: number;
  detail: string;
}

interface ConditionMatch {
  score: number;
  isProbability: false;
  components: MatchComponent[];
}

interface Incident {
  incidentId: string;
  reportedOn: string | null;
  title: string;
  sourceFamily: "GENERAL" | "MAJOR";
  incidentType: string;
  region: { sidoName: string | null; sigunguName: string | null };
  facilityType: string;
  causeCategories: string[];
  damageCategories: string[];
  actionCategories: string[];
  equipmentCategories: string[];
  evidenceQuality: {
    status: "DERIVED_STRUCTURED" | "METADATA_ONLY";
    label: string;
    historicalExampleOnly: true;
    qualityFlags: string[];
  };
  conditionMatch: ConditionMatch | null;
}

interface IncidentSearchData {
  items: Incident[];
  pagination: { page: number; pageSize: number; total: number; totalPages: number };
  selection: {
    explicitRegion: { region_code: string; full_name: string } | null;
    case: { caseId: string; caseNumber: string; title: string; status: string } | null;
    building: {
      buildingId: string;
      name: string;
      regionName: string;
      mainUseName: string | null;
      inferredFromCase: boolean;
    } | null;
  };
}

interface Candidate {
  buildingId: string;
  name: string;
  roadAddress: string | null;
  lotAddress: string;
  region: { regionCode: string; fullName: string };
  center: [number, number];
  attributes: {
    mainUseName: string | null;
    mainStructure: string | null;
    buildingYear: string | null;
  };
  conditionMatch: ConditionMatch;
  risk: {
    finalScore: number;
    regionalRank: number;
    topPercentile: number;
    riskBand: string;
    isProbability: false;
  };
  inspectionPriority: { level: string; basis: string };
  facilitySummary: { linkedFacilityCount: number; latestInspectionDate: string | null };
}

interface CandidateData {
  referenceIncident: Incident;
  items: Candidate[];
  pagination: { page: number; pageSize: number; total: number; totalPages: number };
  ordering: string[];
}

interface ComparisonData {
  referenceIncident: Incident;
  candidateBuilding: Omit<Candidate, "conditionMatch" | "inspectionPriority">;
  conditionMatch: ConditionMatch;
  inspectionPriority: { level: string; riskBand: string; separateFromConditionMatch: true };
  inspectionChecklist: Array<{ code: string; label: string; basis: string }>;
  evidence: {
    status: "INSUFFICIENT";
    warning: string;
    historicalExampleOnly: true;
    requiresOfficialEvidence: true;
  };
}

type MapConfigData = NaverMapConfigData;

interface RegionCollection {
  features: Array<{ properties: { regionCode: string; fullName: string } }>;
}

interface IncidentFilters {
  region: string;
  from: string;
  to: string;
  incidentType: string;
  facilityType: string;
  damage: string;
  query: string;
  sort: string;
}

const facilityTypes = [
  "공동주택",
  "단독주택",
  "근린생활시설",
  "공장",
  "창고시설",
  "동식물 관련시설",
  "판매시설",
  "숙박시설",
  "의료시설",
  "교육연구시설",
  "자동차 관련시설",
  "종교시설",
  "발전시설",
  "ESS",
  "데이터센터",
  "기타 건축물",
];

const riskLabels: Record<string, string> = {
  TOP_1: "최상위 위험",
  HIGH_1_10: "고위험",
  WATCH_10_25: "관심",
  GENERAL: "일반",
};

const priorityLabels: Record<string, string> = {
  URGENT: "긴급 확인",
  HIGH: "우선 확인",
  ATTENTION: "관심 확인",
  NORMAL: "일반 확인",
};

function initialFilters(): IncidentFilters {
  const params = new URLSearchParams(window.location.search);
  return {
    region: params.get("region") ?? "",
    from: params.get("from") ?? "",
    to: params.get("to") ?? "",
    incidentType: params.get("incidentType") ?? "",
    facilityType: params.get("facilityType") ?? "",
    damage: params.get("damage") ?? "",
    query: params.get("q") ?? "",
    sort: params.get("sort") ?? (params.has("building") || params.has("case") ? "match" : "recent"),
  };
}

function setUrl(runtime: ProfileRuntime, path: string, values: Record<string, string | null>) {
  const params = new URLSearchParams(window.location.search);
  for (const [key, value] of Object.entries(values)) {
    if (value) params.set(key, value);
    else params.delete(key);
  }
  navigateInternal(runtime, `${path}?${params.toString()}`, true);
}

function formatDate(value: string | null): string {
  return value ? value.replaceAll("-", ".") : "발생일 미확인";
}

function formatList(values: string[], empty = "분류된 항목 없음"): string {
  return values.length ? values.join(" · ") : empty;
}

function matchLabel(match: ConditionMatch | null): string {
  return match ? `${match.score}점` : "참조 조건 없음";
}

function SimilarityState({ message, error = false }: { message: string; error?: boolean }) {
  return (
    <main className="page similarity-page" id="main-content">
      <div className={`similarity-state${error ? " error" : ""}`} role={error ? "alert" : "status"}>
        {message}
      </div>
    </main>
  );
}

function useRegions(runtime: ProfileRuntime) {
  return useQuery({
    queryKey: ["similarity-regions", runtime.profile],
    queryFn: async () => {
      const [provinces, gwangju, jeonnam] = await Promise.all([
        apiRequest<RegionCollection>(runtime, "/map/regions"),
        apiRequest<RegionCollection>(runtime, "/map/districts?parentCode=29"),
        apiRequest<RegionCollection>(runtime, "/map/districts?parentCode=46"),
      ]);
      return [...provinces.data.features, ...gwangju.data.features, ...jeonnam.data.features].map(
        (item) => item.properties,
      );
    },
    staleTime: 5 * 60_000,
  });
}

function IncidentSearch({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const baseParams = new URLSearchParams(window.location.search);
  const building = baseParams.get("building");
  const caseId = baseParams.get("case");
  const [draft, setDraft] = useState(initialFilters);
  const [filters, setFilters] = useState(initialFilters);
  const [page, setPage] = useState(Number(baseParams.get("page") ?? 1) || 1);
  const [selectedId, setSelectedId] = useState(baseParams.get("referenceIncident"));
  const regions = useRegions(runtime);
  const requestParams = new URLSearchParams({
    page: String(page),
    pageSize: "20",
    sort: filters.sort,
  });
  if (building) requestParams.set("building", building);
  if (caseId) requestParams.set("case", caseId);
  if (filters.region) requestParams.set("region", filters.region);
  if (filters.from) requestParams.set("from", filters.from);
  if (filters.to) requestParams.set("to", filters.to);
  if (filters.incidentType) requestParams.set("incidentType", filters.incidentType);
  if (filters.facilityType) requestParams.set("facilityType", filters.facilityType);
  if (filters.damage) requestParams.set("damage", filters.damage);
  if (filters.query.trim()) requestParams.set("q", filters.query.trim());
  const incidents = useQuery({
    queryKey: ["similar-incidents", runtime.profile, requestParams.toString()],
    queryFn: () =>
      apiRequest<IncidentSearchData>(
        runtime,
        `/similar/incidents?${requestParams.toString()}`,
      ).then((result) => result.data),
    placeholderData: (previous) => previous,
    staleTime: 60_000,
  });
  const selected =
    incidents.data?.items.find((item) => item.incidentId === selectedId) ??
    incidents.data?.items[0];

  const applyFilters = (event: FormEvent) => {
    event.preventDefault();
    setFilters(draft);
    setPage(1);
    setUrl(runtime, "/similar/incidents", {
      region: draft.region,
      from: draft.from,
      to: draft.to,
      incidentType: draft.incidentType,
      facilityType: draft.facilityType,
      damage: draft.damage,
      q: draft.query.trim(),
      sort: draft.sort,
      page: "1",
      referenceIncident: null,
    });
    setSelectedId(null);
  };

  const resetFilters = () => {
    const reset = {
      ...initialFilters(),
      region: "",
      from: "",
      to: "",
      incidentType: "",
      facilityType: "",
      damage: "",
      query: "",
      sort: building || caseId ? "match" : "recent",
    };
    setDraft(reset);
    setFilters(reset);
    setPage(1);
    setSelectedId(null);
    setUrl(runtime, "/similar/incidents", {
      region: null,
      from: null,
      to: null,
      incidentType: null,
      facilityType: null,
      damage: null,
      q: null,
      sort: reset.sort,
      page: "1",
      referenceIncident: null,
    });
  };

  const chooseIncident = (incidentId: string) => {
    setSelectedId(incidentId);
    setUrl(runtime, "/similar/incidents", { referenceIncident: incidentId, page: String(page) });
  };

  const changePage = (next: number) => {
    setPage(next);
    setSelectedId(null);
    setUrl(runtime, "/similar/incidents", { page: String(next), referenceIncident: null });
  };

  return (
    <main className="page similarity-page" id="main-content">
      <div className="page-heading similarity-heading">
        <div>
          <h1>과거 사고사례 검색</h1>
          <p>비식별 파생정보에서 현재 건물·지역 조건과 가까운 과거 사례를 찾습니다.</p>
        </div>
        <span className="similarity-contract">조건 정합도 · 발생확률 아님</span>
      </div>
      {incidents.data?.selection.building || incidents.data?.selection.case ? (
        <aside className="similarity-context">
          <strong>현재 비교 기준</strong>
          {incidents.data.selection.building ? (
            <span>
              건물 {incidents.data.selection.building.name} ·{" "}
              {incidents.data.selection.building.regionName} ·{" "}
              {incidents.data.selection.building.mainUseName ?? "용도 미등록"}
            </span>
          ) : null}
          {incidents.data.selection.case ? (
            <span>
              Case {incidents.data.selection.case.caseNumber} ·{" "}
              {incidents.data.selection.case.title}
            </span>
          ) : null}
        </aside>
      ) : null}
      <form className="similarity-filters" onSubmit={applyFilters}>
        <label>
          <span>발생 시작일</span>
          <input
            type="date"
            value={draft.from}
            onChange={(event) => setDraft({ ...draft, from: event.target.value })}
          />
        </label>
        <label>
          <span>발생 종료일</span>
          <input
            type="date"
            value={draft.to}
            onChange={(event) => setDraft({ ...draft, to: event.target.value })}
          />
        </label>
        <label>
          <span>지역</span>
          <select
            value={draft.region}
            onChange={(event) => setDraft({ ...draft, region: event.target.value })}
          >
            <option value="">광주·전남 및 전국 사례</option>
            {regions.data?.map((region) => (
              <option key={region.regionCode} value={region.regionCode}>
                {region.fullName}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>시설 용도</span>
          <select
            value={draft.facilityType}
            onChange={(event) => setDraft({ ...draft, facilityType: event.target.value })}
          >
            <option value="">전체</option>
            {facilityTypes.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          <span>사고 유형</span>
          <select
            value={draft.incidentType}
            onChange={(event) => setDraft({ ...draft, incidentType: event.target.value })}
          >
            <option value="">전체</option>
            {["화재", "감전", "정전", "설비사고", "기타사고"].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          <span>피해 분류</span>
          <select
            value={draft.damage}
            onChange={(event) => setDraft({ ...draft, damage: event.target.value })}
          >
            <option value="">전체</option>
            {[
              "인명피해 없음",
              "인명피해 보고",
              "재산피해 없음",
              "재산피해 보고",
              "건물 전소",
              "건물 반소",
              "건물 일부 소실",
            ].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label className="similarity-search-field">
          <span>검색어</span>
          <input
            maxLength={80}
            placeholder="지역·시설·원인·설비 범주 검색"
            value={draft.query}
            onChange={(event) => setDraft({ ...draft, query: event.target.value })}
          />
        </label>
        <label>
          <span>정렬</span>
          <select
            value={draft.sort}
            onChange={(event) => setDraft({ ...draft, sort: event.target.value })}
          >
            <option value="recent">최근 발생 순</option>
            <option value="oldest">오래된 순</option>
            <option value="match" disabled={!building && !caseId}>
              조건 정합도 순
            </option>
          </select>
        </label>
        <button className="primary-action" type="submit">
          검색
        </button>
        <button className="outline-action" onClick={resetFilters} type="button">
          초기화
        </button>
      </form>
      {incidents.isLoading ? (
        <div className="similarity-inline-state">사고사례를 불러오고 있습니다.</div>
      ) : null}
      {incidents.isError ? (
        <div className="similarity-inline-state error">사고사례를 불러오지 못했습니다.</div>
      ) : null}
      <div className="incident-workspace">
        <section className="incident-results">
          <div className="similarity-section-heading">
            <h2>검색 결과 {incidents.data?.pagination.total.toLocaleString("ko-KR") ?? 0}건</h2>
            <span>제한 원문이 아닌 비식별 파생정보</span>
          </div>
          <div className="incident-list">
            {incidents.data?.items.map((item) => (
              <button
                className={selected?.incidentId === item.incidentId ? "is-selected" : ""}
                key={item.incidentId}
                onClick={() => chooseIncident(item.incidentId)}
                type="button"
              >
                <time>{formatDate(item.reportedOn)}</time>
                <span>
                  <strong>{item.title}</strong>
                  <small>
                    {[item.region.sidoName, item.region.sigunguName, item.facilityType]
                      .filter(Boolean)
                      .join(" · ")}
                  </small>
                </span>
                <span>
                  <strong>{formatList(item.causeCategories, "원인 분류 없음")}</strong>
                  <small>{formatList(item.damageCategories)}</small>
                </span>
                <b>{matchLabel(item.conditionMatch)}</b>
              </button>
            ))}
            {incidents.data?.items.length === 0 ? (
              <div className="similarity-empty">조건에 맞는 사고사례가 없습니다.</div>
            ) : null}
          </div>
          <div className="similarity-pagination">
            <button disabled={page <= 1} onClick={() => changePage(page - 1)} type="button">
              이전
            </button>
            <span>
              {page} / {incidents.data?.pagination.totalPages || 1}
            </span>
            <button
              disabled={!incidents.data || page >= incidents.data.pagination.totalPages}
              onClick={() => changePage(page + 1)}
              type="button"
            >
              다음
            </button>
          </div>
        </section>
        <aside className="incident-detail">
          {selected ? (
            <>
              <span>선택한 과거 사고사례</span>
              <h2>{selected.title}</h2>
              <p>
                {selected.sourceFamily === "MAJOR" ? "중대사고 보고" : "일반사고 보고"} ·{" "}
                {selected.evidenceQuality.label}
              </p>
              <dl>
                <div>
                  <dt>발생일</dt>
                  <dd>{formatDate(selected.reportedOn)}</dd>
                </div>
                <div>
                  <dt>지역·용도</dt>
                  <dd>
                    {[selected.region.sidoName, selected.region.sigunguName, selected.facilityType]
                      .filter(Boolean)
                      .join(" · ") || "미확인"}
                  </dd>
                </div>
                <div>
                  <dt>사고 유형</dt>
                  <dd>{selected.incidentType}</dd>
                </div>
                <div>
                  <dt>원인 범주</dt>
                  <dd>{formatList(selected.causeCategories)}</dd>
                </div>
                <div>
                  <dt>피해 범주</dt>
                  <dd>{formatList(selected.damageCategories)}</dd>
                </div>
                <div>
                  <dt>설비 범주</dt>
                  <dd>{formatList(selected.equipmentCategories)}</dd>
                </div>
              </dl>
              <div className="evidence-warning">
                <strong>과거 사례 참고</strong>
                <span>
                  공식 현행 대응 근거로 확정할 수 없으며 원문 개인정보는 제공하지 않습니다.
                </span>
              </div>
              {selected.conditionMatch ? (
                <div className="match-summary">
                  <strong>조건 정합도 {selected.conditionMatch.score}점</strong>
                  <span>시설용도·지역의 결정 규칙 합계</span>
                </div>
              ) : null}
              <AppLink
                className="primary-action"
                currentPath={currentPath}
                runtime={runtime}
                to={`/similar/facilities?referenceIncident=${selected.incidentId}`}
              >
                유사 위험시설 탐색 시작
              </AppLink>
            </>
          ) : (
            <div className="similarity-empty">왼쪽 목록에서 사고사례를 선택하세요.</div>
          )}
        </aside>
      </div>
    </main>
  );
}

function CandidateMap({
  candidates,
  selectedId,
  onSelect,
  runtime,
}: {
  candidates: Candidate[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  runtime: ProfileRuntime;
}) {
  const config = useQuery({
    queryKey: ["map-config", runtime.profile],
    queryFn: () => apiRequest<MapConfigData>(runtime, "/map/config").then((result) => result.data),
    staleTime: 5 * 60_000,
  });
  const points = useMemo<NaverPoint[]>(
    () =>
      candidates.map((item) => ({
        id: item.buildingId,
        center: item.center,
        title: item.name,
        tone:
          item.risk.riskBand === "TOP_1"
            ? "danger"
            : item.risk.riskBand === "HIGH_1_10"
              ? "warning"
              : item.risk.riskBand === "WATCH_10_25"
                ? "neutral"
                : "primary",
      })),
    [candidates],
  );
  return (
    <NaverPointMap
      className="candidate-map"
      fallbackMessage="브라우저 지도 대신 오른쪽 실제 후보 목록을 사용합니다."
      initialZoom={8}
      keyId={config.data?.naverMapsNcpKeyId}
      onSelect={onSelect}
      points={points}
      selectedId={selectedId}
    />
  );
}

function CandidateExplorer({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const params = new URLSearchParams(window.location.search);
  const incidentId = params.get("referenceIncident");
  const [page, setPage] = useState(Number(params.get("page") ?? 1) || 1);
  const [selectedId, setSelectedId] = useState(params.get("candidateBuilding"));
  const candidates = useQuery({
    queryKey: ["similar-candidates", runtime.profile, incidentId, page],
    queryFn: () =>
      apiRequest<CandidateData>(
        runtime,
        `/similar/facilities?referenceIncident=${incidentId}&page=${page}&pageSize=20`,
      ).then((result) => result.data),
    enabled: Boolean(incidentId),
    placeholderData: (previous) => previous,
    staleTime: 60_000,
  });
  const selected =
    candidates.data?.items.find((item) => item.buildingId === selectedId) ??
    candidates.data?.items[0];
  const choose = (id: string) => {
    setSelectedId(id);
    setUrl(runtime, "/similar/facilities", {
      referenceIncident: incidentId,
      candidateBuilding: id,
      page: String(page),
    });
  };
  const changePage = (next: number) => {
    setPage(next);
    setSelectedId(null);
    setUrl(runtime, "/similar/facilities", {
      referenceIncident: incidentId,
      candidateBuilding: null,
      page: String(next),
    });
  };
  if (!incidentId)
    return (
      <SimilarityState
        error
        message="기준 사고사례가 없습니다. 과거 사고사례 검색에서 사례를 선택해 주세요."
      />
    );
  if (candidates.isLoading)
    return <SimilarityState message="실제 후보 건물을 탐색하고 있습니다." />;
  if (candidates.isError || !candidates.data)
    return <SimilarityState error message="후보 건물을 불러오지 못했습니다." />;
  const incident = candidates.data.referenceIncident;
  return (
    <main className="page similarity-page" id="main-content">
      <AppLink
        className="analysis-back"
        currentPath={currentPath}
        runtime={runtime}
        to={`/similar/incidents?referenceIncident=${incidentId}`}
      >
        ‹ 과거 사고사례 검색으로 돌아가기
      </AppLink>
      <div className="page-heading similarity-heading">
        <div>
          <h1>유사 위험시설 탐색 결과</h1>
          <p>과거사례와 건물 용도·지역 조건이 가까운 실제 광주·전남 건물을 비교합니다.</p>
        </div>
        <span className="similarity-contract">
          후보 {candidates.data.pagination.total.toLocaleString("ko-KR")}개 · 실제 건물
        </span>
      </div>
      <section className="reference-incident-bar">
        <div>
          <span>검색한 기준 사고</span>
          <strong>{incident.title}</strong>
        </div>
        <dl>
          <div>
            <dt>발생일</dt>
            <dd>{formatDate(incident.reportedOn)}</dd>
          </div>
          <div>
            <dt>시설·원인</dt>
            <dd>
              {incident.facilityType} · {formatList(incident.causeCategories)}
            </dd>
          </div>
          <div>
            <dt>근거 상태</dt>
            <dd>{incident.evidenceQuality.label}</dd>
          </div>
        </dl>
      </section>
      <div className="candidate-workspace">
        <section className="candidate-map-panel">
          <div className="similarity-section-heading">
            <div>
              <h2>후보 위치</h2>
              <span>현재 페이지 20개 실제 좌표</span>
            </div>
            <div className="candidate-legend">
              <span className="top">최상위 위험</span>
              <span className="high">고위험</span>
              <span className="watch">관심</span>
              <span className="general">일반</span>
            </div>
          </div>
          <CandidateMap
            candidates={candidates.data.items}
            onSelect={choose}
            runtime={runtime}
            selectedId={selected?.buildingId ?? null}
          />
        </section>
        <aside className="candidate-list-panel">
          <div className="similarity-section-heading">
            <div>
              <h2>유사 시설 후보</h2>
              <span>정합도와 위험순위는 별도 기준입니다.</span>
            </div>
          </div>
          <div className="candidate-list">
            {candidates.data.items.map((item, index) => (
              <button
                className={selected?.buildingId === item.buildingId ? "is-selected" : ""}
                key={item.buildingId}
                onClick={() => choose(item.buildingId)}
                type="button"
              >
                <span className="candidate-rank">{(page - 1) * 20 + index + 1}위</span>
                <span>
                  <strong>{item.name}</strong>
                  <small>
                    {item.region.fullName} · {item.attributes.mainUseName ?? "용도 미등록"}
                  </small>
                  <span className="candidate-condition">
                    {item.conditionMatch.components.map((part) => part.detail).join(" · ")}
                  </span>
                </span>
                <b>{item.conditionMatch.score}점</b>
                <i>
                  {riskLabels[item.risk.riskBand]} ·{" "}
                  {item.risk.regionalRank.toLocaleString("ko-KR")}위
                </i>
              </button>
            ))}
          </div>
          <div className="similarity-pagination">
            <button disabled={page <= 1} onClick={() => changePage(page - 1)} type="button">
              이전
            </button>
            <span>
              {page} / {candidates.data.pagination.totalPages}
            </span>
            <button
              disabled={page >= candidates.data.pagination.totalPages}
              onClick={() => changePage(page + 1)}
              type="button"
            >
              다음
            </button>
          </div>
          {selected ? (
            <AppLink
              className="primary-action candidate-compare-action"
              currentPath={currentPath}
              runtime={runtime}
              to={`/similar/compare?referenceIncident=${incidentId}&candidateBuilding=${selected.buildingId}`}
            >
              선택 후보 비교하기
            </AppLink>
          ) : null}
        </aside>
      </div>
    </main>
  );
}

function CandidateComparison({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const params = new URLSearchParams(window.location.search);
  const incidentId = params.get("referenceIncident");
  const buildingId = params.get("candidateBuilding");
  const result = useQuery({
    queryKey: ["similar-comparison", runtime.profile, incidentId, buildingId],
    queryFn: () =>
      apiRequest<ComparisonData>(
        runtime,
        `/similar/compare?referenceIncident=${incidentId}&candidateBuilding=${buildingId}`,
      ).then((response) => response.data),
    enabled: Boolean(incidentId && buildingId),
    staleTime: 60_000,
  });
  if (!incidentId || !buildingId)
    return <SimilarityState error message="비교할 사고사례와 후보 건물을 선택해 주세요." />;
  if (result.isLoading)
    return <SimilarityState message="사고사례와 후보 건물을 비교하고 있습니다." />;
  if (result.isError || !result.data)
    return <SimilarityState error message="비교 결과를 불러오지 못했습니다." />;
  const data = result.data;
  const building = data.candidateBuilding;
  return (
    <main className="page similarity-page" id="main-content">
      <AppLink
        className="analysis-back"
        currentPath={currentPath}
        runtime={runtime}
        to={`/similar/facilities?referenceIncident=${incidentId}&candidateBuilding=${buildingId}`}
      >
        ‹ 유사 위험시설 탐색 결과로 돌아가기
      </AppLink>
      <div className="page-heading similarity-heading">
        <div>
          <h1>기준 사고사례와 후보 시설 비교</h1>
          <p>확인된 구조화 항목만 비교하고 현재 상태는 현장 확인 항목으로 남깁니다.</p>
        </div>
        <span className="similarity-contract">조건 정합도 {data.conditionMatch.score}점</span>
      </div>
      <section className="comparison-cards">
        <article className="reference">
          <header>
            <span>기준 사고사례</span>
            <h2>{data.referenceIncident.title}</h2>
            <b>{formatDate(data.referenceIncident.reportedOn)}</b>
          </header>
          <dl>
            <div>
              <dt>지역·용도</dt>
              <dd>
                {[
                  data.referenceIncident.region.sidoName,
                  data.referenceIncident.region.sigunguName,
                  data.referenceIncident.facilityType,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </dd>
            </div>
            <div>
              <dt>사고 유형</dt>
              <dd>{data.referenceIncident.incidentType}</dd>
            </div>
            <div>
              <dt>원인 범주</dt>
              <dd>{formatList(data.referenceIncident.causeCategories)}</dd>
            </div>
            <div>
              <dt>피해 범주</dt>
              <dd>{formatList(data.referenceIncident.damageCategories)}</dd>
            </div>
            <div>
              <dt>주요 설비</dt>
              <dd>{formatList(data.referenceIncident.equipmentCategories)}</dd>
            </div>
            <div>
              <dt>자료 품질</dt>
              <dd>{data.referenceIncident.evidenceQuality.label}</dd>
            </div>
          </dl>
        </article>
        <article className="candidate">
          <header>
            <span>선택 후보 시설</span>
            <h2>{building.name}</h2>
            <b>
              {riskLabels[building.risk.riskBand]} ·{" "}
              {building.risk.regionalRank.toLocaleString("ko-KR")}위
            </b>
          </header>
          <dl>
            <div>
              <dt>지역·주소</dt>
              <dd>
                {building.region.fullName} · {building.roadAddress ?? building.lotAddress}
              </dd>
            </div>
            <div>
              <dt>건물 용도</dt>
              <dd>{building.attributes.mainUseName ?? "미등록"}</dd>
            </div>
            <div>
              <dt>건물 구조</dt>
              <dd>{building.attributes.mainStructure ?? "미등록"}</dd>
            </div>
            <div>
              <dt>건축 연도</dt>
              <dd>{building.attributes.buildingYear ?? "미등록"}</dd>
            </div>
            <div>
              <dt>연결 설비</dt>
              <dd>{building.facilitySummary.linkedFacilityCount.toLocaleString("ko-KR")}건</dd>
            </div>
            <div>
              <dt>최근 점검일</dt>
              <dd>{building.facilitySummary.latestInspectionDate ?? "미등록"}</dd>
            </div>
          </dl>
        </article>
      </section>
      <section className="comparison-lower">
        <article className="match-components">
          <h2>공통 매치 근거</h2>
          <p>두 데이터에서 확인 가능한 조건만 합산합니다.</p>
          {data.conditionMatch.components.map((item) => (
            <div key={item.code}>
              <span>
                <strong>{item.label}</strong>
                <small>{item.detail}</small>
              </span>
              <b>
                {item.points} / {item.maximum}
              </b>
            </div>
          ))}
        </article>
        <article className="match-score">
          <span>조건 정합도</span>
          <strong>{data.conditionMatch.score}점</strong>
          <b>발생확률 아님</b>
          <div>
            <i style={{ width: `${data.conditionMatch.score}%` }} />
          </div>
          <small>
            점검 우선순위{" "}
            {priorityLabels[data.inspectionPriority.level] ?? data.inspectionPriority.level}
          </small>
        </article>
        <article className="inspection-checklist">
          <h2>권고 확인 항목</h2>
          <p>공식 근거 연결 전 검토용 초안입니다.</p>
          <ol>
            {data.inspectionChecklist.map((item, index) => (
              <li key={item.code}>
                <span>{index + 1}</span>
                <div>
                  <strong>{item.label}</strong>
                  <small>{item.basis}</small>
                </div>
              </li>
            ))}
          </ol>
        </article>
      </section>
      <aside className="comparison-warning">
        <strong>근거 부족 · 검토 필요</strong>
        <span>{data.evidence.warning}</span>
      </aside>
      <footer className="comparison-actions">
        <div>
          <strong>선택 후보를 점검 시뮬레이션 조건에 추가</strong>
          <span>사례·후보 ID와 확인 항목을 다음 단계에 전달합니다.</span>
        </div>
        <AppLink
          className="outline-action"
          currentPath={currentPath}
          runtime={runtime}
          to={`/similar/facilities?referenceIncident=${incidentId}`}
        >
          다른 후보 선택
        </AppLink>
        <AppLink
          className="primary-action"
          currentPath={currentPath}
          runtime={runtime}
          to={`/inspections/simulations/new?referenceIncident=${incidentId}&candidateBuilding=${buildingId}`}
        >
          점검 시뮬레이션 조건에 추가
        </AppLink>
      </footer>
    </main>
  );
}

export function SimilarityAnalysis({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  if (currentPath === "/similar/incidents")
    return <IncidentSearch currentPath={currentPath} runtime={runtime} />;
  if (currentPath === "/similar/facilities")
    return <CandidateExplorer currentPath={currentPath} runtime={runtime} />;
  if (currentPath === "/similar/compare")
    return <CandidateComparison currentPath={currentPath} runtime={runtime} />;
  return <SimilarityState error message="유사분석 경로를 찾을 수 없습니다." />;
}
