import { useQuery } from "@tanstack/react-query";
import type { Feature, FeatureCollection, MultiPolygon, Polygon } from "geojson";
import { useEffect, useMemo, useRef, useState } from "react";
import { apiRequest } from "./api";
import {
  loadNaverMaps,
  moveNaverMap,
  type NaverMapConfigData,
  NaverPanoramaView,
  supportsNaverMaps,
} from "./naver_maps";
import type { ProfileRuntime } from "./profile";
import { AppLink, currentInternalLocation } from "./router";

interface MapConfigData extends NaverMapConfigData {
  buildingZoom: { minimum: number; maximum: number };
  neighborhoodZoom: { minimum: number; maximum: number };
}

interface RegionProperties {
  regionCode: string;
  level: "SIDO" | "SIGUNGU" | "EUPMYEONDONG";
  name: string;
  fullName: string;
  parentCode: string | null;
  center: [number, number];
  buildingCount: number;
  top1Count: number;
  top10Count: number;
  riskBands: {
    top1: number;
    high1To10: number;
    watch10To25: number;
    general: number;
  };
  scoreMedian: number | null;
  scoreP90: number | null;
  scoreP99: number | null;
  scoreMax: number | null;
  activeCaseCount: number;
  urgentCaseCount: number;
  hasCurrentSignal: boolean;
  top10Share?: number;
}

type RegionFeature = Feature<MultiPolygon, RegionProperties> & {
  id: string;
  bbox: [number, number, number, number];
};

interface RegionCollection extends FeatureCollection<MultiPolygon, RegionProperties> {
  features: RegionFeature[];
  riskReference: {
    referenceMonth: string;
    horizonDays: number;
    lineageVersion: string;
    isProbability: boolean;
  };
}

interface BuildingListItem {
  buildingId: string;
  regionCode: string;
  name: string;
  roadAddress: string | null;
  lotAddress: string;
  center: [number, number];
  risk: {
    finalScore: number;
    regionalRank: number;
    topPercentile: number;
    riskBand: string;
  };
  hasCurrentSignal: boolean;
  monitoringPriority: string;
}

interface BuildingListData {
  items: BuildingListItem[];
  pagination: { page: number; pageSize: number; total: number; totalPages: number };
}

interface BuildingFeatureProperties {
  buildingId: string;
  regionCode: string;
  label: string;
  finalScore: number;
  regionalRank: number;
  topPercentile: number;
  riskBand: string;
}

interface BuildingFeatureCollection
  extends FeatureCollection<Polygon | MultiPolygon, BuildingFeatureProperties> {
  truncated: boolean;
  limit: number;
}

interface BuildingDetailData {
  buildingId: string;
  name: string;
  lotAddress: string;
  roadAddress: string | null;
  center: [number, number];
  risk: BuildingListItem["risk"];
  currentSignals: { activeCaseCount: number; urgentCaseCount: number; hasCurrentSignal: boolean };
}

interface ViewportState {
  lng: number;
  lat: number;
  zoom: number;
  bbox: string | null;
}

const riskNames: Record<string, string> = {
  TOP_1: "최상위 위험",
  HIGH_1_10: "고위험",
  WATCH_10_25: "관심",
  GENERAL: "일반",
};

const DISTRICT_ZOOM = 8.5;
const NEIGHBORHOOD_ZOOM = 11.5;
const BUILDING_ZOOM = 16;

