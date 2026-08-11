"""Cross-entity invariants for trustworthy context publication."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from threadline.models import (
    Claim,
    ContextSnapshot,
    EpistemicState,
    EvidenceRelation,
    Verification,
    VerificationResult,
)


class InvariantViolation(ValueError):
    """Raised when a context snapshot violates a non-negotiable invariant."""


def _ensure_same_tenant_and_workspace(
    tenant_id: UUID, workspace_id: UUID, entities: Iterable[object]
) -> None:
    for entity in entities:
        entity_tenant = getattr(entity, "tenant_id", None)
        entity_workspace = getattr(entity, "workspace_id", None)
        if entity_tenant != tenant_id or entity_workspace != workspace_id:
            raise InvariantViolation("cross-tenant or cross-workspace context is forbidden")


def _verification_by_claim(verifications: tuple[Verification, ...]) -> dict[UUID, Verification]:
    indexed: dict[UUID, Verification] = {}
    for verification in verifications:
        existing = indexed.get(verification.claim_id)
        if existing is not None and existing.executed_at >= verification.executed_at:
            continue
        indexed[verification.claim_id] = verification
    return indexed


def _validate_claim_state(claim: Claim, verification: Verification | None) -> None:
    if claim.epistemic_state is EpistemicState.VERIFIED:
        if verification is None or verification.result is not VerificationResult.VERIFIED:
            raise InvariantViolation("VERIFIED claims require a successful persisted verification")
        supporting_ids = {
            link.evidence_id
            for link in claim.evidence
            if link.relation is EvidenceRelation.SUPPORTS
        }
        if not supporting_ids.intersection(verification.evidence_ids):
            raise InvariantViolation("VERIFIED claims require shared supporting evidence")

    if claim.epistemic_state is EpistemicState.CONTRADICTED:
        if verification is None or verification.result is not VerificationResult.CONTRADICTED:
            raise InvariantViolation("CONTRADICTED claims require a persisted contradiction")
        contradicting_ids = {
            link.evidence_id
            for link in claim.evidence
            if link.relation is EvidenceRelation.CONTRADICTS
        }
        if not contradicting_ids.intersection(verification.evidence_ids):
            raise InvariantViolation("CONTRADICTED claims require shared contradicting evidence")


def validate_snapshot(snapshot: ContextSnapshot) -> None:
    """Validate a snapshot before it can become an immutable context version."""

    all_entities: tuple[object, ...] = (
        snapshot.task,
        *snapshot.claims,
        *snapshot.evidence,
        *snapshot.verifications,
        *snapshot.edges,
    )
    _ensure_same_tenant_and_workspace(snapshot.tenant_id, snapshot.workspace_id, all_entities)

    if snapshot.task.repository_version != snapshot.repository_version:
        raise InvariantViolation("task repository version must match the snapshot")

    evidence_by_id = {item.id: item for item in snapshot.evidence}
    verifications = _verification_by_claim(snapshot.verifications)
    entity_ids = {
        snapshot.task.id,
        *(item.id for item in snapshot.claims),
        *(item.id for item in snapshot.evidence),
        *(item.id for item in snapshot.verifications),
        *(item.id for item in snapshot.edges),
    }

    for claim in snapshot.claims:
        if claim.task_id != snapshot.task.id:
            raise InvariantViolation("claim belongs to a different task")
        if claim.repository_version != snapshot.repository_version:
            raise InvariantViolation("claim repository version must match the snapshot")
        for link in claim.evidence:
            evidence = evidence_by_id.get(link.evidence_id)
            if evidence is None:
                raise InvariantViolation("claim references evidence outside the snapshot")
            if evidence.repository_version != snapshot.repository_version:
                raise InvariantViolation("claim evidence belongs to a different repository version")
        _validate_claim_state(claim, verifications.get(claim.id))

    for verification in snapshot.verifications:
        if verification.claim_id not in {claim.id for claim in snapshot.claims}:
            raise InvariantViolation("verification references a claim outside the snapshot")
        if not set(verification.evidence_ids).issubset(evidence_by_id):
            raise InvariantViolation("verification references evidence outside the snapshot")

    for edge in snapshot.edges:
        if edge.from_id not in entity_ids or edge.to_id not in entity_ids:
            raise InvariantViolation("edge endpoint is outside the authorized snapshot")
        if edge.source_evidence_id is not None and edge.source_evidence_id not in evidence_by_id:
            raise InvariantViolation("edge provenance is outside the snapshot")
