"""Deterministic verifiers for the initial Threadline continuation scenario."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from threadline.git_repository import GitFile
from threadline.models import (
    Claim,
    ClaimType,
    EpistemicState,
    Evidence,
    EvidenceLink,
    EvidenceRelation,
    RepositoryVersion,
    Verification,
    VerificationResult,
    VerifierKind,
)


@dataclass(frozen=True)
class VerificationContext:
    tenant_id: UUID
    workspace_id: UUID
    actor_id: UUID
    task_id: UUID
    repository_version: RepositoryVersion
    files: dict[str, GitFile]
    content_hashes: dict[str, str]
    evidence_by_path: dict[str, Evidence]


@dataclass(frozen=True)
class VerifiedClaim:
    claim: Claim
    verification: Verification | None


class ClaimVerifier(Protocol):
    key: str
    version: str

    def verify(self, context: VerificationContext) -> VerifiedClaim: ...


def _input_hash(*values: str) -> str:
    digest = hashlib.sha256("\n".join(values).encode()).hexdigest()
    return f"sha256:{digest}"


def _verification(
    *,
    context: VerificationContext,
    claim: Claim,
    evidence_ids: tuple[UUID, ...],
    verifier_key: str,
    verifier_version: str,
    result: VerificationResult,
) -> Verification:
    return Verification(
        tenant_id=context.tenant_id,
        workspace_id=context.workspace_id,
        created_by=context.actor_id,
        claim_id=claim.id,
        verifier_key=verifier_key,
        verifier_version=verifier_version,
        verifier_kind=VerifierKind.DETERMINISTIC,
        input_hash=_input_hash(
            context.repository_version.commit_sha,
            claim.subject_key,
            claim.predicate,
            *(str(item) for item in evidence_ids),
        ),
        result=result,
        evidence_ids=evidence_ids,
        executed_at=datetime.now(UTC),
    )


def _python_tree(context: VerificationContext, path: str) -> tuple[ast.Module, Evidence]:
    git_file = context.files[path]
    return ast.parse(git_file.content, filename=path), context.evidence_by_path[path]


def _calls_symbol(tree: ast.AST, symbol: str) -> bool:
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == symbol
        for node in ast.walk(tree)
    )


def _function(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    return next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name
        ),
        None,
    )


def _calls_argument_unchanged(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    callable_name: str,
    argument_name: str,
) -> bool:
    calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == callable_name
    ]
    if not calls:
        return False
    direct = all(
        call.args and isinstance(call.args[0], ast.Name) and call.args[0].id == argument_name
        for call in calls
    )
    reassigned = any(
        isinstance(node, ast.Name) and node.id == argument_name and isinstance(node.ctx, ast.Store)
        for node in ast.walk(function)
    )
    return direct and not reassigned


class PythonSymbolExistsVerifier:
    key = "python_symbol_exists"
    version = "1.0.0"

    def __init__(self, path: str, symbol: str) -> None:
        self.path = path
        self.symbol = symbol

    def verify(self, context: VerificationContext) -> VerifiedClaim:
        tree, evidence = _python_tree(context, self.path)
        exists = any(
            isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == self.symbol
            for node in ast.walk(tree)
        )
        relation = EvidenceRelation.SUPPORTS if exists else EvidenceRelation.CONTRADICTS
        state = EpistemicState.VERIFIED if exists else EpistemicState.CONTRADICTED
        result = VerificationResult.VERIFIED if exists else VerificationResult.CONTRADICTED
        claim = Claim(
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            created_by=context.actor_id,
            repository_version=context.repository_version,
            task_id=context.task_id,
            claim_type=ClaimType.IMPLEMENTATION,
            subject_key=self.symbol,
            predicate="exists_at_commit",
            value=exists,
            epistemic_state=state,
            evidence=(EvidenceLink(evidence_id=evidence.id, relation=relation),),
            freshness_rule=f"invalidate_on_change:{self.path}",
        )
        return VerifiedClaim(
            claim=claim,
            verification=_verification(
                context=context,
                claim=claim,
                evidence_ids=(evidence.id,),
                verifier_key=self.key,
                verifier_version=self.version,
                result=result,
            ),
        )


class PythonCallPathVerifier:
    key = "python_call_path"
    version = "1.0.0"

    def __init__(self, path: str, caller: str, referenced_symbol: str) -> None:
        self.path = path
        self.caller = caller
        self.referenced_symbol = referenced_symbol

    def verify(self, context: VerificationContext) -> VerifiedClaim:
        tree, evidence = _python_tree(context, self.path)
        caller_node = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name == self.caller
            ),
            None,
        )
        referenced = False
        if caller_node is not None:
            referenced = _calls_symbol(caller_node, self.referenced_symbol)
        relation = EvidenceRelation.SUPPORTS if referenced else EvidenceRelation.CONTRADICTS
        state = EpistemicState.VERIFIED if referenced else EpistemicState.CONTRADICTED
        result = VerificationResult.VERIFIED if referenced else VerificationResult.CONTRADICTED
        claim = Claim(
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            created_by=context.actor_id,
            repository_version=context.repository_version,
            task_id=context.task_id,
            claim_type=ClaimType.IMPLEMENTATION,
            subject_key=self.caller,
            predicate=f"references:{self.referenced_symbol}",
            value=referenced,
            epistemic_state=state,
            evidence=(EvidenceLink(evidence_id=evidence.id, relation=relation),),
            freshness_rule=f"invalidate_on_change:{self.path}",
        )
        return VerifiedClaim(
            claim=claim,
            verification=_verification(
                context=context,
                claim=claim,
                evidence_ids=(evidence.id,),
                verifier_key=self.key,
                verifier_version=self.version,
                result=result,
            ),
        )


class TestReportScopeVerifier:
    key = "test_report_scope"
    version = "1.0.0"

    def __init__(self, path: str) -> None:
        self.path = path

    def verify(self, context: VerificationContext) -> VerifiedClaim:
        git_file = context.files[self.path]
        evidence = context.evidence_by_path[self.path]
        report = json.loads(git_file.content)
        tested_hashes = report.get("tested_content_hashes", {})
        hashes_are_current = bool(tested_hashes) and all(
            context.content_hashes.get(path) == content_hash
            for path, content_hash in tested_hashes.items()
        )
        full_pass = (
            report.get("scope") == "FULL"
            and report.get("status") == "PASSED"
            and hashes_are_current
        )
        failed = report.get("status") == "FAILED"
        if full_pass:
            relation = EvidenceRelation.SUPPORTS
            state = EpistemicState.VERIFIED
            result = VerificationResult.VERIFIED
        elif failed:
            relation = EvidenceRelation.CONTRADICTS
            state = EpistemicState.CONTRADICTED
            result = VerificationResult.CONTRADICTED
        else:
            relation = EvidenceRelation.SUPPORTS
            state = (
                EpistemicState.STALE
                if tested_hashes and not hashes_are_current
                else EpistemicState.UNKNOWN
            )
            result = VerificationResult.INSUFFICIENT_EVIDENCE
        claim = Claim(
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            created_by=context.actor_id,
            repository_version=context.repository_version,
            task_id=context.task_id,
            claim_type=ClaimType.COMPLETION,
            subject_key="test_suite",
            predicate="all_tests_passed",
            value={"full_pass": full_pass, "tested_content_is_current": hashes_are_current},
            epistemic_state=state,
            evidence=(EvidenceLink(evidence_id=evidence.id, relation=relation),),
            freshness_rule="invalidate_on_commit_or_test_report_change",
        )
        return VerifiedClaim(
            claim=claim,
            verification=_verification(
                context=context,
                claim=claim,
                evidence_ids=(evidence.id,),
                verifier_key=self.key,
                verifier_version=self.version,
                result=result,
            ),
        )


class IdempotencyBehaviorVerifier:
    key = "idempotency_behavior"
    version = "2.0.0"

    def __init__(
        self,
        code_path: str,
        decision_path: str,
        integration_test_path: str | None = None,
        test_report_path: str | None = None,
    ) -> None:
        self.code_path = code_path
        self.decision_path = decision_path
        self.integration_test_path = integration_test_path
        self.test_report_path = test_report_path

    def verify(self, context: VerificationContext) -> VerifiedClaim:
        code_evidence = context.evidence_by_path[self.code_path]
        decision_evidence = context.evidence_by_path[self.decision_path]
        tree, _ = _python_tree(context, self.code_path)
        runner = _function(tree, "run_job")
        retry_is_wired = runner is not None and _calls_symbol(runner, "RetryPolicy")
        preserves_key_in_code = runner is not None and _calls_argument_unchanged(
            runner,
            callable_name="operation",
            argument_name="idempotency_key",
        )
        integration_test_covers_key = False
        report_is_full_and_current = False
        extra_evidence: list[Evidence] = []
        if self.integration_test_path is not None and self.integration_test_path in context.files:
            test_tree, test_evidence = _python_tree(context, self.integration_test_path)
            test_function = _function(
                test_tree,
                "test_run_job_reuses_original_idempotency_key",
            )
            integration_test_covers_key = (
                test_function is not None
                and _calls_symbol(test_function, "run_job")
                and any(isinstance(node, ast.Assert) for node in ast.walk(test_function))
            )
            extra_evidence.append(test_evidence)
        if self.test_report_path is not None and self.test_report_path in context.files:
            report_file = context.files[self.test_report_path]
            report = json.loads(report_file.content)
            tested_hashes = report.get("tested_content_hashes", {})
            hashes_are_current = bool(tested_hashes) and all(
                context.content_hashes.get(path) == content_hash
                for path, content_hash in tested_hashes.items()
            )
            report_is_full_and_current = (
                report.get("scope") == "FULL"
                and report.get("status") == "PASSED"
                and hashes_are_current
                and self.code_path in tested_hashes
                and self.integration_test_path in tested_hashes
            )
            extra_evidence.append(context.evidence_by_path[self.test_report_path])

        preserves_key = (
            retry_is_wired
            and preserves_key_in_code
            and integration_test_covers_key
            and report_is_full_and_current
        )
        evidence_items = [code_evidence, decision_evidence, *extra_evidence]
        state = EpistemicState.VERIFIED if preserves_key else EpistemicState.UNKNOWN
        claim = Claim(
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            created_by=context.actor_id,
            repository_version=context.repository_version,
            task_id=context.task_id,
            claim_type=ClaimType.BEHAVIOR,
            subject_key="run_job",
            predicate="retries_preserve_original_idempotency_key",
            value={
                "retry_is_wired": retry_is_wired,
                "preserves_key_in_code": preserves_key_in_code,
                "integration_test_covers_key": integration_test_covers_key,
                "full_current_test_report": report_is_full_and_current,
                "preserves_key": preserves_key,
            },
            epistemic_state=state,
            evidence=tuple(
                EvidenceLink(evidence_id=item.id, relation=EvidenceRelation.SUPPORTS)
                for item in evidence_items
            ),
            freshness_rule="invalidate_on_runner_or_integration_test_change",
        )
        if not preserves_key:
            return VerifiedClaim(claim=claim, verification=None)
        return VerifiedClaim(
            claim=claim,
            verification=_verification(
                context=context,
                claim=claim,
                evidence_ids=tuple(item.id for item in evidence_items),
                verifier_key=self.key,
                verifier_version=self.version,
                result=VerificationResult.VERIFIED,
            ),
        )
