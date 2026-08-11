from __future__ import annotations

from itertools import pairwise

from hypothesis import given
from hypothesis import strategies as st

from tests.unit.test_models import ACTOR, TENANT, WORKSPACE, evidence, snapshot
from threadline.graph import trace_code_graph
from threadline.models import (
    CodeDependency,
    CodeSymbol,
    ContextSnapshot,
    DependencyKind,
    SymbolKind,
)


def _graph_snapshot() -> ContextSnapshot:
    source = evidence()
    base = snapshot(claims=(), evidence_items=(source,), verifications=())
    symbols = tuple(
        CodeSymbol(
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            created_by=ACTOR,
            repository_version=base.repository_version,
            task_id=base.task.id,
            logical_key=f"symbol:chain.py:chain.{name}",
            language="python",
            path="chain.py",
            qualified_name=f"chain.{name}",
            symbol_kind=SymbolKind.FUNCTION,
            line_start=index * 2 + 1,
            line_end=index * 2 + 1,
            evidence_id=source.id,
        )
        for index, name in enumerate(("a", "b", "c", "d"))
    )
    dependencies = tuple(
        CodeDependency(
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            created_by=ACTOR,
            repository_version=base.repository_version,
            task_id=base.task.id,
            logical_key=f"dependency:{source_symbol.logical_key}:CALLS:{target_symbol.qualified_name}",
            source_symbol_key=source_symbol.logical_key,
            target_name=target_symbol.qualified_name,
            target_symbol_key=target_symbol.logical_key,
            dependency_kind=DependencyKind.CALLS,
            path="chain.py",
            line_start=source_symbol.line_start,
            line_end=source_symbol.line_end,
            evidence_id=source.id,
        )
        for source_symbol, target_symbol in pairwise(symbols)
    )
    unresolved = CodeDependency(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        created_by=ACTOR,
        repository_version=base.repository_version,
        task_id=base.task.id,
        logical_key="dependency:chain.d:CALLS:external",
        source_symbol_key=symbols[-1].logical_key,
        target_name="external",
        dependency_kind=DependencyKind.CALLS,
        path="chain.py",
        line_start=symbols[-1].line_start,
        line_end=symbols[-1].line_end,
        evidence_id=source.id,
    )
    return base.model_copy(
        update={
            "code_symbols": symbols,
            "code_dependencies": (*dependencies, unresolved),
        }
    )


@given(
    max_depth=st.integers(min_value=0, max_value=5),
    max_nodes=st.integers(min_value=1, max_value=4),
)
def test_traversal_never_exceeds_caller_bounds(max_depth: int, max_nodes: int) -> None:
    current = _graph_snapshot()

    trace = trace_code_graph(
        current,
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        symbol="chain.a",
        max_depth=max_depth,
        max_nodes=max_nodes,
    )

    assert 1 <= len(trace.nodes) <= max_nodes
    allowed = min(4, max_depth + 1, max_nodes)
    assert len(trace.nodes) == allowed
    assert all(item.tenant_id == TENANT for item in trace.nodes)
    assert all(item.workspace_id == WORKSPACE for item in trace.nodes)


def test_traversal_rejects_cross_scope_access() -> None:
    current = _graph_snapshot()

    try:
        trace_code_graph(
            current,
            tenant_id=ACTOR,
            workspace_id=WORKSPACE,
            symbol="chain.a",
        )
    except PermissionError as exc:
        assert "scope" in str(exc)
    else:
        raise AssertionError("cross-scope traversal must be rejected")


def test_unresolved_relationships_are_visible_without_guessed_targets() -> None:
    current = _graph_snapshot()

    trace = trace_code_graph(
        current,
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        symbol="chain.d",
        max_depth=0,
    )

    assert [item.target_name for item in trace.unresolved_dependencies] == ["external"]
    assert trace.citations
