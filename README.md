# Threadline

> Governed, versioned engineering context for humans and coding agents.

Threadline turns Git history, issues, test evidence, decisions, and agent work into context that is bound to an exact code version and backed by inspectable evidence. Its goal is to let the next developer or coding agent continue a task without replaying an entire transcript or trusting an unsupported summary.

## Why Threadline

Moving a long-running coding task between AI sessions often transfers plenty of text but loses the distinctions that matter:

- what was decided versus merely suggested;
- what is implemented versus only claimed;
- what was verified and at which commit;
- what became stale after the code changed;
- which approach was rejected and why; and
- what the next safe action actually is.

Threadline treats a summary as a claim, not as project truth. Material claims remain separate from their evidence and verification.

## Current status

The repository currently contains the trustworthy foundation and a working local continuation
slice:

- strict context-domain contracts;
- explicit epistemic states;
- tenant, workspace, repository, branch, and commit invariants;
- deterministic verification boundaries;
- typed precedence and contradiction rules;
- external JSON Schema contracts;
- thirty frozen continuation, safety, and reliability cases;
- a deterministic synthetic demo repository;
- eleven architecture decision records and a threat model;
- exact-commit Git ingestion for tracked text evidence;
- a strict, committed `threadline.json` contract for arbitrary local repositories;
- explicit `init` and `sync` commands with refusal of uncommitted context configuration;
- a zero-key SQLite path inside Git's private metadata for single-user local adoption;
- deterministic Python symbol, call-path, test-scope, and evidence-sufficiency verifiers;
- authorization-scoped lexical retrieval with visible ranking reasons;
- cited, content-hashed context versions and handoffs;
- six scope-bound, read-only MCP tools proven through a real stdio client;
- live working-tree and branch-head drift detection on every MCP read;
- stale-handoff refusal with source-level invalidation reasons after the branch head moves;
- an official MCP Agent B client that performs the expected continuation, commits it, and
  re-verifies the resulting repository state;
- an executable primary-scenario evaluation with raw baseline outcomes and disclosed limits;
- explicit Alembic migrations and tenant-scoped PostgreSQL storage;
- a repeatable synthetic CLI demo whose failure outcome comes from the real verifier path;
- a read-only HTTP demo surface over that exact compiled handoff;
- an interactive evidence workbench with state filters, source inspection, and a bundled
  synthetic fallback;
- automated lint, type, contract, property, coverage, and structure checks; and
- a verified local PostgreSQL, Redis, and object-store environment.

No hosted, adoption, accuracy, or production-readiness claim is made yet.

## Core model

Threadline distinguishes:

- `ASSERTED` — stated but not independently verified;
- `OBSERVED` — directly captured from a tool or system;
- `VERIFIED` — certified by a versioned deterministic verifier or authorized human;
- `CONTRADICTED` — credible evidence conflicts with the claim;
- `STALE` — a version or freshness boundary was crossed;
- `SUPERSEDED` — a later authorized decision replaced it; and
- `UNKNOWN` — the available evidence is insufficient.

An LLM may extract or explain a claim. It cannot certify code, tests, deployment, permissions, or its own completion.

## Local setup

Requirements:

- Python 3.12–3.14
- Docker with `docker-compose`

First run:

```bash
make setup
make check
make local-up
make migrate
make demo
make mcp-check
make phase1-eval
make clean-clone-check
npm --prefix apps/web install
```

Later runs:

```bash
make check
make local-up
make migrate
make demo
make mcp-check
make phase1-eval
make clean-clone-check
```

To run the interactive evidence workbench, keep these in two terminals after `make demo`:

```bash
make api
make web
```

Open `http://localhost:3000`. The website connects to the read-only demo API at
`http://localhost:8000`; if that API is unavailable, it remains usable as an explicitly labelled
bundled synthetic snapshot.

Stop local services:

```bash
make local-down
```

## Use Threadline on a real repository

The synthetic demo is not the product boundary. After installing this checkout, initialize context
inside any existing Git repository:

```bash
/path/to/threadline/.venv/bin/threadline init /path/to/your-repository \
  --objective "What the current task must accomplish" \
  --next-action "The next concrete action another engineer should take"
```

