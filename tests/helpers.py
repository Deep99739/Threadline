from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.stdout.strip()


def make_demo_repository(tmp_path: Path) -> Path:
    destination = tmp_path / "threadline-demo"
    shutil.copytree(PROJECT_ROOT / "demo" / "synthetic-repo", destination)
    git(destination, "init", "-b", "feature/retry-jobs")
    git(destination, "add", ".")
    git(
        destination,
        "-c",
        "user.name=Threadline Test",
        "-c",
        "user.email=threadline@example.invalid",
        "commit",
        "-m",
        "Create unfinished retry task",
    )
    return destination
