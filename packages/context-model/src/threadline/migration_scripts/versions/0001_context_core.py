"""Create the repository, context, evidence, and handoff core."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_context_core"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repositories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("branch", sa.String(length=512), nullable=False),
        sa.Column("head_commit", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "path",
            "branch",
            "head_commit",
            name="uq_repository_version",
        ),
    )
    op.create_index("ix_repositories_tenant_id", "repositories", ["tenant_id"])
    op.create_index("ix_repositories_workspace_id", "repositories", ["workspace_id"])

    op.create_table(
        "context_entities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("repository_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("branch", sa.String(length=512), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("epistemic_state", sa.String(length=32), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_context_scope",
        "context_entities",
        ["tenant_id", "workspace_id", "repository_id", "task_id", "entity_type"],
    )
    op.create_index(
        "ix_context_version",
        "context_entities",
        ["repository_id", "branch", "commit_sha"],
    )
    op.create_index("ix_context_entities_task_id", "context_entities", ["task_id"])
    op.create_index("ix_context_entities_tenant_id", "context_entities", ["tenant_id"])
    op.create_index("ix_context_entities_workspace_id", "context_entities", ["workspace_id"])

    op.create_table(
        "evidence_content",
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["evidence_id"], ["context_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("evidence_id"),
    )
    op.create_index("ix_evidence_content_tenant_id", "evidence_content", ["tenant_id"])

    op.create_table(
        "handoffs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("context_version_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("compiled_content", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_handoff_scope", "handoffs", ["tenant_id", "workspace_id", "task_id"])
    op.create_index("ix_handoffs_task_id", "handoffs", ["task_id"])
    op.create_index("ix_handoffs_tenant_id", "handoffs", ["tenant_id"])
    op.create_index("ix_handoffs_workspace_id", "handoffs", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_handoffs_workspace_id", table_name="handoffs")
    op.drop_index("ix_handoffs_tenant_id", table_name="handoffs")
    op.drop_index("ix_handoffs_task_id", table_name="handoffs")
    op.drop_index("ix_handoff_scope", table_name="handoffs")
    op.drop_table("handoffs")

    op.drop_index("ix_evidence_content_tenant_id", table_name="evidence_content")
    op.drop_table("evidence_content")

    op.drop_index("ix_context_entities_workspace_id", table_name="context_entities")
    op.drop_index("ix_context_entities_tenant_id", table_name="context_entities")
    op.drop_index("ix_context_entities_task_id", table_name="context_entities")
    op.drop_index("ix_context_version", table_name="context_entities")
    op.drop_index("ix_context_scope", table_name="context_entities")
    op.drop_table("context_entities")

    op.drop_index("ix_repositories_workspace_id", table_name="repositories")
    op.drop_index("ix_repositories_tenant_id", table_name="repositories")
    op.drop_table("repositories")
