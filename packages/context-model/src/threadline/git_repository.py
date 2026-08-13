"""Read an immutable, commit-bound snapshot from a local Git repository."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
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


def exclude_local_worktree_path(path: Path, relative_path: str) -> bool:
    """Keep a machine-specific generated file out of Git without editing .gitignore."""

    requested = PurePosixPath(relative_path)
    if requested.is_absolute() or ".." in requested.parts or relative_path in {"", "."}:
        raise ValueError("local exclusion must be a repository-relative path")
    root = resolve_git_root(path)
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", relative_path],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if tracked.returncode == 0:
        return False
    raw_exclude = Path(_git(root, "rev-parse", "--git-path", "info/exclude"))
    exclude_path = raw_exclude if raw_exclude.is_absolute() else root / raw_exclude
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    current = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
    entries = {
        line.strip()
        for line in current.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    normalized = requested.as_posix()
    if normalized in entries:
        return False
    separator = "" if not current or current.endswith("\n") else "\n"
    with exclude_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{separator}{normalized}\n")
    return True


def commit_exact_paths(path: Path, relative_paths: tuple[str, ...], message: str) -> str:
    """Commit only the named generated files, refusing any pre-existing repository drift."""

    root = resolve_git_root(path)
    paths = tuple(dict.fromkeys(PurePosixPath(item).as_posix() for item in relative_paths))
    if not paths or any(
        PurePosixPath(item).is_absolute() or ".." in PurePosixPath(item).parts for item in paths
    ):
        raise ValueError("commit paths must be non-empty repository-relative paths")
    dirty_paths = set(read_worktree_dirty_paths(root))
    if dirty_paths != set(paths):
        unexpected = ", ".join(sorted(dirty_paths - set(paths))) or "none"
        missing = ", ".join(sorted(set(paths) - dirty_paths)) or "none"
        raise GitRepositoryError(
            f"automatic commit refused; unexpected paths: {unexpected}; missing paths: {missing}"
        )
    _git(root, "add", "--", *paths)
    staged = set(_git(root, "diff", "--cached", "--name-only", "-z", strip=False).split("\0"))
    staged.discard("")
    if staged != set(paths):
        raise GitRepositoryError("automatic commit refused because the staged paths changed")
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def read_git_working_state(path: Path, repository_id: UUID) -> GitWorkingState:
    """Read the live branch, HEAD, and dirty paths without trusting a caller-supplied version."""

    root = resolve_git_root(path)
    branch = _git(root, "branch", "--show-current")
    commit_sha = _git(root, "rev-parse", "HEAD")
    dirty_paths = read_worktree_dirty_paths(root)
    return GitWorkingState(
        root=root,
        repository_version=RepositoryVersion(
            repository_id=repository_id,
            branch=branch,
            commit_sha=commit_sha,
        ),
        dirty_paths=dirty_paths,
    )


def read_worktree_dirty_paths(path: Path) -> tuple[str, ...]:
    """Return staged, unstaged, and untracked paths without requiring a manifest."""

    root = resolve_git_root(path)
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
    return tuple(dict.fromkeys(dirty))


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


def read_committed_content_hashes(
    path: Path,
    *,
    commit_sha: str,
    relative_paths: tuple[str, ...],
) -> dict[str, str]:
    """Hash selected committed blobs without requiring them to be text evidence."""

    root = resolve_git_root(path)
    hashes: dict[str, str] = {}
    for relative_path in dict.fromkeys(relative_paths):
        process = subprocess.Popen(
            ["git", "-C", str(root), "show", f"{commit_sha}:{relative_path}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if process.stdout is None:  # pragma: no cover - guaranteed by stdout=PIPE
            process.kill()
            process.wait()
            continue
        digest = hashlib.sha256()
        while chunk := process.stdout.read(64 * 1024):
            digest.update(chunk)
        process.stdout.close()
        if process.wait(timeout=15) == 0:
            hashes[relative_path] = f"sha256:{digest.hexdigest()}"
    return hashes


def evidence_from_git_file(
    git_file: GitFile,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    actor_id: UUID,
    repository_version: RepositoryVersion,
    sensitivity: str = "INTERNAL",
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
        sensitivity=sensitivity,
    )
