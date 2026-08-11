from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from threadline.models import (
    Citation,
    ContextChangeType,
    ContextItem,
    ContextPack,
    EpistemicState,
    EvidenceLocator,
    RepositoryVersion,
)
from threadline.semantic_diff import compare_context_versions

TENANT_ID = UUID("71000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("71000000-0000-4000-8000-000000000002")
TASK_ID = UUID("71000000-0000-4000-8000-000000000003")
REPOSITORY_ID = UUID("71000000-0000-4000-8000-000000000004")
SHA256 = "sha256:" + "b" * 64


def _repository(commit: str) -> RepositoryVersion:
    return RepositoryVersion(repository_id=REPOSITORY_ID, branch="main", commit_sha=commit)


def _item(
    logical_key: str,
    *,
    statement: str = "run_job references RetryPolicy",
    state: EpistemicState = EpistemicState.VERIFIED,
) -> ContextItem:
    return ContextItem(
        logical_key=logical_key,
        entity_type="claim",
        entity_id=uuid4(),
        statement=statement,
        epistemic_state=state,
        selection_reason="Selected by deterministic lexical relevance.",
        authority_reason="GIT_FILE is tier 1 for implementation claims.",
        citations=(
            Citation(
                evidence_id=uuid4(),
                locator=EvidenceLocator(
                    uri="repo://demo/src/job_runner.py",
                    content_hash=SHA256,
                    line_start=1,
                    line_end=4,
                ),
            ),
        ),
    )


def _pack(
    context_version_id: UUID,
    commit: str,
    items: tuple[ContextItem, ...],
    *,
    tenant_id: UUID = TENANT_ID,
    workspace_id: UUID = WORKSPACE_ID,
    task_id: UUID = TASK_ID,
) -> dict[str, object]:
    pack = ContextPack(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        repository_version=_repository(commit),
        context_version_id=context_version_id,
        config_version="lexical-precedence.v2",
        purpose="continue_task",
        token_budget=2048,
        items=items,
    )
    return {"context_pack": pack.model_dump(mode="json")}


def test_semantic_diff_ignores_volatile_storage_and_request_identifiers() -> None:
    base = _pack(uuid4(), "abc1234", (_item("claim:run_job:references:RetryPolicy"),))
    target = _pack(uuid4(), "def5678", (_item("claim:run_job:references:RetryPolicy"),))

    result = compare_context_versions(base, target)

    assert result.changes == ()
    assert result.base_repository_version.commit_sha == "abc1234"
    assert result.target_repository_version.commit_sha == "def5678"


def test_semantic_diff_reports_added_and_removed_logical_items() -> None:
    base = _pack(uuid4(), "abc1234", (_item("claim:removed:value"),))
    target = _pack(uuid4(), "def5678", (_item("claim:added:value"),))

    result = compare_context_versions(base, target)

    assert [(item.logical_key, item.change_type) for item in result.changes] == [
        ("claim:added:value", ContextChangeType.ADDED),
        ("claim:removed:value", ContextChangeType.REMOVED),
    ]


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (EpistemicState.VERIFIED, ContextChangeType.CHANGED),
        (EpistemicState.STALE, ContextChangeType.STALE),
        (EpistemicState.CONTRADICTED, ContextChangeType.CONTRADICTED),
        (EpistemicState.SUPERSEDED, ContextChangeType.SUPERSEDED),
    ],
)
def test_semantic_diff_classifies_material_state_transitions(
    state: EpistemicState,
    expected: ContextChangeType,
) -> None:
    logical_key = "claim:run_job:references:RetryPolicy"
    base = _pack(uuid4(), "abc1234", (_item(logical_key, state=EpistemicState.ASSERTED),))
    target = _pack(uuid4(), "def5678", (_item(logical_key, state=state),))

    result = compare_context_versions(base, target)

    assert result.changes[0].change_type is expected
    assert "Epistemic state changed" in result.changes[0].reasons[0]


def test_semantic_diff_rejects_cross_scope_and_cross_task_comparisons() -> None:
    base = _pack(uuid4(), "abc1234", ())
    foreign_scope = _pack(uuid4(), "def5678", (), workspace_id=uuid4())
    foreign_task = _pack(uuid4(), "def5678", (), task_id=uuid4())

    with pytest.raises(PermissionError, match="authorized scope"):
        compare_context_versions(base, foreign_scope)
    with pytest.raises(ValueError, match="same task"):
        compare_context_versions(base, foreign_task)


def test_semantic_diff_requires_compiled_context_packs() -> None:
    with pytest.raises(ValueError, match="missing its context pack"):
        compare_context_versions({}, {})
