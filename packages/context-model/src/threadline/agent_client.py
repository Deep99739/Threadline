"""Client-side continuation contract for MCP-capable coding agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from mcp import Client
from mcp.server import MCPServer


@dataclass(frozen=True)
class AgentHandoff:
    status: str
    branch: str
    commit_sha: str
    objective: str
    constraints: tuple[str, ...]
    next_action: str
    citations: tuple[dict[str, Any], ...]
    unknowns: tuple[str, ...]
    conflicts: tuple[str, ...]


async def read_agent_handoff(
    server: MCPServer,
    *,
    task_id: UUID,
    branch: str,
    commit_sha: str,
) -> AgentHandoff:
    """Consume Threadline exactly as an external MCP coding client would."""

    async with Client(server) as client:
        result = await client.call_tool(
            "get_task_context",
            {
                "task_id": str(task_id),
                "branch": branch,
                "commit_sha": commit_sha,
            },
        )
        if result.is_error or not isinstance(result.structured_content, dict):
            raise RuntimeError("Threadline did not return a structured handoff")
        payload = result.structured_content
        status = str(payload.get("status", "abstained"))
        if status not in {"ok", "partial"}:
            warnings = payload.get("warnings", [])
            raise RuntimeError(f"Threadline refused continuation: {warnings}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Threadline handoff has no continuation data")

        citations = payload.get("citations", [])
        return AgentHandoff(
            status=status,
            branch=branch,
            commit_sha=commit_sha,
            objective=str(data["objective"]),
            constraints=tuple(str(item) for item in data.get("constraints", [])),
            next_action=str(data["next_action"]),
            citations=tuple(item for item in citations if isinstance(item, dict)),
            unknowns=tuple(str(item) for item in payload.get("unknowns", [])),
            conflicts=tuple(str(item) for item in payload.get("conflicts", [])),
        )


async def read_cited_evidence(
    server: MCPServer,
    *,
    task_id: UUID,
    branch: str,
    commit_sha: str,
    citations: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Open explicitly selected citations after the compact handoff has been reviewed."""

    evidence: list[dict[str, Any]] = []
    async with Client(server) as client:
        for citation in citations:
            evidence_id = citation.get("evidence_id")
            if evidence_id is None:
                continue
            result = await client.call_tool(
                "get_evidence",
                {
                    "task_id": str(task_id),
                    "branch": branch,
                    "commit_sha": commit_sha,
                    "evidence_id": evidence_id,
                },
            )
            if result.is_error or not isinstance(result.structured_content, dict):
                raise RuntimeError("A selected handoff source could not be opened")
            payload = result.structured_content
            if payload.get("status") != "ok":
                raise RuntimeError("A selected handoff source was denied")
            data = payload.get("data")
            if isinstance(data, dict):
                evidence.append(data)
    return tuple(evidence)
