from __future__ import annotations

from pathlib import Path

from threadline.graph_evaluation import run_graph_ablation


def test_graph_ablation_recovers_cited_relationship(tmp_path: Path) -> None:
    report = run_graph_ablation(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'graph-eval.db'}",
        repository_path=tmp_path / "demo-repository",
    )

    lexical, graph = report["ablations"]
    assert lexical["expected_relationship_recall"] == 0.0
    assert graph["expected_relationship_recall"] == 1.0
    assert graph["citation_validity"] == 1.0
    assert graph["truncated"] is False
