"""Deterministic local evidence exclusions, redaction, and trust signals."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase

from threadline.git_repository import GitFile

REDACTION = "[THREADLINE_REDACTED:{kind}]"


@dataclass(frozen=True)
class SafeEvidenceContent:
    content: str
    content_hash: str
    redaction_kinds: tuple[str, ...]

    @property
    def redacted(self) -> bool:
        return bool(self.redaction_kinds)


SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
            r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,255}\b")),
    ("github_token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,255}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,255}\b")),
    ("provider_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,255}\b")),
    (
        "credential_assignment",
        re.compile(
            r"(?im)(\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|"
            r"client[_-]?secret|password|passwd|secret)\b\s*[:=]\s*)"
            r"(?P<quote>[\"']?)(?P<value>[^\s\"']{8,})(?P=quote)"
        ),
    ),
    (
        "credential_url",
        re.compile(r"(?i)\b(https?://[^\s:/@]+:)([^\s/@]{4,})(@)"),
    ),
)

INSTRUCTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override_instructions",
        re.compile(r"(?i)\b(ignore|disregard|override)\b.{0,40}\binstructions?\b"),
    ),
    (
        "scope_expansion",
        re.compile(r"(?i)\b(read|open|access|exfiltrate)\b.{0,45}\b(other|another)\b.{0,20}\b(repository|workspace|tenant)\b"),
    ),
    (
        "self_approval",
        re.compile(r"(?i)\b(mark|treat|declare)\b.{0,30}\b(approved|verified)\b"),
    ),
    ("system_prompt_request", re.compile(r"(?i)\b(system prompt|hidden instructions)\b")),
)


def _digest(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"


def path_is_excluded(path: str, patterns: tuple[str, ...]) -> bool:
    """Apply committed, repository-relative glob exclusions."""

    return any(fnmatchcase(path, pattern) for pattern in patterns)


def detect_instruction_signals(content: str) -> tuple[str, ...]:
    """Flag instruction-shaped repository data without executing or deleting it."""

    return tuple(
        kind for kind, pattern in INSTRUCTION_PATTERNS if pattern.search(content) is not None
    )


def redact_evidence_content(content: str) -> SafeEvidenceContent:
    """Redact known credential forms while preserving surrounding review context."""

    result = content
    found: list[str] = []
    for kind, pattern in SECRET_PATTERNS:
        replacement = REDACTION.format(kind=kind)

        def replace(
            match: re.Match[str],
            *,
            matched_kind: str = kind,
            marker: str = replacement,
        ) -> str:
            found.append(matched_kind)
            if matched_kind == "credential_assignment":
                return f"{match.group(1)}\"{marker}\""
            if matched_kind == "credential_url":
                return f"{match.group(1)}{marker}{match.group(3)}"
            return marker

        result = pattern.sub(replace, result)
    return SafeEvidenceContent(
        content=result,
        content_hash=_digest(result),
        redaction_kinds=tuple(dict.fromkeys(found)),
    )


def safe_git_file(file: GitFile) -> SafeEvidenceContent:
    """Build the persistable representation of one immutable Git file."""

    return redact_evidence_content(file.content)
