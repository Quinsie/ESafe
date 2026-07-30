import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { apiRequest } from "./api";
import type { ProfileRuntime } from "./profile";

type RegionLevel = "SIDO" | "SIGUNGU";
type TopPercent = 1 | 5 | 10;

interface ExtractRegion {
  regionCode: string;
  name: string;
  fullName: string;
  parentCode: string | null;
  buildingCount: number;
  eligibleCounts: Record<`${TopPercent}`, number>;
}

interface ExtractRegionData {
  level: RegionLevel;
  levelName: string;
  items: ExtractRegion[];
  riskReference: {
    referenceMonth: string;
    horizonDays: number;
    lineageVersion: string;
    isProbability: boolean;
  };
}

const exportColumns = [
  "번호",
  "건물명",
  "지번주소",
  "광역시·도",
  "시·군·구",
  "선택 지역 내 위험순위",
  "광주·전남 전체 위험순위",
  "위험점수",
  "상위백분위(%)",
  "건물 주용도",
  "최근 점검·검사일",
  "6개월 내 점검·검사 여부",
  "1년 내 점검·검사 여부",
  "점검·검사 이력 건수",
] as const;

function regionsPath(level: RegionLevel, parentCode?: string): string {
  const params = new URLSearchParams({ level });
  if (parentCode) {
    params.set("parentCode", parentCode);
  }
  return `/data-extract/regions?${params.toString()}`;
}

