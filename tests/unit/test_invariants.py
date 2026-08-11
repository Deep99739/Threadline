from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from tests.unit.test_models import (
    NOW,
    TENANT,
    WORKSPACE,
    claim,
    evidence,
    repository_version,
    snapshot,
    task,
    verification,
)
from threadline.invariants import InvariantViolation, validate_snapshot
from threadline.models import (
    ContextEdge,
    EdgeType,
    EpistemicState,
    EvidenceRelation,
    RepositoryVersion,
    VerificationResult,
)


def test_valid_snapshot_passes() -> None:
    validate_snapshot(snapshot())


def test_cross_tenant_entity_is_rejected() -> None:
    foreign = evidence(tenant_id=uuid4())

    with pytest.raises(InvariantViolation, match="cross-tenant"):
        validate_snapshot(snapshot(evidence_items=(foreign,), claims=(), verifications=()))


def test_task_repository_version_must_match() -> None:
    wrong_version = RepositoryVersion(
        repository_id=repository_version().repository_id,
        branch="other",
        commit_sha="def5678",
    )

    with pytest.raises(InvariantViolation, match="task repository version"):
        validate_snapshot(snapshot(active_task=task(repo=wrong_version)))


def test_claim_must_belong_to_snapshot_task() -> None:
    current_task = task()
    item = evidence()
    foreign_task = task()
    foreign_claim = claim(foreign_task, item)

    with pytest.raises(InvariantViolation, match="different task"):
        validate_snapshot(
            snapshot(
                active_task=current_task,
                claims=(foreign_claim,),
                evidence_items=(item,),
                verifications=(verification(foreign_claim, item),),
            )
        )


def test_claim_repository_version_must_match() -> None:
    current_task = task()
    item = evidence()
    other_version = RepositoryVersion(
        repository_id=repository_version().repository_id,
        branch="other",
        commit_sha="def5678",
    )
    wrong_claim = claim(current_task, item, repo=other_version)

    with pytest.raises(InvariantViolation, match="claim repository version"):
        validate_snapshot(
            snapshot(
                active_task=current_task,
                claims=(wrong_claim,),
                evidence_items=(item,),
                verifications=(verification(wrong_claim, item),),
            )
        )


def test_claim_cannot_reference_missing_evidence() -> None:
    active_task = task()
    item = evidence()
    active_claim = claim(active_task, item)

    with pytest.raises(InvariantViolation, match="outside the snapshot"):
        validate_snapshot(
            snapshot(
                active_task=active_task,
                claims=(active_claim,),
                evidence_items=(),
                verifications=(),
            )
        )


def test_claim_evidence_repository_version_must_match() -> None:
    active_task = task()
    other_version = RepositoryVersion(
        repository_id=repository_version().repository_id,
        branch="other",
        commit_sha="def5678",
    )
    wrong_evidence = evidence(repo=other_version)
    active_claim = claim(active_task, wrong_evidence)

    with pytest.raises(InvariantViolation, match="evidence belongs"):
        validate_snapshot(
            snapshot(
                active_task=active_task,
                claims=(active_claim,),
                evidence_items=(wrong_evidence,),
                verifications=(verification(active_claim, wrong_evidence),),
            )
        )


def test_verified_claim_requires_successful_verification() -> None:
    active_task = task()
    item = evidence()
    active_claim = claim(active_task, item)

    with pytest.raises(InvariantViolation, match="successful persisted verification"):
        validate_snapshot(
            snapshot(
                active_task=active_task,
                claims=(active_claim,),
                evidence_items=(item,),
                verifications=(),
            )
        )


def test_verified_claim_and_verifier_share_supporting_evidence() -> None:
    active_task = task()
    item = evidence()
    other = evidence()
    active_claim = claim(active_task, item)
    wrong_verification = verification(active_claim, other)

    with pytest.raises(InvariantViolation, match="shared supporting evidence"):
        validate_snapshot(
            snapshot(
                active_task=active_task,
                claims=(active_claim,),
                evidence_items=(item, other),
                verifications=(wrong_verification,),
            )
        )


def test_contradicted_claim_requires_matching_contradiction() -> None:
    active_task = task()
    item = evidence()
    active_claim = claim(
        active_task,
        item,
        state=EpistemicState.CONTRADICTED,
        relation=EvidenceRelation.CONTRADICTS,
    )

    with pytest.raises(InvariantViolation, match="persisted contradiction"):
        validate_snapshot(
            snapshot(
                active_task=active_task,
                claims=(active_claim,),
                evidence_items=(item,),
                verifications=(verification(active_claim, item),),
            )
        )