function initialNumber(name: string, fallback: number): number {
  const raw = new URLSearchParams(window.location.search).get(name);
  const parsed = raw === null ? Number.NaN : Number(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function currentSelection(name: string): string | null {
  return new URLSearchParams(window.location.search).get(name);
}

function adminFillColor(share: number): string {
  if (share >= 30) return "#ce3d3d";
  if (share >= 15) return "#f1b88b";
  return "#dbe7f2";
}

function buildingFillColor(riskBand: string): string {
  return (
    {
      TOP_1: "#c9232c",
      HIGH_1_10: "#e66b2f",
      WATCH_10_25: "#efb43c",
      GENERAL: "#7d9ab5",
    }[riskBand] ?? "#7d9ab5"
  );
}

function clearDataLayer(layer: naver.maps.Data | null): void {
  for (const feature of layer?.getAllFeature() ?? []) {
    layer?.removeFeature(feature);
  }
}
function updateMapUrl(
  viewport: ViewportState,
  regionCode: string | null,
  buildingId: string | null,
): void {
  const params = new URLSearchParams(window.location.search);
  const level =
    viewport.zoom >= BUILDING_ZOOM
      ? "building"
      : viewport.zoom >= NEIGHBORHOOD_ZOOM
        ? "neighborhood"
        : viewport.zoom >= DISTRICT_ZOOM
          ? "district"
          : "province";
  params.set("level", level);
  params.set("lng", viewport.lng.toFixed(5));
  params.set("lat", viewport.lat.toFixed(5));
  params.set("zoom", viewport.zoom.toFixed(2));
  params.set("layer", params.get("layer") ?? "risk");
  if (regionCode) {
    params.set("region", regionCode);
  } else {
    params.delete("region");
  }
  if (buildingId) {
    params.set("building", buildingId);
  } else {
    params.delete("building");
  }
  window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
}

function useSpatialData(runtime: ProfileRuntime, bbox: string | null, zoom: number) {
  const config = useQuery({
    queryKey: ["map-config", runtime.profile],
    queryFn: () => apiRequest<MapConfigData>(runtime, "/map/config").then((result) => result.data),
    staleTime: 5 * 60_000,
  });
  const provinces = useQuery({
    queryKey: ["map-regions", runtime.profile],
    queryFn: () =>
      apiRequest<RegionCollection>(runtime, "/map/regions").then((result) => result.data),
    staleTime: 5 * 60_000,
  });
  const districts = useQuery({
    queryKey: ["map-districts", runtime.profile],
    queryFn: async () => {
      const [gwangju, jeonnam] = await Promise.all([
        apiRequest<RegionCollection>(runtime, "/map/districts?parentCode=29"),
        apiRequest<RegionCollection>(runtime, "/map/districts?parentCode=46"),
      ]);
      return {
        ...gwangju.data,
        features: [...gwangju.data.features, ...jeonnam.data.features],
      } satisfies RegionCollection;
    },
    staleTime: 5 * 60_000,
  });
  const neighborhoods = useQuery({
    queryKey: ["map-neighborhoods", runtime.profile, bbox],
    queryFn: () =>
      apiRequest<RegionCollection>(
        runtime,
        `/map/neighborhoods?bbox=${encodeURIComponent(bbox ?? "")}`,
      ).then((result) => result.data),
    enabled: Boolean(bbox) && zoom >= NEIGHBORHOOD_ZOOM && zoom < BUILDING_ZOOM,
    staleTime: 5 * 60_000,
  });
  return { config, provinces, districts, neighborhoods };
}

function withShares(collection: RegionCollection | undefined): RegionCollection | undefined {
  if (!collection) {
    return undefined;
  }
  return {
    ...collection,
    features: collection.features.map((feature) => ({
      ...feature,
      properties: {
        ...feature.properties,
        top10Share:
          feature.properties.buildingCount > 0
            ? Number(
                ((feature.properties.top10Count / feature.properties.buildingCount) * 100).toFixed(
                  2,
                ),
              )
            : 0,
      },
    })),
  };
}

export function RiskMap({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<naver.maps.Map | null>(null);
  const adminLayerRef = useRef<naver.maps.Data | null>(null);
  const buildingLayerRef = useRef<naver.maps.Data | null>(null);
  const selectionRef = useRef({
    region: currentSelection("region"),
    building: currentSelection("building"),
  });
  const [selectedRegion, setSelectedRegion] = useState(selectionRef.current.region);
  const [selectedBuilding, setSelectedBuilding] = useState(selectionRef.current.building);
  const [viewport, setViewport] = useState<ViewportState>({
    lng: initialNumber("lng", 126.65),
    lat: initialNumber("lat", 34.8),
    zoom: initialNumber("zoom", 7.35),
    bbox: null,
  });
  const initialViewportRef = useRef(viewport);
  const overlayRef = useRef<RegionCollection | undefined>(undefined);
  const [overlayError, setOverlayError] = useState<string | null>(null);
  const [mapLoadError, setMapLoadError] = useState(false);
  const [mapReady, setMapReady] = useState(false);
  const [mapSupported] = useState(supportsNaverMaps);
  const [panoramaPosition, setPanoramaPosition] = useState<[number, number] | null>(null);
  const { config, provinces, districts, neighborhoods } = useSpatialData(
    runtime,
    viewport.bbox,
    viewport.zoom,
  );
  const provinceData = useMemo(() => withShares(provinces.data), [provinces.data]);
  const districtData = useMemo(() => withShares(districts.data), [districts.data]);
  const neighborhoodData = useMemo(() => withShares(neighborhoods.data), [neighborhoods.data]);
  const overlay =
    viewport.zoom < DISTRICT_ZOOM
      ? provinceData
      : viewport.zoom < NEIGHBORHOOD_ZOOM
        ? districtData
        : viewport.zoom < BUILDING_ZOOM
          ? neighborhoodData
          : undefined;
  overlayRef.current = overlay;

  selectionRef.current = { region: selectedRegion, building: selectedBuilding };

  useEffect(() => {
    const keyId = config.data?.naverMapsNcpKeyId;
    if (!mapSupported || !containerRef.current || !keyId) {
      return;
    }
    let cancelled = false;
    let map: naver.maps.Map | null = null;
    let adminLayer: naver.maps.Data | null = null;
    let buildingLayer: naver.maps.Data | null = null;
    let listeners: naver.maps.MapEventListener[] = [];
    setMapLoadError(false);
    loadNaverMaps(keyId)
      .then(() => {
        if (cancelled || !containerRef.current) {
          return;
        }
        map = new naver.maps.Map(containerRef.current, {
          center: new naver.maps.LatLng(
            initialViewportRef.current.lat,
            initialViewportRef.current.lng,
          ),
          zoom: Math.round(initialViewportRef.current.zoom),
          minZoom: 6,
          maxZoom: 21,
          zoomControl: true,
          zoomControlOptions: {
            position: naver.maps.Position.TOP_LEFT,
            style: naver.maps.ZoomControlStyle.SMALL,
          },
          mapTypeControl: true,
          scaleControl: true,
          scrollWheel: true,
          pinchZoom: true,
        });
        mapRef.current = map;
        adminLayer = new naver.maps.Data();
        buildingLayer = new naver.maps.Data();
        adminLayerRef.current = adminLayer;
        buildingLayerRef.current = buildingLayer;
        adminLayer.setMap(map);
        buildingLayer.setMap(map);
        adminLayer.setStyle((feature) => ({
          fillColor: adminFillColor(Number(feature.getProperty("top10Share") ?? 0)),
          fillOpacity: 0.38,
          strokeColor: "#264b73",
          strokeWeight: 2,
          clickable: true,
        }));
        buildingLayer.setStyle((feature) => {
          const selected = feature.getProperty("buildingId") === selectionRef.current.building;
          return {
            fillColor: buildingFillColor(String(feature.getProperty("riskBand") ?? "GENERAL")),
            fillOpacity: selected ? 0.64 : 0.48,
            strokeColor: selected ? "#005fcc" : "#4e6175",
            strokeWeight: selected ? 4 : 1,
            clickable: true,
            zIndex: selected ? 20 : 10,
          };
        });

        const captureViewport = () => {
          if (!map) return;
          const center = map.getCenter() as naver.maps.LatLng;
          const bounds = map.getBounds() as naver.maps.LatLngBounds;
          const next = {
            lng: center.lng(),
            lat: center.lat(),
            zoom: map.getZoom(),
            bbox: [bounds.west(), bounds.south(), bounds.east(), bounds.north()]
              .map((value) => value.toFixed(6))
              .join(","),
          };
          setViewport(next);
          updateMapUrl(next, selectionRef.current.region, selectionRef.current.building);
        };
        listeners.push(naver.maps.Event.addListener(map, "idle", captureViewport));
        listeners.push(
          naver.maps.Event.addListener(adminLayer, "click", (event: naver.maps.PointerEvent) => {
            const code = event.feature.getProperty("regionCode") as string | undefined;
            const center = event.feature.getProperty("center") as
              | [number, number]
              | string
              | undefined;
            if (!code) return;
            const parsedCenter =
              typeof center === "string" ? (JSON.parse(center) as [number, number]) : center;
            const level = event.feature.getProperty("level") as string | undefined;
            setSelectedRegion(code);
            setSelectedBuilding(null);
            setPanoramaPosition(null);
            if (parsedCenter) {
              moveNaverMap(
                map,
                parsedCenter,
                level === "SIDO"
                  ? 9
                  : level === "SIGUNGU"
                    ? NEIGHBORHOOD_ZOOM + 0.7
                    : BUILDING_ZOOM + 0.5,
              );
            }
          }),
        );
        listeners.push(
          naver.maps.Event.addListener(buildingLayer, "click", (event: naver.maps.PointerEvent) => {
            const buildingId = event.feature.getProperty("buildingId") as string | undefined;
            if (!buildingId) return;
            setSelectedBuilding(buildingId);
            if (event.coord instanceof naver.maps.LatLng) {
              setPanoramaPosition([event.coord.lng(), event.coord.lat()]);
            } else if (map) {
              const center = map.getCenter() as naver.maps.LatLng;
              setPanoramaPosition([center.lng(), center.lat()]);
            }
          }),
        );
        const initialOverlay = overlayRef.current;
        if (initialOverlay) {
          adminLayer.addGeoJson(initialOverlay, false);
        }
        captureViewport();
        setMapReady(true);
      })
      .catch(() => {
        if (!cancelled) setMapLoadError(true);
      });
    return () => {
      cancelled = true;
      const sdk = (
        globalThis as typeof globalThis & {
          naver?: typeof naver;
        }
      ).naver;
      if (sdk) sdk.maps.Event.removeListener(listeners);
      listeners = [];
      adminLayer?.setMap(null);
      buildingLayer?.setMap(null);
      map?.destroy();
      adminLayerRef.current = null;
      buildingLayerRef.current = null;
      mapRef.current = null;
      setMapReady(false);
    };
  }, [config.data?.naverMapsNcpKeyId, mapSupported]);

  useEffect(() => {
    if (!mapReady) return;
    const frame = requestAnimationFrame(() => mapRef.current?.refresh());
    return () => cancelAnimationFrame(frame);
  }, [mapReady]);

  useEffect(() => {
    if (!mapReady) return;
    const layer = adminLayerRef.current;
    if (!layer) return;
    clearDataLayer(layer);
    if (overlay) layer.addGeoJson(overlay, false);
  }, [mapReady, overlay]);

  useEffect(() => {
    if (!mapReady) return;
    buildingLayerRef.current?.setStyle((feature) => {
      const selected = feature.getProperty("buildingId") === selectedBuilding;
      return {
        fillColor: buildingFillColor(String(feature.getProperty("riskBand") ?? "GENERAL")),
        fillOpacity: selected ? 0.64 : 0.48,
        strokeColor: selected ? "#005fcc" : "#4e6175",
        strokeWeight: selected ? 4 : 1,
        clickable: true,
        zIndex: selected ? 20 : 10,
      };
    });
    updateMapUrl(viewport, selectedRegion, selectedBuilding);
  }, [mapReady, selectedBuilding, selectedRegion, viewport]);

  const buildingList = useQuery({
    queryKey: ["map-building-list", runtime.profile, viewport.bbox, viewport.zoom],
    queryFn: () =>
      apiRequest<BuildingListData>(
        runtime,
        `/map/buildings?bbox=${encodeURIComponent(viewport.bbox ?? "")}&zoom=${viewport.zoom.toFixed(2)}&pageSize=50&sort=rank`,
      ).then((result) => result.data),
    enabled: Boolean(viewport.bbox) && viewport.zoom >= BUILDING_ZOOM,
    placeholderData: (previous) => previous,
    staleTime: 60_000,
  });
  const buildingFeatures = useQuery({
    queryKey: ["map-building-features", runtime.profile, viewport.bbox, viewport.zoom],
    queryFn: () =>
      apiRequest<BuildingFeatureCollection>(
        runtime,
        `/map/building-features?bbox=${encodeURIComponent(viewport.bbox ?? "")}&zoom=${viewport.zoom.toFixed(2)}&limit=2000`,
      ).then((result) => result.data),
    enabled: Boolean(viewport.bbox) && viewport.zoom >= BUILDING_ZOOM,
    placeholderData: (previous) => previous,
    staleTime: 60_000,
  });
  const selectedDetail = useQuery({
    queryKey: ["map-building-detail", runtime.profile, selectedBuilding],
    queryFn: () =>
      apiRequest<BuildingDetailData>(runtime, `/buildings/${selectedBuilding}`).then(
        (result) => result.data,
      ),
    enabled: Boolean(selectedBuilding),
    staleTime: 60_000,
  });

  useEffect(() => {
    if (!mapReady) return;
    const layer = buildingLayerRef.current;
    if (!layer) return;
    clearDataLayer(layer);
    if (viewport.zoom >= BUILDING_ZOOM && buildingFeatures.data) {
      layer.addGeoJson(buildingFeatures.data, false);
    }
  }, [buildingFeatures.data, mapReady, viewport.zoom]);

  useEffect(() => {
    if (buildingFeatures.isError) {
      setOverlayError("건물 폴리곤을 불러오지 못했습니다. 지도를 이동하거나 다시 시도해 주세요.");
    } else if (buildingFeatures.data?.truncated) {
      setOverlayError(
        `현재 화면의 건물이 ${buildingFeatures.data.limit.toLocaleString("ko-KR")}개를 넘어 상위 위험 건물만 표시합니다. 더 확대해 주세요.`,
      );
    } else if (
      overlayError?.startsWith("건물 폴리곤") ||
      overlayError?.startsWith("현재 화면의 건물")
    ) {
      setOverlayError(null);
    }
  }, [buildingFeatures.data, buildingFeatures.isError, overlayError]);

  const visibleRegions = useMemo(
    () =>
      [...(overlay?.features ?? [])].sort((left, right) => {
        const shareDifference =
          (right.properties.top10Share ?? 0) - (left.properties.top10Share ?? 0);
        return (
          shareDifference || left.properties.regionCode.localeCompare(right.properties.regionCode)
        );
      }),
    [overlay],
  );
  const selectedRegionFeature = [
    ...(provinceData?.features ?? []),
    ...(districtData?.features ?? []),
    ...(neighborhoodData?.features ?? []),
  ].find((feature) => feature.properties.regionCode === selectedRegion);
  const provinceTotal = provinceData?.features.reduce(
    (total, feature) => total + feature.properties.buildingCount,
    0,
  );
  const top1Total = provinceData?.features.reduce(
    (total, feature) => total + feature.properties.top1Count,
    0,
  );
  const levelLabel =
    viewport.zoom >= BUILDING_ZOOM
      ? "건물"
      : viewport.zoom >= NEIGHBORHOOD_ZOOM
        ? "읍·면·동"
        : viewport.zoom >= DISTRICT_ZOOM
          ? "시·군·구"
          : "광역시·도";
  const returnToMap = encodeURIComponent(currentInternalLocation(runtime));

  const chooseRegionFromList = (feature: RegionFeature) => {
    setSelectedRegion(feature.properties.regionCode);
    setSelectedBuilding(null);
    setPanoramaPosition(null);
    moveNaverMap(
      mapRef.current,
      feature.properties.center,
      feature.properties.level === "SIDO"
        ? 9
        : feature.properties.level === "SIGUNGU"
          ? NEIGHBORHOOD_ZOOM + 0.7
          : BUILDING_ZOOM + 0.5,
    );
  };

  const chooseBuildingFromList = (building: BuildingListItem) => {
    setSelectedBuilding(building.buildingId);
    setPanoramaPosition(building.center);
    moveNaverMap(mapRef.current, building.center, Math.max(viewport.zoom, 16));
  };

  const retryOverlay = () => {
    setOverlayError(null);
    void provinces.refetch();
    void districts.refetch();
    if (viewport.bbox && viewport.zoom >= NEIGHBORHOOD_ZOOM && viewport.zoom < BUILDING_ZOOM)
      void neighborhoods.refetch();
    void buildingList.refetch();
    void buildingFeatures.refetch();
  };

  return (
    <main className="page map-page" id="main-content">
      <div className="page-heading map-heading">
        <div>
          <h1>통합 위험지도</h1>
          <p>실제 광역·시군구·읍면동 경계와 현재 뷰포트의 건물 폴리곤을 조회합니다.</p>
        </div>
        <fieldset className="map-basis">
          <legend className="sr-only">지도 기준</legend>
          <span>v27.1 · 2026-03</span>
          <span>향후 60일 상대 위험순위</span>
        </fieldset>
      </div>

      <section className="map-summary" aria-label="지도 요약">
        <article>
          <span>분석 건물</span>
          <strong>{provinceTotal?.toLocaleString("ko-KR") ?? "—"}</strong>
          <small>실제 폴리곤 정합 건물</small>
        </article>
        <article>
          <span>상위 1% 건물</span>
          <strong>{top1Total?.toLocaleString("ko-KR") ?? "—"}</strong>
          <small>광주·전남 상대순위</small>
        </article>
        <article>
          <span>현재 표현 단계</span>
          <strong>{levelLabel}</strong>
          <small>확대수준 {viewport.zoom.toFixed(1)}</small>
        </article>
        <article>
          <span>현재 신호</span>
          <strong>
            {visibleRegions.reduce((sum, feature) => sum + feature.properties.activeCaseCount, 0)}건
          </strong>
          <small>표시 지역의 활성 Case</small>
        </article>
      </section>

      <div className="map-workspace">
        <section className="map-canvas-panel" aria-label="실제 위험지도">
          <div className="map-toolbar">
            <div>
              <strong>{levelLabel} 위험도</strong>
              <span>건물 영역을 클릭하면 지도 안에서 거리뷰가 열립니다.</span>
            </div>
            <fieldset className="map-legend">
              <legend className="sr-only">위험구간 범례</legend>
              <span className="risk-top">최상위 위험</span>
              <span className="risk-high">고위험</span>
              <span className="risk-watch">관심</span>
              <span className="risk-general">일반</span>
            </fieldset>
          </div>
          {config.isError ? (
            <div className="map-layer-error" role="alert">
              배경지도 설정을 불러오지 못했습니다.
              <button onClick={() => void config.refetch()} type="button">
                다시 시도
              </button>
            </div>
          ) : null}
          {!config.isLoading && !config.data?.naverMapsNcpKeyId ? (
            <div className="map-layer-error" role="alert">
              NAVER_MAPS_NCP_KEY_ID가 설정되지 않았습니다.
            </div>
          ) : null}
          {mapLoadError ? (
            <div className="map-layer-error" role="alert">
              네이버 지도 SDK를 불러오지 못했습니다. 네이버 Cloud의 Web 서비스 URL 등록과 ncpKeyId를
              확인하세요.
            </div>
          ) : null}
          {provinces.isError ||
          districts.isError ||
          (neighborhoods.isError &&
            viewport.zoom >= NEIGHBORHOOD_ZOOM &&
            viewport.zoom < BUILDING_ZOOM) ||
          overlayError ? (
            <div className="map-layer-error overlay" role="alert">
              {overlayError ?? "업무 위험 레이어를 불러오지 못했습니다."}
              <button onClick={retryOverlay} type="button">
                업무 레이어 다시 시도
              </button>
            </div>
          ) : null}
          {!mapSupported ? (
            <div className="map-webgl-fallback" role="status">
              지도 렌더링을 지원하지 않는 환경입니다. 우측 실제 지역 목록으로 동일 대상을 선택할 수
              있습니다.
            </div>
          ) : null}
          <div className="map-canvas" ref={containerRef} />
          {panoramaPosition ? (
            <section className="map-panorama-overlay" aria-label="선택 건물 거리뷰">
              <header>
                <div>
                  <strong>{selectedDetail.data?.name ?? "선택 건물"}</strong>
                  <span>건물 주변 네이버 거리뷰</span>
                </div>
                <button
                  aria-label="거리뷰 닫기"
                  onClick={() => setPanoramaPosition(null)}
                  type="button"
                >
                  닫기
                </button>
              </header>
              <NaverPanoramaView
                keyId={config.data?.naverMapsNcpKeyId}
                position={panoramaPosition}
              />
            </section>
          ) : null}
          <div className="map-attribution-note">
            지도·거리뷰 © NAVER Cloud · 위험도는 발생확률이 아닌 광주·전남 내 상대점수·순위입니다.
          </div>
        </section>

        <aside className="map-side-panel" aria-label="지도 선택과 목록">
          <div className="map-side-heading">
            <div>
              <span>현재 단계</span>
              <h2>{levelLabel} 선택</h2>
            </div>
            <span className="map-count">
              {viewport.zoom >= BUILDING_ZOOM
                ? `${buildingList.data?.pagination.total.toLocaleString("ko-KR") ?? 0}개`
                : `${visibleRegions.length}개 지역`}
            </span>
          </div>

          {selectedRegionFeature ? (
            <section className="map-selection-card">
              <span>선택 지역</span>
              <strong>{selectedRegionFeature.properties.fullName}</strong>
              <p>
                건물 {selectedRegionFeature.properties.buildingCount.toLocaleString("ko-KR")}개 ·
                상위 10% {selectedRegionFeature.properties.top10Count.toLocaleString("ko-KR")}개
              </p>
              <div>
                {selectedRegionFeature.properties.level !== "EUPMYEONDONG" ? (
                  <AppLink
                    className="outline-action"
                    currentPath={currentPath}
                    runtime={runtime}
                    to={`/regions/${selectedRegionFeature.properties.regionCode}?returnTo=${returnToMap}`}
                  >
                    지역 분석 보기
                  </AppLink>
                ) : null}
                {selectedRegionFeature.properties.level !== "SIDO" ? (
                  <button
                    className="primary-map-action"
                    onClick={() =>
                      moveNaverMap(
                        mapRef.current,
                        selectedRegionFeature.properties.center,
                        selectedRegionFeature.properties.level === "SIGUNGU"
                          ? NEIGHBORHOOD_ZOOM + 0.7
                          : BUILDING_ZOOM + 0.5,
                      )
                    }
                    type="button"
                  >
                    {selectedRegionFeature.properties.level === "SIGUNGU"
                      ? "읍·면·동 단계로 확대"
                      : "건물 단계로 확대"}
                  </button>
                ) : null}
              </div>
            </section>
          ) : null}

          {selectedDetail.data ? (
            <section className="map-selection-card building">
              <span>선택 건물</span>
              <strong>{selectedDetail.data.name}</strong>
              <p>{selectedDetail.data.roadAddress ?? selectedDetail.data.lotAddress}</p>
              <dl>
                <div>
                  <dt>위험구간</dt>
                  <dd>{riskNames[selectedDetail.data.risk.riskBand]}</dd>
                </div>
                <div>
                  <dt>광주·전남 순위</dt>
                  <dd>{selectedDetail.data.risk.regionalRank.toLocaleString("ko-KR")}위</dd>
                </div>
                <div>
                  <dt>상위 백분위</dt>
                  <dd>상위 {selectedDetail.data.risk.topPercentile.toFixed(2)}%</dd>
                </div>
              </dl>
              <div className="map-selection-actions">
                <AppLink
                  className="primary-action"
                  currentPath={currentPath}
                  runtime={runtime}
                  to={`/buildings/${selectedDetail.data.buildingId}?returnTo=${returnToMap}`}
                >
                  건물 분석 보기
                </AppLink>
              </div>
            </section>
          ) : null}

          <div className="map-list" aria-live="polite">
            {viewport.zoom < BUILDING_ZOOM ? (
              <ol>
                {visibleRegions.map((feature, index) => (
                  <li key={feature.properties.regionCode}>
                    <button onClick={() => chooseRegionFromList(feature)} type="button">
                      <span className="region-rank">{index + 1}</span>
                      <span>
                        <strong>{feature.properties.fullName}</strong>
                        <small>
                          건물 {feature.properties.buildingCount.toLocaleString("ko-KR")}개 · 상위
                          10% {feature.properties.top10Count.toLocaleString("ko-KR")}개
                        </small>
                      </span>
                      <b>{feature.properties.top10Share?.toFixed(1)}%</b>
                    </button>
                  </li>
                ))}
              </ol>
            ) : buildingList.isLoading ? (
              <div className="map-list-message">현재 화면의 건물을 불러오는 중입니다.</div>
            ) : buildingList.isError ? (
              <div className="map-list-message error">건물 목록을 불러오지 못했습니다.</div>
            ) : buildingList.data?.items.length ? (
              <ol>
                {buildingList.data.items.map((building) => (
                  <li key={building.buildingId}>
                    <button onClick={() => chooseBuildingFromList(building)} type="button">
                      <span className={`risk-marker ${building.risk.riskBand.toLowerCase()}`} />
                      <span>
                        <strong>{building.name}</strong>
                        <small>{building.roadAddress ?? building.lotAddress}</small>
                      </span>
                      <b>{building.risk.regionalRank.toLocaleString("ko-KR")}위</b>
                    </button>
                  </li>
                ))}
              </ol>
            ) : (
              <div className="map-list-message">현재 화면 범위에 정합된 건물이 없습니다.</div>
            )}
          </div>
        </aside>
      </div>
    </main>
  );
}
