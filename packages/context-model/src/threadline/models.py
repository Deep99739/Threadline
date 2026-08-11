"""Versioned domain models for Threadline.

These contracts intentionally keep claims, evidence, and verification separate. An LLM can
propose a claim, but only a deterministic verifier or an authorized human may certify it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

NonEmpty = Annotated[str, Field(min_length=1)]
CommitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{7,64}$")]


def utc_now() -> datetime:
    """Return a timezone-aware timestamp for default factories."""

    return datetime.now(UTC)


class ActorType(StrEnum):
    HUMAN = "HUMAN"
    SERVICE = "SERVICE"
    AGENT = "AGENT"
    INTEGRATION = "INTEGRATION"


class EpistemicState(StrEnum):
    ASSERTED = "ASSERTED"
    OBSERVED = "OBSERVED"
    VERIFIED = "VERIFIED"
    CONTRADICTED = "CONTRADICTED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"
    UNKNOWN = "UNKNOWN"


class ClaimType(StrEnum):
    IMPLEMENTATION = "IMPLEMENTATION"
    BEHAVIOR = "BEHAVIOR"
    TEST = "TEST"
    DEPLOYMENT = "DEPLOYMENT"
    DECISION = "DECISION"
    INTENTION = "INTENTION"
    PERMISSION = "PERMISSION"
    COMPLETION = "COMPLETION"


class EvidenceRelation(StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"


class VerificationResult(StrEnum):
    VERIFIED = "VERIFIED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    ERROR = "ERROR"


class VerifierKind(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    AUTHORIZED_HUMAN = "AUTHORIZED_HUMAN"


class EdgeType(StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    SUPERSEDES = "SUPERSEDES"
    DERIVED_FROM = "DERIVED_FROM"
    AFFECTS = "AFFECTS"
    VERIFIED_BY = "VERIFIED_BY"
    PRODUCED_BY = "PRODUCED_BY"
    APPROVED_BY = "APPROVED_BY"
    BLOCKS = "BLOCKS"
    NEXT_STEP = "NEXT_STEP"
    DEPENDS_ON = "DEPENDS_ON"
    IMPLEMENTS = "IMPLEMENTS"
    REJECTED_IN_FAVOR_OF = "REJECTED_IN_FAVOR_OF"
    VISIBLE_TO = "VISIBLE_TO"
    VALID_AT = "VALID_AT"


class FrozenContract(BaseModel):
    """Immutable contract used for evidence and published context objects."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_assignment=True)


class MutableContract(BaseModel):
    """Strict contract used for draft/control-plane objects."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class TenantScoped(FrozenContract):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    workspace_id: UUID
    created_at: datetime = Field(default_factory=utc_now)
    created_by: UUID
    version: int = Field(default=1, ge=1)


class RepositoryVersion(FrozenContract):
    repository_id: UUID
    branch: NonEmpty
    commit_sha: CommitSha


class EvidenceLocator(FrozenContract):
    uri: NonEmpty
    content_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def line_range_is_ordered(self) -> Self:
        if self.line_end is not None and self.line_start is None:
            raise ValueError("line_start is required when line_end is provided")
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


class Evidence(TenantScoped):
    repository_version: RepositoryVersion
    evidence_type: NonEmpty
    locator: EvidenceLocator
    captured_at: datetime
    sensitivity: str = "INTERNAL"


class EvidenceLink(FrozenContract):
    evidence_id: UUID
    relation: EvidenceRelation


class Claim(TenantScoped):
    repository_version: RepositoryVersion
    task_id: UUID
    claim_type: ClaimType
    subject_key: NonEmpty
    predicate: NonEmpty
    value: Any
    epistemic_state: EpistemicState
    evidence: tuple[EvidenceLink, ...] = ()
    freshness_rule: NonEmpty


class Verification(TenantScoped):
    claim_id: UUID
    verifier_key: NonEmpty
    verifier_version: NonEmpty
    verifier_kind: VerifierKind
    input_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    result: VerificationResult
    evidence_ids: tuple[UUID, ...]
    executed_at: datetime

    @model_validator(mode="after")
    def successful_results_require_evidence(self) -> Self:
        if (
            self.result
            in {
                VerificationResult.VERIFIED,
                VerificationResult.CONTRADICTED,
            }
            and not self.evidence_ids
        ):
            raise ValueError("verified and contradicted results require evidence")
        return self


class Decision(TenantScoped):
    repository_version: RepositoryVersion
    task_id: UUID
    decision_key: NonEmpty
    status: str
    statement: NonEmpty
    rationale: NonEmpty
    approved_by: UUID | None = None


class Constraint(TenantScoped):
    repository_version: RepositoryVersion
    task_id: UUID
    constraint_key: NonEmpty
    statement: NonEmpty
    severity: str
    approved_by: UUID | None = None


class Observation(TenantScoped):
    repository_version: RepositoryVersion
    task_id: UUID
    session_id: UUID
    actor_type: ActorType
    statement: NonEmpty
    observed_at: datetime
    source_evidence_id: UUID | None = None


class Task(TenantScoped):
    repository_version: RepositoryVersion
    objective: NonEmpty
    status: str
    owner_actor_id: UUID


class ContextEdge(TenantScoped):
    from_type: NonEmpty
    from_id: UUID
    edge_type: EdgeType
    to_type: NonEmpty
    to_id: UUID
    source_evidence_id: UUID | None = None


class ContextVersion(TenantScoped):
    repository_version: RepositoryVersion
    config_version: NonEmpty
    root_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    published_at: datetime


class Citation(FrozenContract):
    evidence_id: UUID
    locator: EvidenceLocator


class ContextItem(FrozenContract):
    entity_type: NonEmpty
    entity_id: UUID
    statement: NonEmpty
    epistemic_state: EpistemicState
    selection_reason: NonEmpty
    citations: tuple[Citation, ...]


class ContextPack(FrozenContract):
    request_id: UUID = Field(default_factory=uuid4)
    trace_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    workspace_id: UUID
    task_id: UUID
    repository_version: RepositoryVersion
    context_version_id: UUID
    config_version: NonEmpty
    purpose: NonEmpty
    token_budget: int = Field(ge=128, le=100_000)
    items: tuple[ContextItem, ...]
    unknowns: tuple[NonEmpty, ...] = ()
    conflicts: tuple[NonEmpty, ...] = ()


class Handoff(TenantScoped):
    task_id: UUID
    context_version_id: UUID
    producer_actor_id: UUID
    intended_receiver: NonEmpty
    purpose: NonEmpty
    content_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    expires_at: datetime | None = None
    supersedes_id: UUID | None = None


class ContextSnapshot(MutableContract):
    """Aggregate checked by trust invariants before publication."""

    tenant_id: UUID
    workspace_id: UUID
    repository_version: RepositoryVersion
    task: Task
    claims: tuple[Claim, ...]
    evidence: tuple[Evidence, ...]
    verifications: tuple[Verification, ...]
    edges: tuple[ContextEdge, ...] = ()
