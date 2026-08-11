"""Deterministic Agent B proof for the flagship continuation scenario."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from mcp import Client

from threadline.agent_client import AgentHandoff, read_agent_handoff
from threadline.demo import DEMO_TASK_ID
from threadline.mcp_server import create_mcp_server
from threadline.service import ServiceScope, ThreadlineService
from threadline.storage import ThreadlineStore

RUNNER_SOURCE = '''"""Synthetic queue runner completed by the second coding agent."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.25

    def delays(self) -> tuple[float, ...]:
        return tuple(
            self.base_delay_seconds * 2**attempt for attempt in range(self.max_attempts - 1)
        )


def run_job[Result](
    operation: Callable[[str], Result],
    idempotency_key: str,
    policy: RetryPolicy | None = None,
) -> Result:
    """Retry a failed operation without changing its idempotency identity."""

    active_policy = policy or RetryPolicy()
    for attempt in range(active_policy.max_attempts):
        try:
            return operation(idempotency_key)
        except Exception:
            if attempt + 1 == active_policy.max_attempts:
                raise
    raise RuntimeError("retry loop exhausted without returning or raising")
'''

TEST_SOURCE = """from src.job_runner import RetryPolicy, run_job


def test_retry_policy_builds_bounded_exponential_delays() -> None:
    policy = RetryPolicy(max_attempts=3, base_delay_seconds=0.25)

    assert policy.delays() == (0.25, 0.5)


def test_run_job_reuses_original_idempotency_key() -> None:
    attempted_keys: list[str] = []

    def operation(key: str) -> str:
        attempted_keys.append(key)
        if len(attempted_keys) < 3:
            raise RuntimeError("transient failure")
        return "completed"

    result = run_job(
        operation,
        "job-42",
        policy=RetryPolicy(max_attempts=3),
    )

    assert result == "completed"
    assert attempted_keys == ["job-42", "job-42", "job-42"]
"""


@dataclass(frozen=True)
class ContinuationProof:
    initial_commit: str
    resulting_commit: str
    action_taken: str
    cited_evidence_count: int
    live_drift_refused_before_ingest: bool
    stale_items: tuple[dict[str, Any], ...]
    stale_handoff_refused: bool
    final_context_version_id: UUID
    final_status: str
    verified_completed_work: tuple[str, ...]
    test_output: str

    def as_dict(self) -> dict[str, object]:
        return {
            "initial_commit": self.initial_commit,
            "resulting_commit": self.resulting_commit,
            "action_taken": self.action_taken,
            "cited_evidence_count": self.cited_evidence_count,
            "live_drift_refused_before_ingest": self.live_drift_refused_before_ingest,
            "stale_items": list(self.stale_items),
            "stale_handoff_refused": self.stale_handoff_refused,
            "final_context_version_id": str(self.final_context_version_id),
            "final_status": self.final_status,
            "verified_completed_work": list(self.verified_completed_work),
            "test_output": self.test_output,
        }


def _git(
    root: Path,
    *arguments: str,
    environment: dict[str, str] | None = None,
) -> str:
    command_environment = os.environ.copy()
    if environment:
        command_environment.update(environment)
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env=command_environment,
    )
    return result.stdout.strip()


def _content_hash(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _apply_expected_action(repository_path: Path, handoff: AgentHandoff) -> str:
    required_constraint = "Every retry attempt must reuse the original idempotency key."
    if required_constraint not in handoff.constraints:
        raise RuntimeError("Agent B refused: the required idempotency constraint is absent")
    if "Wire RetryPolicy into run_job" not in handoff.next_action:
        raise RuntimeError("Agent B refused: the expected next action was not selected")
    if not handoff.evidence:
        raise RuntimeError("Agent B refused: the next action has no inspectable evidence")

    runner = repository_path / "src" / "job_runner.py"
    tests = repository_path / "tests" / "test_retry_policy.py"
    report = repository_path / "threadline" / "test-report.json"
    runner.write_text(RUNNER_SOURCE, encoding="utf-8")
    tests.write_text(TEST_SOURCE, encoding="utf-8")

    test_environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("COV_CORE_") and not key.startswith("COVERAGE_")
    }
    test_result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-cov"],
        cwd=repository_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=test_environment,
    )
    output = (test_result.stdout + test_result.stderr).strip()
    report.write_text(
        json.dumps(
            {
                "scope": "FULL",
                "status": "PASSED" if test_result.returncode == 0 else "FAILED",
                "passed": 2 if test_result.returncode == 0 else 0,
                "failed": 0 if test_result.returncode == 0 else 1,
                "tested_content_hashes": {
                    "src/job_runner.py": _content_hash(runner),
                    "tests/test_retry_policy.py": _content_hash(tests),
                },
                "runner": "python -m pytest -q",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if test_result.returncode != 0:
        raise RuntimeError(f"Agent B change failed verification:\n{output}")

    _git(
        repository_path,
        "add",
        "src/job_runner.py",
        "tests/test_retry_policy.py",
        "threadline/test-report.json",
    )
    _git(
        repository_path,
        "-c",
        "user.name=Threadline Demo Agent B",
        "-c",
        "user.email=threadline-agent-b@example.invalid",
        "commit",
        "-m",
        "Complete retry continuation from cited handoff",
        environment={
            "GIT_AUTHOR_DATE": "2026-08-09T10:45:00Z",
            "GIT_COMMITTER_DATE": "2026-08-09T10:45:00Z",
        },
    )
    return output


async def run_agent_b_continuation(
    *,
    store: ThreadlineStore,
    scope: ServiceScope,
    repository_path: Path,
) -> ContinuationProof:
    """Run the complete Agent A to Agent B continuation lifecycle through MCP."""

    service = ThreadlineService(store)
    initial_snapshot = store.load_snapshot(
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        task_id=DEMO_TASK_ID,
    )
    initial = initial_snapshot.repository_version
    server = create_mcp_server(store, scope, DEMO_TASK_ID, repository_path)
    handoff = await read_agent_handoff(
        server,
        task_id=DEMO_TASK_ID,
        branch=initial.branch,
        commit_sha=initial.commit_sha,
    )
    test_output = _apply_expected_action(repository_path, handoff)
    resulting_commit = _git(repository_path, "rev-parse", "HEAD")

    async with Client(server) as client:
        drift_status_result = await client.call_tool("get_workspace_status", {})
        drift_context_result = await client.call_tool(
            "get_task_context",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": initial.branch,
                "commit_sha": initial.commit_sha,
            },
        )
        drift_status = drift_status_result.structured_content
        drift_context = drift_context_result.structured_content
        live_drift_refused_before_ingest = (
            isinstance(drift_status, dict)
            and drift_status.get("status") == "stale"
            and isinstance(drift_context, dict)
            and drift_context.get("status") == "abstained"
        )
        if not live_drift_refused_before_ingest:
            raise RuntimeError("Threadline served context after live repository drift")

    service.ingest(repository_path=repository_path, scope=scope)

    async with Client(
        create_mcp_server(store, scope, DEMO_TASK_ID, repository_path)
    ) as client:
        stale_result = await client.call_tool(
            "list_stale_context",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": initial.branch,
                "commit_sha": resulting_commit,
            },
        )
        stale_payload = stale_result.structured_content
        if not isinstance(stale_payload, dict) or stale_payload.get("status") != "stale":
            raise RuntimeError("Threadline failed to mark the prior handoff stale")
        stale_data = stale_payload.get("data", {})
        stale_items = stale_data.get("items", []) if isinstance(stale_data, dict) else []

        refused = await client.call_tool(
            "get_task_context",
            {
                "task_id": str(DEMO_TASK_ID),
                "branch": initial.branch,
                "commit_sha": resulting_commit,
            },
        )
        refused_payload = refused.structured_content
        stale_handoff_refused = (
            isinstance(refused_payload, dict) and refused_payload.get("status") == "abstained"
        )
        if not stale_handoff_refused:
            raise RuntimeError("Threadline served stale context after the repository changed")

    compiled = service.compile_task_handoff(
        scope=scope,
        task_id=DEMO_TASK_ID,
        query="verify retry completion and original idempotency key reuse",
    )
    final_status = (
        "partial" if compiled.content["unknowns"] or compiled.content["contradictions"] else "ok"
    )
    verified_completed_work = compiled.content.get("verified_completed_work")
    if not isinstance(verified_completed_work, list):
        raise RuntimeError("Compiled handoff omitted verified completed work")
    return ContinuationProof(
        initial_commit=initial.commit_sha,
        resulting_commit=resulting_commit,
        action_taken=handoff.next_action,
        cited_evidence_count=len(handoff.evidence),
        live_drift_refused_before_ingest=live_drift_refused_before_ingest,
        stale_items=tuple(item for item in stale_items if isinstance(item, dict)),
        stale_handoff_refused=stale_handoff_refused,
        final_context_version_id=compiled.context_version.id,
        final_status=final_status,
        verified_completed_work=tuple(str(item) for item in verified_completed_work),
        test_output=test_output,
    )
