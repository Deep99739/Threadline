<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="apps/web/public/threadline-mark-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="apps/web/public/threadline-mark.svg">
    <img src="apps/web/public/threadline-mark.svg" alt="Threadline commit seam" width="120">
  </picture>
</p>

<h1 align="center">Threadline</h1>

<p align="center"><strong>Evidence-bound handoffs for coding agents.</strong></p>

[![CI](https://github.com/Deep99739/Threadline/actions/workflows/ci.yml/badge.svg)](https://github.com/Deep99739/Threadline/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Deep99739/Threadline)](https://github.com/Deep99739/Threadline/releases/latest)
[![License](https://img.shields.io/github/license/Deep99739/Threadline)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12--3.14-3776AB)](./pyproject.toml)

[Live product demo](https://threadline-context.vercel.app) · [Quick start](#quick-start) · [Evaluation](#evaluation)

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

| Ordinary session memory | Threadline |
|---|---|
| Describes what probably happened | Cites what the repository can prove |
| Floats independently of Git state | Binds every handoff to branch and commit |
| Smooths over missing or conflicting evidence | Preserves unknowns and contradictions |
| Can outlive the code it describes | Refuses reads when the worktree or commit moves |

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

## Quick start

Requirements:

- Git
- Python 3.12 to 3.14

On macOS with Homebrew, install `pipx` without writing into Apple's or Homebrew's managed Python:

```bash
brew install pipx
pipx ensurepath
pipx install git+https://github.com/Deep99739/Threadline.git
```

On Linux, install `pipx` with the operating system package manager, then run the same final two
commands. Open a new terminal after `ensurepath` the first time.

From a clean Git repository, onboard the task and one coding client:

```bash
threadline onboard /path/to/your-repository \
  --objective "What this task must accomplish" \
  --next-action "The next concrete action" \
  --client codex
```

Supported clients are `codex`, `claude`, `cursor`, `vscode`, and `antigravity`.

Onboarding requires a clean Git working tree. In one command, Threadline:

- creates and commits only the repository-owned `threadline.json` contract;
- compiles the first handoff at that exact commit;
- connects the selected project's read-only MCP server;
- keeps the machine-specific client profile local; and
- performs a real MCP handshake and reports client registration separately.

It uses your configured Git identity for the context commit and does not require an API key,
Docker, or an external database. Local derived state stays at `.git/threadline/threadline.db`.
Repository-local Git hooks refresh the handoff after commits, checkouts, merges, and rebases.
Existing custom hooks are never replaced; when Threadline reports a hook conflict, run
`threadline sync .` after the repository changes.

Confirm or read the resulting handoff at any time:

```bash
threadline doctor .
threadline verify-client codex .
threadline handoff .
```

Codex deliberately ignores project `.codex/config.toml` settings until you trust the repository.
Review the repository, choose **Trust** in Codex, reopen it, and run
`threadline verify-client codex .`. Threadline reports this requirement; it never grants trust to
itself.

The lower-level `init`, `sync`, `clients`, and `connect` commands remain available for custom
workflows.

## Connect another coding client

Generate one project-scoped MCP profile:

```bash
threadline connect codex .
```

Supported values are:

```text
codex  claude  cursor  vscode  antigravity
```

To inspect every supported profile without writing a client configuration:

```bash
threadline clients .
```

Threadline changes only the selected project's configuration. It does not modify global client
settings or commit machine-specific runtime paths.

Disconnect one client without affecting its other MCP servers:

```bash
threadline disconnect codex .
```

Remove every local integration and rebuildable database while retaining the portable
`threadline.json` contract:

```bash
threadline uninstall .
```

## Everyday workflow

Run a check and record the next handoff in one operation:

```bash
threadline advance . \
  --statement "The parser change is implemented; integration coverage is missing" \
  --next-action "Add and run the whitespace integration test" \
  --scope FULL \
  --include src/parser.py \
  --include tests/test_parser.py \
  -- python -m pytest -q
```

`advance` keeps the statement asserted, records the command result and exact tested content hashes,
and updates the next action. It never commits product code on your behalf. The lower-level
`checkpoint` and `check` commands remain available when those actions need to happen separately.

Commit the work and generated evidence, then read the automatically refreshed handoff:

```bash
git add threadline.json threadline/ src/parser.py tests/test_parser.py
git commit -m "Verify parser behavior"
threadline handoff .
```

Use `threadline handoff . --format json` for machine-readable output.

## MCP tools

Every MCP server is bound to one task and repository scope. Clients begin with `get_workspace_status`, then use the returned branch, commit, and task identity for subsequent reads.

| Tool | Purpose |
|---|---|
| `get_workspace_status` | Discover the active task and handoff freshness |
| `get_task_context` | Read the compact current cited handoff; request ranked items only when needed |
| `get_evidence` | Inspect one cited evidence object |
| `explain_context_selection` | See why an item entered the handoff |
| `trace_decision` | Read a decision and its supporting evidence |
| `trace_code_symbol` | Traverse bounded typed code relationships |
| `compare_context_versions` | Classify changes between context versions |
| `list_stale_context` | Explain which context was invalidated |

All eight tools are read-only. A dirty worktree or moved branch head causes Threadline to abstain until the repository is committed and synchronized again.

`get_task_context` keeps the default continuation small: exact version, objective, constraints,
verified work, next action, uncertainty, conflicts, and citation locators. Set
`include_items=true` only when the client needs every ranked item and selection explanation; open
source bodies individually with `get_evidence`.

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

- 171 Python tests with a 90% coverage gate, plus server-rendered website checks.
- 30 frozen continuation, conflict, freshness, retrieval, permission, injection, secret, ingestion, and degraded-mode cases.
- A 12-case executed continuation benchmark covering cross-agent continuation, stale refusal, citation resolution, command evidence, scope denial, redaction, instruction boundaries, and compact context preservation.
- An end-to-end Agent B scenario that reads a handoff over MCP, changes code, runs tests, commits, observes stale refusal, and receives a newly verified handoff.
- A lexical-versus-graph ablation showing the typed test-to-class relationship recovered by bounded graph traversal.

Raw results are committed with the code:

- [Executed continuation benchmark](./evals/results/continuation-benchmark-v0.3.json)
- [Primary continuation scenario](./evals/results/phase1-primary.json)
- [Code-graph ablation](./evals/results/phase2-graph-ablation.json)

## Demo

Open the [public product demo](https://threadline-context.vercel.app) without an account. It presents
the interactive evidence workbench, an executed continuation proof, the evidence contract, and the
local adoption path.

In the retained synthetic continuation fixture, the compact MCP response is 2,695 bytes versus
10,330 bytes for the full ranked response, a 73.9% reduction while preserving the exact version,
headline decisions, uncertainty, conflicts, and six citation locators. This is a minified UTF-8 byte
measurement, not a model-specific token, time, cost, or external-adoption claim.

To run the same product surface locally, create the deterministic handoff:

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
