"""Run and optionally persist the executable Phase 1 primary evaluation."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from threadline.evaluation import run_phase1_evaluation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="threadline-phase1-") as directory:
        root = Path(directory)
        report = asyncio.run(
            run_phase1_evaluation(
                database_url=f"sqlite+pysqlite:///{root / 'evaluation.db'}",
                repository_path=root / "demo-repository",
            )
        )
    encoded = json.dumps(report, indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
