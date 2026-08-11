"""Explain when a published handoff no longer matches the active repository state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from threadline.models import ContextSnapshot, RepositoryVersion


@dataclass(frozen=True)
class StaleContextItem:
    entity_id: str
    entity_type: str
    statement: str
    prior_state: str
    freshness_rule: str
    reasons: tuple[str, ...]
    changed_sources: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "statement": self.statement,
            "prior_state": self.prior_state,
            "current_state": "STALE",
            "freshness_rule": self.freshness_rule,
            "reasons": list(self.reasons),
            "changed_sources": list(self.changed_sources),
        }


def handoff_repository_version(content: dict[str, Any]) -> RepositoryVersion:
    raw = content.get("repository_version")
    if not isinstance(raw, dict):
        raise ValueError("handoff is missing its repository version")
    return RepositoryVersion.model_validate(raw)


def _active_hashes(snapshot: ContextSnapshot) -> dict[str, set[str]]:
    hashes: dict[str, set[str]] = {}
    for evidence in snapshot.evidence:
        hashes.setdefault(evidence.locator.uri, set()).add(evidence.locator.content_hash)
    return hashes


def stale_context_items(
    content: dict[str, Any], snapshot: ContextSnapshot
) -> tuple[StaleContextItem, ...]:
    """Return cited handoff items invalidated by the active repository version.

    The comparison uses source content hashes instead of timestamps. Commit-wide rules are
    invalidated whenever the branch head moves, while path-scoped rules are invalidated only
    when their cited source disappears or changes.
    """

    prior_version = handoff_repository_version(content)
    active_version = snapshot.repository_version
    if prior_version == active_version:
        return ()

    pack = content.get("context_pack")
    if not isinstance(pack, dict):
        raise ValueError("handoff is missing its context pack")
    items = pack.get("items")
    if not isinstance(items, list):
        raise ValueError("handoff context pack has no items")
    freshness_rules = content.get("freshness_rules", {})
    if not isinstance(freshness_rules, dict):
        freshness_rules = {}

    current_hashes = _active_hashes(snapshot)
    stale: list[StaleContextItem] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entity_id = str(item.get("entity_id", ""))
        freshness_rule = str(freshness_rules.get(entity_id, "invalidate_on_commit"))
        citations = item.get("citations", [])
        changed_sources: list[str] = []
        if isinstance(citations, list):
            for citation in citations:
                if not isinstance(citation, dict):
                    continue
                locator = citation.get("locator")
                if not isinstance(locator, dict):
                    continue
                uri = str(locator.get("uri", ""))
                old_hash = str(locator.get("content_hash", ""))
                if uri and old_hash not in current_hashes.get(uri, set()):
                    changed_sources.append(uri)

        reasons: list[str] = []
        if freshness_rule.startswith("invalidate_on_commit"):
            reasons.append(
                "repository head moved from "
                f"{prior_version.commit_sha} to {active_version.commit_sha}"
            )
        if changed_sources:
            reasons.append("cited source content changed or disappeared")
        if not reasons:
            continue
        stale.append(
            StaleContextItem(
                entity_id=entity_id,
                entity_type=str(item.get("entity_type", "unknown")),
                statement=str(item.get("statement", "")),
                prior_state=str(item.get("epistemic_state", "UNKNOWN")),
                freshness_rule=freshness_rule,
                reasons=tuple(reasons),
                changed_sources=tuple(sorted(set(changed_sources))),
            )
        )
    return tuple(stale)
