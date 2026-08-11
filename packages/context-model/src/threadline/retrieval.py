"""Authorization-scoped lexical baseline for Threadline context retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from threadline.models import (
    Claim,
    ContextSnapshot,
    EpistemicState,
    Evidence,
)

TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_:-]*")


@dataclass(frozen=True)
class RetrievedEntity:
    entity_type: str
    entity_id: UUID
    statement: str
    state: EpistemicState
    score: float
    evidence_ids: tuple[UUID, ...]
    selection_reason: str


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(token.lower() for token in TOKEN_PATTERN.findall(value))


def _score(query_tokens: tuple[str, ...], statement: str) -> float:
    terms = _tokens(statement)
    if not terms or not query_tokens:
        return 0.0
    exact = sum(1 for token in query_tokens if token in terms)
    prefix = sum(
        1
        for token in query_tokens
        if token not in terms and any(term.startswith(token) for term in terms)
    )
    return exact * 2.0 + prefix * 0.5


def _claim_statement(claim: Claim) -> str:
    return f"{claim.subject_key} {claim.predicate} {claim.value}"


def lexical_retrieve(
    snapshot: ContextSnapshot,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    query: str,
    limit: int = 12,
) -> tuple[RetrievedEntity, ...]:
    """Retrieve only after the caller scope matches the already authorized snapshot."""

    if snapshot.tenant_id != tenant_id or snapshot.workspace_id != workspace_id:
        raise PermissionError("caller scope does not match the authorized context snapshot")
    query_tokens = _tokens(query)
    candidates: list[RetrievedEntity] = []

    for claim in snapshot.claims:
        statement = _claim_statement(claim)
        score = _score(query_tokens, statement)
        if claim.epistemic_state in {
            EpistemicState.CONTRADICTED,
            EpistemicState.STALE,
            EpistemicState.UNKNOWN,
        }:
            score += 3.0
        candidates.append(
            RetrievedEntity(
                entity_type="claim",
                entity_id=claim.id,
                statement=statement,
                state=claim.epistemic_state,
                score=score,
                evidence_ids=tuple(link.evidence_id for link in claim.evidence),
                selection_reason="lexical relevance plus epistemic risk priority",
            )
        )

    for constraint in snapshot.constraints:
        candidates.append(
            RetrievedEntity(
                entity_type="constraint",
                entity_id=constraint.id,
                statement=constraint.statement,
                state=EpistemicState.ASSERTED,
                score=_score(query_tokens, constraint.statement) + 5.0,
                evidence_ids=constraint.evidence_ids,
                selection_reason="high-severity task constraint with source provenance",
            )
        )

    for decision in snapshot.decisions:
        statement = f"{decision.statement} {decision.rationale}"
        candidates.append(
            RetrievedEntity(
                entity_type="decision",
                entity_id=decision.id,
                statement=statement,
                state=EpistemicState.ASSERTED,
                score=_score(query_tokens, statement) + 2.0,
                evidence_ids=decision.evidence_ids,
                selection_reason="decision relevance with source provenance",
            )
        )

    for observation in snapshot.observations:
        candidates.append(
            RetrievedEntity(
                entity_type="observation",
                entity_id=observation.id,
                statement=observation.statement,
                state=observation.epistemic_state,
                score=_score(query_tokens, observation.statement),
                evidence_ids=(
                    (observation.source_evidence_id,)
                    if observation.source_evidence_id is not None
                    else ()
                ),
                selection_reason="lexical relevance from attributed observation",
            )
        )

    return tuple(
        sorted(candidates, key=lambda item: (-item.score, item.entity_type, str(item.entity_id)))[
            :limit
        ]
    )


def evidence_index(snapshot: ContextSnapshot) -> dict[UUID, Evidence]:
    return {item.id: item for item in snapshot.evidence}
