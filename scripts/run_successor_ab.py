"""Run a private, real-model successor-agent A/B pilot against frozen repositories."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from threadline.manifest import ProjectManifest, initialize_manifest
from threadline.product_workflow import handoff_content, render_handoff_markdown
from threadline.workspace import sync_local_workspace

DEFAULT_CODEX = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Scenario:
    name: str
    objective: str
    next_action: str
    constraint: str
    transcript_filler: str


SCENARIOS = (
    Scenario(
        name="unicode-normalizer",
        objective="Harden identifier normalization without changing Unicode semantics",
        next_action="Add a regression test for Unicode whitespace before editing normalize",
        constraint="Do not use casefold because downstream identifiers remain case-sensitive",
        transcript_filler="We inspected cache behavior, logging names, and deployment notes.",
    ),
    Scenario(
        name="retry-budget",
        objective="Bound retry behavior without changing the public client interface",
        next_action="Add a failing integration test for a fourth transient failure",
        constraint="Keep the existing three-attempt budget and idempotency key",
        transcript_filler="We discussed metrics labels, queue names, and documentation cleanup.",
    ),
)

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "objective": {"type": "string"},
        "next_action": {"type": "string"},
        "constraint": {"type": "string"},
        "entry_point": {"type": "string"},
        "test_file": {"type": "string"},
    },
    "required": ["objective", "next_action", "constraint", "entry_point", "test_file"],
    "additionalProperties": False,
}


def _run(*arguments: str, cwd: Path) -> str:
    completed = subprocess.run(
        list(arguments),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return completed.stdout.strip()


def _write_repository(root: Path, scenario: Scenario) -> None:
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "normalizer.py").write_text(
        "def normalize(value: str) -> str:\n"
        "    \"\"\"Normalize surrounding ASCII whitespace.\"\"\"\n"
        "    return value.strip()\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_normalizer.py").write_text(
        "from src.normalizer import normalize\n\n\n"
        "def test_normalize_ascii_whitespace() -> None:\n"
        "    assert normalize(' value ') == 'value'\n",
        encoding="utf-8",
    )
    filler = "\n".join(f"Note {index}: {scenario.transcript_filler}" for index in range(80))
    (root / "prior-session.txt").write_text(
        f"{filler}\n\n"
        f"CURRENT OBJECTIVE: {scenario.objective}\n"
        f"NEXT ACTION: {scenario.next_action}\n"
        f"HARD CONSTRAINT: {scenario.constraint}\n"
        "Do not treat brainstorming above as current state.\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "# Successor benchmark fixture\n\nThe implementation lives in `src/normalizer.py`.\n",
        encoding="utf-8",
    )
    _run("git", "init", "-b", "main", cwd=root)
    _run("git", "config", "user.name", "Benchmark Fixture", cwd=root)
    _run("git", "config", "user.email", "benchmark@example.invalid", cwd=root)
    _run("git", "add", ".", cwd=root)
    _run("git", "commit", "-m", "Create successor fixture", cwd=root)


def _add_threadline(root: Path, scenario: Scenario) -> str:
    path, manifest = initialize_manifest(
        root,
        objective=scenario.objective,
        next_action=scenario.next_action,
    )
    payload = manifest.model_dump(mode="json")
    payload["constraints"] = [
        {
            "key": "continuation-safety",
            "statement": scenario.constraint,
            "severity": "HIGH",
            "source_path": "threadline.json",
        }
    ]
    updated = ProjectManifest.model_validate(payload)
    path.write_text(json.dumps(updated.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    _run("git", "add", "threadline.json", cwd=root)
    _run("git", "commit", "-m", "Add continuation contract", cwd=root)
    sync_local_workspace(root)
    return render_handoff_markdown(handoff_content(root))


def _prompt(condition: str, handoff: str | None) -> str:
    source = (
        "Use the compact Threadline handoff below as the primary continuation evidence.\n\n"
        f"{handoff}"
        if condition == "threadline"
        else (
            "You are succeeding another coding agent. Inspect the repository and its prior-session "
            "record to reconstruct the current handoff."
        )
    )
    return (
        f"{source}\n\n"
        "Return the current objective, next concrete action, hard constraint, likely code entry "
        "point, and relevant test file. Use UNKNOWN for anything not supported by evidence. "
        "Do not modify files."
    )


def parse_events(path: Path) -> tuple[dict[str, Any], dict[str, int], int]:
    response: dict[str, Any] = {}
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    tool_events = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("type") == "item.completed":
            item = event.get("item", {})
            if item.get("type") in {"command_execution", "mcp_tool_call", "tool_call"}:
                tool_events += 1
            if item.get("type") == "agent_message":
                response = json.loads(item.get("text", "{}"))
        if event.get("type") == "turn.completed":
            raw_usage = event.get("usage", {})
            usage = {
                "input_tokens": int(raw_usage.get("input_tokens", 0)),
                "cached_input_tokens": int(raw_usage.get("cached_input_tokens", 0)),
                "output_tokens": int(raw_usage.get("output_tokens", 0)),
            }
    return response, usage, tool_events


def score_response(response: dict[str, Any], expected: dict[str, str]) -> dict[str, Any]:
    def normalized(value: object) -> str:
        text = str(value).strip().lower()
        text = re.sub(r"\s+[—-]\s+.*$", "", text)
        text = re.sub(r":\d+(?::\d+)?$", "", text)
        text = text.removesuffix(".")
        return re.sub(r"\s+", " ", text)

    def matches(actual: object, expected_value: str) -> bool:
        actual_text = normalized(actual)
        expected_text = normalized(expected_value)
        return actual_text == expected_text or (
            "/" in expected_text and expected_text in actual_text
        )

    correct = sum(
        matches(response.get(key, UNKNOWN), value)
        for key, value in expected.items()
    )
    unsupported = sum(
        normalized(response.get(key, UNKNOWN)) != normalized(UNKNOWN)
        and not matches(response.get(key, UNKNOWN), value)
        for key, value in expected.items()
    )
    return {
        "correct_fields": correct,
        "total_fields": len(expected),
        "correctness": round(correct / len(expected), 4),
        "unsupported_fields": unsupported,
    }


def summarize_trials(trials: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the paired pilot without presenting a tiny sample as a benchmark claim."""

    conditions: dict[str, dict[str, float]] = {}
    for condition in ("repository_only", "threadline"):
        selected = [trial for trial in trials if trial["condition"] == condition]
        if not selected:
            continue
        count = len(selected)
        conditions[condition] = {
            "trials": float(count),
            "mean_duration_seconds": round(
                sum(float(trial["duration_seconds"]) for trial in selected) / count,
                3,
            ),
            "mean_input_tokens": round(
                sum(float(trial["usage"]["input_tokens"]) for trial in selected)
                / count,
                1,
            ),
            "mean_output_tokens": round(
                sum(float(trial["usage"]["output_tokens"]) for trial in selected)
                / count,
                1,
            ),
            "mean_tool_events": round(
                sum(float(trial["tool_events"]) for trial in selected) / count,
                2,
            ),
            "mean_correctness": round(
                sum(float(trial["score"]["correctness"]) for trial in selected)
                / count,
                4,
            ),
            "unsupported_fields": float(
                sum(int(trial["score"]["unsupported_fields"]) for trial in selected)
            ),
        }

    change: dict[str, float] = {}
    baseline = conditions.get("repository_only")
    threadline = conditions.get("threadline")
    if baseline is not None and threadline is not None:
        for name in ("duration_seconds", "input_tokens", "output_tokens", "tool_events"):
            baseline_value = baseline[f"mean_{name}"]
            threadline_value = threadline[f"mean_{name}"]
            if baseline_value:
                change[f"{name}_reduction"] = round(
                    (baseline_value - threadline_value) / baseline_value,
                    4,
                )
    return {
        "scope": "directional private pilot; not a universal product claim",
        "conditions": conditions,
        "threadline_change": change,
    }


