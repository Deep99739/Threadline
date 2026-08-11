from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from threadline.models import (
    ActorType,
    Claim,
    ClaimType,
    ContextEdge,
    ContextSnapshot,
    Decision,
    EpistemicState,
    Evidence,
    EvidenceLink,
    EvidenceLocator,
    EvidenceRelation,
    Observation,
    RepositoryVersion,
    Task,
    Verification,
    VerificationResult,
    VerifierKind,
)

NOW = datetime(2026, 8, 11, tzinfo=UTC)
TENANT = UUID("30000000-0000-4000-8000-000000000001")
WORKSPACE = UUID("30000000-0000-4000-8000-000000000002")
ACTOR = UUID("30000000-0000-4000-8000-000000000003")
REPOSITORY = UUID("30000000-0000-4000-8000-000000000004")
SHA256 = "sha256:" + "a" * 64


def repository_version(commit: str = "abc1234") -> RepositoryVersion:
    return RepositoryVersion(repository_id=REPOSITORY, branch="feature/retry", commit_sha=commit)


def task(*, tenant_id: UUID = TENANT, repo: RepositoryVersion | None = None) -> Task:
    return Task(
        tenant_id=tenant_id,
        workspace_id=WORKSPACE,
        created_by=ACTOR,
        repository_version=repo or repository_version(),
        objective="Add safe retries",
        status="IN_PROGRESS",
        owner_actor_id=ACTOR,
    )


def evidence(*, tenant_id: UUID = TENANT, repo: RepositoryVersion | None = None) -> Evidence:
    return Evidence(
        tenant_id=tenant_id,
        workspace_id=WORKSPACE,
        created_by=ACTOR,
        repository_version=repo or repository_version(),
        evidence_type="SOURCE",
        locator=EvidenceLocator(uri="repo://demo/src/job_runner.py", content_hash=SHA256),
        captured_at=NOW,
    )


def claim(
    active_task: Task,
    item: Evidence,
    *,
    state: EpistemicState = EpistemicState.VERIFIED,
    relation: EvidenceRelation = EvidenceRelation.SUPPORTS,
    repo: RepositoryVersion | None = None,
) -> Claim:
    return Claim(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        created_by=ACTOR,
        repository_version=repo or repository_version(),
        task_id=active_task.id,
        claim_type=ClaimType.IMPLEMENTATION,
        subject_key="RetryPolicy",
        predicate="exists",
        value=True,
        epistemic_state=state,
        evidence=(EvidenceLink(evidence_id=item.id, relation=relation),),
        freshness_rule="invalidate_on_symbol_change",
    )


def verification(
    active_claim: Claim,
    item: Evidence,
    *,
    result: VerificationResult = VerificationResult.VERIFIED,
    executed_at: datetime = NOW,
) -> Verification:
    return Verification(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        created_by=ACTOR,
        claim_id=active_claim.id,
        verifier_key="symbol_exists",
        verifier_version="1.0.0",
        verifier_kind=VerifierKind.DETERMINISTIC,
        input_hash=SHA256,
        result=result,
        evidence_ids=(item.id,),
        executed_at=executed_at,
    )


def snapshot(
    *,
    active_task: Task | None = None,
    claims: tuple[Claim, ...] | None = None,
    evidence_items: tuple[Evidence, ...] | None = None,
    verifications: tuple[Verification, ...] | None = None,
    edges: tuple[ContextEdge, ...] = (),
    repo: RepositoryVersion | None = None,
) -> ContextSnapshot:
    version = repo or repository_version()
    current_task = active_task or task(repo=version)
    current_evidence = evidence_items if evidence_items is not None else (evidence(repo=version),)
    current_claims = (
        claims if claims is not None else (claim(current_task, current_evidence[0], repo=version),)
    )
    current_verifications = (
        verifications
        if verifications is not None
        else (verification(current_claims[0], current_evidence[0]),)
    )
    return ContextSnapshot(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        repository_version=version,
        task=current_task,
        claims=current_claims,
        evidence=current_evidence,
        verifications=current_verifications,
        edges=edges,
    )


def test_repository_version_rejects_ambiguous_commit() -> None:
    with pytest.raises(ValidationError, match="commit_sha"):
        RepositoryVersion(repository_id=REPOSITORY, branch="main", commit_sha="latest")


def test_evidence_locator_rejects_invalid_ranges() -> None:
    with pytest.raises(ValidationError, match="line_start is required"):
        EvidenceLocator(uri="repo://demo/file.py", content_hash=SHA256, line_end=2)

    with pytest.raises(ValidationError, match="line_end must be"):
        EvidenceLocator(uri="repo://demo/file.py", content_hash=SHA256, line_start=4, line_end=2)


def test_verification_success_requires_evidence() -> None:
    active_task = task()
    item = evidence()
    active_claim = claim(active_task, item)

    with pytest.raises(ValidationError, match="require evidence"):
        Verification(
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            created_by=ACTOR,
            claim_id=active_claim.id,
            verifier_key="symbol_exists",
            verifier_version="1.0.0",
            verifier_kind=VerifierKind.DETERMINISTIC,
            input_hash=SHA256,
            result=VerificationResult.VERIFIED,
            evidence_ids=(),
            executed_at=NOW,
        )


def test_nonconclusive_verification_can_have_no_evidence() -> None:
    active_task = task()
    item = evidence()
    active_claim = claim(active_task, item, state=EpistemicState.UNKNOWN)

    result = Verification(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        created_by=ACTOR,
        claim_id=active_claim.id,
        verifier_key="runtime_observation",
        verifier_version="1.0.0",
        verifier_kind=VerifierKind.DETERMINISTIC,
        input_hash=SHA256,
        result=VerificationResult.INSUFFICIENT_EVIDENCE,
        evidence_ids=(),
        executed_at=NOW,
    )

    assert result.result is VerificationResult.INSUFFICIENT_EVIDENCE


def test_published_evidence_is_immutable() -> None:
    item = evidence()

    with pytest.raises(ValidationError, match="frozen"):
        item.sensitivity = "PUBLIC"  # type: ignore[misc]


def test_strict_contract_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        RepositoryVersion.model_validate(
            {
                "repository_id": str(REPOSITORY),
                "branch": "main",
                "commit_sha": "abc1234",
                "latest": True,
            }
        )


def test_decision_and_observation_preserve_authority_metadata() -> None:
    version = repository_version()
    active_task = task(repo=version)
    decision = Decision(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        created_by=ACTOR,
        repository_version=version,
        task_id=active_task.id,
        decision_key="retry-idempotency-v1",
        status="APPROVED",
        statement="Reuse the original idempotency key.",
        rationale="Prevent duplicate side effects.",
        approved_by=ACTOR,
    )
    observation = Observation(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        created_by=ACTOR,
        repository_version=version,
        task_id=active_task.id,
        session_id=UUID("30000000-0000-4000-8000-000000000099"),
        actor_type=ActorType.AGENT,
        statement="All tests pass.",
        observed_at=NOW,
    )

    assert decision.approved_by == ACTOR
    assert observation.actor_type is ActorType.AGENT


def test_snapshot_builder_creates_valid_shape() -> None:
    current = snapshot()

    assert current.task.repository_version == current.repository_version
    assert current.claims[0].task_id == current.task.id
