# ruff: noqa: E501
import hashlib
import json
import math
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.config import Settings
from app.inspections import (
    _FACILITY_CATEGORY_SQL,
    SCENARIO_TYPES,
)


async def _create_candidates(connection: AsyncConnection, simulation_id: UUID) -> None:
    await connection.execute(
        text(
            f"""
            CREATE TEMP TABLE inspection_candidate ON COMMIT DROP AS
            WITH simulation AS (
                SELECT * FROM inspection_simulation
                WHERE inspection_simulation_id = :simulation_id
            ), categorized AS (
                SELECT b.building_id, r.risk_snapshot_id, b.region_code,
                       region.full_name AS region_name,
                       coalesce(b.building_name, b.road_address, b.lot_address) AS building_label,
                       coalesce(b.road_address, b.lot_address) AS address,
                       r.final_score, r.regional_rank, r.top_percentile,
                       {_FACILITY_CATEGORY_SQL} AS facility_type,
                       simulation.top_percentile AS base_percentile,
                       simulation.minimum_score AS base_score,
                       simulation.expanded_top_percentile AS expanded_percentile,
                       simulation.expanded_minimum_score AS expanded_score,
                       simulation.building_id AS forced_building_id,
                       simulation.facility_types
                FROM simulation
                JOIN building_risk_snapshot r
                  ON r.reference_month = simulation.reference_month
                 AND r.horizon_days = simulation.horizon_days
                 AND r.lineage_version = simulation.lineage_version
                JOIN building b ON b.building_id = r.building_id
                JOIN admin_region region ON region.region_code = b.region_code
                LEFT JOIN admin_region parent ON parent.region_code = region.parent_code
                CROSS JOIN LATERAL (
                    SELECT coalesce(b.customer_data ->> 'main_use_name', '') AS main_use
                ) use_value
                WHERE simulation.region_code IS NULL
                   OR b.region_code = simulation.region_code
                   OR region.parent_code = simulation.region_code
            )
            SELECT building_id, risk_snapshot_id, region_code, region_name,
                   building_label, address, facility_type, final_score,
                   regional_rank, top_percentile,
                   (
                       (top_percentile <= base_percentile AND final_score >= base_score)
                       OR building_id = forced_building_id
                   ) AS base_eligible,
                   (building_id = forced_building_id) AS forced_inclusion
            FROM categorized
            WHERE (
                    (top_percentile <= expanded_percentile AND final_score >= expanded_score)
                    OR building_id = forced_building_id
                  )
              AND (
                    cardinality(facility_types) = 0
                    OR facility_type = ANY(facility_types)
                    OR building_id = forced_building_id
                  )
            """
        ),
        {"simulation_id": simulation_id},
    )
    await connection.execute(
        text(
            """
            CREATE INDEX inspection_candidate_base_order
            ON inspection_candidate (base_eligible, final_score DESC, building_id)
            """
        )
    )


def _ranked_sql(scenario_type: str) -> str:
    if scenario_type == "BALANCED":
        return """
            WITH grouped AS (
                SELECT candidate.*,
                       row_number() OVER (
                           PARTITION BY region_code, facility_type
                           ORDER BY final_score DESC, building_id
                       ) AS group_position
                FROM inspection_candidate candidate
                WHERE base_eligible
            ), ranked AS (
                SELECT grouped.*,
                       row_number() OVER (
                           ORDER BY group_position, final_score DESC,
                                    region_code, facility_type, building_id
                       ) AS target_order
                FROM grouped
            )
        """
    eligibility = "" if scenario_type == "COVERAGE_EXPANDED" else "WHERE base_eligible"
    return f"""
        WITH ranked AS (
            SELECT candidate.*,
                   row_number() OVER (
                       ORDER BY final_score DESC, regional_rank, building_id
                   ) AS target_order
            FROM inspection_candidate candidate
            {eligibility}
        )
    """


