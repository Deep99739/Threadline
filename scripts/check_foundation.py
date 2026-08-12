"""Enforce the public repository foundation and evidence gates."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = (
    "README.md",
    "packages/context-model/src/threadline/models.py",
    "packages/context-model/src/threadline/invariants.py",
    "packages/contracts/schemas/context-pack.schema.json",
    "packages/contracts/schemas/eval-case.schema.json",
    "docs/threat-model/THREAT_MODEL_V1.md",
    "demo/expected/primary_demo.json",
    ".github/workflows/ci.yml",
)


def _load_cases() -> list[dict[str, object]]:
    dataset = ROOT / "evals" / "datasets" / "v0.1" / "continuation_cases.jsonl"
    with dataset.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    missing = [path for path in REQUIRED_PATHS if not (ROOT / path).is_file()]
    if missing:
        raise SystemExit(f"Missing foundation paths: {', '.join(missing)}")

    adrs = sorted((ROOT / "docs" / "adr").glob("ADR-0??-*.md"))
    if len(adrs) != 14:
        raise SystemExit(f"Expected fourteen current ADRs, found {len(adrs)}")

    cases = _load_cases()
    if not 25 <= len(cases) <= 40:
        raise SystemExit(f"Expected 25-40 foundation eval cases, found {len(cases)}")

    case_ids = [str(case["id"]) for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise SystemExit("Evaluation case IDs must be unique")

    case_types = {str(case["case_type"]) for case in cases}
    required_types = {
        "continuation",
        "conflict",
        "freshness",
        "retrieval",
        "permission",
        "injection",
        "secret",
        "ingestion",
        "degraded_mode",
    }
    if case_types != required_types:
        raise SystemExit(f"Evaluation type coverage mismatch: {sorted(case_types)}")

    print(f"Foundation structure passes: 14 ADRs and {len(cases)} eval cases.")


if __name__ == "__main__":
    main()
