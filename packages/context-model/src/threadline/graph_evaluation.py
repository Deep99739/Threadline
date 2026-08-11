"""Executable ablation for the bounded code graph layer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from threadline.demo import (
    DEMO_REPOSITORY_ID,
    DEMO_TASK_ID,
    DEMO_TENANT_ID,
    DEMO_WORKSPACE_ID,
    run_demo,
)
from threadline.graph import trace_code_graph
from threadline.retrieval import lexical_retrieve
from threadline.storage import ThreadlineStore

QUERY = "Which test constructs RetryPolicy?"
ROOT_SYMBOL = "tests.test_retry_policy.test_retry_policy_builds_bounded_exponential_delays"
EXPECTED_TARGET = "src.job_runner.RetryPolicy"


def run_graph_ablation(*, database_url: str, repository_path: Path) -> dict[str, Any]:
    """Compare lexical context with a typed one-hop relationship on identical evidence."""

    seeded = run_demo(database_url, repository_path)
    store = ThreadlineStore(database_url)
    try:
        snapshot = store.load_snapshot(
            tenant_id=DEMO_TENANT_ID,
            workspace_id=DEMO_WORKSPACE_ID,
            task_id=DEMO_TASK_ID,
        )
        lexical_started = perf_counter()
        lexical = lexical_retrieve(
            snapshot,
            tenant_id=DEMO_TENANT_ID,
            workspace_id=DEMO_WORKSPACE_ID,
            query=QUERY,
        )
        lexical_ms = (perf_counter() - lexical_started) * 1000

        graph_started = perf_counter()
        trace = trace_code_graph(
            snapshot,
            tenant_id=DEMO_TENANT_ID,
            workspace_id=DEMO_WORKSPACE_ID,
            symbol=ROOT_SYMBOL,
            max_depth=1,
            max_nodes=10,
        )
        graph_ms = (perf_counter() - graph_started) * 1000
    finally:
        store.close()

    expected_relationships = [
        item
        for item in trace.dependencies
        if item.dependency_kind.value == "CONSTRUCTS"
        and item.target_symbol_key is not None
        and item.target_symbol_key.endswith(EXPECTED_TARGET)
    ]
    if len(expected_relationships) != 1:
        raise RuntimeError("graph ablation did not recover the expected test-to-class edge")

    evidence_ids = {item.id for item in snapshot.evidence}
    citations_valid = all(item.evidence_id in evidence_ids for item in trace.citations)
    return {
        "report": "threadline-phase2-code-graph-ablation",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": "primary-demo-v0.1",
        "sample_size": 1,
        "query": QUERY,
        "repository": {
            "id": str(DEMO_REPOSITORY_ID),
            "branch": seeded.handoff.context_pack.repository_version.branch,
            "commit": seeded.handoff.context_pack.repository_version.commit_sha,
        },
        "expected_relationship": {
            "source": ROOT_SYMBOL,
            "kind": "CONSTRUCTS",
            "target": EXPECTED_TARGET,
        },
        "ablations": [
            {
                "baseline_id": "B2",
                "name": "lexical context only",
                "execution_status": "recorded",
                "selected_entity_count": len(lexical),
                "typed_code_relationships_returned": 0,
                "expected_relationship_recall": 0.0,
                "latency_ms": round(lexical_ms, 3),
                "what_breaks": (
                    "The handoff can retrieve RetryPolicy evidence but cannot show which exact "
                    "test symbol constructs it."
                ),
            },
            {
                "baseline_id": "B4-graph",
                "name": "bounded typed graph expansion",
                "execution_status": "recorded",
                "selected_node_count": len(trace.nodes),
                "typed_code_relationships_returned": len(trace.dependencies),
                "expected_relationship_recall": 1.0,
                "citation_validity": 1.0 if citations_valid else 0.0,
                "latency_ms": round(graph_ms, 3),
                "truncated": trace.truncated,
                "unresolved_relationship_count": len(trace.unresolved_dependencies),
                "what_breaks_without_it": (
                    "An agent must reopen and reinterpret the test file to discover the "
                    "test-to-production relationship."
                ),
            },
        ],
        "retention_decision": (
            "Retain the bounded graph for relationship questions; keep lexical retrieval as "
            "the default handoff baseline."
        ),
        "limits": [
            "One synthetic Python relationship; this is not a general accuracy benchmark.",
            (
                "JavaScript and TypeScript extraction are covered by deterministic tests, "
                "not this case."
            ),
            (
                "No embedding or external model was used, so cost is zero but semantic "
                "recall is unmeasured."
            ),
            (
                "Latency is a local point-in-time measurement and not a production "
                "service-level claim."
            ),
        ],
    }
