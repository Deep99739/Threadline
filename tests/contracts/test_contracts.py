from __future__ import annotations

import json
from pathlib import Path

from scripts.check_foundation import main as check_foundation
from scripts.validate_contracts import main as validate_contracts

ROOT = Path(__file__).resolve().parents[2]


def test_tracked_contract_examples_validate() -> None:
    validate_contracts()


def test_repository_foundation_gate_passes() -> None:
    check_foundation()


def test_eval_labels_are_frozen_and_unique() -> None:
    dataset = ROOT / "evals" / "datasets" / "v0.1" / "continuation_cases.jsonl"
    cases = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines()]

    assert len(cases) == 30
    assert len({case["id"] for case in cases}) == 30
    assert any(case["expected"]["must_abstain"] for case in cases)
    assert any(case["expected"]["forbidden_evidence"] for case in cases)
