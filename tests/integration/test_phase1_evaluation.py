from __future__ import annotations

from pathlib import Path

import pytest

from threadline.evaluation import run_phase1_evaluation


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_phase1_evaluation_records_real_gates_and_discloses_missing_model_baseline(
    tmp_path: Path,
) -> None:
    report = await run_phase1_evaluation(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'evaluation.db'}",
        repository_path=tmp_path / "demo-repository",
    )

    assert report["sample_size"] == 1
    gates = report["phase1_gates"]
    assert isinstance(gates, dict)
    assert all(gates.values())
    baselines = report["baselines"]
    assert isinstance(baselines, list)
    summary = next(item for item in baselines if item["baseline_id"] == "B1")
    assert summary["execution_status"] == "not_run"
    assert summary["next_action_correct"] is None