export function DataExtract({ runtime }: { runtime: ProfileRuntime }) {
  const [sidoCode, setSidoCode] = useState("");
  const [sigunguCode, setSigunguCode] = useState("");
  const [topPercent, setTopPercent] = useState<TopPercent>(10);

  const sidoRegions = useQuery({
    queryKey: ["data-extract-regions", runtime.profile, "SIDO"],
    queryFn: () =>
      apiRequest<ExtractRegionData>(runtime, regionsPath("SIDO")).then((result) => result.data),
    staleTime: 5 * 60_000,
  });
  const sigunguRegions = useQuery({
    queryKey: ["data-extract-regions", runtime.profile, "SIGUNGU", sidoCode],
    queryFn: () =>
      apiRequest<ExtractRegionData>(runtime, regionsPath("SIGUNGU", sidoCode)).then(
        (result) => result.data,
      ),
    enabled: Boolean(sidoCode),
    staleTime: 5 * 60_000,
  });
  useEffect(() => {
    const items = sidoRegions.data?.items ?? [];
    if (items.length === 0) {
      setSidoCode("");
      return;
    }
    if (!items.some((item) => item.regionCode === sidoCode)) {
      setSidoCode(items[0].regionCode);
    }
  }, [sidoCode, sidoRegions.data]);

  useEffect(() => {
    if (
      sigunguCode &&
      sigunguRegions.data &&
      !sigunguRegions.data.items.some((item) => item.regionCode === sigunguCode)
    ) {
      setSigunguCode("");
    }
  }, [sigunguCode, sigunguRegions.data]);

  const selectedSido = sidoRegions.data?.items.find((item) => item.regionCode === sidoCode);
  const selectedSigungu = sigunguRegions.data?.items.find(
    (item) => item.regionCode === sigunguCode,
  );
  const selected = selectedSigungu ?? selectedSido;
  const selectedLevel: RegionLevel = selectedSigungu ? "SIGUNGU" : "SIDO";
  const expectedRows = selected?.eligibleCounts[String(topPercent) as `${TopPercent}`] ?? 0;
  const downloadHref = selected
    ? `${runtime.apiBase}/data-extract/buildings.xlsx?level=${selectedLevel}&regionCode=${encodeURIComponent(selected.regionCode)}&topPercent=${topPercent}`
    : undefined;
  const regionError = sidoRegions.isError || sigunguRegions.isError;
  const regionLoading = sidoRegions.isLoading || (Boolean(sidoCode) && sigunguRegions.isLoading);

  return (
    <main className="page data-extract-page" id="main-content">
      <div className="page-heading">
        <div>
          <h1>자료 추출</h1>
          <p>
            행정구역과 위험도 범위를 선택해 점검·검사 이력을 포함한 건축물 목록을 엑셀로 받습니다.
          </p>
        </div>
      </div>

      <aside className="analysis-contract-note">
        v27.1 · 2026-03 · 향후 60일 상대점수 기준입니다. 상위 백분위는 발생확률이 아닙니다.
      </aside>

      <div className="data-extract-layout">
        <section className="panel data-extract-form" aria-labelledby="data-extract-condition-title">
          <div className="panel-heading">
            <div>
              <h2 id="data-extract-condition-title">추출 조건</h2>
              <p>
                상위 행정구역부터 차례로 선택하세요. 하위의 전체 선택은 현재 상위 범위를 유지합니다.
              </p>
            </div>
          </div>

          <fieldset className="data-extract-region-chain">
            <legend>행정구역</legend>
            <label className="data-extract-field" htmlFor="extract-sido">
              <span>광역시·도</span>
              <select
                disabled={sidoRegions.isLoading || sidoRegions.isError}
                id="extract-sido"
                onChange={(event) => {
                  setSidoCode(event.target.value);
                  setSigunguCode("");
                }}
                value={sidoCode}
              >
                {sidoRegions.data?.items.map((item) => (
                  <option key={item.regionCode} value={item.regionCode}>
                    {item.fullName}
                  </option>
                ))}
              </select>
            </label>

            <label className="data-extract-field" htmlFor="extract-sigungu">
              <span>시·군·구</span>
              <select
                disabled={!sidoCode || sigunguRegions.isLoading || sigunguRegions.isError}
                id="extract-sigungu"
                onChange={(event) => setSigunguCode(event.target.value)}
                value={sigunguCode}
              >
                <option value="">전체 시·군·구</option>
                {sigunguRegions.data?.items.map((item) => (
                  <option key={item.regionCode} value={item.regionCode}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          </fieldset>

          <fieldset className="data-extract-percent">
            <legend>위험도 범위</legend>
            {([1, 5, 10] as TopPercent[]).map((value) => (
              <label key={value}>
                <input
                  checked={topPercent === value}
                  name="top-percent"
                  onChange={() => setTopPercent(value)}
                  type="radio"
                />
                <span>상위 {value}%</span>
              </label>
            ))}
          </fieldset>

          {regionLoading ? (
            <div className="data-extract-state" role="status">
              지역 목록을 불러오고 있습니다.
            </div>
          ) : regionError ? (
            <div className="data-extract-state error" role="alert">
              <span>지역 목록을 불러오지 못했습니다.</span>
              <button
                onClick={() => {
                  void sidoRegions.refetch();
                  if (sidoCode) {
                    void sigunguRegions.refetch();
                  }
                }}
                type="button"
              >
                다시 시도
              </button>
            </div>
          ) : null}

          <div className="data-extract-selection">
            <span>{selectedSido?.name ?? "광역시·도 미선택"}</span>
            <b>AND</b>
            <span>{selectedSigungu?.name ?? "전체 시·군·구"}</span>
          </div>

          <div className="data-extract-summary" aria-live="polite">
            <span>예상 추출 건수</span>
            <strong>{expectedRows.toLocaleString("ko-KR")}개 건축물</strong>
            <small>
              {selected?.fullName ?? "지역 미선택"} · 모델 상위 {topPercent}%
            </small>
          </div>

          <a
            aria-disabled={!downloadHref}
            className={`primary-action data-extract-download${downloadHref ? "" : " is-disabled"}`}
            download
            href={downloadHref}
          >
            Excel(.xlsx)로 추출
          </a>
        </section>

        <section
          className="panel data-extract-columns"
          aria-labelledby="data-extract-columns-title"
        >
          <div className="panel-heading">
            <div>
              <h2 id="data-extract-columns-title">포함 열</h2>
              <p>번호를 포함해 총 14열이며 점검·검사 이력은 최근 점검일을 기준으로 판정합니다.</p>
            </div>
            <span className="status-pill neutral">14열</span>
          </div>
          <ol>
            {exportColumns.map((column, index) => (
              <li key={column}>
                <span>{index + 1}</span>
                <strong>{column}</strong>
              </li>
            ))}
          </ol>
          <div className="data-extract-note">
            <strong>이력 해석</strong>
            <p>
              최근 점검·검사일을 기준으로 6개월 또는 1년 이내인지 표시하며, 연결 이력이 없으면
              미등록으로 내보냅니다.
            </p>
          </div>
        </section>
      </div>
    </main>
  );
}
