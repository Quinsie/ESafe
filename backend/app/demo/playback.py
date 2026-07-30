# ruff: noqa: E501
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.config import Settings
from app.demo.scenarios import ScenarioStep, scenario_steps, step_contract
from app.signals.ingestion import run_demo_fixture_step, run_demo_source_state_step
from app.workflow import WorkflowContractError


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def require_demo_profile(profile: str) -> None:
    if profile != "DEMO":
        raise WorkflowContractError(
            403,
            "DEMO_PROFILE_REQUIRED",
            "시나리오 제어는 체험 데이터 환경에서만 사용할 수 있습니다.",
        )


def _contract(row: dict[str, Any], count: int) -> dict[str, object]:
    return {
        "playbackId": str(row["demo_playback_id"]),
        "status": row["status"],
        "currentStep": int(row["current_step"]),
        "stepCount": count,
        "generation": int(row["generation"]),
        "version": int(row["version"]),
        "startedAt": _iso(row.get("started_at")),
        "pausedAt": _iso(row.get("paused_at")),
        "completedAt": _iso(row.get("completed_at")),
        "updatedAt": _iso(row.get("updated_at")),
    }


async def _replay(connection: AsyncConnection, key: str) -> dict[str, Any] | None:
    value = (
        await connection.execute(
            text("SELECT result FROM demo_playback_event WHERE idempotency_key=:key"), {"key": key}
        )
    ).scalar_one_or_none()
    return dict(value) if value is not None else None


