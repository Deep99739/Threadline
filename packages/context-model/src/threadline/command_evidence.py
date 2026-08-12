"""Execute an approved local check and record content-bound, reviewable evidence."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path, PurePosixPath
from time import perf_counter
from typing import Any

from threadline.git_repository import read_git_working_state
from threadline.manifest import ProjectManifest, read_worktree_manifest

REPORT_PATH = "threadline/test-report.json"
MAX_CAPTURED_OUTPUT_BYTES = 1_000_000
SENSITIVE_ARGUMENT_NAMES = ("token", "secret", "password", "api-key", "apikey")


def _relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value in {"", "."}:
        raise ValueError("included files must use non-empty repository-relative paths")
    return path.as_posix()


def _digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _redacted_command(command: tuple[str, ...]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    redact_inline_command = False
    for argument in command:
        if redact_inline_command:
            redacted.append("[INLINE_COMMAND_REDACTED]")
            redact_inline_command = False
            continue
        lowered = argument.lower()
        if redact_next:
            redacted.append("[REDACTED]")
            redact_next = False
            continue
        if argument.startswith("-") and any(name in lowered for name in SENSITIVE_ARGUMENT_NAMES):
            if "=" in argument:
                redacted.append(f"{argument.split('=', 1)[0]}=[REDACTED]")
            else:
                redacted.append(argument)
                redact_next = True
            continue
        if argument in {"-c", "--command"}:
            redacted.append(argument)
            redact_inline_command = True
            continue
        if "=" in argument:
            name, _value = argument.split("=", 1)
            if any(sensitive in name.lower() for sensitive in SENSITIVE_ARGUMENT_NAMES):
                redacted.append(f"{name}=[REDACTED]")
                continue
        redacted.append(argument)
    return redacted


def _update_manifest(root: Path, current: ProjectManifest) -> None:
    payload = current.model_dump(mode="json")
    if not any(
        item.get("kind") == "test_report_scope" and item.get("path") == REPORT_PATH
        for item in payload["verifiers"]
    ):
        payload["verifiers"].append(
            {
                "kind": "test_report_scope",
                "path": REPORT_PATH,
            }
        )
    updated = ProjectManifest.model_validate(payload)
    (root / "threadline.json").write_text(
        json.dumps(updated.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )


def run_and_record_check(
    repository_path: Path,
    *,
    command: tuple[str, ...],
    include_paths: tuple[str, ...],
    scope: str,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Run one exact command and write a report without persisting its raw output."""

    if not command or not command[0]:
        raise ValueError("command is required")
    if scope not in {"FULL", "FOCUSED"}:
        raise ValueError("scope must be FULL or FOCUSED")
    if not include_paths:
        raise ValueError("at least one included file is required")
    if not 1 <= timeout_seconds <= 3600:
        raise ValueError("timeout must be between 1 and 3600 seconds")

    root, manifest = read_worktree_manifest(repository_path)
    live = read_git_working_state(root, manifest.repository_id)
    if "threadline.json" in live.dirty_paths:
        raise ValueError(
            "threadline.json already has uncommitted changes; review, commit, or revert "
            "them before recording command evidence"
        )

    paths = tuple(dict.fromkeys(_relative_path(item) for item in include_paths))
    tested_hashes: dict[str, str] = {}
    for path in paths:
        candidate = root / path
        if not candidate.is_file():
            raise FileNotFoundError(f"included evidence file was not found: {path}")
        tested_hashes[path] = _digest(candidate.read_bytes())

    started = perf_counter()
    command_environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("COV_CORE_") and not key.startswith("COVERAGE_")
    }
    completed = subprocess.run(
        list(command),
        cwd=root,
        check=False,
        capture_output=True,
        timeout=timeout_seconds,
        env=command_environment,
    )
    duration_ms = (perf_counter() - started) * 1000
    captured = (completed.stdout + completed.stderr)[:MAX_CAPTURED_OUTPUT_BYTES]
    output_truncated = len(completed.stdout) + len(completed.stderr) > len(captured)
    status = "PASSED" if completed.returncode == 0 else "FAILED"
    report = {
        "schema_version": 1,
        "scope": scope,
        "status": status,
        "exit_code": completed.returncode,
        "tested_content_hashes": tested_hashes,
        "runner": {
            "argv": _redacted_command(command),
            "python": platform.python_version(),
        },
        "duration_ms": round(duration_ms, 3),
        "output_digest": _digest(captured),
        "output_bytes": len(captured),
        "output_truncated": output_truncated,
        "privacy": "raw stdout and stderr are intentionally not persisted",
    }
    report_path = root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _update_manifest(root, manifest)
    return {
        "status": status,
        "exit_code": completed.returncode,
        "duration_ms": report["duration_ms"],
        "report": str(report_path),
        "tested_paths": list(paths),
        "raw_output_persisted": False,
        "paths_to_commit_together": [*paths, "threadline.json", REPORT_PATH],
        "next": (
            "Review the changed files and report, commit them together, then run "
            f"threadline sync {root}."
        ),
    }
