from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from tests.helpers import git, make_demo_repository
from threadline.git_repository import (
    MAX_TEXT_BYTES,
    GitRepositoryError,
    evidence_from_git_file,
    read_committed_content_hashes,
    read_git_snapshot,
    read_git_working_state,
    threadline_git_state_path,
)


def test_reads_only_commit_bound_text_files(tmp_path: Path) -> None:
    root = make_demo_repository(tmp_path)
    (root / "ignored.dat").write_text("not an allowed source type")
    (root / "invalid.md").write_bytes(b"\xff\xfe")
    (root / "large.md").write_text("x" * (MAX_TEXT_BYTES + 1))
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Threadline Test",
        "-c",
        "user.email=threadline@example.invalid",
        "commit",
        "-m",
        "Add filtered files",
    )

    repository_id = uuid4()
    result = read_git_snapshot(root / "src", repository_id)
    paths = {item.path for item in result.files}

    assert result.root == root.resolve()
    assert result.name == "threadline-demo"
    assert result.repository_version.repository_id == repository_id
    assert result.repository_version.branch == "feature/retry-jobs"
    assert result.repository_version.commit_sha == git(root, "rev-parse", "HEAD")
    assert "src/job_runner.py" in paths
    assert "ignored.dat" not in paths
    assert "invalid.md" not in paths
    assert "large.md" not in paths

    source = next(item for item in result.files if item.path == "src/job_runner.py")
    expected_hash = hashlib.sha256(source.content.encode()).hexdigest()
    assert source.content_hash == f"sha256:{expected_hash}"


def test_rejects_non_repository_and_detached_head(tmp_path: Path) -> None:
    directory = tmp_path / "not-a-repository"
    directory.mkdir()

    with pytest.raises(GitRepositoryError):
        read_git_snapshot(directory, uuid4())

    root = make_demo_repository(tmp_path)
    git(root, "checkout", "--detach")
    with pytest.raises(GitRepositoryError, match="detached HEAD"):
        read_git_snapshot(root, uuid4())


def test_reads_live_head_and_dirty_paths(tmp_path: Path) -> None:
    root = make_demo_repository(tmp_path)
    repository_id = uuid4()
    initial = read_git_working_state(root / "src", repository_id)

    assert initial.root == root.resolve()
    assert initial.repository_version.repository_id == repository_id
    assert initial.repository_version.commit_sha == git(root, "rev-parse", "HEAD")
    assert initial.dirty_paths == ()

    (root / "src" / "job_runner.py").write_text(
        (root / "src" / "job_runner.py").read_text() + "\n# unfinished local edit\n"
    )
    (root / "new-note.md").write_text("untracked context\n")
    dirty = read_git_working_state(root, repository_id)

    assert set(dirty.dirty_paths) == {"new-note.md", "src/job_runner.py"}


def test_repository_private_state_path_is_inside_git_metadata(tmp_path: Path) -> None:
    root = make_demo_repository(tmp_path)

    state_path = threadline_git_state_path(root)

    assert state_path == root / ".git" / "threadline" / "threadline.db"
    assert state_path.parent.parent == root / ".git"


def test_builds_immutable_evidence_locator(tmp_path: Path) -> None:
    result = read_git_snapshot(make_demo_repository(tmp_path), uuid4())
    source = next(item for item in result.files if item.path == "src/job_runner.py")
    tenant_id = uuid4()
    workspace_id = uuid4()
    actor_id = uuid4()

    evidence = evidence_from_git_file(
        source,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        repository_version=result.repository_version,
    )

    assert evidence.tenant_id == tenant_id
    assert evidence.workspace_id == workspace_id
    assert evidence.created_by == actor_id
    assert evidence.locator.content_hash == source.content_hash
    assert evidence.locator.uri.endswith("/src/job_runner.py")


def test_hashes_selected_committed_binary_and_filtered_files(tmp_path: Path) -> None:
    root = make_demo_repository(tmp_path)
    (root / "asset.bin").write_bytes(b"\x00\xffthreadline")
    (root / "ignored.txt").write_text("exact release input", encoding="utf-8")
    git(root, "add", "asset.bin", "ignored.txt")
    git(
        root,
        "-c",
        "user.name=Threadline Test",
        "-c",
        "user.email=threadline@example.invalid",
        "commit",
        "-m",
        "Add release inputs",
    )

    hashes = read_committed_content_hashes(
        root,
        commit_sha=git(root, "rev-parse", "HEAD"),
        relative_paths=("asset.bin", "ignored.txt", "missing.bin"),
    )

    assert hashes == {
        "asset.bin": f"sha256:{hashlib.sha256((root / 'asset.bin').read_bytes()).hexdigest()}",
        "ignored.txt": (
            f"sha256:{hashlib.sha256((root / 'ignored.txt').read_bytes()).hexdigest()}"
        ),
    }
