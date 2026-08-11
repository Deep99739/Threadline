"""Prove the seeded demo through a real stdio MCP client session."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from threadline.cli import DEFAULT_DATABASE_URL
from threadline.demo import DEMO_TASK_ID, DEMO_TENANT_ID, DEMO_WORKSPACE_ID
from threadline.storage import ThreadlineStore

ROOT = Path(__file__).resolve().parents[1]


async def verify() -> None:
    database_url = os.getenv("THREADLINE_DATABASE_URL") or DEFAULT_DATABASE_URL
    store = ThreadlineStore(database_url)
    try:
        snapshot = store.load_snapshot(
            tenant_id=DEMO_TENANT_ID,
            workspace_id=DEMO_WORKSPACE_ID,
            task_id=DEMO_TASK_ID,
        )
    finally:
        store.close()

    version = snapshot.repository_version
    parameters = StdioServerParameters(
        command=str(ROOT / ".venv" / "bin" / "threadline"),
        args=["mcp", "--database-url", database_url],
        cwd=ROOT,
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        tool_names = {tool.name for tool in tools.tools}
        expected_tools = {
            "explain_context_selection",
            "get_evidence",
            "get_task_context",
            "list_stale_context",
            "trace_decision",
        }
        if tool_names != expected_tools:
            raise RuntimeError(f"MCP tool mismatch: {sorted(tool_names)}")
        if not all(tool.annotations and tool.annotations.read_only_hint for tool in tools.tools):
            raise RuntimeError("Every local MCP tool must declare itself read-only")

        result = await session.call_tool(
            "get_task_context",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": version.branch,
                "commit_sha": version.commit_sha,
            },
        )
        if result.is_error or result.structured_content is None:
            raise RuntimeError("MCP task-context call failed")
        content = result.structured_content
        if content["status"] != "partial":
            raise RuntimeError("The unfinished fixture must produce a partial handoff")
        if not content["citations"] or not content["unknowns"] or not content["conflicts"]:
            raise RuntimeError("The handoff must preserve citations, unknowns, and conflicts")
        if content["repository"]["commit"] != version.commit_sha:
            raise RuntimeError("The MCP response is not bound to the active commit")

    print(
        "MCP proof passes: real stdio client, 5 read-only tools, exact commit, "
        "cited partial handoff."
    )


def main() -> None:
    asyncio.run(verify())


if __name__ == "__main__":
    main()
