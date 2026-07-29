# ruff: noqa: E501
import asyncio
import json
import math
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.inspections import InspectionContractError


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _payload(row: Any, scenarios: list[Any]) -> dict[str, Any]:
    return {
        "inspectionSimulationId": str(row["inspection_simulation_id"]),
        "status": row["status"],
        "version": int(row["version"]),
        "context": {
            "regionCode": row["region_code"],
            "regionName": row["region_name"],
            "buildingId": str(row["building_id"]) if row["building_id"] else None,
            "buildingLabel": row["building_label"],
            "caseId": str(row["case_id"]) if row["case_id"] else None,
            "caseNumber": row["case_number"],
        },
        "conditions": {
            "facilityTypes": list(row["facility_types"]),
            "startDate": row["start_date"].isoformat(),
            "endDate": row["end_date"].isoformat(),
            "inclusiveDayCount": int(row["inclusive_day_count"]),
            "teamCount": int(row["team_count"]),
            "dailyCapacityPerTeam": int(row["daily_capacity_per_team"]),
            "totalCapacity": int(row["total_capacity"]),
            "topPercentile": float(row["top_percentile"]),
            "minimumScore": float(row["minimum_score"]),
            "expandedTopPercentile": float(row["expanded_top_percentile"]),
            "expandedMinimumScore": float(row["expanded_minimum_score"]),
        },
        "riskSnapshot": {
            "referenceMonth": row["reference_month"].isoformat(),
            "horizonDays": int(row["horizon_days"]),
            "lineageVersion": row["lineage_version"],
            "manifestHash": row["manifest_hash"],
            "isProbability": False,
        },
        "algorithmVersion": row["algorithm_version"],
        "inputSha256": row["input_sha256"],
        "selectedScenarioId": str(row["selected_scenario_id"])
        if row["selected_scenario_id"]
        else None,
        "error": {"code": row["error_code"], "message": row["error_message"]}
        if row["status"] == "FAILED"
        else None,
        "createdAt": _iso(row["created_at"]),
        "startedAt": _iso(row["started_at"]),
        "completedAt": _iso(row["completed_at"]),
        "scenarios": [
            {
                "inspectionScenarioId": str(item["inspection_scenario_id"]),
                "scenarioType": item["scenario_type"],
                "ordinal": int(item["ordinal"]),
                "status": item["status"],
                "candidateCount": int(item["candidate_count"]),
                "selectedCount": int(item["selected_count"]),
                "excludedCount": int(item["excluded_count"]),
                "candidateCoveragePercent": float(item["candidate_coverage_percent"]),
                "requiredDays": int(item["required_days"]),
                "overCapacity": bool(item["over_capacity"]),
                "confirmable": bool(item["confirmable"]),
                "explanation": dict(item["explanation"]),
                "contentSha256": item["content_sha256"],
                "version": int(item["version"]),
                "selected": item["inspection_scenario_id"] == row["selected_scenario_id"],
            }
            for item in scenarios
        ],
    }