def run_trial(
    *,
    codex: Path,
    repository: Path,
    condition: str,
    handoff: str | None,
    schema_path: Path,
    output_path: Path,
    expected: dict[str, str],
) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        [
            str(codex),
            "exec",
            "--ephemeral",
            "--json",
            "--ignore-user-config",
            "--ignore-rules",
            "--sandbox",
            "read-only",
            "--output-schema",
            str(schema_path),
            "-C",
            str(repository),
            _prompt(condition, handoff),
        ],
        check=False,
        stdout=output_path.open("w", encoding="utf-8"),
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=300,
    )
    duration = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(f"Codex trial failed for {condition} with exit {completed.returncode}")
    response, usage, tool_events = parse_events(output_path)
    return {
        "condition": condition,
        "duration_seconds": round(duration, 3),
        "tool_events": tool_events,
        "usage": usage,
        "response": response,
        "score": score_response(response, expected),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", type=Path, default=DEFAULT_CODEX)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--keep-workspace", type=Path)
    arguments = parser.parse_args()
    if not arguments.codex.is_file():
        raise FileNotFoundError(f"Codex executable was not found: {arguments.codex}")

    if arguments.keep_workspace is None:
        temporary = tempfile.TemporaryDirectory(prefix="threadline-successor-ab-")
        workspace = Path(temporary.name)
    else:
        temporary = None
        workspace = arguments.keep_workspace.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
    schema_path = workspace / "response-schema.json"
    schema_path.write_text(json.dumps(OUTPUT_SCHEMA, indent=2) + "\n", encoding="utf-8")
    trials: list[dict[str, Any]] = []
    try:
        for scenario in SCENARIOS:
            baseline = workspace / f"{scenario.name}-baseline"
            threadline = workspace / f"{scenario.name}-threadline"
            baseline.mkdir()
            _write_repository(baseline, scenario)
            shutil.copytree(baseline, threadline)
            handoff = _add_threadline(threadline, scenario)
            expected = {
                "objective": scenario.objective,
                "next_action": scenario.next_action,
                "constraint": scenario.constraint,
                "entry_point": "src/normalizer.py",
                "test_file": "tests/test_normalizer.py",
            }
            for condition, repository, supplied_handoff in (
                ("repository_only", baseline, None),
                ("threadline", threadline, handoff),
            ):
                trial = run_trial(
                    codex=arguments.codex,
                    repository=repository,
                    condition=condition,
                    handoff=supplied_handoff,
                    schema_path=schema_path,
                    output_path=workspace / f"{scenario.name}-{condition}.jsonl",
                    expected=expected,
                )
                trial["scenario"] = scenario.name
                trials.append(trial)
        report = {
            "kind": "private_real_model_pilot",
            "model_client": str(arguments.codex),
            "trial_count": len(trials),
            "summary": summarize_trials(trials),
            "trials": trials,
        }
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    main()
