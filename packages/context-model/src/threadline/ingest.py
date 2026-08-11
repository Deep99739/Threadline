"""Manifest-driven Git ingestion into a validated Threadline context snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from threadline.git_repository import (
    GitSnapshot,
    evidence_from_git_file,
    read_git_snapshot,
)
from threadline.manifest import (
    IdempotencyVerifierManifest,
    ProjectManifest,
    PythonCallPathVerifierManifest,
    PythonSymbolVerifierManifest,
    TestReportVerifierManifest,
    VerifierManifest,
    manifest_from_git_snapshot,
)
from threadline.models import (
    Constraint,
    ContextEdge,
    ContextSnapshot,
    Decision,
    EdgeType,
    Evidence,
    Observation,
    Task,
    utc_now,
)
from threadline.storage import ThreadlineStore
from threadline.verifiers import (
    ClaimVerifier,
    IdempotencyBehaviorVerifier,
    PythonCallPathVerifier,
    PythonSymbolExistsVerifier,
    TestReportScopeVerifier,
    VerificationContext,
)


@dataclass(frozen=True)
class IngestionResult:
    snapshot: ContextSnapshot
    git_snapshot: GitSnapshot


def _required_evidence(
    evidence_by_path: dict[str, Evidence], path: str
) -> Evidence:
    if path not in evidence_by_path:
        raise ValueError(f"manifest evidence is missing from the committed snapshot: {path}")
    return evidence_by_path[path]


def _verifier(specification: VerifierManifest) -> ClaimVerifier:
    if isinstance(specification, PythonSymbolVerifierManifest):
        return PythonSymbolExistsVerifier(specification.path, specification.symbol)
    if isinstance(specification, PythonCallPathVerifierManifest):
        return PythonCallPathVerifier(
            specification.path,
            specification.caller,
            specification.referenced_symbol,
        )
    if isinstance(specification, TestReportVerifierManifest):
        return TestReportScopeVerifier(specification.path)
    if isinstance(specification, IdempotencyVerifierManifest):
        return IdempotencyBehaviorVerifier(
            specification.code_path,
            specification.decision_path,
            specification.integration_test_path,
            specification.test_report_path,
        )
    raise TypeError(f"unsupported verifier manifest: {type(specification).__name__}")


def ingest_local_repository(
    store: ThreadlineStore,
    *,
    path: Path,
    tenant_id: UUID,
    workspace_id: UUID,
    actor_id: UUID,
    repository_id: UUID,
) -> IngestionResult:
    git_snapshot = read_git_snapshot(path, repository_id)
    manifest: ProjectManifest = manifest_from_git_snapshot(git_snapshot)
    file_by_path = {item.path: item for item in git_snapshot.files}
    evidence_by_path = {
        item.path: evidence_from_git_file(
            item,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            repository_version=git_snapshot.repository_version,
        )
        for item in git_snapshot.files
    }
    manifest_evidence = evidence_by_path["threadline.json"]
    task = Task(
        id=manifest.task.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        created_by=actor_id,
        repository_version=git_snapshot.repository_version,
        objective=manifest.task.objective,
        status=manifest.task.status,
        owner_actor_id=actor_id,
        next_action=manifest.task.next_action,
        evidence_ids=(manifest_evidence.id,),
    )

    decisions = tuple(
        Decision(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            created_by=actor_id,
            repository_version=git_snapshot.repository_version,
            task_id=task.id,
            decision_key=item.key,
            status=item.status,
            statement=item.statement,
            rationale=item.rationale,
            rejected_alternatives=item.rejected_alternatives,
            approved_by=item.approved_by,
            evidence_ids=(_required_evidence(evidence_by_path, item.source_path).id,),
        )
        for item in manifest.decisions
    )
    constraints = tuple(
        Constraint(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            created_by=actor_id,
            repository_version=git_snapshot.repository_version,
            task_id=task.id,
            constraint_key=item.key,
            statement=item.statement,
            severity=item.severity,
            approved_by=item.approved_by,
            evidence_ids=(_required_evidence(evidence_by_path, item.source_path).id,),
        )
        for item in manifest.constraints
    )

    observations = tuple(
        Observation(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            created_by=actor_id,
            repository_version=git_snapshot.repository_version,
            task_id=task.id,
            session_id=actor_id,
            actor_type=item.actor_type,
            statement=item.statement,
            epistemic_state=item.state,
            observed_at=utc_now(),
            source_evidence_id=_required_evidence(evidence_by_path, item.source_path).id,
        )
        for item in manifest.observations
    )

    verification_context = VerificationContext(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        task_id=task.id,
        repository_version=git_snapshot.repository_version,
        files=file_by_path,
        evidence_by_path=evidence_by_path,
    )
    verified_claims = tuple(
        verifier.verify(verification_context)
        for verifier in (_verifier(item) for item in manifest.verifiers)
    )
    claims = tuple(item.claim for item in verified_claims)
    verifications = tuple(
        item.verification for item in verified_claims if item.verification is not None
    )

    edges: list[ContextEdge] = []
    for claim in claims:
        edges.append(
            ContextEdge(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                created_by=actor_id,
                from_type="task",
                from_id=task.id,
                edge_type=EdgeType.DEPENDS_ON,
                to_type="claim",
                to_id=claim.id,
            )
        )
        for link in claim.evidence:
            edges.append(
                ContextEdge(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    created_by=actor_id,
                    from_type="claim",
                    from_id=claim.id,
                    edge_type=(
                        EdgeType.SUPPORTS
                        if link.relation.value == "SUPPORTS"
                        else EdgeType.CONTRADICTS
                    ),
                    to_type="evidence",
                    to_id=link.evidence_id,
                    source_evidence_id=link.evidence_id,
                )
            )
    for verification in verifications:
        edges.append(
            ContextEdge(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                created_by=actor_id,
                from_type="claim",
                from_id=verification.claim_id,
                edge_type=EdgeType.VERIFIED_BY,
                to_type="verification",
                to_id=verification.id,
                source_evidence_id=verification.evidence_ids[0],
            )
        )

    snapshot = ContextSnapshot(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        repository_version=git_snapshot.repository_version,
        task=task,
        claims=claims,
        evidence=tuple(evidence_by_path.values()),
        verifications=verifications,
        decisions=decisions,
        constraints=constraints,
        observations=observations,
        edges=tuple(edges),
    )
    store.save_repository(
        repository_id=repository_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        name=git_snapshot.name,
        path=str(git_snapshot.root),
        branch=git_snapshot.repository_version.branch,
        head_commit=git_snapshot.repository_version.commit_sha,
    )
    store.save_snapshot(
        snapshot,
        evidence_content={
            evidence_by_path[path].id: git_file.content for path, git_file in file_by_path.items()
        },
    )
    return IngestionResult(snapshot=snapshot, git_snapshot=git_snapshot)