async def _load(
    connection: AsyncConnection, simulation_id: UUID, *, lock: bool = False
) -> tuple[Any, list[Any]]:
    suffix = " FOR UPDATE OF simulation" if lock else ""
    row = (
        (
            await connection.execute(
                text(f"""
        SELECT simulation.*, region.full_name AS region_name,
               coalesce(building.building_name, building.road_address, building.lot_address) AS building_label,
               case_record.case_number
        FROM inspection_simulation simulation
        LEFT JOIN admin_region region ON region.region_code = simulation.region_code
        LEFT JOIN building ON building.building_id = simulation.building_id
        LEFT JOIN case_record ON case_record.case_id = simulation.case_id
        WHERE simulation.inspection_simulation_id = :simulation_id {suffix}
    """),
                {"simulation_id": simulation_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise InspectionContractError(
            404, "INSPECTION_SIMULATION_NOT_FOUND", "점검 시뮬레이션을 찾을 수 없습니다."
        )
    scenarios = (
        (
            await connection.execute(
                text("""
        SELECT * FROM inspection_scenario
        WHERE inspection_simulation_id = :simulation_id ORDER BY ordinal
    """),
                {"simulation_id": simulation_id},
            )
        )
        .mappings()
        .all()
    )
    return row, list(scenarios)


async def simulation_detail(
    engine: AsyncEngine, simulation_id: UUID, timeout_seconds: float
) -> dict[str, Any]:
    async with asyncio.timeout(timeout_seconds):
        async with engine.connect() as connection:
            row, scenarios = await _load(connection, simulation_id)
    return _payload(row, scenarios)


async def select_scenario(
    engine: AsyncEngine,
    *,
    profile: str,
    simulation_id: UUID,
    scenario_id: UUID,
    expected_version: int,
    user_id: UUID,
    request_id: UUID,
    idempotency_key: str,
) -> dict[str, Any]:
    audit_key = f"inspection-select:{profile}:{idempotency_key}"
    async with engine.begin() as connection:
        duplicate = (
            await connection.execute(
                text("SELECT target_id FROM audit_event WHERE idempotency_key = :key"),
                {"key": audit_key},
            )
        ).scalar_one_or_none()
        if duplicate is None:
            simulation, _ = await _load(connection, simulation_id, lock=True)
            if int(simulation["version"]) != expected_version:
                raise InspectionContractError(
                    409,
                    "INSPECTION_VERSION_CONFLICT",
                    "다른 변경이 반영되었습니다. 최신 결과를 다시 확인해 주세요.",
                )
            if simulation["status"] not in ("CALCULATED", "ON_HOLD"):
                raise InspectionContractError(
                    409,
                    "INSPECTION_SELECTION_LOCKED",
                    "현재 상태에서는 시나리오를 변경할 수 없습니다.",
                )
            scenario = (
                (
                    await connection.execute(
                        text("""
                SELECT * FROM inspection_scenario
                WHERE inspection_scenario_id = :scenario_id
                  AND inspection_simulation_id = :simulation_id FOR UPDATE
            """),
                        {"scenario_id": scenario_id, "simulation_id": simulation_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if scenario is None:
                raise InspectionContractError(
                    404, "INSPECTION_SCENARIO_NOT_FOUND", "선택할 시나리오를 찾을 수 없습니다."
                )
            if not scenario["confirmable"]:
                code = (
                    "INSPECTION_CAPACITY_EXCEEDED"
                    if scenario["over_capacity"]
                    else "INSPECTION_TARGET_EMPTY"
                )
                raise InspectionContractError(
                    409,
                    code,
                    "용량을 넘거나 대상이 없는 시나리오는 확정 대상으로 선택할 수 없습니다.",
                )
            await connection.execute(
                text("""
                UPDATE inspection_simulation
                SET selected_scenario_id = :scenario_id, status = 'CALCULATED',
                    version = version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE inspection_simulation_id = :simulation_id
            """),
                {"scenario_id": scenario_id, "simulation_id": simulation_id},
            )
            await connection.execute(
                text("""
                INSERT INTO audit_event (
                    audit_event_id, profile, actor_type, actor_user_id, action,
                    target_type, target_id, target_version, correlation_id,
                    idempotency_key, metadata
                ) VALUES (
                    :audit_id, :profile, 'USER', :user_id, 'INSPECTION_SCENARIO_SELECTED',
                    'inspection_scenario', :target_id, :target_version, :request_id,
                    :key, CAST(:metadata AS jsonb)
                )
            """),
                {
                    "audit_id": uuid4(),
                    "profile": profile,
                    "user_id": user_id,
                    "target_id": str(scenario_id),
                    "target_version": expected_version + 1,
                    "request_id": request_id,
                    "key": audit_key,
                    "metadata": json.dumps(
                        {"simulationId": str(simulation_id)}, ensure_ascii=False
                    ),
                },
            )
    return await simulation_detail(engine, simulation_id, 2.0)


async def target_list(
    engine: AsyncEngine,
    simulation_id: UUID,
    *,
    scenario_id: UUID | None,
    include: str,
    team_number: int | None,
    query: str | None,
    page: int,
    page_size: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    include_value = include.upper()
    if include_value not in ("ALL", "INCLUDED", "EXCLUDED"):
        raise InspectionContractError(
            422, "INVALID_INSPECTION_TARGET_FILTER", "포함 상태 필터가 올바르지 않습니다."
        )
    async with asyncio.timeout(timeout_seconds):
        async with engine.connect() as connection:
            simulation, scenarios = await _load(connection, simulation_id)
            selected_id = scenario_id or simulation["selected_scenario_id"]
            scenario = next(
                (item for item in scenarios if item["inspection_scenario_id"] == selected_id), None
            )
            if scenario is None:
                raise InspectionContractError(
                    409, "INSPECTION_SCENARIO_NOT_SELECTED", "조회할 시나리오를 먼저 선택해 주세요."
                )
            where = ["target.inspection_scenario_id = :scenario_id"]
            params: dict[str, Any] = {
                "scenario_id": selected_id,
                "limit": page_size,
                "offset": (page - 1) * page_size,
            }
            if include_value != "ALL":
                where.append("target.included = :included")
                params["included"] = include_value == "INCLUDED"
            if team_number is not None:
                where.append("target.team_number = :team_number")
                params["team_number"] = team_number
            if query and query.strip():
                where.append(
                    "(building.building_name ILIKE :query OR building.road_address ILIKE :query OR building.lot_address ILIKE :query OR target.region_name ILIKE :query OR target.facility_type ILIKE :query)"
                )
                params["query"] = f"%{query.strip()}%"
            clause = " AND ".join(where)
            total = (
                await connection.execute(
                    text(f"""
                SELECT count(*) FROM inspection_target target
                JOIN building ON building.building_id = target.building_id WHERE {clause}
            """),
                    params,
                )
            ).scalar_one()
            rows = (
                (
                    await connection.execute(
                        text(f"""
                SELECT target.*,
                       coalesce(building.building_name, building.road_address, building.lot_address) AS building_label,
                       coalesce(building.road_address, building.lot_address) AS address
                FROM inspection_target target JOIN building ON building.building_id = target.building_id
                WHERE {clause}
                ORDER BY target.included DESC, target.selection_order NULLS LAST,
                         target.final_score DESC, target.building_id
                LIMIT :limit OFFSET :offset
            """),
                        params,
                    )
                )
                .mappings()
                .all()
            )
    return {
        "inspectionSimulationId": str(simulation_id),
        "inspectionScenarioId": str(selected_id),
        "scenarioType": scenario["scenario_type"],
        "items": [
            {
                "inspectionTargetId": str(row["inspection_target_id"]),
                "buildingId": str(row["building_id"]),
                "buildingLabel": row["building_label"],
                "address": row["address"],
                "regionCode": row["region_code"],
                "regionName": row["region_name"],
                "facilityType": row["facility_type"],
                "finalScore": float(row["final_score"]),
                "regionalRank": int(row["regional_rank"]),
                "topPercentile": float(row["top_percentile"]),
                "included": bool(row["included"]),
                "selectionOrder": row["selection_order"],
                "teamNumber": row["team_number"],
                "selectionReason": row["selection_reason"],
                "exclusionReason": row["exclusion_reason"],
            }
            for row in rows
        ],
        "pagination": {
            "page": page,
            "pageSize": page_size,
            "total": int(total),
            "totalPages": math.ceil(int(total) / page_size) if total else 0,
        },
    }