Review the generated `threadline.json`, then commit it. Threadline refuses to sync an uncommitted
manifest because an agent should never receive task context that cannot be tied to the same Git
commit as its evidence.

```bash
git add threadline.json
git commit -m "Add Threadline project context"
/path/to/threadline/.venv/bin/threadline sync .
/path/to/threadline/.venv/bin/threadline mcp --repository .
```

This local repository flow requires no API key and no separately provisioned database. It writes
derived state beneath Git's private metadata at `.git/threadline/threadline.db`, so Threadline does
not dirty the working tree or require a project-wide ignore rule. The committed manifest starts with
task context only; it does not invent verified claims. Add deterministic verifier entries only for
claims that the repository can actually prove. PostgreSQL remains available through
`THREADLINE_DATABASE_URL` for shared or deployed environments.

Print reviewable project profiles for local coding clients:

```bash
/path/to/threadline/.venv/bin/threadline clients .
```

The command does not modify editor or user settings. It returns project-scoped configurations for
[Codex](https://developers.openai.com/codex/mcp),
[Claude Code](https://docs.anthropic.com/en/docs/claude-code/mcp),
[Cursor](https://docs.cursor.com/context/model-context-protocol),
[VS Code](https://code.visualstudio.com/docs/agent-customization/mcp-servers), and
[Antigravity](https://antigravity.google/docs/mcp). Merge only the profile you intend to trust.
Codex desktop, CLI, and its IDE extension share Codex MCP configuration on the same host; Cursor's
project profile is used by both its IDE and CLI. The generated server command is exercised through
the official MCP client in Threadline's test suite. Final trust acceptance still happens inside the
chosen proprietary client.

Every client can call `get_workspace_status` first to discover the bound task, branch, commit, and
handoff freshness. The remaining tools require that exact identity and refuse another task or stale
commit. Threadline also re-reads the live Git state on every tool call. Uncommitted edits force
abstention, and a moved branch head remains stale until Threadline synchronizes and recompiles the
handoff.

The demo command seeds and compiles a real unfinished-task handoff. `make mcp-check` then starts
Threadline over stdio, connects with the official MCP client, discovers six read-only tools, and
verifies an exact-commit response with citations, unknowns, and conflicts. To keep the synthetic
demo server open for another local client, run:

```bash
make mcp
```

`make phase1-eval` runs the complete scenario in an isolated temporary repository. Agent B reads
the exact handoff through MCP, opens its cited evidence, completes the retry integration, runs the
full suite, commits the change, proves that the old handoff is stale and refused, and recompiles a
current verified handoff. The raw point-in-time report is retained in
[`evals/results/phase1-primary.json`](./evals/results/phase1-primary.json). The report deliberately
marks the LLM-summary baseline unmeasured until a provider, model, and prompt are frozen.

`make clean-clone-check` exports the committed repository into a temporary clean checkout, creates
a new virtual environment, installs only the declared runtime dependencies, initializes a separate
Git repository, synchronizes it with the default zero-key database, and connects through a real
stdio MCP client. The gate also proves that onboarding leaves the user's working tree clean.

Threadline uses dedicated local host ports so it does not collide with common local services:

- PostgreSQL: `55432`
- Redis: `56379`
- object-store API: `59000`
- object-store console: `59001`

## Repository map

```text
packages/context-model/   immutable domain contracts and invariants
packages/contracts/       public JSON Schemas and examples
apps/web/                 interactive evidence workbench
evals/                    frozen cases and baseline definitions
demo/                     deterministic synthetic continuation scenario
docs/adr/                 architectural decisions and tradeoffs
docs/threat-model/        security boundaries and known limitations
scripts/                  contract and repository quality gates
infra/migrations/         explicit forward and reverse database migrations
tests/                    unit, property, and contract tests
```

## Engineering principles

1. Context is not a transcript.
2. Evidence outranks generated confidence.
3. Authorization happens before retrieval.
4. Repository, branch, and commit are first-class.
5. Contradictions remain visible.
6. Humans own canonical and irreversible decisions.
7. Every retained architecture layer must earn its complexity through evaluation.
8. Public claims never exceed reproducible evidence.

See [the ADR index](./docs/adr/README.md), [the threat model](./docs/threat-model/THREAT_MODEL_V1.md), and [the evaluation baselines](./evals/baselines/README.md) for the current technical contract.
