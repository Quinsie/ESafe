from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse, Response

from app.api.auth import require_session
from app.api.responses import envelope
from app.auth import AuthenticatedSession
from app.spatial import (
    MAX_BUILDING_ZOOM,
    MIN_BUILDING_ZOOM,
    MIN_NEIGHBORHOOD_ZOOM,
    SpatialContractError,
    building_detail,
    building_tile,
    parse_bbox,
    parse_region_bbox,
    region_detail,
    region_features,
    risk_rankings,
    viewport_buildings,
)

router = APIRouter(prefix="/api/v1", tags=["spatial"])
Session = Annotated[AuthenticatedSession, Depends(require_session)]


def _spatial_error(request: Request, error: SpatialContractError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=envelope(request, None, error={"code": error.code, "message": error.message}),
    )


@router.get("/map/config")
async def map_config(request: Request, _: Session) -> dict[str, object]:
    settings = request.app.state.settings
    vworld_url = settings.vworld_tile_url
    providers: list[dict[str, object]] = []
    if vworld_url:
        providers.append(
            {
                "id": "vworld",
                "name": "VWorld",
                "urlTemplate": vworld_url,
                "attribution": "공간정보 오픈플랫폼 VWorld",
                "priority": 1,
            }
        )
    providers.append(
        {
            "id": "osm",
            "name": "OpenStreetMap",
            "urlTemplate": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            "attribution": "© OpenStreetMap contributors",
            "priority": 2,
        }
    )
    return envelope(
        request,
        {
            "providers": providers,
            "preferredProvider": "vworld" if vworld_url else "osm",
            "fallbackActive": not bool(vworld_url),
            "fallbackReason": None if vworld_url else "VWORLD_NOT_CONFIGURED",
            "buildingZoom": {"minimum": MIN_BUILDING_ZOOM, "maximum": MAX_BUILDING_ZOOM},
            "neighborhoodZoom": {"minimum": MIN_NEIGHBORHOOD_ZOOM, "maximum": MIN_BUILDING_ZOOM},
        },
    )


@router.get("/map/regions")
async def map_regions(request: Request, _: Session) -> dict[str, object]:
    settings = request.app.state.settings
    data = await region_features(
        request.app.state.db_engine, "SIDO", None, settings.health_timeout_seconds
    )
    return envelope(request, data)


@router.get("/map/districts")
async def map_districts(
    request: Request,
    _: Session,
    parent_code: Annotated[str, Query(alias="parentCode", pattern="^(29|46)$")],
) -> dict[str, object]:
    settings = request.app.state.settings
    data = await region_features(
        request.app.state.db_engine,
        "SIGUNGU",
        parent_code,
        settings.health_timeout_seconds,
    )
    return envelope(request, data)


@router.get("/map/neighborhoods")
async def map_neighborhoods(
    request: Request,
    _: Session,
    bbox: str,
) -> Any:
    settings = request.app.state.settings
    try:
        parsed = parse_region_bbox(bbox)
        data = await region_features(
            request.app.state.db_engine,
            "EUPMYEONDONG",
            None,
            settings.health_timeout_seconds,
            parsed,
        )
    except SpatialContractError as error:
        return _spatial_error(request, error)
    return envelope(request, data)


@router.get("/map/buildings/{z}/{x}/{y}.mvt")
async def map_building_tile(request: Request, _: Session, z: int, x: int, y: int) -> Response:
    settings = request.app.state.settings
    try:
        data = await building_tile(
            request.app.state.db_engine, z, x, y, settings.health_timeout_seconds
        )
    except SpatialContractError as error:
        return _spatial_error(request, error)
    return Response(
        content=data,
        media_type="application/vnd.mapbox-vector-tile",
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/map/buildings")
async def map_building_list(
    request: Request,
    _: Session,
    bbox: str,
    zoom: float,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 50,
    risk_band: Annotated[str | None, Query(alias="riskBand")] = None,
    sort: str = "rank",
) -> Any:
    settings = request.app.state.settings
    try:
        parsed = parse_bbox(bbox, zoom)
        data = await viewport_buildings(
            request.app.state.db_engine,
            parsed,
            page,
            page_size,
            risk_band,
            sort,
            settings.health_timeout_seconds,
        )
    except SpatialContractError as error:
        return _spatial_error(request, error)
    return envelope(request, data)


@router.get("/risk-rankings")
async def get_risk_rankings(
    request: Request,
    _: Session,
    level: Literal["SIDO", "SIGUNGU", "EUPMYEONDONG", "BUILDING"],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 24,
) -> Any:
    settings = request.app.state.settings
    data = await risk_rankings(
        request.app.state.db_engine,
        level,
        page,
        page_size,
        settings.health_timeout_seconds,
    )
    return envelope(request, data)


@router.get("/regions/{region_code}")
async def get_region(
    request: Request,
    _: Session,
    region_code: Annotated[str, Path(pattern="^[0-9]{2,10}$")],
) -> Any:
    settings = request.app.state.settings
    data = await region_detail(
        request.app.state.db_engine, region_code, settings.health_timeout_seconds
    )
    if data is None:
        return JSONResponse(
            status_code=404,
            content=envelope(
                request,
                None,
                error={"code": "REGION_NOT_FOUND", "message": "지역을 찾을 수 없습니다."},
            ),
        )
    return envelope(request, data)


@router.get("/buildings/{building_id}")
async def get_building(
    request: Request,
    _: Session,
    building_id: UUID,
) -> Any:
    settings = request.app.state.settings
    data = await building_detail(
        request.app.state.db_engine, building_id, settings.health_timeout_seconds
    )
    if data is None:
        return JSONResponse(
            status_code=404,
            content=envelope(
                request,
                None,
                error={"code": "BUILDING_NOT_FOUND", "message": "건물을 찾을 수 없습니다."},
            ),
        )
    return envelope(request, data)
