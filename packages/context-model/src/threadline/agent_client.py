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
    evidence: tuple[dict[str, Any], ...]


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
        evidence: list[dict[str, Any]] = []
        for citation in citations:
            if not isinstance(citation, dict) or "evidence_id" not in citation:
                continue
            evidence_result = await client.call_tool(
                "get_evidence",
                {
                    "task_id": str(task_id),
                    "branch": branch,
                    "commit_sha": commit_sha,
                    "evidence_id": citation["evidence_id"],
                },
            )
            if evidence_result.is_error or not isinstance(evidence_result.structured_content, dict):
                raise RuntimeError("A cited handoff source could not be opened")
            evidence_payload = evidence_result.structured_content
            if evidence_payload.get("status") != "ok":
                raise RuntimeError("A cited handoff source was denied")
            evidence_data = evidence_payload.get("data")
            if isinstance(evidence_data, dict):
                evidence.append(evidence_data)

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
            evidence=tuple(evidence),
        )
