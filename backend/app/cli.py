import argparse
import asyncio
import json
from collections.abc import Sequence
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.ai_control import CONTROL_SCHEMA_VERSION, AiCostGate, initialize_ai_control
from app.config import get_settings
from app.rag_embeddings import build_embedding_bundle
from app.security import hash_password
from app.signals.ingestion import run_kma_source_repair
from app.signals.reprocess import reprocess_kma_events
from app.upstage import UpstageEmbeddingClient


async def seed_system_metadata() -> None:
    settings = get_settings()
    if settings.public_user_password is None:
        raise RuntimeError("ESAFE_PUBLIC_USER_PASSWORD is required for seed")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO system_metadata (key, value)
                    VALUES ('bootstrap_profile', :profile)
                    ON CONFLICT (key)
                    DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                    """
                ),
                {"profile": settings.profile},
            )
            existing = await connection.execute(
                text("SELECT username FROM app_user ORDER BY created_at LIMIT 1")
            )
            existing_username = existing.scalar_one_or_none()
            if existing_username is None:
                password_hash = await asyncio.to_thread(
                    hash_password,
                    settings.public_user_password.get_secret_value(),
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO app_user (
                            user_id, username, display_name, password_hash, is_active
                        )
                        VALUES (:user_id, :username, '사용자', :password_hash, true)
                        """
                    ),
                    {
                        "user_id": uuid4(),
                        "username": settings.public_user_id,
                        "password_hash": password_hash,
                    },
                )
            elif existing_username != settings.public_user_id:
                raise RuntimeError(
                    "The configured public user ID differs from the initialized account"
                )

            execution_mode = "EXTERNAL" if settings.profile == "LIVE" else "FIXTURE"
            sources = (
                ("NFDS", settings.nfds_enabled if settings.profile == "LIVE" else True),
                ("KMA_WARNING", True),
                ("DISASTER_MESSAGE", True),
            )
            for source, enabled in sources:
                await connection.execute(
                    text(
                        """
                        INSERT INTO source_health (
                            source, execution_mode, enabled, status,
                            parser_version, contract_version
                        )
                        VALUES (
                            :source, :execution_mode, :enabled,
                            CASE WHEN :enabled THEN 'OUTAGE' ELSE 'DISABLED' END,
                            'pending', 'pending'
                        )
                        ON CONFLICT (source) DO UPDATE
                        SET execution_mode = EXCLUDED.execution_mode,
                            enabled = EXCLUDED.enabled,
                            status = CASE
                                WHEN NOT EXCLUDED.enabled THEN 'DISABLED'
                                WHEN source_health.status = 'DISABLED' THEN 'OUTAGE'
                                ELSE source_health.status
                            END,
                            updated_at = CASE
                                WHEN source_health.execution_mode
                                     IS DISTINCT FROM EXCLUDED.execution_mode
                                  OR source_health.enabled IS DISTINCT FROM EXCLUDED.enabled
                                THEN CURRENT_TIMESTAMP
                                ELSE source_health.updated_at
                            END
                        """
                    ),
                    {
                        "source": source,
                        "execution_mode": execution_mode,
                        "enabled": enabled,
                    },
                )
    finally:
        await engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument(
        "command",
        choices=(
            "seed",
            "reprocess-kma",
            "repair-kma-source",
            "init-ai-control",
            "probe-upstage-embedding",
            "build-rag-embeddings",
        ),
    )
    return parser


async def probe_upstage_embedding() -> dict[str, object]:
    settings = get_settings()
    gate = AiCostGate(settings)
    try:
        result = await UpstageEmbeddingClient(settings, gate).embed_passages(
            ["전기재해 예방 관제 근거 검색 연결 시험"],
            feature_name="embedding-contract-probe",
            privacy_verified=True,
        )
        return {
            "status": "SUCCESS",
            "model": settings.upstage_embed_passage_model,
            "dimension": len(result.vectors[0]),
            "embeddingTokens": result.embedding_tokens,
            "reservationId": result.reservation_id,
        }
    finally:
        await gate.close()


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "seed":
        asyncio.run(seed_system_metadata())
    elif args.command == "reprocess-kma":
        result = asyncio.run(reprocess_kma_events(get_settings()))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif args.command == "repair-kma-source":
        result = asyncio.run(run_kma_source_repair(get_settings()))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif args.command == "init-ai-control":
        asyncio.run(initialize_ai_control(get_settings()))
        print(
            json.dumps(
                {"status": "SUCCESS", "schemaVersion": CONTROL_SCHEMA_VERSION},
                sort_keys=True,
            )
        )
    elif args.command == "probe-upstage-embedding":
        result = asyncio.run(probe_upstage_embedding())
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif args.command == "build-rag-embeddings":
        result = asyncio.run(build_embedding_bundle(get_settings()))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
