from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from tests.unit.test_models import ACTOR, TENANT, WORKSPACE, repository_version
from threadline import code_graph
from threadline.code_graph import CodeGraphExtraction, extract_code_graph
from threadline.git_repository import GitFile, evidence_from_git_file
from threadline.models import DependencyKind, ParseStatus, SymbolKind

TASK_ID = UUID("30000000-0000-4000-8000-000000000099")


def _file(path: str, content: str) -> GitFile:
    digest = hashlib.sha256(content.encode()).hexdigest()
    return GitFile(path=path, content=content, content_hash=f"sha256:{digest}")


def _extract(*files: GitFile, isolate_native: bool = False) -> CodeGraphExtraction:
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
        isolate_native=isolate_native,
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


def test_overloads_are_one_logical_symbol_with_a_complete_source_range() -> None:
    source = _file(
        "serializer.py",
        "from typing import overload\n\n"
        "@overload\n"
        "def loads(value: str) -> str: ...\n\n"
        "@overload\n"
        "def loads(value: bytes) -> bytes: ...\n\n"
        "def loads(value: str | bytes) -> str | bytes:\n"
        "    return value\n",
    )

    result = _extract(source)

    loads = [item for item in result.symbols if item.qualified_name == "serializer.loads"]
    assert len(loads) == 1
    assert loads[0].logical_key == "symbol:serializer.py:serializer.loads"
    assert loads[0].line_start == 4
    assert loads[0].line_end == 10
    assert len({item.logical_key for item in result.symbols}) == len(result.symbols)


def test_isolates_a_native_failure_on_a_large_tsx_product_surface() -> None:
    rows = "\n".join(
        f"<button onClick={{() => inspectSource('src/{index}.ts')}}>Row {index}</button>"
        for index in range(600)
    )
    surface = _file(
        "ProductSurface.tsx",
        "export function ProductSurface() {\n"
        "  function inspectSource(path: string) { return path.trim(); }\n"
        f"  return <main>{rows}</main>;\n"
        "}\n",
    )

    result = _extract(surface, isolate_native=True)

    assert result.diagnostics[0].status is ParseStatus.COMPLETE
    assert any(item.qualified_name.endswith("ProductSurface") for item in result.symbols)


def test_native_parser_failure_becomes_an_explicit_empty_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _file("service.py", "def run():\n    return 1\n")

    def fail_parse(*_args: object) -> object:
        raise RuntimeError("native parser stopped")

    monkeypatch.setattr(code_graph, "_parse_file_isolated", fail_parse)

    result = _extract(source, isolate_native=True)

    assert result.diagnostics[0].status is ParseStatus.FAILED
    assert not result.symbols
    assert not result.dependencies


def test_content_hash_cache_reuses_unchanged_files_and_rebinds_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _file("service.py", "def run():\n    return 1\n")
    cache_path = tmp_path / "code-cache.json"
    version = repository_version()
    evidence = {
        source.path: evidence_from_git_file(
            source,
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            actor_id=ACTOR,
            repository_version=version,
        )
    }
    first = extract_code_graph(
        (source,),
        evidence,
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        actor_id=ACTOR,
        task_id=TASK_ID,
        repository_version=version,
        isolate_native=False,
        cache_path=cache_path,
    )

    def reject_parse(*_args: object) -> object:
        raise AssertionError("unchanged source must not be parsed again")

    monkeypatch.setattr(code_graph, "_parse_file", reject_parse)
    second_evidence = evidence[source.path].model_copy(
        update={"id": UUID("30000000-0000-4000-8000-000000000101")}
    )
    second = extract_code_graph(
        (source,),
        {source.path: second_evidence},
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        actor_id=ACTOR,
        task_id=TASK_ID,
        repository_version=version,
        isolate_native=False,
        cache_path=cache_path,
    )

    assert cache_path.is_file()
    assert len(json.loads(cache_path.read_text())["entries"]) == 1
    assert second.symbols[0].evidence_id == second_evidence.id
    assert second.diagnostics[0].evidence_id == second_evidence.id
    assert [item.logical_key for item in second.symbols] == [
        item.logical_key for item in first.symbols
    ]


def test_malformed_incremental_cache_is_ignored_and_rebuilt(tmp_path: Path) -> None:
    source = _file("service.py", "def run():\n    return 1\n")
    cache_path = tmp_path / "code-cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {
                    f"python:{source.path}:{source.content_hash}": {
                        "symbols": [{"line_start": False}],
                        "dependencies": [],
                        "status": "COMPLETE",
                        "error_lines": [],
                    }
                },
            }
        )
    )

    result = _extract(source)
    evidence = {
        source.path: evidence_from_git_file(
            source,
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            actor_id=ACTOR,
            repository_version=repository_version(),
        )
    }
    cached = extract_code_graph(
        (source,),
        evidence,
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        actor_id=ACTOR,
        task_id=TASK_ID,
        repository_version=repository_version(),
        isolate_native=False,
        cache_path=cache_path,
    )

    assert [item.logical_key for item in cached.symbols] == [
        item.logical_key for item in result.symbols
    ]


def test_corrupt_incremental_cache_is_rebuilt(tmp_path: Path) -> None:
    source = _file("service.py", "def run():\n    return 1\n")
    cache_path = tmp_path / "code-cache.json"
    cache_path.write_text("not-json", encoding="utf-8")
    version = repository_version()
    evidence = {
        source.path: evidence_from_git_file(
            source,
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            actor_id=ACTOR,
            repository_version=version,
        )
    }

    result = extract_code_graph(
        (source,),
        evidence,
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        actor_id=ACTOR,
        task_id=TASK_ID,
        repository_version=version,
        isolate_native=False,
        cache_path=cache_path,
    )

    assert result.diagnostics[0].status is ParseStatus.COMPLETE
    assert json.loads(cache_path.read_text())["schema_version"] == 1
