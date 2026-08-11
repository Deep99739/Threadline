from __future__ import annotations

from uuid import UUID, uuid4

from tests.unit.test_models import TENANT, WORKSPACE, evidence, repository_version, task
from threadline.models import Claim, ClaimType, EpistemicState, EvidenceLink, EvidenceRelation
from threadline.precedence import assess_claim_authority


def _claim(claim_type: ClaimType, evidence_ids: tuple[UUID, ...]) -> Claim:
    active_task = task()
    return Claim(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        created_by=active_task.created_by,
        repository_version=repository_version(),
        task_id=active_task.id,
        claim_type=claim_type,
        subject_key="test_suite",
        predicate="all_tests_passed",
        value=True,
        epistemic_state=EpistemicState.ASSERTED,
        evidence=tuple(
            EvidenceLink(evidence_id=evidence_id, relation=EvidenceRelation.SUPPORTS)
            for evidence_id in evidence_ids
        ),
        freshness_rule="invalidate_on_test_report_change",
    )


def test_precedence_depends_on_claim_type_without_certifying_truth() -> None:
    git_file = evidence().model_copy(update={"evidence_type": "GIT_FILE"})
    test_report = evidence().model_copy(
        update={"id": uuid4(), "evidence_type": "TEST_REPORT"}
    )
    evidence_by_id = {git_file.id: git_file, test_report.id: test_report}

    implementation = _claim(ClaimType.IMPLEMENTATION, (git_file.id, test_report.id))
    completion = _claim(ClaimType.COMPLETION, (git_file.id, test_report.id))

    implementation_authority = assess_claim_authority(implementation, evidence_by_id)
    completion_authority = assess_claim_authority(completion, evidence_by_id)

    assert implementation_authority.strongest_evidence_type == "GIT_FILE"
    assert implementation_authority.tier == 1
    assert completion_authority.strongest_evidence_type == "TEST_REPORT"
    assert completion_authority.tier == 2
    assert implementation.epistemic_state is EpistemicState.ASSERTED
    assert completion.epistemic_state is EpistemicState.ASSERTED


def test_unrecognized_evidence_is_explicitly_low_authority() -> None:
    summary = evidence().model_copy(update={"evidence_type": "CHAT_SUMMARY"})
    active_claim = _claim(ClaimType.IMPLEMENTATION, (summary.id,))

    authority = assess_claim_authority(active_claim, {summary.id: summary})

    assert authority.strongest_evidence_type is None
    assert authority.tier > 5
    assert "CHAT_SUMMARY" in authority.reason
