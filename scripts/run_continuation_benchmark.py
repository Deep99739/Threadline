"""Run and persist Threadline's executed synthetic continuation benchmark."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from threadline.continuation_benchmark import run_continuation_benchmark


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/results/continuation-benchmark-v0.3.json"),
    )
    arguments = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="threadline-continuation-benchmark-") as temporary:
        report = asyncio.run(run_continuation_benchmark(Path(temporary) / "workspace"))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
