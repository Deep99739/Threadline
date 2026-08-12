from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.helpers import git
from threadline.manifest import ProjectManifest, initialize_manifest


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-b", "main")
    (root / "README.md").write_text("# Example\n")
    git(root, "add", "README.md")
    git(
        root,
        "-c",
        "user.name=Threadline Test",
        "-c",
        "user.email=threadline@example.invalid",
        "commit",
        "-m",
        "Initialize repository",
    )
    return root


def test_initialize_manifest_creates_strict_repository_owned_contract(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    path, manifest = initialize_manifest(
        root,
        objective="Finish the parser with evidence",
        next_action="Add the missing integration test",
    )

    assert path == root / "threadline.json"
    assert ProjectManifest.model_validate_json(path.read_text()) == manifest
    assert manifest.task.query == (
        "Finish the parser with evidence Add the missing integration test"
    )
    with pytest.raises(FileExistsError, match="already exists"):
        initialize_manifest(root, objective="Other", next_action="Other")


def test_manifest_rejects_path_traversal_and_self_certified_observations() -> None:
    base = {
        "task": {
            "objective": "Continue safely",
            "next_action": "Run focused tests",
            "query": "continue",
        }
    }
    traversal = {
        **base,
        "constraints": [
            {
                "key": "boundary",
                "statement": "Stay in scope",
                "source_path": "../secret.txt",
            }
        ],
    }
    with pytest.raises(ValidationError, match="repository-relative"):
        ProjectManifest.model_validate(traversal)

    self_certified = {
        **base,
        "observations": [
            {
                "actor_type": "AGENT",
                "statement": "Everything works",
                "state": "VERIFIED",
            }
        ],
    }
    with pytest.raises(ValidationError, match="cannot self-certify"):
        ProjectManifest.model_validate(self_certified)


def test_manifest_rejects_unknown_verifier_fields() -> None:
    payload = {
        "task": {
            "objective": "Continue safely",
            "next_action": "Inspect parser",
            "query": "parser",
        },
        "verifiers": [
            {
                "kind": "python_symbol_exists",
                "path": "src/parser.py",
                "symbol": "Parser",
                "trust_me": True,
            }
        ],
    }

    with pytest.raises(ValidationError, match="Extra inputs"):
        ProjectManifest.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "pattern",
    ["../private/*", "/absolute/*", ".", "threadline.json", "private\\*"],
)
def test_manifest_rejects_unsafe_evidence_exclusions(pattern: str) -> None:
    payload = {
        "task": {
            "objective": "Continue safely",
            "next_action": "Inspect parser",
            "query": "parser",
        },
        "evidence_exclusions": [pattern],
    }

    with pytest.raises(ValidationError, match=r"exclud|repository-relative"):
        ProjectManifest.model_validate(payload)


def test_manifest_accepts_reviewable_repository_exclusions() -> None:
    manifest = ProjectManifest.model_validate(
        {
            "task": {
                "objective": "Continue safely",
                "next_action": "Inspect parser",
                "query": "parser",
            },
            "evidence_exclusions": ["private/*", "fixtures/**/*.json"],
        }
    )

    assert manifest.evidence_exclusions == ("private/*", "fixtures/**/*.json")
