# ruff: noqa: E501
import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

REFERENCE_MONTH = date(2026, 3, 1)
HORIZON_DAYS = 60
ALGORITHM_VERSION = "inspection-v1.0.0"
SCENARIO_TYPES = (
    "BALANCED",
    "HIGH_RISK_FOCUSED",
    "COVERAGE_EXPANDED",
)
FACILITY_TYPES = (
    "ESS",
    "데이터센터",
    "발전시설",
    "공동주택",
    "단독주택",
    "숙박시설",
    "공장",
    "동식물 관련시설",
    "판매시설",
    "근린생활시설",
    "창고시설",
    "자동차 관련시설",
    "교육연구시설",
    "의료시설",
    "종교시설",
    "기타",
)

_FACILITY_CATEGORY_SQL = """
CASE
    WHEN main_use ILIKE '%에너지저장%' OR main_use ILIKE '%ESS%' THEN 'ESS'
    WHEN main_use ILIKE '%데이터센터%' THEN '데이터센터'
    WHEN main_use ILIKE '%발전%' THEN '발전시설'
    WHEN main_use ILIKE '%공동주택%' OR main_use ILIKE '%아파트%' THEN '공동주택'
    WHEN main_use ILIKE '%단독주택%' THEN '단독주택'
    WHEN main_use ILIKE '%숙박%' THEN '숙박시설'
    WHEN main_use ILIKE '%공장%' THEN '공장'
    WHEN main_use ILIKE '%동식물%' OR main_use ILIKE '%축사%' THEN '동식물 관련시설'
    WHEN main_use ILIKE '%판매%' OR main_use ILIKE '%시장%' THEN '판매시설'
    WHEN main_use ILIKE '%근린생활%' OR main_use ILIKE '%제1종근생%'
      OR main_use ILIKE '%제2종근생%' THEN '근린생활시설'
    WHEN main_use ILIKE '%창고%' THEN '창고시설'
    WHEN main_use ILIKE '%자동차%' OR main_use ILIKE '%주차%' THEN '자동차 관련시설'
    WHEN main_use ILIKE '%교육%' OR main_use ILIKE '%학교%'
      OR main_use ILIKE '%연구%' THEN '교육연구시설'
    WHEN main_use ILIKE '%의료%' OR main_use ILIKE '%병원%'
      OR main_use ILIKE '%요양%' THEN '의료시설'
    WHEN main_use ILIKE '%종교%' THEN '종교시설'
    ELSE '기타'
END
"""


@dataclass(frozen=True)
class InspectionContractError(Exception):
    status_code: int
    code: str
    message: str


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def inclusive_days(start_date: date, end_date: date) -> int:
    if end_date < start_date:
        raise InspectionContractError(
            422,
            "INVALID_INSPECTION_DATE_RANGE",
            "종료일은 시작일보다 빠를 수 없습니다.",
        )
    return (end_date - start_date).days + 1


def expanded_filters(top_percentile: float, minimum_score: float) -> tuple[float, float]:
    for threshold in (1.0, 5.0, 10.0, 25.0, 100.0):
        if threshold > top_percentile:
            expanded_percentile = threshold
            break
    else:
        expanded_percentile = 100.0
    return expanded_percentile, max(0.0, round(minimum_score - 0.05, 6))


async def inspection_options(
    engine: AsyncEngine,
    timeout_seconds: float,
) -> dict[str, Any]:
    async with asyncio.timeout(timeout_seconds):
        async with engine.connect() as connection:
            regions = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT region_code, level, name, full_name, parent_code
                            FROM admin_region
                            WHERE level IN ('SIDO', 'SIGUNGU')
                            ORDER BY level, region_code
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )
    return {
        "regions": [
            {
                "regionCode": row["region_code"],
                "level": row["level"],
                "name": row["name"],
                "fullName": row["full_name"],
                "parentCode": row["parent_code"],
            }
            for row in regions
        ],
        "facilityTypes": list(FACILITY_TYPES),
        "risk": {
            "referenceMonth": REFERENCE_MONTH.isoformat(),
            "horizonDays": HORIZON_DAYS,
            "scoreMeaning": "발생확률이 아닌 v27.1 상대점수",
            "topPercentileOptions": [1, 5, 10, 25],
        },
        "algorithmVersion": ALGORITHM_VERSION,
    }


