from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from tests.helpers import git, make_demo_repository

from threadline.models import EpistemicState
from threadline.retrieval import lexical_retrieve
from threadline.service import ServiceScope, ThreadlineService
from threadline.storage import ThreadlineStore

TENANT_ID = UUID("50000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("50000000-0000-4000-8000-000000000002")
ACTOR_ID = UUID("50000000-0000-4000-8000-000000000003")
REPOSITORY_ID = UUID("60000000-0000-4000-8000-000000000004")
TASK_ID = UUID("20000000-0000-4000-8000-000000000001")


def service_scope() -> ServiceScope:
    return ServiceScope(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        repository_id=REPOSITORY_ID,
    )


def test_ingest_compile_and_read_cited_handoff(tmp_path: Path) -> None:
    root = make_demo_repository(tmp_path)
    store = ThreadlineStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    service = ThreadlineService(store)

    ingestion = service.ingest(repository_path=root, scope=service_scope())
    claims = {(item.subject_key, item.predicate): item for item in ingestion.snapshot.claims}

    assert claims[("RetryPolicy", "exists_at_commit")].epistemic_state is EpistemicState.VERIFIED
    assert (
        claims[("run_job", "references:RetryPolicy")].epistemic_state is EpistemicState.CONTRADICTED
    )
    assert claims[("test_suite", "all_tests_passed")].epistemic_state is EpistemicState.UNKNOWN
    assert (
        claims[("run_job", "retries_preserve_original_idempotency_key")].epistemic_state
        is EpistemicState.UNKNOWN
    )

    compiled = service.compile_task_handoff(
        scope=service_scope(),
        task_id=TASK_ID,
        query="continue retry work without duplicate side effects",
    )

    assert compiled.context_pack.repository_version.commit_sha == git(root, "rev-parse", "HEAD")
    assert compiled.context_pack.conflicts
    assert compiled.context_pack.unknowns
    assert compiled.content["next_action"] == (
        "Wire RetryPolicy into run_job while reusing the original idempotency key, "
        "then add an integration test and run the complete suite."
    )
    assert compiled.handoff.content_hash.startswith("sha256:")
    constraint_items = [
        item for item in compiled.context_pack.items if item.entity_type == "constraint"
    ]
    assert constraint_items
    assert constraint_items[0].citations[0].locator.uri.endswith("/threadline/decision.json")
    assert service.latest_handoff(scope=service_scope(), task_id=TASK_ID) == compiled.content

    with pytest.raises(PermissionError, match="caller scope"):
        lexical_retrieve(
            ingestion.snapshot,
            tenant_id=uuid4(),
            workspace_id=WORKSPACE_ID,
            query="retry",
        )
    unfiltered = lexical_retrieve(
        ingestion.snapshot,
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        query="",
    )
    assert unfiltered

    evidence_ids = [item.id for item in ingestion.snapshot.evidence]
    evidence_content = store.load_evidence_content(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        evidence_ids=evidence_ids,
    )
    assert evidence_content
    assert any("class RetryPolicy" in value for value in evidence_content.values())
    assert (
        store.load_evidence_content(
            tenant_id=TENANT_ID,
            workspace_id=uuid4(),
            evidence_ids=evidence_ids,
        )
        == {}
    )
    assert (
        store.load_evidence_content(
            tenant_id=TENANT_ID,
            workspace_id=WORKSPACE_ID,
            evidence_ids=[],
        )
        == {}
    )

    store.close()


def test_latest_commit_replaces_active_projection_without_mixing_history(
    tmp_path: Path,
) -> None:
    root = make_demo_repository(tmp_path)
    store = ThreadlineStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    service = ThreadlineService(store)
    first = service.ingest(repository_path=root, scope=service_scope())

    source_path = root / "src" / "job_runner.py"
    source_path.write_text(
        source_path.read_text().replace(
            "return operation(idempotency_key)",
            "return RetryPolicy() and operation(idempotency_key)",
        )
    )
    git(root, "add", "src/job_runner.py")
    git(
        root,
        "-c",
        "user.name=Threadline Test",
        "-c",
        "user.email=threadline@example.invalid",
        "commit",
        "-m",
        "Wire retry policy",
    )
    second = service.ingest(repository_path=root, scope=service_scope())

    loaded = store.load_snapshot(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        task_id=TASK_ID,
    )
    assert first.snapshot.repository_version != second.snapshot.repository_version
    assert loaded.repository_version == second.snapshot.repository_version
    assert len(loaded.claims) == len(second.snapshot.claims)
    assert all(
        item.repository_version == second.snapshot.repository_version for item in loaded.claims
    )
    store.close()


def test_store_rejects_out_of_scope_reads_and_content(tmp_path: Path) -> None:
    root = make_demo_repository(tmp_path)
    store = ThreadlineStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    service = ThreadlineService(store)
    result = service.ingest(repository_path=root, scope=service_scope())

    with pytest.raises(LookupError, match="authorized scope"):
        store.load_snapshot(
            tenant_id=uuid4(),
            workspace_id=WORKSPACE_ID,
            task_id=TASK_ID,
        )
    with pytest.raises(LookupError, match="authorized scope"):
        store.load_snapshot(
            tenant_id=TENANT_ID,
            workspace_id=uuid4(),
            task_id=TASK_ID,
        )
    with pytest.raises(LookupError, match="handoff"):
        service.latest_handoff(scope=service_scope(), task_id=TASK_ID)
    with pytest.raises(ValueError, match="outside the snapshot"):
        store.save_snapshot(result.snapshot, evidence_content={uuid4(): "foreign"})

    store.reset_tenant_for_demo(TENANT_ID)
    with pytest.raises(LookupError, match="authorized scope"):
        store.load_snapshot(
            tenant_id=TENANT_ID,
            workspace_id=WORKSPACE_ID,
            task_id=TASK_ID,
        )
    store.drop_schema_for_test()
    store.close()
