"""PostgreSQL-compatible canonical storage for the local vertical slice.

The store uses an explicitly invoked schema initializer. Importing the application never creates
or mutates database schema.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from threadline.invariants import validate_snapshot
from threadline.models import (
    Claim,
    Constraint,
    ContextEdge,
    ContextSnapshot,
    ContextVersion,
    Decision,
    Evidence,
    Handoff,
    Observation,
    Task,
    Verification,
)


class Base(DeclarativeBase):
    pass


class RepositoryRow(Base):
    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "path",
            "branch",
            "head_commit",
            name="uq_repository_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    branch: Mapped[str] = mapped_column(String(512), nullable=False)
    head_commit: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContextEntityRow(Base):
    __tablename__ = "context_entities"
    __table_args__ = (
        Index(
            "ix_context_scope",
            "tenant_id",
            "workspace_id",
            "repository_id",
            "task_id",
            "entity_type",
        ),
        Index("ix_context_version", "repository_id", "branch", "commit_sha"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    repository_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.id"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    branch: Mapped[str] = mapped_column(String(512), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    epistemic_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceContentRow(Base):
    __tablename__ = "evidence_content"

    evidence_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("context_entities.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class HandoffRow(Base):
    __tablename__ = "handoffs"
    __table_args__ = (Index("ix_handoff_scope", "tenant_id", "workspace_id", "task_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    context_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    compiled_content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


ENTITY_MODELS: dict[str, type[BaseModel]] = {
    "task": Task,
    "claim": Claim,
    "evidence": Evidence,
    "verification": Verification,
    "decision": Decision,
    "constraint": Constraint,
    "observation": Observation,
    "edge": ContextEdge,
    "context_version": ContextVersion,
}


def utc_now() -> datetime:
    return datetime.now(UTC)


class ThreadlineStore:
    """Tenant-scoped repository over the canonical context tables."""

    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        self.engine: Engine = create_engine(database_url, echo=echo)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def init_schema(self) -> None:
        """Create the local schema explicitly; never called on import or API startup."""

        Base.metadata.create_all(self.engine)

    def drop_schema_for_test(self) -> None:
        """Drop only Threadline-owned tables in an isolated test database."""

        Base.metadata.drop_all(self.engine)

    def close(self) -> None:
        self.engine.dispose()

    def save_repository(
        self,
        *,
        repository_id: UUID,
        tenant_id: UUID,
        workspace_id: UUID,
        name: str,
        path: str,
        branch: str,
        head_commit: str,
    ) -> None:
        row = RepositoryRow(
            id=str(repository_id),
            tenant_id=str(tenant_id),
            workspace_id=str(workspace_id),
            name=name,
            path=path,
            branch=branch,
            head_commit=head_commit,
            observed_at=utc_now(),
        )
        with self._sessions.begin() as session:
            session.merge(row)

    def save_snapshot(
        self,
        snapshot: ContextSnapshot,
        *,
        evidence_content: Mapping[UUID, str],
    ) -> None:
        validate_snapshot(snapshot)
        entities: tuple[tuple[str, BaseModel], ...] = (
            ("task", snapshot.task),
            *(("claim", item) for item in snapshot.claims),
            *(("evidence", item) for item in snapshot.evidence),
            *(("verification", item) for item in snapshot.verifications),
            *(("decision", item) for item in snapshot.decisions),
            *(("constraint", item) for item in snapshot.constraints),
            *(("observation", item) for item in snapshot.observations),
            *(("edge", item) for item in snapshot.edges),
        )
        with self._sessions.begin() as session:
            for entity_type, entity in entities:
                self._merge_entity(
                    session,
                    entity_type=entity_type,
                    entity=entity,
                    repository_id=snapshot.repository_version.repository_id,
                    branch=snapshot.repository_version.branch,
                    commit_sha=snapshot.repository_version.commit_sha,
                    task_id=snapshot.task.id,
                )
            for evidence_id, content in evidence_content.items():
                if evidence_id not in {item.id for item in snapshot.evidence}:
                    raise ValueError("evidence content references evidence outside the snapshot")
                session.merge(
                    EvidenceContentRow(
                        evidence_id=str(evidence_id),
                        tenant_id=str(snapshot.tenant_id),
                        content=content,
                    )
                )

    def save_context_version(self, context_version: ContextVersion, task_id: UUID) -> None:
        with self._sessions.begin() as session:
            self._merge_entity(
                session,
                entity_type="context_version",
                entity=context_version,
                repository_id=context_version.repository_version.repository_id,
                branch=context_version.repository_version.branch,
                commit_sha=context_version.repository_version.commit_sha,
                task_id=task_id,
            )

    def save_handoff(self, handoff: Handoff, compiled_content: dict[str, Any]) -> None:
        with self._sessions.begin() as session:
            session.merge(
                HandoffRow(
                    id=str(handoff.id),
                    tenant_id=str(handoff.tenant_id),
                    workspace_id=str(handoff.workspace_id),
                    task_id=str(handoff.task_id),
                    context_version_id=str(handoff.context_version_id),
                    payload=handoff.model_dump(mode="json"),
                    compiled_content=compiled_content,
                    created_at=handoff.created_at,
                )
            )

    def load_snapshot(
        self, *, tenant_id: UUID, workspace_id: UUID, task_id: UUID
    ) -> ContextSnapshot:
        with self._sessions() as session:
            task_row = session.scalar(
                select(ContextEntityRow).where(
                    ContextEntityRow.tenant_id == str(tenant_id),
                    ContextEntityRow.workspace_id == str(workspace_id),
                    ContextEntityRow.task_id == str(task_id),
                    ContextEntityRow.entity_type == "task",
                )
            )
            if task_row is None:
                raise LookupError("task context was not found in the authorized scope")
            rows = session.scalars(
                select(ContextEntityRow).where(
                    ContextEntityRow.tenant_id == str(tenant_id),
                    ContextEntityRow.workspace_id == str(workspace_id),
                    ContextEntityRow.task_id == str(task_id),
                    ContextEntityRow.repository_id == task_row.repository_id,
                    ContextEntityRow.branch == task_row.branch,
                    ContextEntityRow.commit_sha == task_row.commit_sha,
                    ContextEntityRow.entity_type != "context_version",
                )
            ).all()

        grouped: dict[str, list[BaseModel]] = {}
        for row in rows:
            model_type = ENTITY_MODELS[row.entity_type]
            grouped.setdefault(row.entity_type, []).append(model_type.model_validate(row.payload))

        active_task = Task.model_validate(task_row.payload)
        snapshot = ContextSnapshot(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            repository_version=active_task.repository_version,
            task=active_task,
            claims=tuple(_typed(grouped.get("claim", []), Claim)),
            evidence=tuple(_typed(grouped.get("evidence", []), Evidence)),
            verifications=tuple(_typed(grouped.get("verification", []), Verification)),
            decisions=tuple(_typed(grouped.get("decision", []), Decision)),
            constraints=tuple(_typed(grouped.get("constraint", []), Constraint)),
            observations=tuple(_typed(grouped.get("observation", []), Observation)),
            edges=tuple(_typed(grouped.get("edge", []), ContextEdge)),
        )
        validate_snapshot(snapshot)
        return snapshot

    def load_evidence_content(
        self,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        evidence_ids: Iterable[UUID],
    ) -> dict[UUID, str]:
        requested = [str(item) for item in evidence_ids]
        if not requested:
            return {}
        with self._sessions() as session:
            rows = session.execute(
                select(EvidenceContentRow.evidence_id, EvidenceContentRow.content)
                .join(
                    ContextEntityRow,
                    ContextEntityRow.id == EvidenceContentRow.evidence_id,
                )
                .where(
                    EvidenceContentRow.tenant_id == str(tenant_id),
                    ContextEntityRow.workspace_id == str(workspace_id),
                    EvidenceContentRow.evidence_id.in_(requested),
                )
            ).all()
        return {UUID(evidence_id): content for evidence_id, content in rows}

    def load_latest_handoff(
        self, *, tenant_id: UUID, workspace_id: UUID, task_id: UUID
    ) -> dict[str, Any]:
        with self._sessions() as session:
            row = session.scalar(
                select(HandoffRow)
                .where(
                    HandoffRow.tenant_id == str(tenant_id),
                    HandoffRow.workspace_id == str(workspace_id),
                    HandoffRow.task_id == str(task_id),
                )
                .order_by(HandoffRow.created_at.desc())
                .limit(1)
            )
        if row is None:
            raise LookupError("handoff was not found in the authorized scope")
        return dict(row.compiled_content)

    def reset_tenant_for_demo(self, tenant_id: UUID) -> None:
        """Delete one explicit synthetic tenant; unavailable through public serving APIs."""

        tenant = str(tenant_id)
        with self._sessions.begin() as session:
            session.execute(delete(HandoffRow).where(HandoffRow.tenant_id == tenant))
            evidence_ids = session.scalars(
                select(ContextEntityRow.id).where(
                    ContextEntityRow.tenant_id == tenant,
                    ContextEntityRow.entity_type == "evidence",
                )
            ).all()
            if evidence_ids:
                session.execute(
                    delete(EvidenceContentRow).where(
                        EvidenceContentRow.evidence_id.in_(evidence_ids)
                    )
                )
            session.execute(delete(ContextEntityRow).where(ContextEntityRow.tenant_id == tenant))
            session.execute(delete(RepositoryRow).where(RepositoryRow.tenant_id == tenant))

    @staticmethod
    def _merge_entity(
        session: Session,
        *,
        entity_type: str,
        entity: BaseModel,
        repository_id: UUID,
        branch: str,
        commit_sha: str,
        task_id: UUID,
    ) -> None:
        payload = entity.model_dump(mode="json")
        state = payload.get("epistemic_state")
        session.merge(
            ContextEntityRow(
                id=str(payload["id"]),
                tenant_id=str(payload["tenant_id"]),
                workspace_id=str(payload["workspace_id"]),
                repository_id=str(repository_id),
                task_id=str(task_id),
                branch=branch,
                commit_sha=commit_sha,
                entity_type=entity_type,
                epistemic_state=str(state) if state is not None else None,
                payload=payload,
                created_at=datetime.fromisoformat(str(payload["created_at"])),
            )
        )


def _typed[Entity: BaseModel](items: Iterable[BaseModel], expected: type[Entity]) -> list[Entity]:
    typed: list[Entity] = []
    for item in items:
        if not isinstance(item, expected):
            raise TypeError(f"stored entity is not {expected.__name__}")
        typed.append(item)
    return typed
