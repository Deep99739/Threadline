"""Manifest-driven Git ingestion into a validated Threadline context snapshot."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid5

from threadline.code_graph import CODE_GRAPH_NAMESPACE, extract_code_graph
from threadline.evidence_safety import path_is_excluded, safe_git_file
from threadline.git_repository import (
    GitSnapshot,
    evidence_from_git_file,
    read_committed_content_hashes,
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


INGEST_ENTITY_NAMESPACE = UUID("1d508ff0-b19b-4ab2-a923-3eaf121f296c")


def _entity_id(
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    repository_id: UUID,
    branch: str,
    commit_sha: str,
    task_id: UUID,
    entity_type: str,
    logical_key: str,
) -> UUID:
    """Return one stable identity for an entity in an exact repository snapshot."""

    return uuid5(
        INGEST_ENTITY_NAMESPACE,
        ":".join(
            (
                str(tenant_id),
                str(workspace_id),
                str(repository_id),
                branch,
                commit_sha,
                str(task_id),
                entity_type,
                logical_key,
            )
        ),
    )


def _edge_id(
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    repository_id: UUID,
    branch: str,
    commit_sha: str,
    task_id: UUID,
    from_type: str,
    from_id: UUID,
    edge_type: EdgeType,
    to_type: str,
    to_id: UUID,
    source_evidence_id: UUID | None,
) -> UUID:
    return _entity_id(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        repository_id=repository_id,
        branch=branch,
        commit_sha=commit_sha,
        task_id=task_id,
        entity_type="edge",
        logical_key=":".join(
            (
                from_type,
                str(from_id),
                edge_type.value,
                to_type,
                str(to_id),
                str(source_evidence_id or "none"),
            )
        ),
    )


def _required_evidence(evidence_by_path: dict[str, Evidence], path: str) -> Evidence:
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
    scoped_files = tuple(
        item
        for item in git_snapshot.files
        if item.path == "threadline.json"
        or not path_is_excluded(item.path, manifest.evidence_exclusions)
    )
    file_by_path = {item.path: item for item in scoped_files}
    safe_content_by_path = {item.path: safe_git_file(item) for item in scoped_files}
    evidence_by_path: dict[str, Evidence] = {}
    for item in scoped_files:
        evidence = evidence_from_git_file(
            item,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            repository_version=git_snapshot.repository_version,
            sensitivity=("REDACTED" if safe_content_by_path[item.path].redacted else "INTERNAL"),
        )
        evidence_by_path[item.path] = evidence.model_copy(
            update={
                "id": _entity_id(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    repository_id=repository_id,
                    branch=git_snapshot.repository_version.branch,
                    commit_sha=git_snapshot.repository_version.commit_sha,
                    task_id=manifest.task.id,
                    entity_type="evidence",
                    logical_key=f"{item.path}:{item.content_hash}",
                )
            }
        )
    manifest_evidence = evidence_by_path["threadline.json"]
    tested_paths: list[str] = []
    for specification in manifest.verifiers:
        if not isinstance(specification, TestReportVerifierManifest):
            continue
        report_file = file_by_path.get(specification.path)
        if report_file is None:
            continue
        report = json.loads(report_file.content)
        tested_hashes = report.get("tested_content_hashes", {})
        if isinstance(tested_hashes, dict):
            tested_paths.extend(str(item) for item in tested_hashes)
    committed_hashes = {item.path: item.content_hash for item in scoped_files}
    missing_hash_paths = tuple(
        path for path in dict.fromkeys(tested_paths) if path not in committed_hashes
    )
    committed_hashes.update(
        read_committed_content_hashes(
            git_snapshot.root,
            commit_sha=git_snapshot.repository_version.commit_sha,
            relative_paths=missing_hash_paths,
        )
    )
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
            id=_entity_id(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                repository_id=repository_id,
                branch=git_snapshot.repository_version.branch,
                commit_sha=git_snapshot.repository_version.commit_sha,
                task_id=task.id,
                entity_type="decision",
                logical_key=item.key,
            ),
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
            id=_entity_id(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                repository_id=repository_id,
                branch=git_snapshot.repository_version.branch,
                commit_sha=git_snapshot.repository_version.commit_sha,
                task_id=task.id,
                entity_type="constraint",
                logical_key=item.key,
            ),
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
            id=_entity_id(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                repository_id=repository_id,
                branch=git_snapshot.repository_version.branch,
                commit_sha=git_snapshot.repository_version.commit_sha,
                task_id=task.id,
                entity_type="observation",
                logical_key=f"{index}:{item.actor_type}:{item.source_path}:{item.statement}",
            ),
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
        for index, item in enumerate(manifest.observations)
    )

    verification_context = VerificationContext(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        task_id=task.id,
        repository_version=git_snapshot.repository_version,
        files=file_by_path,
        content_hashes=committed_hashes,
        evidence_by_path=evidence_by_path,
    )
    verified_claims_list = []
    for index, specification in enumerate(manifest.verifiers):
        verified = _verifier(specification).verify(verification_context)
        verifier_key = json.dumps(
            specification.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        claim_id = _entity_id(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            repository_id=repository_id,
            branch=git_snapshot.repository_version.branch,
            commit_sha=git_snapshot.repository_version.commit_sha,
            task_id=task.id,
            entity_type="claim",
            logical_key=(
                f"{index}:{verifier_key}:{verified.claim.subject_key}:{verified.claim.predicate}"
            ),
        )
        claim = verified.claim.model_copy(update={"id": claim_id})
        verification = verified.verification
        if verification is not None:
            verification = verification.model_copy(
                update={
                    "id": _entity_id(
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        repository_id=repository_id,
                        branch=git_snapshot.repository_version.branch,
                        commit_sha=git_snapshot.repository_version.commit_sha,
                        task_id=task.id,
                        entity_type="verification",
                        logical_key=(
                            f"{index}:{verification.verifier_key}:"
                            f"{verification.verifier_version}:{verification.input_hash}"
                        ),
                    ),
                    "claim_id": claim_id,
                }
            )
        verified_claims_list.append((claim, verification))
    verified_claims = tuple(verified_claims_list)
    claims = tuple(item[0] for item in verified_claims)
    verifications = tuple(item[1] for item in verified_claims if item[1] is not None)
    code_graph = extract_code_graph(
        scoped_files,
        evidence_by_path,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        task_id=task.id,
        repository_version=git_snapshot.repository_version,
    )

    edges: list[ContextEdge] = []
    for claim in claims:
        edge_type = EdgeType.DEPENDS_ON
        edges.append(
            ContextEdge(
                id=_edge_id(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    repository_id=repository_id,
                    branch=git_snapshot.repository_version.branch,
                    commit_sha=git_snapshot.repository_version.commit_sha,
                    task_id=task.id,
                    from_type="task",
                    from_id=task.id,
                    edge_type=edge_type,
                    to_type="claim",
                    to_id=claim.id,
                    source_evidence_id=None,
                ),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                created_by=actor_id,
                from_type="task",
                from_id=task.id,
                edge_type=edge_type,
                to_type="claim",
                to_id=claim.id,
            )
        )
        for link in claim.evidence:
            edge_type = (
                EdgeType.SUPPORTS if link.relation.value == "SUPPORTS" else EdgeType.CONTRADICTS
            )
            edges.append(
                ContextEdge(
                    id=_edge_id(
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        repository_id=repository_id,
                        branch=git_snapshot.repository_version.branch,
                        commit_sha=git_snapshot.repository_version.commit_sha,
                        task_id=task.id,
                        from_type="claim",
                        from_id=claim.id,
                        edge_type=edge_type,
                        to_type="evidence",
                        to_id=link.evidence_id,
                        source_evidence_id=link.evidence_id,
                    ),
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    created_by=actor_id,
                    from_type="claim",
                    from_id=claim.id,
                    edge_type=edge_type,
                    to_type="evidence",
                    to_id=link.evidence_id,
                    source_evidence_id=link.evidence_id,
                )
            )
    for verification in verifications:
        edge_type = EdgeType.VERIFIED_BY
        edges.append(
            ContextEdge(
                id=_edge_id(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    repository_id=repository_id,
                    branch=git_snapshot.repository_version.branch,
                    commit_sha=git_snapshot.repository_version.commit_sha,
                    task_id=task.id,
                    from_type="claim",
                    from_id=verification.claim_id,
                    edge_type=edge_type,
                    to_type="verification",
                    to_id=verification.id,
                    source_evidence_id=verification.evidence_ids[0],
                ),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                created_by=actor_id,
                from_type="claim",
                from_id=verification.claim_id,
                edge_type=edge_type,
                to_type="verification",
                to_id=verification.id,
                source_evidence_id=verification.evidence_ids[0],
            )
        )
    symbol_by_key = {item.logical_key: item for item in code_graph.symbols}
    for dependency in code_graph.dependencies:
        if dependency.target_symbol_key is None:
            continue
        source = symbol_by_key[dependency.source_symbol_key]
        target = symbol_by_key[dependency.target_symbol_key]
        edges.append(
            ContextEdge(
                id=uuid5(CODE_GRAPH_NAMESPACE, f"edge:{dependency.id}"),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                created_by=actor_id,
                from_type="code_symbol",
                from_id=source.id,
                edge_type=EdgeType(dependency.dependency_kind.value),
                to_type="code_symbol",
                to_id=target.id,
                source_evidence_id=dependency.evidence_id,
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
        code_symbols=code_graph.symbols,
        code_dependencies=code_graph.dependencies,
        code_parse_diagnostics=code_graph.diagnostics,
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
            evidence_by_path[path].id: safe_content_by_path[path].content for path in file_by_path
        },
    )
    return IngestionResult(snapshot=snapshot, git_snapshot=git_snapshot)
