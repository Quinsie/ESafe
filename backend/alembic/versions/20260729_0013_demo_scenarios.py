"""Create deterministic DEMO scenario catalog and playback state.

Revision ID: 20260729_0013
Revises: 20260729_0012
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260729_0013"
down_revision: str | None = "20260729_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE demo_scenario (
            demo_scenario_id uuid PRIMARY KEY,
            code varchar(16) NOT NULL UNIQUE,
            name text NOT NULL,
            description text NOT NULL,
            ordinal integer NOT NULL UNIQUE,
            scenario_version integer NOT NULL DEFAULT 1,
            enabled boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_demo_scenario_code CHECK (code ~ '^DS-[0-9]{2}$'),
            CONSTRAINT ck_demo_scenario_text CHECK (
                length(trim(name)) > 0 AND length(trim(description)) > 0
            ),
            CONSTRAINT ck_demo_scenario_numbers CHECK (
                ordinal > 0 AND scenario_version > 0
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE demo_playback (
            demo_playback_id uuid PRIMARY KEY,
            demo_scenario_id uuid NOT NULL
                REFERENCES demo_scenario(demo_scenario_id) ON DELETE RESTRICT,
            status varchar(16) NOT NULL,
            current_step integer NOT NULL DEFAULT 0,
            generation integer NOT NULL DEFAULT 1,
            version integer NOT NULL DEFAULT 1,
            started_at timestamptz,
            paused_at timestamptz,
            completed_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_demo_playback_status CHECK (
                status IN ('READY', 'RUNNING', 'PAUSED', 'COMPLETED')
            ),
            CONSTRAINT ck_demo_playback_numbers CHECK (
                current_step >= 0 AND generation > 0 AND version > 0
            ),
            CONSTRAINT ck_demo_playback_dates CHECK (
                (status = 'READY' AND started_at IS NULL AND paused_at IS NULL
                    AND completed_at IS NULL)
                OR (status = 'RUNNING' AND started_at IS NOT NULL
                    AND paused_at IS NULL AND completed_at IS NULL)
                OR (status = 'PAUSED' AND started_at IS NOT NULL
                    AND paused_at IS NOT NULL AND completed_at IS NULL)
                OR (status = 'COMPLETED' AND started_at IS NOT NULL
                    AND completed_at IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ux_demo_playback_active
        ON demo_playback ((true))
        WHERE status IN ('READY', 'RUNNING', 'PAUSED')
        """
    )
    op.execute(
        """
        CREATE TABLE demo_playback_event (
            demo_playback_event_id uuid PRIMARY KEY,
            demo_playback_id uuid NOT NULL
                REFERENCES demo_playback(demo_playback_id) ON DELETE RESTRICT,
            command varchar(16) NOT NULL,
            step_ordinal integer,
            source_time timestamptz,
            replayed_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            result jsonb NOT NULL DEFAULT '{}'::jsonb,
            idempotency_key varchar(160) NOT NULL UNIQUE,
            CONSTRAINT ck_demo_playback_event_command CHECK (
                command IN ('START', 'PAUSE', 'NEXT', 'RESET', 'COMPLETE')
            ),
            CONSTRAINT ck_demo_playback_event_step CHECK (
                step_ordinal IS NULL OR step_ordinal > 0
            ),
            CONSTRAINT ck_demo_playback_event_result CHECK (
                jsonb_typeof(result) = 'object'
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_demo_playback_event_timeline
        ON demo_playback_event (demo_playback_id, replayed_at, demo_playback_event_id)
        """
    )
    op.execute(
        """
        INSERT INTO demo_scenario (
            demo_scenario_id, code, name, description, ordinal
        )
        VALUES
            ('89ec1b9e-6dc2-5f49-95bf-971098c85101', 'DS-01',
             '화재 전체 여정',
             'NFDS 신규 화재부터 갱신, 근거·문서 처리와 원천 종료까지 재현합니다.', 1),
            ('89ec1b9e-6dc2-5f49-95bf-971098c85102', 'DS-02',
             '기상특보 생명주기',
             '광주·전남 특보 발표, 영향지역 변경, 단계 조정과 해제를 재현합니다.', 2),
            ('89ec1b9e-6dc2-5f49-95bf-971098c85103', 'DS-03',
             '재난문자 필터·중복',
             '포함·조건부 포함·제외와 중복·페이지 보충 처리를 검증합니다.', 3),
            ('89ec1b9e-6dc2-5f49-95bf-971098c85104', 'DS-04',
             '교차 신호원 관계',
             '자동 연결과 후보 관계, 사용자 병합·해제의 경계를 검증합니다.', 4),
            ('89ec1b9e-6dc2-5f49-95bf-971098c85105', 'DS-05',
             '소스 장애·복구',
             '정상, 지연, 장애, 백오프와 정상 복구를 순서대로 재현합니다.', 5),
            ('89ec1b9e-6dc2-5f49-95bf-971098c85106', 'DS-06',
             '근거 상태',
             '충분, 부족, 충돌 근거에서 화면·문서·승인 흐름을 검증합니다.', 6)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS demo_playback_event")
    op.execute("DROP INDEX IF EXISTS ux_demo_playback_active")
    op.execute("DROP TABLE IF EXISTS demo_playback")
    op.execute("DROP TABLE IF EXISTS demo_scenario")
