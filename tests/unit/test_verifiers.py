from __future__ import annotations

import hashlib
import json
from uuid import UUID

import pytest

from threadline.git_repository import GitFile, evidence_from_git_file
from threadline.models import (
    EpistemicState,
    EvidenceRelation,
    RepositoryVersion,
    VerificationResult,
)
from threadline.verifiers import (
    IdempotencyBehaviorVerifier,
    PythonCallPathVerifier,
    PythonSymbolExistsVerifier,
    VerificationContext,
)
from threadline.verifiers import (
    TestReportScopeVerifier as ReportScopeVerifier,
)

TENANT_ID = UUID("40000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("40000000-0000-4000-8000-000000000002")
ACTOR_ID = UUID("40000000-0000-4000-8000-000000000003")
TASK_ID = UUID("40000000-0000-4000-8000-000000000004")
REPOSITORY_VERSION = RepositoryVersion(
    repository_id=UUID("40000000-0000-4000-8000-000000000005"),
    branch="feature/retry",
    commit_sha="abc1234",
)


def git_file(path: str, content: str) -> GitFile:
    digest = hashlib.sha256(content.encode()).hexdigest()
    return GitFile(path=path, content=content, content_hash=f"sha256:{digest}")


def context(*files: GitFile) -> VerificationContext:
    by_path = {item.path: item for item in files}
    evidence = {
        path: evidence_from_git_file(
            item,
            tenant_id=TENANT_ID,
            workspace_id=WORKSPACE_ID,
            actor_id=ACTOR_ID,
            repository_version=REPOSITORY_VERSION,
        )
        for path, item in by_path.items()
    }
    return VerificationContext(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        task_id=TASK_ID,
        repository_version=REPOSITORY_VERSION,
        files=by_path,
        content_hashes={path: item.content_hash for path, item in by_path.items()},
        evidence_by_path=evidence,
    )


@pytest.mark.parametrize(
    ("source", "expected_state", "expected_result", "expected_relation"),
    [
        (
            "class RetryPolicy:\n    pass\n",
            EpistemicState.VERIFIED,
            VerificationResult.VERIFIED,
            EvidenceRelation.SUPPORTS,
        ),
        (
            "def other():\n    pass\n",
            EpistemicState.CONTRADICTED,
            VerificationResult.CONTRADICTED,
            EvidenceRelation.CONTRADICTS,
        ),
    ],
)
def test_symbol_verifier_certifies_both_outcomes(
    source: str,
    expected_state: EpistemicState,
    expected_result: VerificationResult,
    expected_relation: EvidenceRelation,
) -> None:
    source_file = git_file("src/job_runner.py", source)

    verified = PythonSymbolExistsVerifier(source_file.path, "RetryPolicy").verify(
        context(source_file)
    )

    assert verified.claim.epistemic_state is expected_state
    assert verified.claim.evidence[0].relation is expected_relation
    assert verified.verification is not None
    assert verified.verification.result is expected_result
    assert verified.verification.input_hash.startswith("sha256:")


@pytest.mark.parametrize(
    ("source", "expected_state"),
    [
        (
            "class RetryPolicy:\n    pass\n\ndef run_job():\n    return RetryPolicy()\n",
            EpistemicState.VERIFIED,
        ),
        (
            "class RetryPolicy:\n    pass\n\ndef run_job():\n    return None\n",
            EpistemicState.CONTRADICTED,
        ),
        (
            "class RetryPolicy:\n    pass\n\n"
            "def run_job(policy: RetryPolicy):\n    return policy\n",
            EpistemicState.CONTRADICTED,
        ),
        ("class RetryPolicy:\n    pass\n", EpistemicState.CONTRADICTED),
    ],
)
def test_call_path_verifier_requires_reference_inside_caller(
    source: str, expected_state: EpistemicState
) -> None:
    source_file = git_file("src/job_runner.py", source)

    verified = PythonCallPathVerifier(source_file.path, "run_job", "RetryPolicy").verify(
        context(source_file)
    )

    assert verified.claim.epistemic_state is expected_state
    assert verified.verification is not None
    assert verified.verification.result.value == expected_state.value


@pytest.mark.parametrize(
    ("scope", "status", "content_hash", "expected_state", "is_current"),
    [
        ("FULL", "PASSED", "CURRENT", EpistemicState.VERIFIED, True),
        ("FOCUSED", "PASSED", "CURRENT", EpistemicState.UNKNOWN, True),
        ("FULL", "PASSED", "STALE", EpistemicState.STALE, False),
        ("FULL", "FAILED", "CURRENT", EpistemicState.CONTRADICTED, True),
    ],
)
def test_test_report_requires_full_pass_and_current_content(
    scope: str,
    status: str,
    content_hash: str,
    expected_state: EpistemicState,
    is_current: bool,
) -> None:
    source_file = git_file("src/job_runner.py", "def run_job():\n    pass\n")
    recorded_hash = source_file.content_hash if content_hash == "CURRENT" else "sha256:" + "0" * 64
    report = git_file(
        "threadline/test-report.json",
        json.dumps(
            {
                "scope": scope,
                "status": status,
                "tested_content_hashes": {source_file.path: recorded_hash},
            }
        ),
    )

    verified = ReportScopeVerifier(report.path).verify(context(source_file, report))

    assert verified.claim.epistemic_state is expected_state
    assert verified.claim.value["tested_content_is_current"] is is_current


def test_test_report_without_bound_content_is_not_certified() -> None:
    report = git_file(
        "threadline/test-report.json",
        json.dumps({"scope": "FULL", "status": "PASSED"}),
    )

    verified = ReportScopeVerifier(report.path).verify(context(report))

    assert verified.claim.epistemic_state is EpistemicState.UNKNOWN
    assert verified.claim.value["tested_content_is_current"] is False


@pytest.mark.parametrize("wired", [True, False])
def test_behavior_verifier_refuses_to_infer_runtime_idempotency(wired: bool) -> None:
    runner_body = "return RetryPolicy()" if wired else "return operation(key)"
    source = git_file(
        "src/job_runner.py",
        f"class RetryPolicy:\n    pass\n\ndef run_job(operation, key):\n    {runner_body}\n",
    )
    decision = git_file("threadline/decision.json", "{}")

    result = IdempotencyBehaviorVerifier(source.path, decision.path).verify(
        context(source, decision)
    )

    assert result.claim.epistemic_state is EpistemicState.UNKNOWN
    assert result.claim.value == {
        "retry_is_wired": wired,
        "preserves_key_in_code": False,
        "integration_test_covers_key": False,
        "full_current_test_report": False,
        "preserves_key": False,
    }
    assert result.verification is None
    assert len(result.claim.evidence) == 2


def test_behavior_verifier_certifies_key_reuse_only_with_current_full_test() -> None:
    source = git_file(
        "src/job_runner.py",
        "class RetryPolicy:\n"
        "    pass\n\n"
        "def run_job(operation, idempotency_key):\n"
        "    policy = RetryPolicy()\n"
        "    for _ in range(3):\n"
        "        try:\n"
        "            return operation(idempotency_key)\n"
        "        except Exception:\n"
        "            pass\n",
    )
    integration_test = git_file(
        "tests/test_retry_policy.py",
        "from src.job_runner import run_job\n\n"
        "def test_run_job_reuses_original_idempotency_key():\n"
        "    attempted_keys = []\n"
        "    result = run_job(lambda key: attempted_keys.append(key), 'job-42')\n"
        "    assert attempted_keys == ['job-42']\n",
    )
    decision = git_file("threadline/decision.json", "{}")
    report = git_file(
        "threadline/test-report.json",
        json.dumps(
            {
                "scope": "FULL",
                "status": "PASSED",
                "tested_content_hashes": {
                    source.path: source.content_hash,
                    integration_test.path: integration_test.content_hash,
                },
            }
        ),
    )

    result = IdempotencyBehaviorVerifier(
        source.path,
        decision.path,
        integration_test.path,
        report.path,
    ).verify(context(source, integration_test, decision, report))

    assert result.claim.epistemic_state is EpistemicState.VERIFIED
    assert result.claim.value["preserves_key"] is True
    assert result.verification is not None
    assert result.verification.result is VerificationResult.VERIFIED
