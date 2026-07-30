import type { MultiPolygon, Polygon } from "geojson";
import { useEffect, useRef, useState } from "react";

export interface NaverMapConfigData {
  naverMapsNcpKeyId?: string | null;
  naverMapsConfigured?: boolean;
}

export interface NaverPoint {
  id: string;
  center: [number, number];
  title: string;
  tone: "danger" | "warning" | "primary" | "neutral";
  emphasized?: boolean;
}

export interface NaverPolygonItem {
  id: string;
  center: [number, number];
  title: string;
  geometry: Polygon | MultiPolygon;
  isIncidentBuilding: boolean;
}

let sdkPromise: Promise<typeof naver> | null = null;
let sdkKeyId: string | null = null;

function currentSdk(): typeof naver | undefined {
  return (globalThis as typeof globalThis & { naver?: typeof naver }).naver;
}

export function supportsNaverMaps(): boolean {
  return (
    typeof document !== "undefined" &&
    typeof navigator !== "undefined" &&
    !navigator.userAgent.toLowerCase().includes("jsdom")
  );
}

export function loadNaverMaps(keyId: string): Promise<typeof naver> {
  const loaded = currentSdk();
  if (loaded?.maps?.Map) {
    return Promise.resolve(loaded);
  }
  if (!keyId.trim()) {
    return Promise.reject(new Error("NAVER_MAPS_NCP_KEY_ID_REQUIRED"));
  }
  if (sdkPromise) {
    if (sdkKeyId !== keyId) {
      return Promise.reject(new Error("NAVER_MAPS_NCP_KEY_ID_CHANGED"));
    }
    return sdkPromise;
  }
  sdkKeyId = keyId;
  sdkPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.id = "naver-maps-sdk";
    script.async = true;
    script.src = `https://oapi.map.naver.com/openapi/v3/maps.js?ncpKeyId=${encodeURIComponent(keyId)}&submodules=panorama`;
    script.onload = () => {
      const sdk = currentSdk();
      if (sdk?.maps?.Map) {
        resolve(sdk);
      } else {
        sdkPromise = null;
        reject(new Error("NAVER_MAPS_SDK_UNAVAILABLE"));
      }
    };
    script.onerror = () => {
      sdkPromise = null;
      reject(new Error("NAVER_MAPS_SDK_LOAD_FAILED"));
    };
    document.head.appendChild(script);
  });
  return sdkPromise;
}

export function moveNaverMap(
  map: naver.maps.Map | null,
  center: [number, number],
  zoom: number,
): void {
  if (!map) {
    return;
  }
  map.morph(new naver.maps.LatLng(center[1], center[0]), Math.round(zoom), {
    duration: 400,
  });
}

