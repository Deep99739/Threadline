"""Run and optionally persist the Phase 2 code graph ablation."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from threadline.graph_evaluation import run_graph_ablation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="threadline-phase2-graph-") as directory:
        root = Path(directory)
        report = run_graph_ablation(
            database_url=f"sqlite+pysqlite:///{root / 'evaluation.db'}",
            repository_path=root / "demo-repository",
        )
    encoded = json.dumps(report, indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
