"""Load the committed executed benchmark without inflating its claim boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def default_benchmark_path() -> Path | None:
    """Find the repository report during local development or an explicit deployment."""

    configured = os.getenv("THREADLINE_BENCHMARK_REPORT")
    if configured:
        return Path(configured).expanduser().resolve()

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "evals" / "results" / "continuation-benchmark-v0.2.json"
        if candidate.is_file():
            return candidate
    return None


def load_benchmark_report(path: Path | None = None) -> dict[str, Any]:
    """Return the retained report after validating the public fields the UI relies on."""

    resolved = path or default_benchmark_path()
    if resolved is None or not resolved.is_file():
        raise FileNotFoundError("the executed benchmark report is unavailable")
    payload: object = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("benchmark report must be a JSON object")

    required = {
        "report",
        "dataset",
        "sample_size",
        "repository_count",
        "cases",
        "metrics",
        "limits",
        "claim_boundary",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise ValueError(f"benchmark report is missing required fields: {', '.join(missing)}")
    if not isinstance(payload["cases"], list) or not payload["cases"]:
        raise ValueError("benchmark report must contain executed cases")
    if payload["sample_size"] != len(payload["cases"]):
        raise ValueError("benchmark sample size must match the retained cases")
    return payload