function markerIcon(tone: NaverPoint["tone"], selected: boolean, emphasized: boolean) {
  const classNames = [
    "naver-point-marker",
    `tone-${tone}`,
    selected ? "selected" : "",
    emphasized ? "emphasized" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return {
    content: `<span class="${classNames}" aria-hidden="true"></span>`,
    anchor: new naver.maps.Point(10, 10),
  };
}

export function NaverPointMap({
  keyId,
  points,
  selectedId = null,
  onSelect,
  initialZoom = 13,
  className,
  fallbackMessage,
}: {
  keyId: string | null | undefined;
  points: NaverPoint[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  initialZoom?: number;
  className: string;
  fallbackMessage: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<naver.maps.Map | null>(null);
  const markersRef = useRef<Map<string, naver.maps.Marker>>(new Map());
  const pointByIdRef = useRef<Map<string, NaverPoint>>(new Map());
  const onSelectRef = useRef(onSelect);
  const selectedIdRef = useRef(selectedId);
  const [loadError, setLoadError] = useState(false);
  onSelectRef.current = onSelect;
  selectedIdRef.current = selectedId;
  pointByIdRef.current = new Map(points.map((point) => [point.id, point]));

  useEffect(() => {
    if (!supportsNaverMaps() || !keyId || !containerRef.current || points.length === 0) {
      return;
    }
    let cancelled = false;
    let listeners: naver.maps.MapEventListener[] = [];
    let map: naver.maps.Map | null = null;
    setLoadError(false);
    loadNaverMaps(keyId)
      .then(() => {
        if (cancelled || !containerRef.current) {
          return;
        }
        map = new naver.maps.Map(containerRef.current, {
          center: new naver.maps.LatLng(points[0].center[1], points[0].center[0]),
          zoom: initialZoom,
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
        const firstPosition = new naver.maps.LatLng(points[0].center[1], points[0].center[0]);
        const bounds = new naver.maps.LatLngBounds(firstPosition, firstPosition);
        const markers = new Map<string, naver.maps.Marker>();
        for (const point of points) {
          const position = new naver.maps.LatLng(point.center[1], point.center[0]);
          bounds.extend(position);
          const marker = new naver.maps.Marker({
            map,
            position,
            title: point.title,
            clickable: Boolean(onSelectRef.current),
            icon: markerIcon(
              point.tone,
              selectedIdRef.current === point.id,
              Boolean(point.emphasized),
            ),
          });
          if (onSelectRef.current) {
            listeners.push(
              naver.maps.Event.addListener(marker, "click", () => onSelectRef.current?.(point.id)),
            );
          }
          markers.set(point.id, marker);
        }
        markersRef.current = markers;
        if (points.length > 1) {
          map.fitBounds(bounds, { top: 55, right: 55, bottom: 55, left: 55, maxZoom: 15 });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoadError(true);
        }
      });
    return () => {
      cancelled = true;
      currentSdk()?.maps.Event.removeListener(listeners);
      listeners = [];
      for (const marker of markersRef.current.values()) {
        marker.setMap(null);
      }
      markersRef.current.clear();
      map?.destroy();
      mapRef.current = null;
    };
  }, [initialZoom, keyId, points]);

  useEffect(() => {
    for (const [id, marker] of markersRef.current) {
      const point = pointByIdRef.current.get(id);
      if (point) {
        marker.setIcon(markerIcon(point.tone, selectedId === id, Boolean(point.emphasized)));
      }
    }
  }, [selectedId]);

  if (!supportsNaverMaps()) {
    return <div className={`${className}-fallback`}>{fallbackMessage}</div>;
  }
  if (!keyId) {
    return (
      <div className={`${className}-fallback`}>네이버 지도 ncpKeyId가 설정되지 않았습니다.</div>
    );
  }
  if (loadError) {
    return <div className={`${className}-fallback`}>네이버 지도를 불러오지 못했습니다.</div>;
  }
  return <div className={className} ref={containerRef} />;
}

export function NaverPolygonMap({
  keyId,
  polygons,
  initialZoom = 18,
  className,
  fallbackMessage,
}: {
  keyId: string | null | undefined;
  polygons: NaverPolygonItem[];
  initialZoom?: number;
  className: string;
  fallbackMessage: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    if (!supportsNaverMaps() || !keyId || !containerRef.current || polygons.length === 0) {
      return;
    }
    let cancelled = false;
    let map: naver.maps.Map | null = null;
    let layer: naver.maps.Data | null = null;
    setLoadError(false);
    loadNaverMaps(keyId)
      .then(() => {
        if (cancelled || !containerRef.current) return;
        const first = polygons[0];
        const firstPosition = new naver.maps.LatLng(first.center[1], first.center[0]);
        map = new naver.maps.Map(containerRef.current, {
          center: firstPosition,
          zoom: initialZoom,
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
        layer = new naver.maps.Data();
        layer.setStyle((feature) => {
          const incident = feature.getProperty("isIncidentBuilding") === true;
          return {
            fillColor: incident ? "#d71920" : "#f47b20",
            fillOpacity: incident ? 0.76 : 0.56,
            strokeColor: incident ? "#870d13" : "#b9500f",
            strokeOpacity: 1,
            strokeWeight: incident ? 4 : 2,
            clickable: false,
            zIndex: incident ? 40 : 25,
          };
        });
        layer.addGeoJson(
          {
            type: "FeatureCollection",
            features: polygons.map((polygon) => ({
              type: "Feature",
              id: polygon.id,
              geometry: polygon.geometry,
              properties: {
                buildingId: polygon.id,
                title: polygon.title,
                isIncidentBuilding: polygon.isIncidentBuilding,
              },
            })),
          },
          false,
        );
        layer.setMap(map);
        const bounds = new naver.maps.LatLngBounds(firstPosition, firstPosition);
        for (const polygon of polygons.slice(1)) {
          bounds.extend(new naver.maps.LatLng(polygon.center[1], polygon.center[0]));
        }
        if (polygons.length > 1) {
          map.fitBounds(bounds, { top: 45, right: 45, bottom: 45, left: 45, maxZoom: 19 });
        }
      })
      .catch(() => {
        if (!cancelled) setLoadError(true);
      });
    return () => {
      cancelled = true;
      layer?.setMap(null);
      map?.destroy();
    };
  }, [initialZoom, keyId, polygons]);

  if (!supportsNaverMaps()) {
    return <div className={`${className}-fallback`}>{fallbackMessage}</div>;
  }
  if (!keyId) {
    return (
      <div className={`${className}-fallback`}>네이버 지도 ncpKeyId가 설정되지 않았습니다.</div>
    );
  }
  if (loadError) {
    return <div className={`${className}-fallback`}>네이버 지도를 불러오지 못했습니다.</div>;
  }
  return <div className={className} ref={containerRef} />;
}

export function NaverPanoramaView({
  keyId,
  position,
}: {
  keyId: string | null | undefined;
  position: [number, number];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    if (!supportsNaverMaps() || !keyId || !containerRef.current) {
      return;
    }
    let cancelled = false;
    let panorama: naver.maps.Panorama | null = null;
    let resizeObserver: ResizeObserver | null = null;
    setLoadError(false);
    loadNaverMaps(keyId)
      .then(() => {
        if (cancelled || !containerRef.current) {
          return;
        }
        panorama = new naver.maps.Panorama(containerRef.current, {
          position: new naver.maps.LatLng(position[1], position[0]),
          pov: { pan: 0, tilt: 0, fov: 90 },
          minZoom: 0,
          maxZoom: 4,
          zoomControl: true,
          zoomControlOptions: {
            position: naver.maps.Position.TOP_LEFT,
            style: naver.maps.ZoomControlStyle.SMALL,
          },
          aroundControl: true,
          aroundControlOptions: { position: naver.maps.Position.TOP_RIGHT },
          logoControl: true,
          flightSpot: true,
        });
        resizeObserver = new ResizeObserver(() => {
          if (panorama && containerRef.current) {
            panorama.setSize(
              new naver.maps.Size(
                containerRef.current.clientWidth,
                containerRef.current.clientHeight,
              ),
            );
          }
        });
        resizeObserver.observe(containerRef.current);
      })
      .catch(() => {
        if (!cancelled) {
          setLoadError(true);
        }
      });
    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
      panorama?.setVisible(false);
      if (containerRef.current) {
        containerRef.current.replaceChildren();
      }
    };
  }, [keyId, position]);

  if (!keyId) {
    return <div className="map-panorama-fallback">네이버 지도 ncpKeyId가 설정되지 않았습니다.</div>;
  }
  if (loadError) {
    return (
      <div className="map-panorama-fallback">
        이 위치의 거리뷰를 불러오지 못했습니다. 주변 300m의 촬영 지점을 확인하세요.
      </div>
    );
  }
  return <div className="map-panorama" ref={containerRef} />;
}
