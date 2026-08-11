from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from mcp import Client, ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from tests.helpers import PROJECT_ROOT, git

from threadline.demo import (
    DEMO_ACTOR_ID,
    DEMO_REPOSITORY_ID,
    DEMO_TASK_ID,
    DEMO_TENANT_ID,
    DEMO_WORKSPACE_ID,
    run_demo,
)
from threadline.mcp_server import create_mcp_server
from threadline.service import ServiceScope
from threadline.storage import ThreadlineStore


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_official_client_reads_bound_handoff_and_evidence(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'mcp.db'}"
    seeded = run_demo(database_url, tmp_path / "demo-repository")
    version = seeded.handoff.context_pack.repository_version
    store = ThreadlineStore(database_url)
    scope = ServiceScope(
        tenant_id=DEMO_TENANT_ID,
        workspace_id=DEMO_WORKSPACE_ID,
        actor_id=DEMO_ACTOR_ID,
        repository_id=DEMO_REPOSITORY_ID,
    )

    async with Client(
        create_mcp_server(store, scope, DEMO_TASK_ID, seeded.repository_path)
    ) as client:
        discovered = await client.list_tools()
        assert {tool.name for tool in discovered.tools} == {
            "compare_context_versions",
            "explain_context_selection",
            "get_evidence",
            "get_task_context",
            "get_workspace_status",
            "list_stale_context",
            "trace_code_symbol",
            "trace_decision",
        }
        assert all(
            tool.annotations and tool.annotations.read_only_hint for tool in discovered.tools
        )
        assert all("tenant_id" not in tool.input_schema["properties"] for tool in discovered.tools)

        workspace_result = await client.call_tool("get_workspace_status", {})
        workspace = workspace_result.structured_content
        assert workspace["status"] == "partial"
        assert workspace["data"]["task_id"] == str(DEMO_TASK_ID)
        assert workspace["repository"]["commit"] == version.commit_sha

        foreign_task_result = await client.call_tool(
            "get_task_context",
            {
                "task_id": str(uuid4()),
                "branch": version.branch,
                "commit_sha": version.commit_sha,
            },
        )
        assert foreign_task_result.is_error is True

        context_result = await client.call_tool(
            "get_task_context",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": version.branch,
                "commit_sha": version.commit_sha,
            },
        )
        assert context_result.is_error is False
        context = context_result.structured_content
        assert context["status"] == "partial"
        assert context["repository"]["commit"] == version.commit_sha
        assert context["data"]["next_action"] == seeded.handoff.content["next_action"]
        assert context["citations"]
        assert context["unknowns"]
        assert context["conflicts"]

        stale_result = await client.call_tool(
            "get_task_context",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": version.branch,
                "commit_sha": "deadbee",
            },
        )
        assert stale_result.structured_content["status"] == "abstained"
        assert stale_result.structured_content["data"] == {}

        current_staleness = await client.call_tool(
            "list_stale_context",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": version.branch,
                "commit_sha": version.commit_sha,
            },
        )
        assert current_staleness.structured_content["status"] == "ok"
        assert current_staleness.structured_content["data"]["items"] == []

        graph_result = await client.call_tool(
            "trace_code_symbol",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": version.branch,
                "commit_sha": version.commit_sha,
                "symbol": "src.job_runner.RetryPolicy.delays",
                "max_depth": 1,
                "max_nodes": 10,
            },
        )
        graph = graph_result.structured_content
        assert graph["status"] == "partial"
        assert graph["data"]["root_symbol_key"].endswith("RetryPolicy.delays")
        assert graph["data"]["nodes"]
        assert graph["data"]["unresolved_relationships"]
        assert graph["citations"]

        decision_result = await client.call_tool(
            "trace_decision",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": version.branch,
                "commit_sha": version.commit_sha,
                "decision_key": "retry-idempotency-v1",
            },
        )
        decision = decision_result.structured_content
        assert decision["status"] == "partial"
        assert decision["data"]["state"] == "ASSERTED"
        assert decision["data"]["rejected_alternatives"] == [
            "Generate a new idempotency key for every attempt."
        ]
        assert decision["warnings"]

        missing_decision = await client.call_tool(
            "trace_decision",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": version.branch,
                "commit_sha": version.commit_sha,
                "decision_key": "missing",
            },
        )
        assert missing_decision.structured_content["status"] == "abstained"

        selected = context["data"]["items"][0]
        explanation_result = await client.call_tool(
            "explain_context_selection",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": version.branch,
                "commit_sha": version.commit_sha,
                "entity_id": selected["entity_id"],
            },
        )
        explanation = explanation_result.structured_content
        assert explanation["status"] == "ok"
        assert explanation["data"]["logical_key"]
        assert explanation["data"]["selection_reason"]
        assert explanation["data"]["authority_reason"]
        assert explanation["data"]["ranker_version"] == "lexical-precedence.v2"

        missing_selection = await client.call_tool(
            "explain_context_selection",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": version.branch,
                "commit_sha": version.commit_sha,
                "entity_id": str(uuid4()),
            },
        )
        assert missing_selection.structured_content["status"] == "abstained"

        evidence_id = context["citations"][0]["evidence_id"]
        evidence_result = await client.call_tool(
            "get_evidence",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": version.branch,
                "commit_sha": version.commit_sha,
                "evidence_id": evidence_id,
            },
        )
        evidence = evidence_result.structured_content
        assert evidence["status"] == "ok"
        assert evidence["data"]["content"]

        denied_evidence = await client.call_tool(
            "get_evidence",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": version.branch,
                "commit_sha": version.commit_sha,
                "evidence_id": str(uuid4()),
            },
        )
        assert denied_evidence.structured_content["status"] == "denied"

    store.close()


