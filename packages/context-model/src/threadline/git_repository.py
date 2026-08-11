"""Read an immutable, commit-bound snapshot from a local Git repository."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from threadline.models import Evidence, EvidenceLocator, RepositoryVersion, utc_now

MAX_TEXT_BYTES = 256_000
ALLOWED_SUFFIXES = {
    ".c",
    ".cpp",
    ".go",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".py",
    ".rs",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True)
class GitFile:
    path: str
    content: str
    content_hash: str


@dataclass(frozen=True)
class GitSnapshot:
    root: Path
    name: str
    repository_version: RepositoryVersion
    files: tuple[GitFile, ...]


class GitRepositoryError(ValueError):
    pass


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "git command failed"
        raise GitRepositoryError(message)
    return result.stdout.strip()


def resolve_git_root(path: Path) -> Path:
    """Resolve a path to its containing Git root without reading worktree files."""

    requested = path.resolve(strict=True)
    root = Path(_git(requested, "rev-parse", "--show-toplevel")).resolve(strict=True)
    branch = _git(root, "branch", "--show-current")
    if not branch:
        raise GitRepositoryError("detached HEAD is not accepted for a continuation task")
    return root


def read_git_snapshot(path: Path, repository_id: UUID) -> GitSnapshot:
    root = resolve_git_root(path)
    branch = _git(root, "branch", "--show-current")
    if not branch:
        raise GitRepositoryError("detached HEAD is not accepted for a continuation task")
    commit_sha = _git(root, "rev-parse", "HEAD")
    tracked_files = _git(root, "ls-tree", "-r", "--name-only", "HEAD").splitlines()

    files: list[GitFile] = []
    for relative_path in tracked_files:
        if Path(relative_path).suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        raw = subprocess.run(
            ["git", "-C", str(root), "show", f"HEAD:{relative_path}"],
            check=False,
            capture_output=True,
            timeout=15,
        )
        if raw.returncode != 0 or len(raw.stdout) > MAX_TEXT_BYTES:
            continue
        try:
            content = raw.stdout.decode("utf-8")
        except UnicodeDecodeError:
            continue
        digest = hashlib.sha256(raw.stdout).hexdigest()
        files.append(
            GitFile(
                path=relative_path,
                content=content,
                content_hash=f"sha256:{digest}",
            )
        )

    return GitSnapshot(
        root=root,
        name=root.name,
        repository_version=RepositoryVersion(
            repository_id=repository_id,
            branch=branch,
            commit_sha=commit_sha,
        ),
        files=tuple(files),
    )


def evidence_from_git_file(
    git_file: GitFile,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    actor_id: UUID,
    repository_version: RepositoryVersion,
) -> Evidence:
    return Evidence(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        created_by=actor_id,
        repository_version=repository_version,
        evidence_type="GIT_FILE",
        locator=EvidenceLocator(
            uri=f"repo://{repository_version.repository_id}/{git_file.path}",
            content_hash=git_file.content_hash,
        ),
        captured_at=utc_now(),
    )
