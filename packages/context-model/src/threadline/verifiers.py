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
            path in context.files and context.files[path].content_hash == content_hash
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
    version = "1.0.0"

    def __init__(self, code_path: str, decision_path: str) -> None:
        self.code_path = code_path
        self.decision_path = decision_path

    def verify(self, context: VerificationContext) -> VerifiedClaim:
        code_evidence = context.evidence_by_path[self.code_path]
        decision_evidence = context.evidence_by_path[self.decision_path]
        tree, _ = _python_tree(context, self.code_path)
        runner = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == "run_job"
            ),
            None,
        )
        retry_is_wired = runner is not None and _calls_symbol(runner, "RetryPolicy")
        claim = Claim(
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            created_by=context.actor_id,
            repository_version=context.repository_version,
            task_id=context.task_id,
            claim_type=ClaimType.BEHAVIOR,
            subject_key="run_job",
            predicate="retries_preserve_original_idempotency_key",
            value={"retry_is_wired": retry_is_wired, "preserves_key": None},
            epistemic_state=EpistemicState.UNKNOWN,
            evidence=(
                EvidenceLink(evidence_id=code_evidence.id, relation=EvidenceRelation.SUPPORTS),
                EvidenceLink(
                    evidence_id=decision_evidence.id,
                    relation=EvidenceRelation.SUPPORTS,
                ),
            ),
            freshness_rule="invalidate_on_runner_or_integration_test_change",
        )
        return VerifiedClaim(claim=claim, verification=None)
