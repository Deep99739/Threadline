"""Repository-local refresh hooks for keeping committed handoffs current."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from threadline.git_repository import resolve_git_root

HOOK_NAMES = ("post-commit", "post-checkout", "post-merge", "post-rewrite")
MANAGED_MARKER = "# managed-by: threadline"


def _custom_hooks_path(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "config", "--get", "core.hooksPath"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "could not inspect Git hooks configuration")
    return result.stdout.strip() or None


def _default_hooks_path(root: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-path", "hooks"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    path = Path(result.stdout.strip())
    return path if path.is_absolute() else (root / path).resolve()


def _render_hook(root: Path, python_executable: Path, log_path: Path) -> str:
    command = " ".join(
        shlex.quote(value)
        for value in (
            str(python_executable.expanduser().absolute()),
            "-m",
            "threadline",
            "sync",
            str(root),
        )
    )
    quoted_log = shlex.quote(str(log_path))
    return (
        "#!/bin/sh\n"
        f"{MANAGED_MARKER}\n"
        f"output=$({command} 2>&1)\n"
        "status=$?\n"
        "if [ \"$status\" -ne 0 ]; then\n"
        f"  printf '%s\\n' \"Threadline refresh failed: $output\" >> {quoted_log}\n"
        "fi\n"
        "exit 0\n"
    )


def install_refresh_hooks(
    repository_path: Path,
    *,
    python_executable: Path | None = None,
) -> dict[str, Any]:
    """Install non-blocking local hooks without replacing another tool's hooks."""

    root = resolve_git_root(repository_path)
    custom_path = _custom_hooks_path(root)
    if custom_path is not None:
        return {
            "automatic_refresh": False,
            "installed": [],
            "existing": [],
            "blocked": list(HOOK_NAMES),
            "reason": f"custom core.hooksPath is configured: {custom_path}",
        }

    hooks_path = _default_hooks_path(root)
    hooks_path.mkdir(parents=True, exist_ok=True)
    executable = python_executable or Path(sys.executable)
    if not executable.expanduser().absolute().is_file():
        raise FileNotFoundError(f"Python executable was not found: {executable}")
    log_path = hooks_path.parent / "threadline" / "hook-errors.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = _render_hook(root, executable, log_path)
    installed: list[str] = []
    existing: list[str] = []
    blocked: list[str] = []
    for hook_name in HOOK_NAMES:
        target = hooks_path / hook_name
        if target.exists():
            current = target.read_text(encoding="utf-8", errors="replace")
            if MANAGED_MARKER not in current:
                blocked.append(hook_name)
                continue
            if current == rendered and target.stat().st_mode & 0o111:
                existing.append(hook_name)
                continue
        target.write_text(rendered, encoding="utf-8")
        target.chmod(0o755)
        installed.append(hook_name)
    return {
        "automatic_refresh": not blocked,
        "installed": installed,
        "existing": existing,
        "blocked": blocked,
        "reason": (
            None
            if not blocked
            else "existing unmanaged hooks were left untouched; run threadline sync after commits"
        ),
    }
