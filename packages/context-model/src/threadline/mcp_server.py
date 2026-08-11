"""Read-only MCP tools over an already authorized local Threadline workspace."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from threadline.models import ContextSnapshot
from threadline.service import ServiceScope
from threadline.staleness import handoff_repository_version, stale_context_items
from threadline.storage import ThreadlineStore

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def _repository(snapshot: ContextSnapshot) -> dict[str, str]:
    version = snapshot.repository_version
    return {
        "id": str(version.repository_id),
        "branch": version.branch,
        "commit": version.commit_sha,
    }


def _citations(content: dict[str, Any]) -> list[dict[str, Any]]:
    context_pack = content.get("context_pack", {})
    items = context_pack.get("items", []) if isinstance(context_pack, dict) else []
    unique: dict[str, dict[str, Any]] = {}
    for item in items:
        for citation in item.get("citations", []):
            unique[str(citation["evidence_id"])] = citation
    return list(unique.values())


def _envelope(
    snapshot: ContextSnapshot,
    content: dict[str, Any],
    *,
    status: str,
    data: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    context_pack = content["context_pack"]
    return {
        "request_id": context_pack["request_id"],
        "trace_id": context_pack["trace_id"],
        "context_version": context_pack["context_version_id"],
        "repository": _repository(snapshot),
        "status": status,
        "data": data,
        "citations": _citations(content),
        "unknowns": list(content.get("unknowns", [])),
        "conflicts": list(content.get("contradictions", [])),
        "warnings": warnings or [],
    }


def _version_warning(
    snapshot: ContextSnapshot,
    content: dict[str, Any],
    branch: str,
    commit_sha: str,
) -> str | None:
    current = snapshot.repository_version
    if current.branch != branch or current.commit_sha != commit_sha:
        return (
            "Requested repository version does not match the active repository state: "
            f"requested {branch}@{commit_sha}, active {current.branch}@{current.commit_sha}."
        )
    handoff_version = handoff_repository_version(content)
    if handoff_version.branch != branch or handoff_version.commit_sha != commit_sha:
        return (
            "The latest handoff is stale for the active repository state: "
            f"handoff {handoff_version.branch}@{handoff_version.commit_sha}, "
            f"active {current.branch}@{current.commit_sha}. Recompile before continuing."
        )
    return None


def create_mcp_server(store: ThreadlineStore, scope: ServiceScope) -> MCPServer:
    """Bind tools to one trusted local scope; callers cannot select a tenant or workspace."""

    server = MCPServer(
        "Threadline",
        description="Read-only, cited engineering context bound to an exact Git commit.",
        instructions=(
            "Always provide the exact task, branch, and commit. Treat ASSERTED, UNKNOWN, STALE, "
            "and CONTRADICTED items as unverified. Follow cited constraints before continuing."
        ),
        version="0.1.0",
    )

    def load(task_id: UUID) -> tuple[ContextSnapshot, dict[str, Any]]:
        snapshot = store.load_snapshot(
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            task_id=task_id,
        )
        content = store.load_latest_handoff(
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            task_id=task_id,
        )
        return snapshot, content

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def get_task_context(task_id: UUID, branch: str, commit_sha: str) -> dict[str, Any]:
        """Return the latest cited handoff only when its repository version matches exactly."""

        snapshot, content = load(task_id)
        warning = _version_warning(snapshot, content, branch, commit_sha)
        if warning is not None:
            return _envelope(
                snapshot,
                content,
                status="abstained",
                data={},
                warnings=[warning],
            )
        status = "partial" if content.get("unknowns") or content.get("contradictions") else "ok"
        return _envelope(
            snapshot,
            content,
            status=status,
            data={
                "objective": content["objective"],
                "constraints": content["constraints"],
                "verified_completed_work": content["verified_completed_work"],
                "next_action": content["next_action"],
                "items": content["context_pack"]["items"],
            },
        )

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def trace_decision(
        task_id: UUID, branch: str, commit_sha: str, decision_key: str
    ) -> dict[str, Any]:
        """Trace a decision without treating repository metadata as authenticated approval."""

        snapshot, content = load(task_id)
        warning = _version_warning(snapshot, content, branch, commit_sha)
        if warning is not None:
            return _envelope(snapshot, content, status="abstained", data={}, warnings=[warning])
        decision = next(
            (item for item in snapshot.decisions if item.decision_key == decision_key),
            None,
        )
        if decision is None:
            return _envelope(
                snapshot,
                content,
                status="abstained",
                data={},
                warnings=[f"Decision was not found: {decision_key}"],
            )
        evidence = {str(item.id): item for item in snapshot.evidence}
        citations = [
            {
                "evidence_id": str(evidence_id),
                "locator": evidence[str(evidence_id)].locator.model_dump(mode="json"),
            }
            for evidence_id in decision.evidence_ids
            if str(evidence_id) in evidence
        ]
        response = _envelope(
            snapshot,
            content,
            status="partial",
            data={
                "decision_key": decision.decision_key,
                "state": "ASSERTED",
                "status": decision.status,
                "statement": decision.statement,
                "rationale": decision.rationale,
                "rejected_alternatives": list(decision.rejected_alternatives),
                "source_asserted_approver": (
                    str(decision.approved_by) if decision.approved_by else None
                ),
                "citations": citations,
            },
            warnings=["Repository metadata does not authenticate the asserted approver."],
        )
        response["citations"] = citations
        return response

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def explain_context_selection(
        task_id: UUID, branch: str, commit_sha: str, entity_id: UUID
    ) -> dict[str, Any]:
        """Explain the deterministic lexical and risk signals for one selected entity."""

        snapshot, content = load(task_id)
        warning = _version_warning(snapshot, content, branch, commit_sha)
        if warning is not None:
            return _envelope(snapshot, content, status="abstained", data={}, warnings=[warning])
        selected = next(
            (
                item
                for item in content["context_pack"]["items"]
                if item["entity_id"] == str(entity_id)
            ),
            None,
        )
        if selected is None:
            return _envelope(
                snapshot,
                content,
                status="abstained",
                data={},
                warnings=[f"Entity was not selected in this context version: {entity_id}"],
            )
        return _envelope(
            snapshot,
            content,
            status="ok",
            data={
                "entity_id": selected["entity_id"],
                "entity_type": selected["entity_type"],
                "epistemic_state": selected["epistemic_state"],
                "selection_reason": selected["selection_reason"],
                "ranker_version": content["context_pack"]["config_version"],
                "citations": selected["citations"],
            },
        )

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def get_evidence(
        task_id: UUID, branch: str, commit_sha: str, evidence_id: UUID
    ) -> dict[str, Any]:
        """Read one cited evidence object only when it belongs to the bound authorized snapshot."""

        snapshot, content = load(task_id)
        warning = _version_warning(snapshot, content, branch, commit_sha)
        if warning is not None:
            return _envelope(snapshot, content, status="abstained", data={}, warnings=[warning])
        evidence = next((item for item in snapshot.evidence if item.id == evidence_id), None)
        if evidence is None:
            return _envelope(
                snapshot,
                content,
                status="denied",
                data={},
                warnings=["Evidence is outside the authorized task snapshot."],
            )
        evidence_content = store.load_evidence_content(
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            evidence_ids=[evidence_id],
        )
        return _envelope(
            snapshot,
            content,
            status="ok",
            data={
                "evidence_id": str(evidence.id),
                "locator": evidence.locator.model_dump(mode="json"),
                "content": evidence_content[evidence_id],
            },
        )

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def list_stale_context(task_id: UUID, branch: str, commit_sha: str) -> dict[str, Any]:
        """Explain which items from the latest handoff were invalidated by the active commit."""

        snapshot, content = load(task_id)
        current = snapshot.repository_version
        if current.branch != branch or current.commit_sha != commit_sha:
            warning = (
                "Requested repository version does not match the active repository state: "
                f"requested {branch}@{commit_sha}, active {current.branch}@{current.commit_sha}."
            )
            return _envelope(snapshot, content, status="abstained", data={}, warnings=[warning])

        prior = handoff_repository_version(content)
        stale = stale_context_items(content, snapshot)
        status = "stale" if stale or prior != current else "ok"
        return _envelope(
            snapshot,
            content,
            status=status,
            data={
                "handoff_repository": {
                    "id": str(prior.repository_id),
                    "branch": prior.branch,
                    "commit": prior.commit_sha,
                },
                "active_repository": _repository(snapshot),
                "items": [item.as_dict() for item in stale],
            },
            warnings=(
                ["The previous handoff must be recompiled before an agent continues."]
                if status == "stale"
                else []
            ),
        )

    return server
