from __future__ import annotations

import json
from pathlib import Path

import pytest

from threadline.benchmark_report import load_benchmark_report


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_benchmark_report_requires_a_case_for_every_sample(tmp_path: Path) -> None:
    payload = {
        "report": "benchmark",
        "dataset": "synthetic",
        "sample_size": 1,
        "repository_count": 1,
        "cases": [{"id": "EXEC-001"}],
        "metrics": {},
        "limits": ["synthetic"],
        "claim_boundary": "synthetic",
    }

    assert load_benchmark_report(_write(tmp_path / "valid.json", payload)) == payload

    payload["sample_size"] = 2
    with pytest.raises(ValueError, match="sample size"):
        load_benchmark_report(_write(tmp_path / "mismatch.json", payload))


@pytest.mark.parametrize("payload", [[], {}, {"cases": []}])
def test_benchmark_report_fails_closed_on_unusable_content(
    tmp_path: Path, payload: object
) -> None:
    with pytest.raises(ValueError):
        load_benchmark_report(_write(tmp_path / "invalid.json", payload))
