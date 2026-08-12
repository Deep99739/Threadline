from __future__ import annotations

from pathlib import Path

import pytest

from threadline.continuation_benchmark import run_continuation_benchmark


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_continuation_benchmark_executes_failures_and_reports_small_denominators(
    tmp_path: Path,
) -> None:
    report = await run_continuation_benchmark(tmp_path / "benchmark")

    assert report["sample_size"] == 11
    cases = report["cases"]
    assert isinstance(cases, list)
    assert len(cases) == 11
    assert all(case["passed"] for case in cases)
    metrics = report["metrics"]
    assert metrics["expected_next_action_accuracy"] == {
        "correct": 1,
        "total": 1,
        "rate": 1.0,
    }
    assert metrics["required_abstention_accuracy"] == {
        "correct": 2,
        "total": 2,
        "rate": 1.0,
    }
    assert metrics["scope_denial_accuracy"] == {
        "correct": 1,
        "total": 1,
        "rate": 1.0,
    }
    assert metrics["unsupported_completion_false_acceptance"] == {
        "accepted": 0,
        "total": 1,
        "rate": 0.0,
    }
    assert metrics["known_secret_exposure"] == {
        "accepted": 0,
        "total": 1,
        "rate": 0.0,
    }
    assert metrics["instruction_boundary_detection"] == {
        "correct": 1,
        "total": 1,
        "rate": 1.0,
    }
    baselines = report["baseline_failures"]
    assert baselines[0]["baseline_id"] == "B0"
    assert baselines[0]["failure_observed"] is True
    assert baselines[1]["baseline_id"] == "B2"
    assert baselines[1]["failure_observed"] is True
    assert report["claim_boundary"] == (
        "Eleven deterministic synthetic regression cases; not an external accuracy, adoption, "
        "or production claim."
    )