async def _insert_scenario_targets(
    connection: AsyncConnection,
    simulation: dict[str, Any],
    scenario_id: UUID,
    scenario_type: str,
) -> None:
    expanded = scenario_type == "COVERAGE_EXPANDED"
    await connection.execute(
        text(
            """
            INSERT INTO inspection_scenario (
                inspection_scenario_id, inspection_simulation_id,
                scenario_type, ordinal, status, candidate_count,
                selected_count, excluded_count, candidate_coverage_percent,
                required_days, over_capacity, confirmable, explanation,
                content_sha256
            ) VALUES (
                :scenario_id, :simulation_id, :scenario_type, :ordinal,
                'CALCULATED', 0, 0, 0, 0, 0, false, false,
                '{}'::jsonb, :empty_hash
            )
            """
        ),
        {
            "scenario_id": scenario_id,
            "simulation_id": simulation["inspection_simulation_id"],
            "scenario_type": scenario_type,
            "ordinal": SCENARIO_TYPES.index(scenario_type) + 1,
            "empty_hash": "0" * 64,
        },
    )
    ranked_sql = _ranked_sql(scenario_type)
    included_expression = "true" if expanded else "target_order <= :capacity"
    await connection.execute(
        text(
            f"""
            {ranked_sql}
            INSERT INTO inspection_target (
                inspection_target_id, inspection_scenario_id,
                building_id, risk_snapshot_id, included, selection_order,
                team_number, selection_reason, exclusion_reason,
                region_code, region_name, facility_type, final_score,
                regional_rank, top_percentile
            )
            SELECT md5(CAST(:scenario_id AS text) || ':' || CAST(building_id AS text))::uuid,
                   CAST(:scenario_id AS uuid), building_id, risk_snapshot_id,
                   {included_expression},
                   CASE WHEN {included_expression} THEN target_order END,
                   CASE WHEN {included_expression}
                        THEN ((target_order - 1) % :team_count) + 1 END,
                   CASE WHEN {included_expression} THEN
                       CASE
                           WHEN forced_inclusion THEN 'USER_SELECTED_BUILDING'
                           WHEN CAST(:scenario_type AS varchar) = 'BALANCED' THEN 'BALANCED_GROUP_ORDER'
                           WHEN CAST(:scenario_type AS varchar) = 'HIGH_RISK_FOCUSED' THEN 'FINAL_SCORE_ORDER'
                           ELSE 'RELAXED_THRESHOLD'
                       END
                   END,
                   CASE WHEN NOT ({included_expression}) THEN 'CAPACITY_LIMIT' END,
                   region_code, region_name, facility_type, final_score,
                   regional_rank, top_percentile
            FROM ranked
            """
        ),
        {
            "scenario_id": str(scenario_id),
            "capacity": int(simulation["total_capacity"]),
            "team_count": int(simulation["team_count"]),
            "scenario_type": scenario_type,
        },
    )
    summary = (
        (
            await connection.execute(
                text(
                    """
                    SELECT count(*) AS candidate_count,
                           count(*) FILTER (WHERE included) AS selected_count,
                           count(*) FILTER (WHERE NOT included) AS excluded_count
                    FROM inspection_target
                    WHERE inspection_scenario_id = :scenario_id
                    """
                ),
                {"scenario_id": scenario_id},
            )
        )
        .mappings()
        .one()
    )
    candidate_count = int(summary["candidate_count"])
    selected_count = int(summary["selected_count"])
    excluded_count = int(summary["excluded_count"])
    daily_total = int(simulation["team_count"]) * int(simulation["daily_capacity_per_team"])
    required_days = math.ceil(selected_count / daily_total) if selected_count else 0
    over_capacity = selected_count > int(simulation["total_capacity"])
    confirmable = selected_count > 0 and not over_capacity
    coverage = round((selected_count / candidate_count * 100), 2) if candidate_count else 0.0
    explanation = {
        "coverageFormula": "선정 대상 수 ÷ 해당 시나리오 후보 수 × 100",
        "capacityFormula": "포함 기간 일수 × 점검반 수 × 점검반당 1일 처리량",
        "candidateCoveragePercent": coverage,
        "strategy": {
            "BALANCED": "지역·시설유형 묶음별 고위험 순서를 유지하며 한 건씩 순환 선택",
            "HIGH_RISK_FOCUSED": "지역 균형보다 final_score 내림차순을 우선 선택",
            "COVERAGE_EXPANDED": "상위 백분위와 최소 점수 기준을 한 단계 완화해 추가 후보를 모두 표시",
        }[scenario_type],
        "baseFilters": {
            "topPercentile": float(simulation["top_percentile"]),
            "minimumScore": float(simulation["minimum_score"]),
        },
        "appliedFilters": {
            "topPercentile": float(
                simulation["expanded_top_percentile"] if expanded else simulation["top_percentile"]
            ),
            "minimumScore": float(
                simulation["expanded_minimum_score"] if expanded else simulation["minimum_score"]
            ),
        },
        "capacityExceededBy": max(0, selected_count - int(simulation["total_capacity"])),
    }
    digest = hashlib.sha256()
    digest.update(str(simulation["input_sha256"]).encode())
    digest.update(scenario_type.encode())
    target_rows = (
        (
            await connection.execute(
                text(
                    """
                    SELECT building_id, selection_order, team_number
                    FROM inspection_target
                    WHERE inspection_scenario_id = :scenario_id AND included
                    ORDER BY selection_order
                    """
                ),
                {"scenario_id": scenario_id},
            )
        )
        .mappings()
        .all()
    )
    for target in target_rows:
        digest.update(
            f"{target['building_id']}:{target['selection_order']}:{target['team_number']}\n".encode()
        )
    await connection.execute(
        text(
            """
            UPDATE inspection_scenario
            SET candidate_count = :candidate_count,
                selected_count = :selected_count,
                excluded_count = :excluded_count,
                candidate_coverage_percent = :coverage,
                required_days = :required_days,
                over_capacity = :over_capacity,
                confirmable = :confirmable,
                explanation = CAST(:explanation AS jsonb),
                content_sha256 = :content_sha256,
                updated_at = CURRENT_TIMESTAMP
            WHERE inspection_scenario_id = :scenario_id
            """
        ),
        {
            "scenario_id": scenario_id,
            "candidate_count": candidate_count,
            "selected_count": selected_count,
            "excluded_count": excluded_count,
            "coverage": coverage,
            "required_days": required_days,
            "over_capacity": over_capacity,
            "confirmable": confirmable,
            "explanation": json.dumps(explanation, ensure_ascii=False),
            "content_sha256": digest.hexdigest(),
        },
    )


