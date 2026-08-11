"""Cross-entity invariants for trustworthy context publication."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from threadline.models import (
    Claim,
    CodeDependency,
    CodeParseDiagnostic,
    CodeSymbol,
    Constraint,
    ContextSnapshot,
    Decision,
    EpistemicState,
    EvidenceRelation,
    Observation,
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
        *snapshot.decisions,
        *snapshot.constraints,
        *snapshot.observations,
        *snapshot.code_symbols,
        *snapshot.code_dependencies,
        *snapshot.code_parse_diagnostics,
        *snapshot.edges,
    )
    _ensure_same_tenant_and_workspace(snapshot.tenant_id, snapshot.workspace_id, all_entities)

    if snapshot.task.repository_version != snapshot.repository_version:
        raise InvariantViolation("task repository version must match the snapshot")

    evidence_by_id = {item.id: item for item in snapshot.evidence}
    for evidence in snapshot.evidence:
        if evidence.repository_version != snapshot.repository_version:
            raise InvariantViolation("evidence belongs to a different repository version")
    verifications = _verification_by_claim(snapshot.verifications)
    entity_ids = {
        snapshot.task.id,
        *(item.id for item in snapshot.claims),
        *(item.id for item in snapshot.evidence),
        *(item.id for item in snapshot.verifications),
        *(item.id for item in snapshot.decisions),
        *(item.id for item in snapshot.constraints),
        *(item.id for item in snapshot.observations),
        *(item.id for item in snapshot.code_symbols),
        *(item.id for item in snapshot.code_dependencies),
        *(item.id for item in snapshot.code_parse_diagnostics),
        *(item.id for item in snapshot.edges),
    }

    if not set(snapshot.task.evidence_ids).issubset(evidence_by_id):
        raise InvariantViolation("task references evidence outside the snapshot")

    for claim in snapshot.claims:
        if claim.task_id != snapshot.task.id:
            raise InvariantViolation("claim belongs to a different task")
        if claim.repository_version != snapshot.repository_version:
            raise InvariantViolation("claim repository version must match the snapshot")
        for link in claim.evidence:
            linked_evidence = evidence_by_id.get(link.evidence_id)
            if linked_evidence is None:
                raise InvariantViolation("claim references evidence outside the snapshot")
            if linked_evidence.repository_version != snapshot.repository_version:
                raise InvariantViolation("claim evidence belongs to a different repository version")
        _validate_claim_state(claim, verifications.get(claim.id))

    for verification in snapshot.verifications:
        if verification.claim_id not in {claim.id for claim in snapshot.claims}:
            raise InvariantViolation("verification references a claim outside the snapshot")
        if not set(verification.evidence_ids).issubset(evidence_by_id):
            raise InvariantViolation("verification references evidence outside the snapshot")

    task_entities: tuple[Decision | Constraint | Observation, ...] = (
        *snapshot.decisions,
        *snapshot.constraints,
        *snapshot.observations,
    )
    for task_entity in task_entities:
        if task_entity.task_id != snapshot.task.id:
            raise InvariantViolation("context entity belongs to a different task")
        if task_entity.repository_version != snapshot.repository_version:
            raise InvariantViolation("context entity repository version must match the snapshot")
        if isinstance(task_entity, Decision | Constraint) and not set(
            task_entity.evidence_ids
        ).issubset(evidence_by_id):
            raise InvariantViolation("context entity references evidence outside the snapshot")

    code_entities: tuple[CodeSymbol | CodeDependency | CodeParseDiagnostic, ...] = (
        *snapshot.code_symbols,
        *snapshot.code_dependencies,
        *snapshot.code_parse_diagnostics,
    )
    for code_entity in code_entities:
        if code_entity.task_id != snapshot.task.id:
            raise InvariantViolation("code entity belongs to a different task")
        if code_entity.repository_version != snapshot.repository_version:
            raise InvariantViolation("code entity repository version must match the snapshot")
        if code_entity.evidence_id not in evidence_by_id:
            raise InvariantViolation("code entity references evidence outside the snapshot")

    symbol_by_key = {item.logical_key: item for item in snapshot.code_symbols}
    if len(symbol_by_key) != len(snapshot.code_symbols):
        raise InvariantViolation("code symbol logical keys must be unique")
    dependency_keys = {item.logical_key for item in snapshot.code_dependencies}
    if len(dependency_keys) != len(snapshot.code_dependencies):
        raise InvariantViolation("code dependency logical keys must be unique")
    diagnostic_keys = {item.logical_key for item in snapshot.code_parse_diagnostics}
    if len(diagnostic_keys) != len(snapshot.code_parse_diagnostics):
        raise InvariantViolation("code parse diagnostic logical keys must be unique")
    for dependency in snapshot.code_dependencies:
        if dependency.source_symbol_key not in symbol_by_key:
            raise InvariantViolation("code dependency source is outside the snapshot")
        if (
            dependency.target_symbol_key is not None
            and dependency.target_symbol_key not in symbol_by_key
        ):
            raise InvariantViolation("resolved code dependency target is outside the snapshot")

    for edge in snapshot.edges:
        if edge.from_id not in entity_ids or edge.to_id not in entity_ids:
            raise InvariantViolation("edge endpoint is outside the authorized snapshot")
        if edge.source_evidence_id is not None and edge.source_evidence_id not in evidence_by_id:
            raise InvariantViolation("edge provenance is outside the snapshot")
