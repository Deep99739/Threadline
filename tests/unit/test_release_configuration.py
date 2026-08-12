from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_coverage_target_cannot_be_shadowed_by_threadline_evidence_directory() -> None:
    configuration = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "--cov=packages/context-model/src/threadline" in configuration
    assert "--cov=threadline " not in configuration