async def _resolve_context(
    connection: AsyncConnection,
    region_code: str | None,
    building_id: UUID | None,
    case_id: UUID | None,
) -> tuple[str | None, dict[str, Any]]:
    context: dict[str, Any] = {"region": None, "building": None, "case": None}
    resolved_region = region_code
    if region_code:
        region = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT region_code, level, full_name
                        FROM admin_region WHERE region_code = :region_code
                        """
                    ),
                    {"region_code": region_code},
                )
            )
            .mappings()
            .one_or_none()
        )
        if region is None:
            raise InspectionContractError(404, "REGION_NOT_FOUND", "대상 지역을 찾을 수 없습니다.")
        context["region"] = dict(region)
    if building_id:
        building = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT b.building_id, b.region_code,
                               coalesce(b.building_name, b.road_address, b.lot_address) AS label
                        FROM building b WHERE b.building_id = :building_id
                        """
                    ),
                    {"building_id": building_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if building is None:
            raise InspectionContractError(
                404, "BUILDING_NOT_FOUND", "대상 건물을 찾을 수 없습니다."
            )
        context["building"] = dict(building)
        resolved_region = resolved_region or building["region_code"]
    if case_id:
        case = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT case_id, case_number, title, primary_region_code
                        FROM case_record WHERE case_id = :case_id
                        """
                    ),
                    {"case_id": case_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if case is None:
            raise InspectionContractError(404, "CASE_NOT_FOUND", "연결할 Case를 찾을 수 없습니다.")
        context["case"] = dict(case)
        resolved_region = resolved_region or case["primary_region_code"]
    return resolved_region, context


async def create_simulation(
    engine: AsyncEngine,
    *,
    profile: str,
    region_code: str | None,
    building_id: UUID | None,
    case_id: UUID | None,
    facility_types: list[str],
    start_date: date,
    end_date: date,
    team_count: int,
    daily_capacity_per_team: int,
    top_percentile: float,
    minimum_score: float,
    user_id: UUID,
    request_id: UUID,
    idempotency_key: str,
) -> dict[str, Any]:
    unknown = sorted(set(facility_types) - set(FACILITY_TYPES))
    if unknown:
        raise InspectionContractError(
            422, "INVALID_FACILITY_TYPE", "지원하지 않는 시설유형이 포함되어 있습니다."
        )
    day_count = inclusive_days(start_date, end_date)
    capacity = day_count * team_count * daily_capacity_per_team
    expanded_percentile, expanded_score = expanded_filters(top_percentile, minimum_score)
    normalized_types = sorted(set(facility_types))
    simulation_id = uuid4()
    async with engine.begin() as connection:
        duplicate = (
            await connection.execute(
                text(
                    """
                    SELECT inspection_simulation_id
                    FROM inspection_simulation
                    WHERE idempotency_key = :idempotency_key
                    """
                ),
                {"idempotency_key": idempotency_key},
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            return {"inspectionSimulationId": str(duplicate), "status": "QUEUED", "reused": True}
        resolved_region, context = await _resolve_context(
            connection, region_code, building_id, case_id
        )
        lineage = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT min(lineage_version) AS lineage_version,
                               min(manifest_hash) AS manifest_hash,
                               count(DISTINCT lineage_version) AS lineage_count,
                               count(DISTINCT manifest_hash) AS manifest_count
                        FROM building_risk_snapshot
                        WHERE reference_month = :reference_month AND horizon_days = :horizon_days
                        """
                    ),
                    {"reference_month": REFERENCE_MONTH, "horizon_days": HORIZON_DAYS},
                )
            )
            .mappings()
            .one()
        )
        if lineage["lineage_count"] != 1 or lineage["manifest_count"] != 1:
            raise InspectionContractError(
                503, "RISK_SNAPSHOT_UNAVAILABLE", "고정 위험도 기준자산을 확인할 수 없습니다."
            )
        input_contract = {
            "regionCode": resolved_region,
            "buildingId": str(building_id) if building_id else None,
            "caseId": str(case_id) if case_id else None,
            "facilityTypes": normalized_types,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "teamCount": team_count,
            "dailyCapacityPerTeam": daily_capacity_per_team,
            "topPercentile": top_percentile,
            "minimumScore": minimum_score,
            "referenceMonth": REFERENCE_MONTH.isoformat(),
            "horizonDays": HORIZON_DAYS,
            "lineageVersion": lineage["lineage_version"],
            "algorithmVersion": ALGORITHM_VERSION,
        }
        await connection.execute(
            text(
                """
                INSERT INTO inspection_simulation (
                    inspection_simulation_id, region_code, building_id, case_id,
                    facility_types, start_date, end_date, team_count,
                    daily_capacity_per_team, inclusive_day_count, total_capacity,
                    top_percentile, minimum_score, expanded_top_percentile,
                    expanded_minimum_score, reference_month, horizon_days,
                    lineage_version, manifest_hash, algorithm_version,
                    input_sha256, idempotency_key, status, created_by
                ) VALUES (
                    :simulation_id, :region_code, :building_id, :case_id,
                    CAST(:facility_types AS text[]), :start_date, :end_date, :team_count,
                    :daily_capacity, :day_count, :capacity, :top_percentile,
                    :minimum_score, :expanded_percentile, :expanded_score,
                    :reference_month, :horizon_days, :lineage_version,
                    :manifest_hash, :algorithm_version, :input_sha256,
                    :idempotency_key, 'QUEUED', :created_by
                )
                """
            ),
            {
                "simulation_id": simulation_id,
                "region_code": resolved_region,
                "building_id": building_id,
                "case_id": case_id,
                "facility_types": normalized_types,
                "start_date": start_date,
                "end_date": end_date,
                "team_count": team_count,
                "daily_capacity": daily_capacity_per_team,
                "day_count": day_count,
                "capacity": capacity,
                "top_percentile": top_percentile,
                "minimum_score": minimum_score,
                "expanded_percentile": expanded_percentile,
                "expanded_score": expanded_score,
                "reference_month": REFERENCE_MONTH,
                "horizon_days": HORIZON_DAYS,
                "lineage_version": lineage["lineage_version"],
                "manifest_hash": lineage["manifest_hash"],
                "algorithm_version": ALGORITHM_VERSION,
                "input_sha256": _hash(input_contract),
                "idempotency_key": idempotency_key,
                "created_by": user_id,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO audit_event (
                    audit_event_id, profile, actor_type, actor_user_id, action,
                    target_type, target_id, correlation_id, idempotency_key, metadata
                ) VALUES (
                    :audit_id, :profile, 'USER', :user_id,
                    'INSPECTION_SIMULATION_QUEUED', 'inspection_simulation',
                    :target_id, :request_id, :audit_key, CAST(:metadata AS jsonb)
                )
                """
            ),
            {
                "audit_id": uuid4(),
                "profile": profile,
                "user_id": user_id,
                "target_id": str(simulation_id),
                "request_id": request_id,
                "audit_key": f"inspection-create:{profile}:{idempotency_key}",
                "metadata": json.dumps(
                    {"input": input_contract, "context": context}, ensure_ascii=False
                ),
            },
        )
    return {
        "inspectionSimulationId": str(simulation_id),
        "status": "QUEUED",
        "reused": False,
    }
