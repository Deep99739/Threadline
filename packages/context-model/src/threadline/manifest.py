"""Versioned, repository-owned configuration for a Threadline workspace."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from threadline.git_repository import GitSnapshot, resolve_git_root
from threadline.models import ActorType, EpistemicState

MANIFEST_PATH = "threadline.json"


def _repository_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value in {"", "."}:
        raise ValueError("evidence paths must be non-empty repository-relative paths")
    return path.as_posix()


def _repository_glob(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value in {"", "."} or "\\" in value:
        raise ValueError("exclusions must be non-empty repository-relative glob patterns")
    if value == MANIFEST_PATH:
        raise ValueError(f"{MANIFEST_PATH} cannot be excluded")
    return value


class ManifestContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TaskManifest(ManifestContract):
    id: UUID = Field(default_factory=uuid4)
    objective: str = Field(min_length=1)
    status: str = Field(default="IN_PROGRESS", min_length=1)
    next_action: str = Field(min_length=1)
    query: str = Field(min_length=1)


class DecisionManifest(ManifestContract):
    key: str = Field(min_length=1)
    status: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    rejected_alternatives: tuple[str, ...] = ()
    approved_by: UUID | None = None
    source_path: str = MANIFEST_PATH

    _validate_source_path = field_validator("source_path")(_repository_relative)


class ConstraintManifest(ManifestContract):
    key: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    severity: str = Field(default="HIGH", min_length=1)
    approved_by: UUID | None = None
    source_path: str = MANIFEST_PATH

    _validate_source_path = field_validator("source_path")(_repository_relative)


class ObservationManifest(ManifestContract):
    actor_type: ActorType
    statement: str = Field(min_length=1)
    state: EpistemicState = EpistemicState.ASSERTED
    source_path: str = MANIFEST_PATH

    _validate_source_path = field_validator("source_path")(_repository_relative)

    @field_validator("state")
    @classmethod
    def observation_cannot_self_certify(cls, value: EpistemicState) -> EpistemicState:
        if value is EpistemicState.VERIFIED:
            raise ValueError("repository observations cannot self-certify as VERIFIED")
        return value


class PythonSymbolVerifierManifest(ManifestContract):
    kind: Literal["python_symbol_exists"]
    path: str
    symbol: str = Field(min_length=1)

    _validate_path = field_validator("path")(_repository_relative)


class PythonCallPathVerifierManifest(ManifestContract):
    kind: Literal["python_call_path"]
    path: str
    caller: str = Field(min_length=1)
    referenced_symbol: str = Field(min_length=1)

    _validate_path = field_validator("path")(_repository_relative)


class TestReportVerifierManifest(ManifestContract):
    kind: Literal["test_report_scope"]
    path: str

    _validate_path = field_validator("path")(_repository_relative)


class IdempotencyVerifierManifest(ManifestContract):
    kind: Literal["idempotency_behavior"]
    code_path: str
    decision_path: str
    integration_test_path: str | None = None
    test_report_path: str | None = None

    @field_validator(
        "code_path",
        "decision_path",
        "integration_test_path",
        "test_report_path",
    )
    @classmethod
    def validate_optional_paths(cls, value: str | None) -> str | None:
        return None if value is None else _repository_relative(value)


VerifierManifest = Annotated[
    PythonSymbolVerifierManifest
    | PythonCallPathVerifierManifest
    | TestReportVerifierManifest
    | IdempotencyVerifierManifest,
    Field(discriminator="kind"),
]


class ProjectManifest(ManifestContract):
    schema_version: Literal[1] = 1
    repository_id: UUID = Field(default_factory=uuid4)
    task: TaskManifest
    decisions: tuple[DecisionManifest, ...] = ()
    constraints: tuple[ConstraintManifest, ...] = ()
    observations: tuple[ObservationManifest, ...] = ()
    verifiers: tuple[VerifierManifest, ...] = ()
    evidence_exclusions: tuple[str, ...] = ()

    @field_validator("evidence_exclusions")
    @classmethod
    def validate_evidence_exclusions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_repository_glob(value) for value in values)


def manifest_from_git_snapshot(snapshot: GitSnapshot) -> ProjectManifest:
    manifest_file = next((item for item in snapshot.files if item.path == MANIFEST_PATH), None)
    if manifest_file is None:
        raise ValueError(
            f"{MANIFEST_PATH} is not committed at {snapshot.repository_version.commit_sha}"
        )
    manifest = ProjectManifest.model_validate_json(manifest_file.content)
    if manifest.repository_id != snapshot.repository_version.repository_id:
        raise ValueError("manifest repository_id does not match the authorized repository scope")
    return manifest


def read_worktree_manifest(repository_path: Path) -> tuple[Path, ProjectManifest]:
    root = resolve_git_root(repository_path)
    path = root / MANIFEST_PATH
    if not path.is_file():
        raise FileNotFoundError(f"Threadline manifest was not found: {path}")
    return root, ProjectManifest.model_validate_json(path.read_text())


def initialize_manifest(
    repository_path: Path,
    *,
    objective: str,
    next_action: str,
) -> tuple[Path, ProjectManifest]:
    root = resolve_git_root(repository_path)
    path = root / MANIFEST_PATH
    if path.exists():
        raise FileExistsError(f"Threadline manifest already exists: {path}")
    manifest = ProjectManifest(
        task=TaskManifest(
            objective=objective,
            next_action=next_action,
            query=f"{objective} {next_action}",
        )
    )
    path.write_text(json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n")
    return path, manifest
