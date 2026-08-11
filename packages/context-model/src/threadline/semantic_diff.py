"""Deterministic semantic differences between two immutable context packs."""

from __future__ import annotations

from typing import Any

from threadline.models import (
    ContextChange,
    ContextChangeType,
    ContextItem,
    ContextPack,
    EpistemicState,
    SemanticContextDiff,
)


def _pack(content: dict[str, Any]) -> ContextPack:
    raw = content.get("context_pack")
    if not isinstance(raw, dict):
        raise ValueError("handoff is missing its context pack")
    return ContextPack.model_validate(raw)


def _semantic_item(item: ContextItem) -> dict[str, object]:
    return {
        "logical_key": item.logical_key,
        "entity_type": item.entity_type,
        "statement": item.statement,
        "epistemic_state": item.epistemic_state,
        "selection_reason": item.selection_reason,
        "authority_reason": item.authority_reason,
        "citations": [citation.locator.model_dump(mode="json") for citation in item.citations],
    }


def _changed_type(item: ContextItem) -> ContextChangeType:
    if item.epistemic_state is EpistemicState.STALE:
        return ContextChangeType.STALE
    if item.epistemic_state is EpistemicState.CONTRADICTED:
        return ContextChangeType.CONTRADICTED
    if item.epistemic_state is EpistemicState.SUPERSEDED:
        return ContextChangeType.SUPERSEDED
    return ContextChangeType.CHANGED


def compare_context_versions(
    base_content: dict[str, Any],
    target_content: dict[str, Any],
) -> SemanticContextDiff:
    base = _pack(base_content)
    target = _pack(target_content)
    if base.tenant_id != target.tenant_id or base.workspace_id != target.workspace_id:
        raise PermissionError("context versions do not belong to the same authorized scope")
    if base.task_id != target.task_id:
        raise ValueError("context versions do not belong to the same task")

    base_items = {item.logical_key: item for item in base.items}
    target_items = {item.logical_key: item for item in target.items}
    changes: list[ContextChange] = []
    for logical_key in sorted(base_items.keys() | target_items.keys()):
        before = base_items.get(logical_key)
        after = target_items.get(logical_key)
        if before is None and after is not None:
            changes.append(
                ContextChange(
                    logical_key=logical_key,
                    entity_type=after.entity_type,
                    change_type=ContextChangeType.ADDED,
                    reasons=("Context item entered the selected evidence pack.",),
                    after=after,
                )
            )
            continue
        if before is not None and after is None:
            changes.append(
                ContextChange(
                    logical_key=logical_key,
                    entity_type=before.entity_type,
                    change_type=ContextChangeType.REMOVED,
                    reasons=("Context item left the selected evidence pack.",),
                    before=before,
                )
            )
            continue
        if before is None or after is None or _semantic_item(before) == _semantic_item(after):
            continue

        reasons: list[str] = []
        if before.statement != after.statement:
            reasons.append("Statement changed.")
        if before.epistemic_state != after.epistemic_state:
            reasons.append(
                f"Epistemic state changed from {before.epistemic_state.value} "
                f"to {after.epistemic_state.value}."
            )
        if [item.locator for item in before.citations] != [
            item.locator for item in after.citations
        ]:
            reasons.append("Supporting or contradicting evidence changed.")
        if before.authority_reason != after.authority_reason:
            reasons.append("Typed source-authority assessment changed.")
        if not reasons:
            reasons.append("Selection metadata changed.")
        changes.append(
            ContextChange(
                logical_key=logical_key,
                entity_type=after.entity_type,
                change_type=_changed_type(after),
                reasons=tuple(reasons),
                before=before,
                after=after,
            )
        )

    return SemanticContextDiff(
        base_context_version_id=base.context_version_id,
        target_context_version_id=target.context_version_id,
        base_repository_version=base.repository_version,
        target_repository_version=target.repository_version,
        changes=tuple(changes),
    )
