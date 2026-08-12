"""Run Threadline's complete local release gate in a fixed, reviewable order."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATES = (
    ("backend, contracts, coverage, and foundation", ("make", "check")),
    ("migrations and tenant boundaries on PostgreSQL", ("make", "postgres-check")),
    ("frontend lint, build, and server-rendered surface", ("make", "web-check")),
    ("installation and real stdio MCP from a clean export", ("make", "clean-clone-check")),
)


def main() -> None:
    for title, command in GATES:
        print(f"\nRelease gate: {title}", flush=True)
        subprocess.run(command, cwd=ROOT, check=True, timeout=600)
    print("\nThreadline local release gate passed.")


if __name__ == "__main__":
    main()