async def _scenario(
    connection: AsyncConnection, scenario_id: UUID, lock: bool = False
) -> dict[str, Any]:
    suffix = " FOR UPDATE" if lock else ""
    row = (
        (
            await connection.execute(
                text(
                    "SELECT demo_scenario_id, code, name, scenario_version FROM demo_scenario WHERE demo_scenario_id=:id AND enabled"
                    + suffix
                ),
                {"id": scenario_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise WorkflowContractError(
            404, "DEMO_SCENARIO_NOT_FOUND", "체험 시나리오를 찾을 수 없습니다."
        )
    return dict(row)


async def _active(connection: AsyncConnection, lock: bool = False) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if lock else ""
    row = (
        (
            await connection.execute(
                text(
                    "SELECT * FROM demo_playback WHERE status IN ('READY','RUNNING','PAUSED')"
                    + suffix
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


async def _latest(
    connection: AsyncConnection, scenario_id: UUID, lock: bool = False
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if lock else ""
    row = (
        (
            await connection.execute(
                text(
                    "SELECT * FROM demo_playback WHERE demo_scenario_id=:id ORDER BY generation DESC, updated_at DESC LIMIT 1"
                    + suffix
                ),
                {"id": scenario_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def _version(row: dict[str, Any], expected: int | None) -> None:
    actual = int(row["version"])
    if expected != actual:
        raise WorkflowContractError(
            409,
            "DEMO_PLAYBACK_VERSION_CONFLICT",
            "시나리오 상태가 변경되었습니다. 최신 상태를 다시 확인해 주세요.",
            {"expectedVersion": expected, "actualVersion": actual},
        )


async def _event(
    connection: AsyncConnection,
    playback_id: UUID,
    command: str,
    key: str,
    result: dict[str, Any],
    step: ScenarioStep | None = None,
) -> None:
    await connection.execute(
        text("""
        INSERT INTO demo_playback_event (demo_playback_event_id, demo_playback_id, command, step_ordinal, source_time, result, idempotency_key)
        VALUES (:id,:playback_id,:command,:step,:source_time,CAST(:result AS jsonb),:key)
    """),
        {
            "id": uuid4(),
            "playback_id": playback_id,
            "command": command,
            "step": step.ordinal if step else None,
            "source_time": step.source_time if step else None,
            "result": _json(result),
            "key": key,
        },
    )


async def _audit(
    connection: AsyncConnection,
    user_id: UUID,
    playback_id: UUID,
    action: str,
    key: str,
    data: dict[str, Any],
) -> None:
    await connection.execute(
        text("""
        INSERT INTO audit_event (audit_event_id,profile,actor_type,actor_user_id,action,target_type,target_id,reason,correlation_id,idempotency_key,metadata)
        VALUES (:id,'DEMO','USER',:user_id,:action,'demo_playback',:target_id,CAST(:reason AS jsonb),:playback_id,:key,CAST(:metadata AS jsonb))
    """),
        {
            "id": uuid4(),
            "user_id": user_id,
            "action": action,
            "target_id": str(playback_id),
            "reason": _json({"action": action}),
            "playback_id": playback_id,
            "key": f"audit:demo:{key}",
            "metadata": _json(data),
        },
    )


async def scenario_catalog(
    engine: AsyncEngine, *, profile: str, timeout_seconds: float
) -> dict[str, Any]:
    require_demo_profile(profile)

    async def query() -> dict[str, Any]:
        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        text("""
                SELECT s.*, p.demo_playback_id,p.status,p.current_step,p.generation,p.version,
                       p.started_at,p.paused_at,p.completed_at,p.updated_at
                FROM demo_scenario s LEFT JOIN LATERAL (
                    SELECT * FROM demo_playback x WHERE x.demo_scenario_id=s.demo_scenario_id
                    ORDER BY CASE WHEN x.status IN ('READY','RUNNING','PAUSED') THEN 0 ELSE 1 END,
                             x.generation DESC,x.updated_at DESC LIMIT 1
                ) p ON true WHERE s.enabled ORDER BY s.ordinal
            """)
                    )
                )
                .mappings()
                .all()
            )
        items = []
        for raw in rows:
            row = dict(raw)
            steps = scenario_steps(str(row["code"]))
            items.append(
                {
                    "scenarioId": str(row["demo_scenario_id"]),
                    "code": row["code"],
                    "name": row["name"],
                    "description": row["description"],
                    "scenarioVersion": int(row["scenario_version"]),
                    "stepCount": len(steps),
                    "steps": [step_contract(step) for step in steps],
                    "playback": _contract(row, len(steps)) if row["demo_playback_id"] else None,
                }
            )
        return {"items": items}

    try:
        return await asyncio.wait_for(query(), timeout=timeout_seconds)
    except TimeoutError as error:
        raise WorkflowContractError(
            503,
            "DEMO_SCENARIOS_TIMEOUT",
            "체험 시나리오 목록을 제한 시간 안에 불러오지 못했습니다.",
        ) from error


async def start_scenario(
    engine: AsyncEngine,
    *,
    profile: str,
    scenario_id: UUID,
    expected_version: int | None,
    actor_user_id: UUID,
    idempotency_key: str,
) -> dict[str, Any]:
    require_demo_profile(profile)
    async with engine.begin() as connection:
        cached = await _replay(connection, idempotency_key)
        if cached is not None:
            return cached
        scenario = await _scenario(connection, scenario_id, True)
        steps = scenario_steps(str(scenario["code"]))
        active = await _active(connection, True)
        now = datetime.now(UTC)
        if active and UUID(str(active["demo_scenario_id"])) != scenario_id:
            if active["status"] == "READY" and int(active["current_step"]) == 0:
                await connection.execute(
                    text(
                        """
                        UPDATE demo_playback
                        SET status = 'COMPLETED', started_at = :now,
                            completed_at = :now, updated_at = :now
                        WHERE demo_playback_id = :playback_id
                        """
                    ),
                    {"now": now, "playback_id": active["demo_playback_id"]},
                )
                active = None
            else:
                raise WorkflowContractError(
                    409,
                    "DEMO_PLAYBACK_ACTIVE",
                    "다른 체험 시나리오가 실행 중입니다. 먼저 초기화해 주세요.",
                )
        if active:
            _version(active, expected_version)
            if active["status"] == "RUNNING":
                raise WorkflowContractError(
                    409, "DEMO_PLAYBACK_ALREADY_RUNNING", "시나리오가 이미 실행 중입니다."
                )
            row = dict(
                (
                    await connection.execute(
                        text(
                            "UPDATE demo_playback SET status='RUNNING',started_at=coalesce(started_at,:now),paused_at=NULL,completed_at=NULL,version=version+1,updated_at=:now WHERE demo_playback_id=:id RETURNING *"
                        ),
                        {"now": now, "id": active["demo_playback_id"]},
                    )
                )
                .mappings()
                .one()
            )
        else:
            has_simulated = bool(
                (
                    await connection.execute(
                        text("SELECT exists(SELECT 1 FROM signal_event WHERE is_simulated)")
                    )
                ).scalar_one()
            )
            if has_simulated:
                raise WorkflowContractError(
                    409,
                    "DEMO_RESET_REQUIRED",
                    "이전 체험 데이터가 남아 있습니다. 해당 시나리오를 처음부터 초기화해 주세요.",
                )
            generation = int(
                (
                    await connection.execute(
                        text(
                            "SELECT coalesce(max(generation),0)+1 FROM demo_playback WHERE demo_scenario_id=:id"
                        ),
                        {"id": scenario_id},
                    )
                ).scalar_one()
            )
            playback_id = uuid4()
            row = dict(
                (
                    await connection.execute(
                        text(
                            "INSERT INTO demo_playback (demo_playback_id,demo_scenario_id,status,current_step,generation,version,started_at,updated_at) VALUES (:pid,:sid,'RUNNING',0,:generation,1,:now,:now) RETURNING *"
                        ),
                        {
                            "pid": playback_id,
                            "sid": scenario_id,
                            "generation": generation,
                            "now": now,
                        },
                    )
                )
                .mappings()
                .one()
            )
        data = {
            "scenarioId": str(scenario_id),
            "code": scenario["code"],
            "command": "START",
            "playback": _contract(row, len(steps)),
        }
        pid = UUID(str(row["demo_playback_id"]))
        await _event(connection, pid, "START", idempotency_key, data)
        await _audit(connection, actor_user_id, pid, "DEMO_SCENARIO_STARTED", idempotency_key, data)
        return data


async def pause_scenario(
    engine: AsyncEngine,
    *,
    profile: str,
    scenario_id: UUID,
    expected_version: int,
    actor_user_id: UUID,
    idempotency_key: str,
) -> dict[str, Any]:
    require_demo_profile(profile)
    async with engine.begin() as connection:
        cached = await _replay(connection, idempotency_key)
        if cached is not None:
            return cached
        scenario = await _scenario(connection, scenario_id, True)
        steps = scenario_steps(str(scenario["code"]))
        active = await _active(connection, True)
        if not active or UUID(str(active["demo_scenario_id"])) != scenario_id:
            raise WorkflowContractError(
                409, "DEMO_PLAYBACK_NOT_ACTIVE", "실행 중인 시나리오가 없습니다."
            )
        _version(active, expected_version)
        if active["status"] != "RUNNING":
            raise WorkflowContractError(
                409, "DEMO_PLAYBACK_NOT_RUNNING", "실행 중인 시나리오만 일시정지할 수 있습니다."
            )
        now = datetime.now(UTC)
        row = dict(
            (
                await connection.execute(
                    text(
                        "UPDATE demo_playback SET status='PAUSED',paused_at=:now,version=version+1,updated_at=:now WHERE demo_playback_id=:id RETURNING *"
                    ),
                    {"now": now, "id": active["demo_playback_id"]},
                )
            )
            .mappings()
            .one()
        )
        data = {
            "scenarioId": str(scenario_id),
            "code": scenario["code"],
            "command": "PAUSE",
            "playback": _contract(row, len(steps)),
        }
        pid = UUID(str(row["demo_playback_id"]))
        await _event(connection, pid, "PAUSE", idempotency_key, data)
        await _audit(connection, actor_user_id, pid, "DEMO_SCENARIO_PAUSED", idempotency_key, data)
        return data


async def _execute(
    engine: AsyncEngine, settings: Settings, scenario_id: UUID, generation: int, step: ScenarioStep
) -> dict[str, object]:
    if step.kind == "FIXTURE":
        if not step.fixture_name:
            raise RuntimeError("fixture name missing")
        return await run_demo_fixture_step(
            engine,
            settings,
            source=step.source,
            fixture_name=step.fixture_name,
            scenario_id=scenario_id,
            generation=generation,
            step_ordinal=step.ordinal,
            source_time=step.source_time,
        )
    if not step.source_state:
        raise RuntimeError("source state missing")
    return await run_demo_source_state_step(
        engine,
        settings,
        source=step.source,
        state=step.source_state,
        scenario_id=scenario_id,
        generation=generation,
        step_ordinal=step.ordinal,
        source_time=step.source_time,
    )


async def _pause_failed_step(
    connection: AsyncConnection,
    *,
    playback_id: UUID,
    previous_step: int,
    now: datetime,
) -> dict[str, Any]:
    return dict(
        (
            await connection.execute(
                text(
                    """
                    UPDATE demo_playback
                    SET status = 'PAUSED',
                        current_step = :previous_step,
                        paused_at = :now,
                        version = version + 1,
                        updated_at = :now
                    WHERE demo_playback_id = :id
                    RETURNING *
                    """
                ),
                {
                    "previous_step": previous_step,
                    "now": now,
                    "id": playback_id,
                },
            )
        )
        .mappings()
        .one()
    )


async def next_scenario_step(
    engine: AsyncEngine,
    settings: Settings,
    *,
    profile: str,
    scenario_id: UUID,
    expected_version: int,
    actor_user_id: UUID,
    idempotency_key: str,
) -> dict[str, Any]:
    require_demo_profile(profile)
    async with engine.begin() as connection:
        cached = await _replay(connection, idempotency_key)
        if cached is not None:
            return cached
        scenario = await _scenario(connection, scenario_id, True)
        steps = scenario_steps(str(scenario["code"]))
        active = await _active(connection, True)
        if not active or UUID(str(active["demo_scenario_id"])) != scenario_id:
            raise WorkflowContractError(
                409, "DEMO_PLAYBACK_NOT_ACTIVE", "실행 중인 시나리오가 없습니다."
            )
        _version(active, expected_version)
        if active["status"] != "RUNNING":
            raise WorkflowContractError(
                409,
                "DEMO_PLAYBACK_NOT_RUNNING",
                "시나리오를 시작하거나 재개한 뒤 다음 단계를 실행해 주세요.",
            )
        ordinal = int(active["current_step"]) + 1
        if ordinal > len(steps):
            raise WorkflowContractError(
                409, "DEMO_PLAYBACK_COMPLETE", "시나리오의 모든 단계가 완료되었습니다."
            )
        step = steps[ordinal - 1]
        reserved = dict(
            (
                await connection.execute(
                    text(
                        "UPDATE demo_playback SET current_step=:step,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE demo_playback_id=:id RETURNING *"
                    ),
                    {"step": ordinal, "id": active["demo_playback_id"]},
                )
            )
            .mappings()
            .one()
        )
    try:
        execution = await _execute(engine, settings, scenario_id, int(reserved["generation"]), step)
    except Exception as error:
        async with engine.begin() as connection:
            now = datetime.now(UTC)
            failed = await _pause_failed_step(
                connection,
                playback_id=UUID(str(reserved["demo_playback_id"])),
                previous_step=ordinal - 1,
                now=now,
            )
            await _event(
                connection,
                UUID(str(reserved["demo_playback_id"])),
                "NEXT",
                idempotency_key,
                {
                    "status": "FAILED",
                    "errorClass": type(error).__name__,
                    "playback": _contract(failed, len(steps)),
                },
                step,
            )
        raise
    async with engine.begin() as connection:
        complete = ordinal == len(steps)
        now = datetime.now(UTC)
        row = dict(
            (
                await connection.execute(
                    text(
                        "UPDATE demo_playback SET status=CASE WHEN :complete THEN 'COMPLETED' ELSE status END,completed_at=CASE WHEN :complete THEN CAST(:now AS timestamptz) ELSE NULL END,updated_at=:now WHERE demo_playback_id=:id RETURNING *"
                    ),
                    {"complete": complete, "now": now, "id": reserved["demo_playback_id"]},
                )
            )
            .mappings()
            .one()
        )
        data = {
            "scenarioId": str(scenario_id),
            "code": scenario["code"],
            "command": "NEXT",
            "step": step_contract(step),
            "execution": execution,
            "playback": _contract(row, len(steps)),
        }
        pid = UUID(str(row["demo_playback_id"]))
        await _event(connection, pid, "NEXT", idempotency_key, data, step)
        if complete:
            await _event(connection, pid, "COMPLETE", f"{idempotency_key}:complete", data, step)
        await _audit(
            connection, actor_user_id, pid, "DEMO_SCENARIO_STEP_REPLAYED", idempotency_key, data
        )
        return data


async def _reset_rows(connection: AsyncConnection) -> tuple[dict[str, int], list[str]]:
    paths = [
        str(value)
        for value in (
            await connection.execute(
                text(
                    "SELECT a.storage_path FROM document_artifact a JOIN document_version v ON v.document_version_id=a.document_version_id JOIN document_draft d ON d.document_draft_id=v.document_draft_id JOIN case_record c ON c.case_id=d.case_id WHERE c.is_simulated AND a.storage_path IS NOT NULL"
                )
            )
        )
        .scalars()
        .all()
    ]
    statements = (
        (
            "inspection_approval_decisions",
            "DELETE FROM approval_decision WHERE approval_request_id IN (SELECT approval_request_id FROM approval_request WHERE target_type = 'INSPECTION_SCENARIO')",
        ),
        (
            "inspection_approval_requests",
            "DELETE FROM approval_request WHERE target_type = 'INSPECTION_SCENARIO'",
        ),
        (
            "inspection_team_links",
            "DELETE FROM inspection_team_work_item",
        ),
        (
            "inspection_work_items",
            "DELETE FROM work_item WHERE work_type = 'INSPECTION_PLAN'",
        ),
        (
            "inspection_selection_clear",
            "UPDATE inspection_simulation SET selected_scenario_id = NULL WHERE selected_scenario_id IS NOT NULL",
        ),
        (
            "inspection_simulations",
            "DELETE FROM inspection_simulation",
        ),
        (
            "approval_decisions",
            "DELETE FROM approval_decision WHERE approval_request_id IN (SELECT r.approval_request_id FROM approval_request r JOIN case_record c ON c.case_id=r.case_id WHERE c.is_simulated)",
        ),
        (
            "approval_requests",
            "DELETE FROM approval_request WHERE case_id IN (SELECT case_id FROM case_record WHERE is_simulated)",
        ),
        (
            "document_deliveries",
            "DELETE FROM document_manual_delivery WHERE document_version_id IN (SELECT v.document_version_id FROM document_version v JOIN document_draft d ON d.document_draft_id=v.document_draft_id JOIN case_record c ON c.case_id=d.case_id WHERE c.is_simulated)",
        ),
        (
            "document_artifacts",
            "DELETE FROM document_artifact WHERE document_version_id IN (SELECT v.document_version_id FROM document_version v JOIN document_draft d ON d.document_draft_id=v.document_draft_id JOIN case_record c ON c.case_id=d.case_id WHERE c.is_simulated)",
        ),
        (
            "document_versions",
            "DELETE FROM document_version WHERE document_draft_id IN (SELECT d.document_draft_id FROM document_draft d JOIN case_record c ON c.case_id=d.case_id WHERE c.is_simulated)",
        ),
        (
            "document_drafts",
            "DELETE FROM document_draft WHERE case_id IN (SELECT case_id FROM case_record WHERE is_simulated)",
        ),
        (
            "case_closures",
            "DELETE FROM case_closure WHERE case_id IN (SELECT case_id FROM case_record WHERE is_simulated)",
        ),
        (
            "recommendations",
            "DELETE FROM recommendation WHERE case_id IN (SELECT case_id FROM case_record WHERE is_simulated)",
        ),
        (
            "evidence_bundles",
            "DELETE FROM evidence_bundle WHERE case_id IN (SELECT case_id FROM case_record WHERE is_simulated)",
        ),
        ("cases", "DELETE FROM case_record WHERE is_simulated"),
        ("signal_events", "DELETE FROM signal_event WHERE is_simulated"),
        ("raw_signals", "DELETE FROM raw_signal WHERE is_simulated"),
        (
            "source_responses",
            "DELETE FROM source_response WHERE poll_id IN (SELECT poll_id FROM source_poll WHERE idempotency_key LIKE 'DEMO:%')",
        ),
        ("source_polls", "DELETE FROM source_poll WHERE idempotency_key LIKE 'DEMO:%'"),
        ("source_checkpoints", "DELETE FROM source_checkpoint"),
    )
    counts = {}
    for key, statement in statements:
        result = await connection.execute(text(statement))
        counts[key] = int(result.rowcount or 0)
    await connection.execute(
        text(
            "UPDATE source_health SET status=CASE WHEN enabled THEN 'OUTAGE' ELSE 'DISABLED' END,last_attempt_at=NULL,last_success_at=NULL,last_failure_at=NULL,consecutive_failures=0,next_poll_at=NULL,backoff_until=NULL,last_http_status=NULL,last_error_code=NULL,parser_version='pending',contract_version='pending',updated_at=CURRENT_TIMESTAMP"
        )
    )
    return counts, paths


def _remove_files(root_value: str, paths: list[str]) -> int:
    root = Path(root_value).resolve()
    removed = 0
    for raw in paths:
        relative = PurePosixPath(raw)
        if relative.is_absolute() or ".." in relative.parts:
            continue
        candidate = (root / Path(*relative.parts)).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            candidate.unlink()
            removed += 1
    return removed


async def _clear_redis(redis: Redis, queue: str) -> int:
    keys = {queue, f"{queue}-documents"}
    for pattern in ("rag:*", "recommendation:*", "document:*"):
        async for key in redis.scan_iter(match=pattern, count=100):
            keys.add(str(key))
    return int(await redis.delete(*keys)) if keys else 0


async def reset_scenario(
    engine: AsyncEngine,
    redis: Redis,
    settings: Settings,
    *,
    profile: str,
    scenario_id: UUID,
    expected_version: int | None,
    active_expected_version: int | None,
    confirmed: bool,
    actor_user_id: UUID,
    idempotency_key: str,
) -> dict[str, Any]:
    require_demo_profile(profile)
    if not confirmed:
        raise WorkflowContractError(
            400, "DEMO_RESET_CONFIRMATION_REQUIRED", "처음부터 초기화하려면 확인이 필요합니다."
        )
    paths: list[str] = []
    async with engine.begin() as connection:
        cached = await _replay(connection, idempotency_key)
        if cached is not None:
            return cached
        scenario = await _scenario(connection, scenario_id, True)
        steps = scenario_steps(str(scenario["code"]))
        active = await _active(connection, True)
        active_is_target = bool(
            active and UUID(str(active["demo_scenario_id"])) == scenario_id
        )
        playback = active if active_is_target else await _latest(connection, scenario_id, True)
        if playback is not None:
            _version(playback, expected_version)
        elif expected_version is not None:
            raise WorkflowContractError(
                409,
                "DEMO_PLAYBACK_VERSION_CONFLICT",
                "시나리오 상태가 변경되었습니다. 최신 상태를 다시 확인해 주세요.",
                {"expectedVersion": expected_version, "actualVersion": None},
            )
        if active is not None:
            expected_active = (
                expected_version
                if active_is_target and active_expected_version is None
                else active_expected_version
            )
            _version(active, expected_active)
        counts, paths = await _reset_rows(connection)
        now = datetime.now(UTC)
        replaced_scenario_id: str | None = None
        if active is not None and not active_is_target:
            replaced_scenario_id = str(active["demo_scenario_id"])
            await connection.execute(
                text(
                    """
                    UPDATE demo_playback
                    SET status='COMPLETED', started_at=coalesce(started_at,:now),
                        paused_at=NULL, completed_at=:now, version=version+1,
                        updated_at=:now
                    WHERE demo_playback_id=:id
                    """
                ),
                {"now": now, "id": active["demo_playback_id"]},
            )
        if playback is not None:
            row = dict(
                (
                    await connection.execute(
                        text(
                            "UPDATE demo_playback SET status='READY',current_step=0,generation=generation+1,version=version+1,started_at=NULL,paused_at=NULL,completed_at=NULL,updated_at=:now WHERE demo_playback_id=:id RETURNING *"
                        ),
                        {"now": now, "id": playback["demo_playback_id"]},
                    )
                )
                .mappings()
                .one()
            )
        else:
            generation = int(
                (
                    await connection.execute(
                        text(
                            "SELECT coalesce(max(generation),0)+1 FROM demo_playback WHERE demo_scenario_id=:id"
                        ),
                        {"id": scenario_id},
                    )
                ).scalar_one()
            )
            row = dict(
                (
                    await connection.execute(
                        text(
                            "INSERT INTO demo_playback (demo_playback_id,demo_scenario_id,status,current_step,generation,version,updated_at) VALUES (:pid,:sid,'READY',0,:generation,1,:now) RETURNING *"
                        ),
                        {
                            "pid": uuid4(),
                            "sid": scenario_id,
                            "generation": generation,
                            "now": now,
                        },
                    )
                )
                .mappings()
                .one()
            )
        data = {
            "scenarioId": str(scenario_id),
            "code": scenario["code"],
            "command": "RESET",
            "removed": counts,
            "replacedScenarioId": replaced_scenario_id,
            "playback": _contract(row, len(steps)),
        }
        pid = UUID(str(row["demo_playback_id"]))
        await _event(connection, pid, "RESET", idempotency_key, data)
        await _audit(connection, actor_user_id, pid, "DEMO_SCENARIO_RESET", idempotency_key, data)
    data["removed"]["artifact_files"] = _remove_files(settings.document_storage_root, paths)
    data["removed"]["redis_keys"] = await _clear_redis(redis, settings.celery_queue)
    return data
