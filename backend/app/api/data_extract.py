import asyncio
from datetime import date
from typing import Annotated, Any, Literal, cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response

from app.api.auth import require_session
from app.api.responses import envelope
from app.auth import AuthenticatedSession
from app.data_extract import (
    TopPercent,
    build_extract_workbook,
    extract_building_rows,
    extract_region_options,
)

router = APIRouter(prefix="/api/v1/data-extract", tags=["data-extract"])
Session = Annotated[AuthenticatedSession, Depends(require_session)]


@router.get("/regions")
async def get_extract_regions(
    request: Request,
    _: Session,
    level: Literal["SIDO", "SIGUNGU"],
    parent_code: Annotated[
        str | None, Query(alias="parentCode", pattern="^[0-9]{2,10}$")
    ] = None,
) -> Any:
    settings = request.app.state.settings
    data = await extract_region_options(
        request.app.state.db_engine,
        level,
        parent_code,
        settings.health_timeout_seconds,
    )
    return envelope(request, data)


@router.get("/buildings.xlsx")
async def download_buildings(
    request: Request,
    _: Session,
    level: Literal["SIDO", "SIGUNGU"],
    region_code: Annotated[str, Query(alias="regionCode", pattern="^[0-9]{2,10}$")],
    top_percent: Annotated[int, Query(alias="topPercent", ge=1, le=10)] = 10,
) -> Response:
    settings = request.app.state.settings
    if top_percent not in (1, 5, 10):
        return JSONResponse(
            status_code=422,
            content=envelope(
                request,
                None,
                error={
                    "code": "INVALID_TOP_PERCENT",
                    "message": "위험도 범위는 상위 1%, 5%, 10% 중에서 선택해 주세요.",
                },
            ),
        )
    validated_top_percent = cast(TopPercent, top_percent)
    try:
        region_name, rows = await extract_building_rows(
            request.app.state.db_engine,
            level,
            region_code,
            validated_top_percent,
            settings.health_timeout_seconds,
        )
    except ValueError:
        return JSONResponse(
            status_code=404,
            content=envelope(
                request,
                None,
                error={"code": "REGION_NOT_FOUND", "message": "추출할 지역을 찾을 수 없습니다."},
            ),
        )
    as_of = date.today()
    content = await asyncio.to_thread(
        build_extract_workbook,
        level=level,
        region_name=region_name,
        top_percent=validated_top_percent,
        rows=rows,
        as_of=as_of,
    )
    ascii_name = f"esafe-risk-buildings-{region_code}-top{top_percent}-{as_of.isoformat()}.xlsx"
    korean_name = f"E-Safe_{region_name}_상위{top_percent}pct_{as_of.isoformat()}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(korean_name)}'
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Export-Row-Count": str(len(rows)),
        },
    )
