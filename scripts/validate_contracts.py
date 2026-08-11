"""Validate tracked external contracts and examples."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "packages" / "contracts" / "schemas"


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_jsonl(path: Path) -> list[Any]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def validate_instance(schema_name: str, instance: Any) -> None:
    schema = load_json(SCHEMAS / schema_name)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(instance)


def main() -> None:
    validate_instance(
        "context-pack.schema.json",
        load_json(ROOT / "packages" / "contracts" / "examples" / "context-pack.json"),
    )
    cases = load_jsonl(ROOT / "evals" / "datasets" / "v0.1" / "continuation_cases.jsonl")
    for case in cases:
        validate_instance("eval-case.schema.json", case)
    print(f"Validated 1 context-pack example and {len(cases)} evaluation cases.")


if __name__ == "__main__":
    main()
