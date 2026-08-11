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


@dataclass(frozen=True)
class GitWorkingState:
    root: Path
    repository_version: RepositoryVersion
    dirty_paths: tuple[str, ...]


class GitRepositoryError(ValueError):
    pass


def _git(root: Path, *arguments: str, strip: bool = True) -> str:
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
    return result.stdout.strip() if strip else result.stdout


def resolve_git_root(path: Path) -> Path:
    """Resolve a path to its containing Git root without reading worktree files."""

    requested = path.resolve(strict=True)
    root = Path(_git(requested, "rev-parse", "--show-toplevel")).resolve(strict=True)
    branch = _git(root, "branch", "--show-current")
    if not branch:
        raise GitRepositoryError("detached HEAD is not accepted for a continuation task")
    return root


def threadline_git_state_path(path: Path) -> Path:
    """Return a repository-private state path that Git never exposes as worktree drift."""

    root = resolve_git_root(path)
    git_path = Path(_git(root, "rev-parse", "--git-path", "threadline/threadline.db"))
    if git_path.is_absolute():
        return git_path.resolve()
    return (root / git_path).resolve()


def read_git_working_state(path: Path, repository_id: UUID) -> GitWorkingState:
    """Read the live branch, HEAD, and dirty paths without trusting a caller-supplied version."""

    root = resolve_git_root(path)
    branch = _git(root, "branch", "--show-current")
    commit_sha = _git(root, "rev-parse", "HEAD")
    status = _git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        strip=False,
    )
    records = status.split("\0")
    dirty: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        if len(record) < 4:
            index += 1
            continue
        dirty_path = record[3:]
        if dirty_path:
            dirty.append(dirty_path)
        if (record[0] in "RC" or record[1] in "RC") and index + 1 < len(records):
            prior_path = records[index + 1]
            if prior_path:
                dirty.append(prior_path)
            index += 1
        index += 1
    dirty_paths = tuple(dict.fromkeys(dirty))
    return GitWorkingState(
        root=root,
        repository_version=RepositoryVersion(
            repository_id=repository_id,
            branch=branch,
            commit_sha=commit_sha,
        ),
        dirty_paths=dirty_paths,
    )


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
    evidence_type = {
        "threadline.json": "PROJECT_MANIFEST",
        "threadline/decision.json": "DECISION_RECORD",
        "threadline/observations.json": "OBSERVATION_RECORD",
        "threadline/test-report.json": "TEST_REPORT",
    }.get(git_file.path, "GIT_FILE")
    return Evidence(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        created_by=actor_id,
        repository_version=repository_version,
        evidence_type=evidence_type,
        locator=EvidenceLocator(
            uri=f"repo://{repository_version.repository_id}/{git_file.path}",
            content_hash=git_file.content_hash,
        ),
        captured_at=utc_now(),
    )