def test_contradicted_claim_and_verifier_share_evidence() -> None:
    active_task = task()
    item = evidence()
    other = evidence()
    active_claim = claim(
        active_task,
        item,
        state=EpistemicState.CONTRADICTED,
        relation=EvidenceRelation.CONTRADICTS,
    )
    wrong_verification = verification(
        active_claim,
        other,
        result=VerificationResult.CONTRADICTED,
    )

    with pytest.raises(InvariantViolation, match="shared contradicting evidence"):
        validate_snapshot(
            snapshot(
                active_task=active_task,
                claims=(active_claim,),
                evidence_items=(item, other),
                verifications=(wrong_verification,),
            )
        )


def test_valid_contradiction_passes() -> None:
    active_task = task()
    item = evidence()
    active_claim = claim(
        active_task,
        item,
        state=EpistemicState.CONTRADICTED,
        relation=EvidenceRelation.CONTRADICTS,
    )
    result = verification(active_claim, item, result=VerificationResult.CONTRADICTED)

    validate_snapshot(
        snapshot(
            active_task=active_task,
            claims=(active_claim,),
            evidence_items=(item,),
            verifications=(result,),
        )
    )


def test_newest_verification_controls_state() -> None:
    active_task = task()
    item = evidence()
    active_claim = claim(active_task, item)
    old_error = verification(
        active_claim,
        item,
        result=VerificationResult.ERROR,
        executed_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    latest_success = verification(
        active_claim,
        item,
        result=VerificationResult.VERIFIED,
        executed_at=NOW,
    )

    validate_snapshot(
        snapshot(
            active_task=active_task,
            claims=(active_claim,),
            evidence_items=(item,),
            verifications=(latest_success, old_error),
        )
    )


def test_newer_error_prevents_old_success_from_certifying_claim() -> None:
    active_task = task()
    item = evidence()
    active_claim = claim(active_task, item)
    old_success = verification(active_claim, item, executed_at=NOW)
    latest_error = verification(
        active_claim,
        item,
        result=VerificationResult.ERROR,
        executed_at=NOW + timedelta(seconds=1),
    )

    with pytest.raises(InvariantViolation, match="successful persisted verification"):
        validate_snapshot(
            snapshot(
                active_task=active_task,
                claims=(active_claim,),
                evidence_items=(item,),
                verifications=(old_success, latest_error),
            )
        )


def test_verification_cannot_reference_unknown_claim() -> None:
    active_task = task()
    item = evidence()
    active_claim = claim(active_task, item, state=EpistemicState.OBSERVED)
    foreign_claim = active_claim.model_copy(update={"id": uuid4()})
    foreign_verification = verification(foreign_claim, item)

    with pytest.raises(InvariantViolation, match="claim outside"):
        validate_snapshot(
            snapshot(
                active_task=active_task,
                claims=(active_claim,),
                evidence_items=(item,),
                verifications=(foreign_verification,),
            )
        )


def test_verification_cannot_reference_unknown_evidence() -> None:
    active_task = task()
    item = evidence()
    other = evidence()
    active_claim = claim(active_task, item, state=EpistemicState.OBSERVED)
    result = verification(active_claim, other)

    with pytest.raises(InvariantViolation, match="evidence outside"):
        validate_snapshot(
            snapshot(
                active_task=active_task,
                claims=(active_claim,),
                evidence_items=(item,),
                verifications=(result,),
            )
        )


def test_edge_endpoints_must_be_inside_snapshot() -> None:
    current = snapshot()
    edge = ContextEdge(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        created_by=current.task.created_by,
        from_type="task",
        from_id=current.task.id,
        edge_type=EdgeType.NEXT_STEP,
        to_type="claim",
        to_id=uuid4(),
    )

    with pytest.raises(InvariantViolation, match="edge endpoint"):
        validate_snapshot(current.model_copy(update={"edges": (edge,)}))


def test_edge_provenance_must_be_inside_snapshot() -> None:
    current = snapshot()
    edge = ContextEdge(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        created_by=current.task.created_by,
        from_type="task",
        from_id=current.task.id,
        edge_type=EdgeType.DEPENDS_ON,
        to_type="claim",
        to_id=current.claims[0].id,
        source_evidence_id=uuid4(),
    )

    with pytest.raises(InvariantViolation, match="edge provenance"):
        validate_snapshot(current.model_copy(update={"edges": (edge,)}))


def test_valid_edge_passes() -> None:
    current = snapshot()
    edge = ContextEdge(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        created_by=current.task.created_by,
        from_type="task",
        from_id=current.task.id,
        edge_type=EdgeType.DEPENDS_ON,
        to_type="claim",
        to_id=current.claims[0].id,
        source_evidence_id=current.evidence[0].id,
    )

    validate_snapshot(current.model_copy(update={"edges": (edge,)}))
