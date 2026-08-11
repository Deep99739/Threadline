"""Claim-type-specific source precedence without collapsing contradictions."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from threadline.models import Claim, ClaimType, Evidence

SOURCE_PRECEDENCE: dict[ClaimType, tuple[str, ...]] = {
    ClaimType.IMPLEMENTATION: (
        "GIT_FILE",
        "CODE_ANALYSIS",
        "PULL_REQUEST",
        "ISSUE",
        "AGENT_OBSERVATION",
    ),
    ClaimType.BEHAVIOR: (
        "RUNTIME_OBSERVATION",
        "CI_TEST_REPORT",
        "TEST_REPORT",
        "GIT_FILE",
        "AGENT_OBSERVATION",
    ),
    ClaimType.TEST: (
        "CI_TEST_REPORT",
        "TEST_REPORT",
        "GIT_FILE",
        "AGENT_OBSERVATION",
    ),
    ClaimType.DEPLOYMENT: (
        "DEPLOYMENT_OBSERVATION",
        "CI_DEPLOYMENT",
        "GIT_FILE",
        "AGENT_OBSERVATION",
    ),
    ClaimType.DECISION: (
        "APPROVED_DECISION",
        "DECISION_RECORD",
        "PULL_REQUEST",
        "ISSUE",
        "AGENT_OBSERVATION",
    ),
    ClaimType.INTENTION: (
        "APPROVED_REQUIREMENT",
        "PROJECT_MANIFEST",
        "ISSUE",
        "GIT_FILE",
        "AGENT_OBSERVATION",
    ),
    ClaimType.PERMISSION: (
        "PROVIDER_AUTHORIZATION",
        "POLICY_DECISION",
        "CACHED_ACL",
        "GIT_FILE",
    ),
    ClaimType.COMPLETION: (
        "CI_TEST_REPORT",
        "TEST_REPORT",
        "RUNTIME_OBSERVATION",
        "GIT_FILE",
        "AGENT_OBSERVATION",
    ),
}


@dataclass(frozen=True)
class AuthorityAssessment:
    tier: int
    strongest_evidence_type: str | None
    reason: str


def assess_claim_authority(
    claim: Claim,
    evidence_by_id: dict[UUID, Evidence],
) -> AuthorityAssessment:
    """Classify source authority for this claim type; never decide truth from rank alone."""

    precedence = SOURCE_PRECEDENCE[claim.claim_type]
    evidence_types = {
        evidence_by_id[link.evidence_id].evidence_type
        for link in claim.evidence
        if link.evidence_id in evidence_by_id
    }
    ranked = [
        (precedence.index(evidence_type) + 1, evidence_type)
        for evidence_type in evidence_types
        if evidence_type in precedence
    ]
    if not ranked:
        observed = ", ".join(sorted(evidence_types)) or "none"
        return AuthorityAssessment(
            tier=len(precedence) + 1,
            strongest_evidence_type=None,
            reason=(
                f"No recognized {claim.claim_type.value.lower()} authority source; "
                f"observed evidence types: {observed}."
            ),
        )
    tier, evidence_type = min(ranked)
    return AuthorityAssessment(
        tier=tier,
        strongest_evidence_type=evidence_type,
        reason=(
            f"{evidence_type} is tier {tier} for {claim.claim_type.value.lower()} claims. "
            "Authority rank affects ordering but never converts a claim to VERIFIED."
        ),
    )