@pytest.mark.anyio
async def test_live_repository_drift_forces_abstention_until_resync(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'runtime-drift.db'}"
    seeded = run_demo(database_url, tmp_path / "demo-repository")
    version = seeded.handoff.context_pack.repository_version
    store = ThreadlineStore(database_url)
    scope = ServiceScope(
        tenant_id=DEMO_TENANT_ID,
        workspace_id=DEMO_WORKSPACE_ID,
        actor_id=DEMO_ACTOR_ID,
        repository_id=DEMO_REPOSITORY_ID,
    )

    async with Client(
        create_mcp_server(store, scope, DEMO_TASK_ID, seeded.repository_path)
    ) as client:
        source = seeded.repository_path / "src" / "job_runner.py"
        source.write_text(source.read_text() + "\n# uncommitted runtime drift\n")

        dirty_result = await client.call_tool("get_workspace_status", {})
        dirty = dirty_result.structured_content
        assert dirty["status"] == "dirty"
        assert dirty["data"]["handoff_current"] is False
        assert dirty["data"]["working_repository"]["dirty_paths"] == [
            "src/job_runner.py"
        ]

        dirty_context_result = await client.call_tool(
            "get_task_context",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": version.branch,
                "commit_sha": version.commit_sha,
            },
        )
        dirty_context = dirty_context_result.structured_content
        assert dirty_context["status"] == "abstained"
        assert "uncommitted changes" in dirty_context["warnings"][0]

        git(seeded.repository_path, "add", "src/job_runner.py")
        git(
            seeded.repository_path,
            "-c",
            "user.name=Threadline Test",
            "-c",
            "user.email=threadline@example.invalid",
            "commit",
            "-m",
            "Create runtime drift",
        )
        live_commit = git(seeded.repository_path, "rev-parse", "HEAD")
        assert live_commit != version.commit_sha

        stale_result = await client.call_tool("get_workspace_status", {})
        stale = stale_result.structured_content
        assert stale["status"] == "stale"
        assert stale["data"]["handoff_current"] is False
        assert stale["data"]["working_repository"]["commit"] == live_commit
        assert stale["data"]["working_repository"]["dirty_paths"] == []

        stale_context_result = await client.call_tool(
            "get_task_context",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": version.branch,
                "commit_sha": version.commit_sha,
            },
        )
        stale_context = stale_context_result.structured_content
        assert stale_context["status"] == "abstained"
        assert "repository moved" in stale_context["warnings"][0]

    store.close()


@pytest.mark.anyio
async def test_stdio_process_is_consumed_by_real_client_session(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'stdio.db'}"
    seeded = run_demo(database_url, tmp_path / "demo-repository")
    version = seeded.handoff.context_pack.repository_version
    parameters = StdioServerParameters(
        command=str(PROJECT_ROOT / ".venv" / "bin" / "threadline"),
        args=["mcp", "--demo", "--database-url", database_url],
        cwd=PROJECT_ROOT,
    )

    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialized = await session.initialize()
        assert initialized.server_info.name == "Threadline"
        result = await session.call_tool(
            "get_task_context",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": version.branch,
                "commit_sha": version.commit_sha,
            },
        )
        assert result.is_error is False
        assert result.structured_content["repository"]["commit"] == version.commit_sha


@pytest.mark.anyio
async def test_mcp_scope_fails_closed_without_authorized_task(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'isolated.db'}"
    seeded = run_demo(database_url, tmp_path / "demo-repository")
    version = seeded.handoff.context_pack.repository_version
    store = ThreadlineStore(database_url)
    foreign_scope = ServiceScope(
        tenant_id=uuid4(),
        workspace_id=DEMO_WORKSPACE_ID,
        actor_id=DEMO_ACTOR_ID,
        repository_id=DEMO_REPOSITORY_ID,
    )

    async with Client(
        create_mcp_server(store, foreign_scope, DEMO_TASK_ID, seeded.repository_path)
    ) as client:
        result = await client.call_tool(
            "get_task_context",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": version.branch,
                "commit_sha": version.commit_sha,
            },
        )
        assert result.is_error is True
        assert result.structured_content is None

    store.close()
