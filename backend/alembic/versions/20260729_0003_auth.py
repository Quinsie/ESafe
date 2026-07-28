"""Create public user, server session, and authentication audit tables.

Revision ID: 20260729_0003
Revises: 20260729_0002
Create Date: 2026-07-29 05:35:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260729_0003"
down_revision: str | None = "20260729_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(length=128), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("length(trim(username)) > 0", name="ck_app_user_username"),
        sa.CheckConstraint("length(password_hash) >= 64", name="ck_app_user_password_hash"),
    )
    op.create_table(
        "user_session",
        sa.Column("session_id_hash", sa.CHAR(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("app_user.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("csrf_token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("profile", sa.String(length=8), nullable=False),
        sa.Column("client_fingerprint", sa.CHAR(length=64), nullable=False),
        sa.Column("user_agent_fingerprint", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoke_reason", sa.String(length=32)),
        sa.CheckConstraint("profile IN ('LIVE', 'DEMO')", name="ck_user_session_profile"),
        sa.CheckConstraint(
            "session_id_hash ~ '^[0-9a-f]{64}$'",
            name="ck_user_session_id_hash",
        ),
        sa.CheckConstraint(
            "csrf_token_hash ~ '^[0-9a-f]{64}$'",
            name="ck_user_session_csrf_hash",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_user_session_expiry"),
    )
    op.create_index(
        "ix_user_session_user_active",
        "user_session",
        ["user_id", "revoked_at", "expires_at"],
    )
    op.create_index("ix_user_session_expiry", "user_session", ["expires_at"])
    op.create_table(
        "auth_audit",
        sa.Column("audit_id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("app_user.user_id")),
        sa.Column("username_fingerprint", sa.CHAR(length=64), nullable=False),
        sa.Column("client_fingerprint", sa.CHAR(length=64), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "event_type IN ('LOGIN_SUCCESS', 'LOGIN_FAILURE', 'LOGIN_RATE_LIMITED', "
            "'LOGOUT', 'SESSION_EXPIRED')",
            name="ck_auth_audit_event_type",
        ),
    )
    op.create_index("ix_auth_audit_created_at", "auth_audit", ["created_at"])
    op.create_index(
        "ix_auth_audit_client_time",
        "auth_audit",
        ["client_fingerprint", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("auth_audit")
    op.drop_table("user_session")
    op.drop_table("app_user")
