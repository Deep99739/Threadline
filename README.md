# Threadline

**Evidence-bound handoffs for coding agents.**

[![CI](https://github.com/Deep99739/Threadline/actions/workflows/ci.yml/badge.svg)](https://github.com/Deep99739/Threadline/actions/workflows/ci.yml)

Threadline gives the next developer or coding agent a current, cited picture of unfinished work. It binds claims, decisions, code relationships, and command results to an exact Git commit, then refuses to serve the handoff when the repository has moved.

Use it beside Codex, Claude Code, Cursor, VS Code, Antigravity, or any terminal workflow. The default local path needs no model API key and no separately provisioned database.

## The problem

Coding sessions produce plenty of text, but text alone does not answer the questions that matter when work changes hands:

- What is implemented, and what was only suggested?
- Which tests actually ran?
- What evidence supports a completion claim?
- Which decisions still apply to this commit?
- What changed after the last handoff?
- What should the next agent do first?

Threadline treats every summary as a set of claims, not as project truth.

## What Threadline does

- Creates a repository-owned task contract in `threadline.json`.
- Captures tracked evidence at an exact repository, branch, and commit.
- Verifies code and test claims through deterministic checks.
- Preserves contradictions, missing evidence, and superseded decisions.
- Builds cited handoffs with a concrete next action.
- Extracts typed symbols and code relationships from Python, JavaScript, and TypeScript.
- Exposes eight read-only MCP tools to supported coding clients.
- Detects dirty worktrees and moved branch heads before every MCP read.
- Stores local state under `.git/threadline/` without dirtying the repository.

## How it works

```text
Git repository + threadline.json
               |
               v
      committed evidence snapshot
               |
               v
 deterministic verification + typed code graph
               |
               v
 precedence, conflicts, freshness, and retrieval
               |
               v
       cited exact-commit handoff
               |
               v
  Codex / Claude / Cursor / VS Code / terminal
```

Threadline uses explicit evidence states:

| State | Meaning |
|---|---|
| `ASSERTED` | Stated, but not independently verified |
| `OBSERVED` | Captured directly from a tool or system |
| `VERIFIED` | Proven by a deterministic verifier or authorized human |
| `CONTRADICTED` | Credible evidence conflicts with the claim |
| `STALE` | The repository or freshness boundary changed |
| `SUPERSEDED` | A later decision replaced the earlier one |
| `UNKNOWN` | Available evidence is insufficient |

## Install

Requirements:

- Git
- Python 3.12 to 3.14

```bash
git clone https://github.com/Deep99739/Threadline.git
cd Threadline
make setup
```

This installs the `threadline` command inside `.venv`. Docker is only needed for the PostgreSQL-backed development and release checks.

## Add Threadline to a repository

Set the path to the installed command:

```bash
THREADLINE=/absolute/path/to/Threadline/.venv/bin/threadline
```

Create the task contract:

```bash
$THREADLINE init /path/to/your-repository \
  --objective "What this task must accomplish" \
  --next-action "The next concrete action"
```

Review and commit the generated manifest, then compile the first handoff:

```bash
cd /path/to/your-repository
git add threadline.json
git commit -m "Add Threadline context"
$THREADLINE sync .
$THREADLINE doctor .
```

Threadline stores its derived local database at `.git/threadline/threadline.db`.

## Connect a coding client

Generate one project-scoped MCP profile:

```bash
$THREADLINE connect codex .
```

Supported values are:

```text
codex  claude  cursor  vscode  antigravity
```

To inspect every supported profile without writing a client configuration:

```bash
$THREADLINE clients .
```

Threadline changes only the selected project's configuration. It does not modify global client settings.

## Everyday workflow

Record an observation and the next action:

```bash
$THREADLINE checkpoint . \
  --statement "The parser change is implemented; integration coverage is missing" \
  --next-action "Add and run the whitespace integration test"
```

Run a check and bind its result to the files it covers:

```bash
$THREADLINE check . \
  --scope FULL \
  --include src/parser.py \
  --include tests/test_parser.py \
  -- python -m pytest -q
```

Commit the work and generated evidence, then refresh the handoff:

```bash
git add threadline.json threadline/ src/parser.py tests/test_parser.py
git commit -m "Verify parser behavior"
$THREADLINE sync .
$THREADLINE handoff .
```

Use `threadline handoff . --format json` for machine-readable output.

## MCP tools

Every MCP server is bound to one task and repository scope. Clients begin with `get_workspace_status`, then use the returned branch, commit, and task identity for subsequent reads.

| Tool | Purpose |
|---|---|
| `get_workspace_status` | Discover the active task and handoff freshness |
| `get_task_context` | Read the current cited handoff |
| `get_evidence` | Inspect one cited evidence object |
| `explain_context_selection` | See why an item entered the handoff |
| `trace_decision` | Read a decision and its supporting evidence |
| `trace_code_symbol` | Traverse bounded typed code relationships |
| `compare_context_versions` | Classify changes between context versions |
| `list_stale_context` | Explain which context was invalidated |

All eight tools are read-only. A dirty worktree or moved branch head causes Threadline to abstain until the repository is committed and synchronized again.

## Architecture

Threadline keeps the trust boundary explicit:

- Git provides the immutable source snapshot.
- `threadline.json` provides the repository-owned task contract.
- Deterministic verifiers certify code and command evidence.
- Tree-sitter builds bounded, cited symbol relationships.
- Typed precedence preserves conflicts instead of hiding them.
- SQLite powers zero-configuration local use.
- PostgreSQL provides the tenant-scoped shared storage path.
- MCP exposes a small read-only interface to coding clients.
- The web workbench makes handoffs, evidence, conflicts, and graph traces inspectable.

The design decisions are documented in the [ADR index](./docs/adr/README.md). Security boundaries are documented in the [threat model](./docs/threat-model/THREAT_MODEL_V1.md).

## Evaluation

The repository contains reproducible evidence for the behaviors Threadline depends on:

- 136 automated tests with a 90% coverage gate.
- 30 frozen continuation, conflict, freshness, retrieval, permission, injection, secret, ingestion, and degraded-mode cases.
- An 11-case executed continuation benchmark covering cross-agent continuation, stale refusal, citation resolution, command evidence, scope denial, redaction, and instruction-boundary signals.
- An end-to-end Agent B scenario that reads a handoff over MCP, changes code, runs tests, commits, observes stale refusal, and receives a newly verified handoff.
- A lexical-versus-graph ablation showing the typed test-to-class relationship recovered by bounded graph traversal.

Raw results are committed with the code:

- [Executed continuation benchmark](./evals/results/continuation-benchmark-v0.2.json)
- [Primary continuation scenario](./evals/results/phase1-primary.json)
- [Code-graph ablation](./evals/results/phase2-graph-ablation.json)

## Run the demo locally

Create the deterministic handoff and start the product surface:

```bash
make demo
```

Then run these in separate terminals:

```bash
make api
```

```bash
make web
```

Open `http://localhost:3000`.

## Development

Install development dependencies:

```bash
make setup
npm --prefix apps/web install
```

Run the main checks:

```bash
make check
make mcp-check
make web-check
make continuation-benchmark
```

Run the complete release gate, including PostgreSQL migrations, tenant isolation, clean installation, and the real stdio MCP client:

```bash
make release-check
```

## Repository structure

```text
packages/context-model/   domain model, ingestion, verification, graph, MCP
packages/contracts/       public JSON Schemas and examples
apps/web/                 interactive evidence workbench
evals/                    frozen datasets, baselines, and raw results
demo/                     deterministic continuation scenario
docs/adr/                 architecture decisions and tradeoffs
docs/threat-model/        trust boundaries and security analysis
infra/migrations/         PostgreSQL schema migrations
scripts/                  release and repository quality gates
tests/                    unit, property, contract, and integration tests
```

## Principles

1. Context is not a transcript.
2. Evidence outranks generated confidence.
3. Authorization happens before retrieval.
4. Repository, branch, and commit are first-class identities.
5. Contradictions remain visible.
6. Humans own canonical and irreversible decisions.
7. Every architecture layer must earn its complexity through evaluation.
8. Public claims must remain reproducible.

## License

Threadline is open source under the [Apache License 2.0](./LICENSE).
