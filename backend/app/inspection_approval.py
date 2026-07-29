# ruff: noqa: E501
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.inspections import InspectionContractError


async def inspection_approval_target(
    connection: AsyncConnection,
    scenario_id: UUID,
    target_version: int,
    *,
    lock: bool = False,
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE OF scenario, simulation" if lock else ""
    row = (
        (
            await connection.execute(
                text(f"""
        SELECT scenario.*, simulation.status AS simulation_status,
               simulation.inspection_simulation_id, simulation.region_code,
               simulation.case_id, simulation.start_date, simulation.end_date,
               simulation.team_count, simulation.daily_capacity_per_team,
               simulation.inclusive_day_count, simulation.total_capacity,
               simulation.top_percentile, simulation.minimum_score,
               simulation.reference_month, simulation.horizon_days,
               simulation.lineage_version, simulation.algorithm_version,
               region.full_name AS region_name,
               case_record.case_number, case_record.title AS case_title,
               case_record.case_type, case_record.status AS case_status,
               case_record.monitoring_priority, case_record.primary_region_code
        FROM inspection_scenario scenario
        JOIN inspection_simulation simulation
          ON simulation.inspection_simulation_id = scenario.inspection_simulation_id
        LEFT JOIN admin_region region ON region.region_code = simulation.region_code
        LEFT JOIN case_record ON case_record.case_id = simulation.case_id
        WHERE scenario.inspection_scenario_id = :scenario_id
        {suffix}
    """),
                {"scenario_id": scenario_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    teams = (
        (
            await connection.execute(
                text("""
        SELECT team_number, count(*) AS target_count,
               min(selection_order) AS first_order, max(selection_order) AS last_order
        FROM inspection_target
        WHERE inspection_scenario_id = :scenario_id AND included
        GROUP BY team_number ORDER BY team_number
    """),
                {"scenario_id": scenario_id},
            )
        )
        .mappings()
        .all()
    )
    sample = (
        (
            await connection.execute(
                text("""
        SELECT target.building_id, target.selection_order, target.team_number,
               target.final_score, target.region_name, target.facility_type,
               coalesce(building.building_name, building.road_address, building.lot_address) AS building_label
        FROM inspection_target target
        JOIN building ON building.building_id = target.building_id
        WHERE target.inspection_scenario_id = :scenario_id AND target.included
        ORDER BY target.selection_order LIMIT 10
    """),
                {"scenario_id": scenario_id},
            )
        )
        .mappings()
        .all()
    )
    case = None
    if row["case_id"] is not None:
        case = {
            "caseId": str(row["case_id"]),
            "caseNumber": row["case_number"],
            "title": row["case_title"],
            "caseType": row["case_type"],
            "status": row["case_status"],
            "monitoringPriority": row["monitoring_priority"],
            "regionCode": row["primary_region_code"],
            "regionName": row["region_name"],
        }
    return {
        "case": case,
        "inspection": {
            "inspectionSimulationId": str(row["inspection_simulation_id"]),
            "inspectionScenarioId": str(row["inspection_scenario_id"]),
            "scenarioType": row["scenario_type"],
            "status": row["status"],
            "version": int(row["version"]),
            "regionCode": row["region_code"],
            "regionName": row["region_name"],
            "startDate": row["start_date"].isoformat(),
            "endDate": row["end_date"].isoformat(),
            "inclusiveDayCount": int(row["inclusive_day_count"]),
            "teamCount": int(row["team_count"]),
            "dailyCapacityPerTeam": int(row["daily_capacity_per_team"]),
            "totalCapacity": int(row["total_capacity"]),
            "topPercentile": float(row["top_percentile"]),
            "minimumScore": float(row["minimum_score"]),
            "candidateCount": int(row["candidate_count"]),
            "selectedCount": int(row["selected_count"]),
            "excludedCount": int(row["excluded_count"]),
            "candidateCoveragePercent": float(row["candidate_coverage_percent"]),
            "requiredDays": int(row["required_days"]),
            "overCapacity": bool(row["over_capacity"]),
            "confirmable": bool(row["confirmable"]),
            "explanation": dict(row["explanation"]),
            "referenceMonth": row["reference_month"].isoformat(),
            "horizonDays": int(row["horizon_days"]),
            "lineageVersion": row["lineage_version"],
            "algorithmVersion": row["algorithm_version"],
            "teams": [
                {
                    "teamNumber": int(team["team_number"]),
                    "targetCount": int(team["target_count"]),
                    "firstOrder": int(team["first_order"]),
                    "lastOrder": int(team["last_order"]),
                }
                for team in teams
            ],
            "sampleTargets": [
                {
                    "buildingId": str(item["building_id"]),
                    "buildingLabel": item["building_label"],
                    "selectionOrder": int(item["selection_order"]),
                    "teamNumber": int(item["team_number"]),
                    "finalScore": float(item["final_score"]),
                    "regionName": item["region_name"],
                    "facilityType": item["facility_type"],
                }
                for item in sample
            ],
        },
        "contentSha256": row["content_sha256"],
    }


async def request_inspection_approval(
    engine: AsyncEngine,
    *,
    profile: str,
    simulation_id: UUID,
    user_id: UUID,
    request_id: UUID,
    idempotency_key: str,
) -> dict[str, Any]:
    audit_key = f"inspection-approval-request:{profile}:{idempotency_key}"
    approval_request_id: UUID
    reused = False
    async with engine.begin() as connection:
        duplicate = (
            await connection.execute(
                text("SELECT target_id FROM audit_event WHERE idempotency_key = :key"),
                {"key": audit_key},
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            approval_request_id = UUID(str(duplicate))
            reused = True
        else:
            simulation = (
                (
                    await connection.execute(
                        text("""
                SELECT * FROM inspection_simulation
                WHERE inspection_simulation_id = :simulation_id FOR UPDATE
            """),
                        {"simulation_id": simulation_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if simulation is None:
                raise InspectionContractError(
                    404, "INSPECTION_SIMULATION_NOT_FOUND", "점검 시뮬레이션을 찾을 수 없습니다."
                )
            if simulation["selected_scenario_id"] is None:
                raise InspectionContractError(
                    409, "INSPECTION_SCENARIO_NOT_SELECTED", "확정할 시나리오를 선택해 주세요."
                )
            target = await inspection_approval_target(
                connection, simulation["selected_scenario_id"], 1, lock=True
            )
            if target is None:
                raise InspectionContractError(
                    404, "INSPECTION_SCENARIO_NOT_FOUND", "확정할 시나리오를 찾을 수 없습니다."
                )
            inspection = target["inspection"]
            if simulation["status"] not in ("CALCULATED", "ON_HOLD"):
                raise InspectionContractError(
                    409, "INSPECTION_APPROVAL_LOCKED", "현재 상태에서는 확정을 요청할 수 없습니다."
                )
            if not inspection["confirmable"]:
                raise InspectionContractError(
                    409,
                    "INSPECTION_CAPACITY_EXCEEDED",
                    "대상이 없거나 용량을 넘는 시나리오는 조건 수정 전 확정할 수 없습니다.",
                )
            existing = (
                (
                    await connection.execute(
                        text("""
                SELECT approval_request_id, status FROM approval_request
                WHERE target_type = 'INSPECTION_SCENARIO'
                  AND target_id = :target_id AND target_version = :target_version
                ORDER BY requested_at DESC FOR UPDATE
            """),
                        {
                            "target_id": UUID(inspection["inspectionScenarioId"]),
                            "target_version": inspection["version"],
                        },
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None and existing["status"] in ("APPROVAL_PENDING", "APPROVED"):
                approval_request_id = existing["approval_request_id"]
                reused = True
            else:
                approval_request_id = uuid4()
                title = f"점검계획 확정 · {inspection['scenarioType']} · {inspection['selectedCount']:,}개소"
                await connection.execute(
                    text("""
                    INSERT INTO approval_request (
                        approval_request_id, case_id, target_type, target_id,
                        target_version, title, status, content_sha256,
                        evidence_status, warning, requested_by
                    ) VALUES (
                        :approval_id, :case_id, 'INSPECTION_SCENARIO', :target_id,
                        :target_version, :title, 'APPROVAL_PENDING', :content_sha256,
                        NULL, NULL, :requested_by
                    )
                """),
                    {
                        "approval_id": approval_request_id,
                        "case_id": simulation["case_id"],
                        "target_id": UUID(inspection["inspectionScenarioId"]),
                        "target_version": inspection["version"],
                        "title": title,
                        "content_sha256": target["contentSha256"],
                        "requested_by": user_id,
                    },
                )
                await connection.execute(
                    text("""
                    UPDATE inspection_scenario
                    SET status = 'APPROVAL_PENDING', updated_at = CURRENT_TIMESTAMP
                    WHERE inspection_scenario_id = :scenario_id
                """),
                    {"scenario_id": UUID(inspection["inspectionScenarioId"])},
                )
                await connection.execute(
                    text("""
                    UPDATE inspection_simulation
                    SET status = 'APPROVAL_PENDING', updated_at = CURRENT_TIMESTAMP
                    WHERE inspection_simulation_id = :simulation_id
                """),
                    {"simulation_id": simulation_id},
                )
                await connection.execute(
                    text("""
                    INSERT INTO audit_event (
                        audit_event_id, profile, actor_type, actor_user_id, action,
                        target_type, target_id, target_version, correlation_id,
                        idempotency_key, input_sha256, metadata
                    ) VALUES (
                        :audit_id, :profile, 'USER', :user_id,
                        'INSPECTION_APPROVAL_REQUESTED', 'approval_request',
                        :target_id, 1, :request_id, :key, :input_sha256,
                        CAST(:metadata AS jsonb)
                    )
                """),
                    {
                        "audit_id": uuid4(),
                        "profile": profile,
                        "user_id": user_id,
                        "target_id": str(approval_request_id),
                        "request_id": request_id,
                        "key": audit_key,
                        "input_sha256": target["contentSha256"],
                        "metadata": json.dumps(
                            {
                                "simulationId": str(simulation_id),
                                "scenarioId": inspection["inspectionScenarioId"],
                            },
                            ensure_ascii=False,
                        ),
                    },
                )
    from app.approvals import approval_detail

    result = await approval_detail(engine, approval_request_id, 2.0)
    if result is None:
        raise RuntimeError("created inspection approval request not found")
    return {**result, "reused": reused}


async def apply_inspection_decision(
    connection: AsyncConnection,
    *,
    scenario_id: UUID,
    decision: str,
    approval_request_id: UUID,
) -> list[str]:
    target = await inspection_approval_target(connection, scenario_id, 1, lock=True)
    if target is None:
        raise InspectionContractError(
            409, "APPROVAL_TARGET_MISSING", "점검 시나리오를 찾을 수 없습니다."
        )
    inspection = target["inspection"]
    created: list[str] = []
    if decision == "APPROVED":
        team_rows = (
            (
                await connection.execute(
                    text("""
            SELECT team_number, count(*) AS target_count
            FROM inspection_target
            WHERE inspection_scenario_id = :scenario_id AND included
            GROUP BY team_number ORDER BY team_number
        """),
                    {"scenario_id": scenario_id},
                )
            )
            .mappings()
            .all()
        )
        for team in team_rows:
            work_item_id = uuid4()
            await connection.execute(
                text("""
                INSERT INTO work_item (
                    work_item_id, work_type, case_id, status, priority, title,
                    input_version, progress, idempotency_key
                ) VALUES (
                    :work_item_id, 'INSPECTION_PLAN', :case_id, 'QUEUED', 'NORMAL',
                    :title, :input_version, 0, :idempotency_key
                ) ON CONFLICT (idempotency_key) DO NOTHING
            """),
                {
                    "work_item_id": work_item_id,
                    "case_id": target["case"]["caseId"] if target["case"] else None,
                    "title": f"점검반 {team['team_number']} · {team['target_count']:,}개소 점검",
                    "input_version": f"inspection:{scenario_id}:v{inspection['version']}",
                    "idempotency_key": f"inspection-approval:{approval_request_id}:team:{team['team_number']}",
                },
            )
            stored_id = (
                await connection.execute(
                    text("""
                SELECT work_item_id FROM work_item WHERE idempotency_key = :key
            """),
                    {
                        "key": f"inspection-approval:{approval_request_id}:team:{team['team_number']}"
                    },
                )
            ).scalar_one()
            await connection.execute(
                text("""
                INSERT INTO inspection_team_work_item (
                    inspection_scenario_id, team_number, work_item_id
                ) VALUES (:scenario_id, :team_number, :work_item_id)
                ON CONFLICT (inspection_scenario_id, team_number) DO NOTHING
            """),
                {
                    "scenario_id": scenario_id,
                    "team_number": team["team_number"],
                    "work_item_id": stored_id,
                },
            )
            created.append(str(stored_id))
    await connection.execute(
        text("""
        UPDATE inspection_scenario
        SET status = CAST(:decision AS varchar), version = version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE inspection_scenario_id = :scenario_id
    """),
        {"decision": decision, "scenario_id": scenario_id},
    )
    await connection.execute(
        text("""
        UPDATE inspection_simulation
        SET status = CAST(:decision AS varchar), version = version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE inspection_simulation_id = :simulation_id
    """),
        {"decision": decision, "simulation_id": UUID(inspection["inspectionSimulationId"])},
    )
    return created
