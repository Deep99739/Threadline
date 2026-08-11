"""Deterministic context-pack and verified-handoff compilation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from threadline.models import (
    Citation,
    ContextItem,
    ContextPack,
    ContextSnapshot,
    ContextVersion,
    EpistemicState,
    Handoff,
    utc_now,
)
from threadline.retrieval import RetrievedEntity, evidence_index, lexical_retrieve
from threadline.storage import ThreadlineStore


@dataclass(frozen=True)
class CompiledHandoff:
    context_pack: ContextPack
    context_version: ContextVersion
    handoff: Handoff
    content: dict[str, object]


def _hash_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _citations(retrieved: RetrievedEntity, snapshot: ContextSnapshot) -> tuple[Citation, ...]:
    evidence = evidence_index(snapshot)
    return tuple(
        Citation(evidence_id=evidence_id, locator=evidence[evidence_id].locator)
        for evidence_id in retrieved.evidence_ids
        if evidence_id in evidence
    )


def _next_action(snapshot: ContextSnapshot) -> str:
    if snapshot.task.next_action is not None:
        return snapshot.task.next_action
    call_path_broken = any(
        claim.subject_key == "run_job"
        and claim.predicate == "references:RetryPolicy"
        and claim.epistemic_state is EpistemicState.CONTRADICTED
        for claim in snapshot.claims
    )
    tests_incomplete = any(
        claim.predicate == "all_tests_passed"
        and claim.epistemic_state
        in {
            EpistemicState.CONTRADICTED,
            EpistemicState.STALE,
            EpistemicState.UNKNOWN,
        }
        for claim in snapshot.claims
    )
    if call_path_broken:
        return (
            "Wire RetryPolicy into run_job while reusing the original idempotency key, "
            "then add an integration test and run the complete suite."
        )
    if tests_incomplete:
        return "Run the complete test suite before making a completion claim."
    return "Review the remaining unknown claims and collect their required evidence."


def compile_handoff(
    store: ThreadlineStore,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    task_id: UUID,
    actor_id: UUID,
    query: str,
    token_budget: int = 2048,
) -> CompiledHandoff:
    snapshot = store.load_snapshot(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
    )
    retrieved = lexical_retrieve(
        snapshot,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        query=query,
    )
    context_version_payload = {
        "repository_version": snapshot.repository_version.model_dump(mode="json"),
        "task": snapshot.task.model_dump(mode="json"),
        "claims": [item.model_dump(mode="json") for item in snapshot.claims],
        "decisions": [item.model_dump(mode="json") for item in snapshot.decisions],
        "constraints": [item.model_dump(mode="json") for item in snapshot.constraints],
        "config_version": "lexical-foundation.v1",
    }
    context_version = ContextVersion(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        created_by=actor_id,
        repository_version=snapshot.repository_version,
        config_version="lexical-foundation.v1",
        root_hash=_hash_json(context_version_payload),
        published_at=utc_now(),
    )
    items = tuple(
        ContextItem(
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            statement=item.statement,
            epistemic_state=item.state,
            selection_reason=item.selection_reason,
            citations=_citations(item, snapshot),
        )
        for item in retrieved
    )
    unknowns = tuple(
        item.statement for item in items if item.epistemic_state is EpistemicState.UNKNOWN
    )
    conflicts = tuple(
        item.statement for item in items if item.epistemic_state is EpistemicState.CONTRADICTED
    )
    context_pack = ContextPack(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        repository_version=snapshot.repository_version,
        context_version_id=context_version.id,
        config_version=context_version.config_version,
        purpose="continue_task",
        token_budget=token_budget,
        items=items,
        unknowns=unknowns,
        conflicts=conflicts,
    )
    content: dict[str, object] = {
        "repository_version": snapshot.repository_version.model_dump(mode="json"),
        "objective": snapshot.task.objective,
        "constraints": [item.statement for item in snapshot.constraints],
        "rejected_approaches": [
            rejected
            for decision in snapshot.decisions
            for rejected in decision.rejected_alternatives
        ],
        "verified_completed_work": [
            f"{item.subject_key} {item.predicate}"
            for item in snapshot.claims
            if item.epistemic_state is EpistemicState.VERIFIED
        ],
        "contradictions": list(conflicts),
        "unknowns": list(unknowns),
        "next_action": _next_action(snapshot),
        "freshness_rules": {str(item.id): item.freshness_rule for item in snapshot.claims},
        "context_pack": context_pack.model_dump(mode="json"),
    }
    handoff = Handoff(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        created_by=actor_id,
        task_id=task_id,
        context_version_id=context_version.id,
        producer_actor_id=actor_id,
        intended_receiver="next-coding-agent",
        purpose="continue_task",
        content_hash=_hash_json(content),
    )
    store.save_context_version(context_version, task_id)
    store.save_handoff(handoff, content)
    return CompiledHandoff(
        context_pack=context_pack,
        context_version=context_version,
        handoff=handoff,
        content=content,
    )
