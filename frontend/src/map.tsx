import { useQuery } from "@tanstack/react-query";
import type { Feature, FeatureCollection, MultiPolygon, Polygon } from "geojson";
import {
  AttributionControl,
  type GeoJSONSource,
  type MapGeoJSONFeature,
  Map as MapLibreMap,
  type MapMouseEvent,
  NavigationControl,
  type StyleSpecification,
  setWorkerUrl,
} from "maplibre-gl";
import mapWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef, useState } from "react";
import { apiRequest } from "./api";
import type { ProfileRuntime } from "./profile";
import { AppLink, currentInternalLocation } from "./router";

interface MapProvider {
  id: "vworld" | "osm";
  name: string;
  urlTemplate: string;
  attribution: string;
  priority: number;
}

interface MapConfigData {
  providers: MapProvider[];
  preferredProvider: "vworld" | "osm";
  fallbackActive: boolean;
  fallbackReason: "VWORLD_NOT_CONFIGURED" | null;
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

interface BuildingDetailData {
  buildingId: string;
  name: string;
  lotAddress: string;
  roadAddress: string | null;
  center: [number, number];
  bounds: [number, number, number, number];
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

const emptyCollection: FeatureCollection = { type: "FeatureCollection", features: [] };

const DISTRICT_ZOOM = 8.5;
const NEIGHBORHOOD_ZOOM = 11.5;
const BUILDING_ZOOM = 14;

function selectionRing(
  center: [number, number],
  bounds: [number, number, number, number],
): Feature<Polygon> {
  const [lng, lat] = center;
  const [west, south, east, north] = bounds;
  const metersPerLng = 111_320 * Math.cos((lat * Math.PI) / 180);
  const metersPerLat = 110_540;
  const radiusMeters =
    Math.max(
      15,
      ...[
        [west, south],
        [west, north],
        [east, south],
        [east, north],
      ].map(([cornerLng, cornerLat]) =>
        Math.hypot((cornerLng - lng) * metersPerLng, (cornerLat - lat) * metersPerLat),
      ),
    ) * 1.35;
  const coordinates = Array.from({ length: 65 }, (_, index) => {
    const angle = (index / 64) * Math.PI * 2;
    return [
      lng + (Math.cos(angle) * radiusMeters) / metersPerLng,
      lat + (Math.sin(angle) * radiusMeters) / metersPerLat,
    ];
  });
  return {
    type: "Feature",
    properties: {},
    geometry: { type: "Polygon", coordinates: [coordinates] },
  };
}

function nextRegionZoom(level: RegionProperties["level"]): number {
  if (level === "SIDO") return DISTRICT_ZOOM + 0.4;
  if (level === "SIGUNGU") return NEIGHBORHOOD_ZOOM + 0.4;
  return BUILDING_ZOOM + 0.4;
}

function nextRegionLabel(level: RegionProperties["level"]): string {
  if (level === "SIDO") return "시·군·구 단위로 확대";
  if (level === "SIGUNGU") return "읍·면·동 단위로 확대";
  return "건물 단위로 확대";
}

setWorkerUrl(mapWorkerUrl);

function initialNumber(name: string, fallback: number): number {
  const raw = new URLSearchParams(window.location.search).get(name);
  const parsed = raw === null ? Number.NaN : Number(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function currentSelection(name: string): string | null {
  return new URLSearchParams(window.location.search).get(name);
}

function rasterStyle(provider: MapProvider, runtime: ProfileRuntime): StyleSpecification {
  return {
    version: 8,
    sources: {
      basemap: {
        type: "raster",
        tiles: [provider.urlTemplate],
        tileSize: 256,
        attribution: provider.attribution,
      },
      admin: { type: "geojson", data: emptyCollection },
      selection: { type: "geojson", data: emptyCollection },
      buildings: {
        type: "vector",
        tiles: [`${window.location.origin}${runtime.apiBase}/map/buildings/{z}/{x}/{y}.mvt`],
        minzoom: 14,
        maxzoom: 20,
      },
    },
    layers: [
      { id: "basemap", type: "raster", source: "basemap" },
      {
        id: "admin-fill",
        type: "fill",
        source: "admin",
        maxzoom: BUILDING_ZOOM,
        paint: {
          "fill-color": [
            "interpolate",
            ["linear"],
            ["coalesce", ["get", "top10Share"], 0],
            5,
            "#dbe7f2",
            15,
            "#f1b88b",
            30,
            "#ce3d3d",
          ],
          "fill-opacity": 0.66,
        },
      },
      {
        id: "admin-line",
        type: "line",
        source: "admin",
        maxzoom: BUILDING_ZOOM,
        paint: { "line-color": "#264b73", "line-width": 1.8 },
      },
      {
        id: "admin-selected",
        type: "line",
        source: "admin",
        maxzoom: BUILDING_ZOOM,
        filter: ["==", ["get", "regionCode"], ""],
        paint: { "line-color": "#005fcc", "line-width": 4 },
      },
      {
        id: "building-fill",
        type: "fill",
        source: "buildings",
        "source-layer": "buildings",
        minzoom: 14,
        paint: {
          "fill-color": [
            "match",
            ["get", "risk_band"],
            "TOP_1",
            "#c9232c",
            "HIGH_1_10",
            "#e66b2f",
            "WATCH_10_25",
            "#efb43c",
            "#7d9ab5",
          ],
          "fill-opacity": ["case", ["boolean", ["get", "has_current_signal"], false], 0.95, 0.72],
          "fill-outline-color": "#4e6175",
        },
      },
      {
        id: "building-selected",
        type: "line",
        source: "buildings",
        "source-layer": "buildings",
        minzoom: 14,
        filter: ["==", ["get", "building_id"], ""],
        paint: { "line-color": "#005fcc", "line-width": 4 },
      },
      {
        id: "building-selection-ring",
        type: "line",
        source: "selection",
        minzoom: 14,
        paint: { "line-color": "#0877e1", "line-width": 2, "line-opacity": 0.95 },
      },
    ],
  };
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

function supportsWebGl(): boolean {
  return typeof navigator !== "undefined" && !navigator.userAgent.toLowerCase().includes("jsdom");
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
  const mapRef = useRef<MapLibreMap | null>(null);
  const buildingItemRefs = useRef(new Map<string, HTMLLIElement>());
  const lastCenteredBuildingRef = useRef<string | null>(null);
  const lastScrolledBuildingRef = useRef<string | null>(null);
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
  const [activeProviderId, setActiveProviderId] = useState<"vworld" | "osm" | null>(null);
  const [backgroundFallback, setBackgroundFallback] = useState(false);
  const [overlayError, setOverlayError] = useState<string | null>(null);
  const [mapStyleReady, setMapStyleReady] = useState(false);
  const [webGlReady] = useState(supportsWebGl);
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
    if (config.data && activeProviderId === null) {
      setActiveProviderId(config.data.preferredProvider);
      setBackgroundFallback(config.data.fallbackActive);
    }
  }, [activeProviderId, config.data]);

  const activeProvider = config.data?.providers.find((item) => item.id === activeProviderId);
  const osmProvider = config.data?.providers.find((item) => item.id === "osm");

  useEffect(() => {
    if (!webGlReady || !containerRef.current || !activeProvider) {
      return;
    }
    const map = new MapLibreMap({
      container: containerRef.current,
      style: rasterStyle(activeProvider, runtime),
      center: [initialViewportRef.current.lng, initialViewportRef.current.lat],
      zoom: initialViewportRef.current.zoom,
      minZoom: 6.5,
      maxZoom: 20,
      attributionControl: false,
    });
    mapRef.current = map;
    map.addControl(new NavigationControl({ showCompass: false }), "top-left");
    map.addControl(
      new AttributionControl({
        compact: true,
        customAttribution: activeProvider.attribution,
      }),
      "bottom-right",
    );

    const captureViewport = () => {
      const center = map.getCenter();
      const bounds = map.getBounds();
      const next = {
        lng: center.lng,
        lat: center.lat,
        zoom: map.getZoom(),
        bbox: [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()]
          .map((value) => value.toFixed(6))
          .join(","),
      };
      setViewport(next);
      updateMapUrl(next, selectionRef.current.region, selectionRef.current.building);
    };

    const chooseRegion = (event: MapMouseEvent & { features?: MapGeoJSONFeature[] }) => {
      const feature = event.features?.[0];
      const code = feature?.properties?.regionCode as string | undefined;
      const center = feature?.properties?.center as [number, number] | string | undefined;
      if (!code) {
        return;
      }
      const parsedCenter =
        typeof center === "string" ? (JSON.parse(center) as [number, number]) : center;
      setSelectedRegion(code);
      setSelectedBuilding(null);
      if (parsedCenter) map.easeTo({ center: parsedCenter, zoom: map.getZoom(), duration: 350 });
    };

    const chooseBuilding = (event: MapMouseEvent & { features?: MapGeoJSONFeature[] }) => {
      const feature = event.features?.[0];
      const buildingId = feature?.properties?.building_id as string | undefined;
      if (!buildingId) {
        return;
      }
      setSelectedBuilding(buildingId);
      map.setFilter("building-selected", ["==", ["get", "building_id"], buildingId]);
    };

    map.on("load", () => {
      setMapStyleReady(true);
      const adminSource = map.getSource("admin") as GeoJSONSource | undefined;
      const initialOverlay = overlayRef.current;
      if (initialOverlay) {
        adminSource?.setData(initialOverlay);
      }
      map.setFilter("building-selected", [
        "==",
        ["get", "building_id"],
        selectionRef.current.building ?? "",
      ]);
      map.setFilter("admin-selected", [
        "==",
        ["get", "regionCode"],
        selectionRef.current.region ?? "",
      ]);
      captureViewport();
      map.on("click", "admin-fill", chooseRegion);
      map.on("click", "building-fill", chooseBuilding);
      map.on("mouseenter", "admin-fill", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseenter", "building-fill", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "admin-fill", () => {
        map.getCanvas().style.cursor = "";
      });
      map.on("mouseleave", "building-fill", () => {
        map.getCanvas().style.cursor = "";
      });
    });
    map.on("moveend", captureViewport);
    map.on("error", (event) => {
      const sourceId = (event as unknown as { sourceId?: string }).sourceId;
      if (sourceId === "basemap" && activeProvider.id === "vworld" && osmProvider) {
        setBackgroundFallback(true);
        setActiveProviderId("osm");
      } else if (sourceId === "buildings") {
        setOverlayError("건물 폴리곤을 불러오지 못했습니다. 지도를 이동하거나 다시 시도해 주세요.");
      }
    });

    return () => {
      setMapStyleReady(false);
      map.remove();
      mapRef.current = null;
    };
  }, [activeProvider, osmProvider, runtime, webGlReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) {
      return;
    }
    const source = map.getSource("admin") as GeoJSONSource | undefined;
    source?.setData(overlay ?? emptyCollection);
  }, [overlay]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.getLayer("building-selected")) {
      return;
    }
    map.setFilter("building-selected", ["==", ["get", "building_id"], selectedBuilding ?? ""]);
    map.setFilter("admin-selected", ["==", ["get", "regionCode"], selectedRegion ?? ""]);
    updateMapUrl(viewport, selectedRegion, selectedBuilding);
  }, [selectedBuilding, selectedRegion, viewport]);

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
  const selectedDetail = useQuery({
    queryKey: ["map-building-detail", runtime.profile, selectedBuilding],
    queryFn: () =>
      apiRequest<BuildingDetailData>(runtime, `/buildings/${selectedBuilding}`).then(
        (result) => result.data,
      ),
    enabled: Boolean(selectedBuilding),
    staleTime: 60_000,
  });
  const visibleBuildings = useMemo(() => {
    const items = [...(buildingList.data?.items ?? [])];
    const detail = selectedDetail.data;
    if (detail && !items.some((item) => item.buildingId === detail.buildingId)) {
      items.push({
        buildingId: detail.buildingId,
        regionCode: "",
        name: detail.name,
        roadAddress: detail.roadAddress,
        lotAddress: detail.lotAddress,
        center: detail.center,
        risk: detail.risk,
        hasCurrentSignal: detail.currentSignals.hasCurrentSignal,
        monitoringPriority: "NORMAL",
      });
      items.sort((left, right) => left.risk.regionalRank - right.risk.regionalRank);
    }
    return items;
  }, [buildingList.data?.items, selectedDetail.data]);

  useEffect(() => {
    if (!mapStyleReady) return;
    const detail = selectedDetail.data;
    const map = mapRef.current;
    if (!detail || !map || lastCenteredBuildingRef.current === detail.buildingId) return;
    lastCenteredBuildingRef.current = detail.buildingId;
    map.flyTo({
      center: detail.center,
      zoom: Math.max(map.getZoom(), 16),
      duration: 450,
    });
  }, [mapStyleReady, selectedDetail.data]);

  useEffect(() => {
    if (!mapStyleReady) return;
    const detail = selectedDetail.data;
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) return;
    const source = map.getSource("selection") as GeoJSONSource | undefined;
    source?.setData(detail ? selectionRing(detail.center, detail.bounds) : emptyCollection);
  }, [mapStyleReady, selectedDetail.data]);

  useEffect(() => {
    if (selectedBuilding) return;
    lastCenteredBuildingRef.current = null;
    lastScrolledBuildingRef.current = null;
  }, [selectedBuilding]);

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
    mapRef.current?.flyTo({
      center: feature.properties.center,
      zoom: mapRef.current.getZoom(),
      duration: 350,
    });
  };

  const chooseBuildingFromList = (building: BuildingListItem) => {
    setSelectedBuilding(building.buildingId);
    mapRef.current?.flyTo({
      center: building.center,
      zoom: Math.max(viewport.zoom, 16),
      duration: 450,
    });
  };

  const retryOverlay = () => {
    setOverlayError(null);
    void provinces.refetch();
    void districts.refetch();
    if (viewport.bbox && viewport.zoom >= NEIGHBORHOOD_ZOOM && viewport.zoom < BUILDING_ZOOM)
      void neighborhoods.refetch();
    void buildingList.refetch();
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
              <span>
                {activeProvider?.name ?? "배경 준비 중"}
                {backgroundFallback ? " · 대체 배경" : " · 우선 배경"}
              </span>
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
          {!webGlReady ? (
            <div className="map-webgl-fallback" role="status">
              지도 렌더링을 지원하지 않는 환경입니다. 우측 실제 지역 목록으로 동일 대상을 선택할 수
              있습니다.
            </div>
          ) : null}
          <div className="map-canvas" ref={containerRef} />
          <div className="map-attribution-note">
            위험도는 발생확률이 아닌 광주·전남 내 상대점수·순위입니다.
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
                <AppLink
                  className="outline-action"
                  currentPath={currentPath}
                  runtime={runtime}
                  to={`/regions/${selectedRegionFeature.properties.regionCode}?returnTo=${returnToMap}`}
                >
                  지역 분석 보기
                </AppLink>
                <button
                  className="primary-map-action"
                  onClick={() =>
                    mapRef.current?.flyTo({
                      center: selectedRegionFeature.properties.center,
                      zoom: nextRegionZoom(selectedRegionFeature.properties.level),
                      duration: 600,
                    })
                  }
                  type="button"
                >
                  {nextRegionLabel(selectedRegionFeature.properties.level)}
                </button>
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
              <AppLink
                className="primary-action"
                currentPath={currentPath}
                runtime={runtime}
                to={`/buildings/${selectedDetail.data.buildingId}?returnTo=${returnToMap}`}
              >
                건물 분석 보기
              </AppLink>
            </section>
          ) : null}

          <div className="map-list" aria-live="polite">
            {viewport.zoom < BUILDING_ZOOM ? (
              <ol>
                {visibleRegions.map((feature, index) => (
                  <li
                    className={
                      selectedRegion === feature.properties.regionCode ? "is-selected" : undefined
                    }
                    key={feature.properties.regionCode}
                  >
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
            ) : visibleBuildings.length ? (
              <ol>
                {visibleBuildings.map((building) => (
                  <li
                    className={selectedBuilding === building.buildingId ? "is-selected" : undefined}
                    key={building.buildingId}
                    ref={(element) => {
                      if (element) {
                        buildingItemRefs.current.set(building.buildingId, element);
                        if (
                          selectedBuilding === building.buildingId &&
                          lastScrolledBuildingRef.current !== building.buildingId
                        ) {
                          lastScrolledBuildingRef.current = building.buildingId;
                          element.scrollIntoView({ block: "nearest", behavior: "smooth" });
                        }
                      } else {
                        buildingItemRefs.current.delete(building.buildingId);
                      }
                    }}
                  >
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
