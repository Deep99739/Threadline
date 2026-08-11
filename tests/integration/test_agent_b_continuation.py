from __future__ import annotations

from pathlib import Path

import pytest
from mcp import Client

from threadline.demo import (
    DEMO_ACTOR_ID,
    DEMO_REPOSITORY_ID,
    DEMO_TENANT_ID,
    DEMO_WORKSPACE_ID,
    run_demo,
)
from threadline.demo_continuation import run_agent_b_continuation
from threadline.mcp_server import create_mcp_server
from threadline.service import ServiceScope
from threadline.storage import ThreadlineStore


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_agent_b_continues_through_mcp_and_stale_handoff_is_refused(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'continuation.db'}"
    repository = tmp_path / "demo-repository"
    seeded = run_demo(database_url, repository)
    store = ThreadlineStore(database_url)
    scope = ServiceScope(
        tenant_id=DEMO_TENANT_ID,
        workspace_id=DEMO_WORKSPACE_ID,
        actor_id=DEMO_ACTOR_ID,
        repository_id=DEMO_REPOSITORY_ID,
    )
    try:
        proof = await run_agent_b_continuation(
            store=store,
            scope=scope,
            repository_path=repository,
        )
        async with Client(
            create_mcp_server(store, scope, seeded.handoff.context_pack.task_id, repository)
        ) as client:
            diff_result = await client.call_tool(
                "compare_context_versions",
                {
                    "task_id": str(seeded.handoff.context_pack.task_id),
                    "branch": seeded.handoff.context_pack.repository_version.branch,
                    "commit_sha": proof.resulting_commit,
                    "base_context_version_id": str(seeded.handoff.context_version.id),
                    "target_context_version_id": str(proof.final_context_version_id),
                },
            )
    finally:
        store.close()

    assert proof.initial_commit == seeded.handoff.context_pack.repository_version.commit_sha
    assert proof.resulting_commit != proof.initial_commit
    assert proof.cited_evidence_count >= 3
    assert proof.live_drift_refused_before_ingest is True
    assert proof.stale_handoff_refused is True
    assert proof.stale_items
    assert any(
        any(str(source).endswith("/src/job_runner.py") for source in item["changed_sources"])
        for item in proof.stale_items
    )
    assert proof.final_status == "ok"
    assert "run_job references:RetryPolicy" in proof.verified_completed_work
    assert "run_job retries_preserve_original_idempotency_key" in proof.verified_completed_work
    assert "2 passed" in proof.test_output
    diff_payload = diff_result.structured_content
    assert isinstance(diff_payload, dict)
    assert diff_payload["status"] == "ok"
    changes = diff_payload["data"]["changes"]
    retry_change = next(
        item for item in changes if item["logical_key"] == "claim:run_job:references:RetryPolicy"
    )
    assert retry_change["change_type"] == "CHANGED"
    assert any(
        "CONTRADICTED to VERIFIED" in reason for reason in retry_change["reasons"]
    )