async def _calculate(connection: AsyncConnection, simulation_id: UUID) -> dict[str, Any]:
    simulation = (
        (
            await connection.execute(
                text(
                    """
                    SELECT * FROM inspection_simulation
                    WHERE inspection_simulation_id = :simulation_id
                    FOR UPDATE
                    """
                ),
                {"simulation_id": simulation_id},
            )
        )
        .mappings()
        .one()
    )
    await _create_candidates(connection, simulation_id)
    scenario_ids: dict[str, UUID] = {}
    for scenario_type in SCENARIO_TYPES:
        scenario_id = uuid4()
        scenario_ids[scenario_type] = scenario_id
        await _insert_scenario_targets(connection, dict(simulation), scenario_id, scenario_type)
    selected_id = (
        await connection.execute(
            text(
                """
                SELECT inspection_scenario_id
                FROM inspection_scenario
                WHERE inspection_simulation_id = :simulation_id AND confirmable
                ORDER BY ordinal LIMIT 1
                """
            ),
            {"simulation_id": simulation_id},
        )
    ).scalar_one_or_none()
    await connection.execute(
        text(
            """
            UPDATE inspection_simulation
            SET status = 'CALCULATED', selected_scenario_id = :selected_id,
                completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP,
                version = version + 1
            WHERE inspection_simulation_id = :simulation_id
            """
        ),
        {"simulation_id": simulation_id, "selected_id": selected_id},
    )
    return {
        "inspectionSimulationId": str(simulation_id),
        "status": "CALCULATED",
        "selectedScenarioId": str(selected_id) if selected_id else None,
        "scenarioIds": {key: str(value) for key, value in scenario_ids.items()},
    }


async def run_inspection_simulation(
    settings: Settings,
    simulation_id: UUID,
) -> dict[str, Any]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            state = (
                await connection.execute(
                    text(
                        """
                        SELECT status FROM inspection_simulation
                        WHERE inspection_simulation_id = :simulation_id
                        FOR UPDATE
                        """
                    ),
                    {"simulation_id": simulation_id},
                )
            ).scalar_one_or_none()
            if state is None:
                raise ValueError("inspection simulation not found")
            if state in (
                "CALCULATED",
                "APPROVAL_PENDING",
                "APPROVED",
                "ON_HOLD",
                "DISCARDED",
            ):
                return {
                    "inspectionSimulationId": str(simulation_id),
                    "status": state,
                    "reused": True,
                }
            await connection.execute(
                text(
                    """
                    UPDATE inspection_simulation
                    SET status = 'RUNNING',
                        started_at = coalesce(started_at, CURRENT_TIMESTAMP),
                        error_code = NULL, error_message = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE inspection_simulation_id = :simulation_id
                    """
                ),
                {"simulation_id": simulation_id},
            )
        try:
            async with engine.begin() as connection:
                result = await _calculate(connection, simulation_id)
        except Exception as error:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        UPDATE inspection_simulation
                        SET status = 'FAILED', error_code = :error_code,
                            error_message = :error_message,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE inspection_simulation_id = :simulation_id
                        """
                    ),
                    {
                        "simulation_id": simulation_id,
                        "error_code": type(error).__name__[:80],
                        "error_message": str(error)[:1000] or "점검 시뮬레이션 계산 실패",
                    },
                )
            raise
        return result
    finally:
        await engine.dispose()
