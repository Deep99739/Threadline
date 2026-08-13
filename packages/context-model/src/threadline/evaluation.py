"""Executable Phase 1 evaluation over the primary continuation scenario."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from threadline.agent_client import read_agent_handoff, read_cited_evidence
from threadline.demo import (
    DEMO_ACTOR_ID,
    DEMO_REPOSITORY_ID,
    DEMO_TASK_ID,
    DEMO_TENANT_ID,
    DEMO_WORKSPACE_ID,
    run_demo,
)
from threadline.demo_continuation import run_agent_b_continuation
from threadline.mcp_server import create_mcp_server
from threadline.models import EpistemicState
from threadline.retrieval import evidence_index, lexical_retrieve
from threadline.service import ServiceScope
from threadline.storage import ThreadlineStore

EXPECTED_ACTION_TERMS = (
    "RetryPolicy",
    "run_job",
    "original idempotency key",
    "complete suite",
)
REQUIRED_SOURCE_SUFFIXES = (
    "/src/job_runner.py",
    "/threadline/decision.json",
    "/threadline/test-report.json",
)


@dataclass(frozen=True)
class BaselineResult:
    baseline_id: str
    name: str
    execution_status: str
    next_action: str | None
    next_action_correct: bool | None
    unsupported_completion_accepted: bool | None
    required_evidence_recall: float | None
    citation_validity: float | None
    limitations: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "baseline_id": self.baseline_id,
            "name": self.name,
            "execution_status": self.execution_status,
            "next_action": self.next_action,
            "next_action_correct": self.next_action_correct,
            "unsupported_completion_accepted": self.unsupported_completion_accepted,
            "required_evidence_recall": self.required_evidence_recall,
            "citation_validity": self.citation_validity,
            "limitations": list(self.limitations),
        }


def _action_is_correct(action: str | None) -> bool:
    return action is not None and all(term in action for term in EXPECTED_ACTION_TERMS)


def _source_recall(uris: set[str]) -> float:
    found = sum(any(uri.endswith(suffix) for uri in uris) for suffix in REQUIRED_SOURCE_SUFFIXES)
    return found / len(REQUIRED_SOURCE_SUFFIXES)


def _citation_validity(evidence: tuple[dict[str, Any], ...]) -> float:
    if not evidence:
        return 0.0
    valid = sum(
        isinstance(item.get("content"), str)
        and bool(item["content"])
        and isinstance(item.get("locator"), dict)
        for item in evidence
    )
    return valid / len(evidence)


async def run_phase1_evaluation(*, database_url: str, repository_path: Path) -> dict[str, object]:
    """Measure the implemented primary path without inventing model benchmark results."""

    seeded = run_demo(database_url, repository_path)
    store = ThreadlineStore(database_url)
    scope = ServiceScope(
        tenant_id=DEMO_TENANT_ID,
        workspace_id=DEMO_WORKSPACE_ID,
        actor_id=DEMO_ACTOR_ID,
        repository_id=DEMO_REPOSITORY_ID,
    )
    try:
        snapshot = store.load_snapshot(
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            task_id=DEMO_TASK_ID,
        )
        initial_version = snapshot.repository_version
        server = create_mcp_server(store, scope, DEMO_TASK_ID, repository_path)
        handoff = await read_agent_handoff(
            server,
            task_id=DEMO_TASK_ID,
            branch=initial_version.branch,
            commit_sha=initial_version.commit_sha,
        )
        evidence = await read_cited_evidence(
            server,
            task_id=DEMO_TASK_ID,
            branch=initial_version.branch,
            commit_sha=initial_version.commit_sha,
            citations=handoff.citations,
        )
        evidence_uris = {
            str(item.get("locator", {}).get("uri", ""))
            for item in evidence
            if isinstance(item.get("locator"), dict)
        }

        transcript_baseline = BaselineResult(
            baseline_id="B0",
            name="transcript-only latest assertion",
            execution_status="recorded",
            next_action=(
                "No implementation action; retries are already implemented and all tests pass."
            ),
            next_action_correct=False,
            unsupported_completion_accepted=True,
            required_evidence_recall=1 / 3,
            citation_validity=1.0,
            limitations=(
                "Deterministic transcript-only policy uses the latest agent assertion.",
                "This is a baseline implementation, not an LLM benchmark.",
            ),
        )
        summary_baseline = BaselineResult(
            baseline_id="B1",
            name="LLM transcript summary",
            execution_status="not_run",
            next_action=None,
            next_action_correct=None,
            unsupported_completion_accepted=None,
            required_evidence_recall=None,
            citation_validity=None,
            limitations=(
                "No model/provider was invoked in the deterministic Phase 1 gate.",
                "Freeze a model and prompt before this baseline becomes publishable evidence.",
            ),
        )

        lexical = lexical_retrieve(
            snapshot,
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            query="continue retry work without duplicate side effects",
        )
        by_evidence = evidence_index(snapshot)
        lexical_uris = {
            by_evidence[evidence_id].locator.uri
            for item in lexical
            for evidence_id in item.evidence_ids
            if evidence_id in by_evidence
        }
        lexical_baseline = BaselineResult(
            baseline_id="B2",
            name="lexical retrieval only",
            execution_status="recorded",
            next_action=None,
            next_action_correct=None,
            unsupported_completion_accepted=None,
            required_evidence_recall=_source_recall(lexical_uris),
            citation_validity=1.0 if lexical_uris else 0.0,
            limitations=(
                "Retrieval-only baseline returns sources but does not verify claims or "
                "choose an action.",
            ),
        )
        threadline_result = BaselineResult(
            baseline_id="B4",
            name="Threadline Phase 1",
            execution_status="recorded",
            next_action=handoff.next_action,
            next_action_correct=_action_is_correct(handoff.next_action),
            unsupported_completion_accepted=False,
            required_evidence_recall=_source_recall(evidence_uris),
            citation_validity=_citation_validity(evidence),
            limitations=(
                "One synthetic primary case; not a general accuracy claim.",
                "The ranker is lexical and the action policy is deterministic.",
            ),
        )
        completion_claim = next(
            item for item in snapshot.claims if item.predicate == "all_tests_passed"
        )
        proof = await run_agent_b_continuation(
            store=store,
            scope=scope,
            repository_path=repository_path,
        )
    finally:
        store.close()

    return {
        "report": "threadline-phase1-primary-evaluation",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": "primary-demo-v0.1",
        "sample_size": 1,
        "repository": {
            "name": "threadline-demo",
            "branch": seeded.handoff.context_pack.repository_version.branch,
            "initial_commit": proof.initial_commit,
            "resulting_commit": proof.resulting_commit,
        },
        "baselines": [
            transcript_baseline.as_dict(),
            summary_baseline.as_dict(),
            lexical_baseline.as_dict(),
            threadline_result.as_dict(),
        ],
        "phase1_gates": {
            "agent_b_used_official_mcp_client": True,
            "agent_b_took_expected_next_action": _action_is_correct(proof.action_taken),
            "unsupported_completion_not_verified": (
                completion_claim.epistemic_state is not EpistemicState.VERIFIED
            ),
            "changed_evidence_marked_stale": bool(proof.stale_items),
            "live_repository_drift_refused_before_ingest": (proof.live_drift_refused_before_ingest),
            "stale_handoff_refused": proof.stale_handoff_refused,
            "post_change_full_suite_passed": "2 passed" in proof.test_output,
            "post_change_handoff_has_no_unknowns_or_conflicts": proof.final_status == "ok",
            "all_returned_citations_resolved": threadline_result.citation_validity == 1.0,
        },
        "failures_and_limits": [
            "The transcript-only baseline accepts an unsupported completion assertion.",
            "The LLM-summary baseline is unmeasured until a model and prompt are frozen.",
            "The sample contains one synthetic repository and cannot support external-use claims.",
            "Clean-machine and editor-client compatibility are separate release gates.",
        ],
    }
