"""Local Git ingestion into a validated Threadline context snapshot."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from threadline.git_repository import (
    GitSnapshot,
    evidence_from_git_file,
    read_git_snapshot,
)
from threadline.models import (
    ActorType,
    Constraint,
    ContextEdge,
    ContextSnapshot,
    Decision,
    EdgeType,
    EpistemicState,
    Observation,
    Task,
    utc_now,
)
from threadline.storage import ThreadlineStore
from threadline.verifiers import (
    IdempotencyBehaviorVerifier,
    PythonCallPathVerifier,
    PythonSymbolExistsVerifier,
    TestReportScopeVerifier,
    VerificationContext,
)

TASK_PATH = "threadline/task.json"
DECISION_PATH = "threadline/decision.json"
OBSERVATIONS_PATH = "threadline/observations.json"
TEST_REPORT_PATH = "threadline/test-report.json"
CODE_PATH = "src/job_runner.py"


@dataclass(frozen=True)
class IngestionResult:
    snapshot: ContextSnapshot
    git_snapshot: GitSnapshot


def _required_file(git_snapshot: GitSnapshot, path: str) -> str:
    file_by_path = {item.path: item for item in git_snapshot.files}
    if path not in file_by_path:
        raise ValueError(f"required demo evidence is missing: {path}")
    return file_by_path[path].content


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
    task_data = json.loads(_required_file(git_snapshot, TASK_PATH))
    task = Task(
        id=UUID(task_data["task_id"]),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        created_by=actor_id,
        repository_version=git_snapshot.repository_version,
        objective=task_data["objective"],
        status=task_data["status"],
        owner_actor_id=actor_id,
    )

    decision_data = json.loads(_required_file(git_snapshot, DECISION_PATH))
    decision = Decision(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        created_by=actor_id,
        repository_version=git_snapshot.repository_version,
        task_id=task.id,
        decision_key=decision_data["decision_key"],
        status=decision_data["status"],
        statement=decision_data["statement"],
        rationale=decision_data["rationale"],
        rejected_alternatives=(decision_data["rejected_alternative"],),
        approved_by=UUID(decision_data["approved_by"]),
        evidence_ids=(evidence_by_path[DECISION_PATH].id,),
    )
    constraint = Constraint(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        created_by=actor_id,
        repository_version=git_snapshot.repository_version,
        task_id=task.id,
        constraint_key="retry-idempotency",
        statement=decision_data["statement"],
        severity="HIGH",
        approved_by=UUID(decision_data["approved_by"]),
        evidence_ids=(evidence_by_path[DECISION_PATH].id,),
    )

    observation_data = json.loads(_required_file(git_snapshot, OBSERVATIONS_PATH))
    observations = tuple(
        Observation(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            created_by=actor_id,
            repository_version=git_snapshot.repository_version,
            task_id=task.id,
            session_id=actor_id,
            actor_type=(ActorType.AGENT if item["actor_type"] == "AGENT" else ActorType.SERVICE),
            statement=item["statement"],
            epistemic_state=EpistemicState(item["state"]),
            observed_at=utc_now(),
            source_evidence_id=evidence_by_path[OBSERVATIONS_PATH].id,
        )
        for item in observation_data
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
        for verifier in (
            PythonSymbolExistsVerifier(CODE_PATH, "RetryPolicy"),
            PythonCallPathVerifier(CODE_PATH, "run_job", "RetryPolicy"),
            TestReportScopeVerifier(TEST_REPORT_PATH),
            IdempotencyBehaviorVerifier(
                CODE_PATH,
                DECISION_PATH,
                "tests/test_retry_policy.py",
                TEST_REPORT_PATH,
            ),
        )
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
        decisions=(decision,),
        constraints=(constraint,),
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
