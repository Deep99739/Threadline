from __future__ import annotations

import hashlib
from uuid import UUID

from tests.unit.test_models import ACTOR, TENANT, WORKSPACE, repository_version
from threadline.code_graph import CodeGraphExtraction, extract_code_graph
from threadline.git_repository import GitFile, evidence_from_git_file
from threadline.models import DependencyKind, ParseStatus, SymbolKind

TASK_ID = UUID("30000000-0000-4000-8000-000000000099")


def _file(path: str, content: str) -> GitFile:
    digest = hashlib.sha256(content.encode()).hexdigest()
    return GitFile(path=path, content=content, content_hash=f"sha256:{digest}")


def _extract(*files: GitFile) -> CodeGraphExtraction:
    version = repository_version()
    evidence = {
        item.path: evidence_from_git_file(
            item,
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            actor_id=ACTOR,
            repository_version=version,
        )
        for item in files
    }
    return extract_code_graph(
        tuple(files),
        evidence,
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        actor_id=ACTOR,
        task_id=TASK_ID,
        repository_version=version,
    )


def test_extracts_python_symbols_calls_construction_and_local_imports() -> None:
    shared = _file("shared.py", "def helper():\n    return 1\n")
    worker = _file(
        "worker.py",
        "from shared import helper\n\n"
        "class Worker:\n"
        "    def run(self):\n"
        "        return helper()\n\n"
        "def build():\n"
        "    return Worker()\n",
    )

    result = _extract(shared, worker)

    assert {
        (item.qualified_name, item.symbol_kind)
        for item in result.symbols
    } >= {
        ("shared", SymbolKind.MODULE),
        ("shared.helper", SymbolKind.FUNCTION),
        ("worker.Worker", SymbolKind.CLASS),
        ("worker.Worker.run", SymbolKind.METHOD),
        ("worker.build", SymbolKind.FUNCTION),
    }
    resolved = {
        (item.dependency_kind, item.target_name, item.target_symbol_key)
        for item in result.dependencies
    }
    assert (
        DependencyKind.IMPORTS,
        "shared",
        "symbol:shared.py:shared",
    ) in resolved
    assert (
        DependencyKind.CALLS,
        "helper",
        "symbol:shared.py:shared.helper",
    ) in resolved
    assert (
        DependencyKind.CONSTRUCTS,
        "Worker",
        "symbol:worker.py:worker.Worker",
    ) in resolved
    assert all(item.status is ParseStatus.COMPLETE for item in result.diagnostics)


def test_extracts_javascript_and_typescript_functions_methods_and_construction() -> None:
    javascript = _file(
        "web.js",
        "class Panel { render() { return helper(); } }\n"
        "const mount = () => new Panel();\n",
    )
    typescript = _file(
        "client.ts",
        "export function helper(): number { return 1; }\n"
        "export const start = (): number => helper();\n",
    )

    result = _extract(javascript, typescript)
    names = {item.qualified_name for item in result.symbols}
    assert {
        "web.Panel",
        "web.Panel.render",
        "web.mount",
        "client.helper",
        "client.start",
    }.issubset(names)
    assert any(
        item.dependency_kind is DependencyKind.CONSTRUCTS
        and item.target_symbol_key == "symbol:web.js:web.Panel"
        for item in result.dependencies
    )
    assert any(
        item.dependency_kind is DependencyKind.CALLS
        and item.target_symbol_key == "symbol:client.ts:client.helper"
        for item in result.dependencies
    )


def test_malformed_file_is_partial_and_does_not_invent_broken_symbols() -> None:
    broken = _file("broken.py", "def broken(:\n    unknown()\n")

    result = _extract(broken)

    assert [item.qualified_name for item in result.symbols] == ["broken"]
    assert all(item.source_symbol_key == "symbol:broken.py:broken" for item in result.dependencies)
    assert all(item.target_symbol_key is None for item in result.dependencies)
    assert result.diagnostics[0].status is ParseStatus.PARTIAL
    assert result.diagnostics[0].error_lines


def test_exact_snapshot_produces_stable_entity_ids() -> None:
    source = _file("service.py", "def run():\n    return 1\n")

    first = _extract(source)
    second = _extract(source)

    assert [item.id for item in first.symbols] == [item.id for item in second.symbols]
    assert [item.id for item in first.diagnostics] == [
        item.id for item in second.diagnostics
    ]
