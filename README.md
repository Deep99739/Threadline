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
- sixteen architecture decision records and a threat model;
- exact-commit Git ingestion for tracked text evidence;
- a strict, committed `threadline.json` contract for arbitrary local repositories;
- explicit `init` and `sync` commands with refusal of uncommitted context configuration;
- a zero-key SQLite path inside Git's private metadata for single-user local adoption;
- deterministic Python symbol, call-path, test-scope, and evidence-sufficiency verifiers;
- authorization-scoped lexical retrieval with visible ranking reasons;
- cited, content-hashed context versions and handoffs;
- eight scope-bound, read-only MCP tools proven through a real stdio client;
- deterministic typed source precedence and semantic context-version comparison;
- commit-bound Tree-sitter symbols and typed imports, calls, and construction edges for Python and
  JavaScript-family repositories;
- bounded, cited code traversal with explicit parse health and unresolved relationships;
- live working-tree and branch-head drift detection on every MCP read;
- stale-handoff refusal with source-level invalidation reasons after the branch head moves;
- an official MCP Agent B client that performs the expected continuation, commits it, and
  re-verifies the resulting repository state;
- an executable primary-scenario evaluation with raw baseline outcomes and disclosed limits;
- an executable lexical-versus-graph ablation with raw relationship evidence and disclosed limits;
- an eleven-case executed continuation benchmark covering the MCP Agent B path, unsupported
  completion, citations, dirty and moved repository refusal, command evidence, graph recovery,
  scope denial, known-secret redaction, and instruction-boundary signals;
- reviewable evidence path exclusions, known-secret redaction before storage, served-content hashes,
  and explicit untrusted-repository warnings on MCP evidence reads;
- explicit Alembic migrations and tenant-scoped PostgreSQL storage;
- a repeatable synthetic CLI demo whose failure outcome comes from the real verifier path;
- a read-only HTTP demo surface over that exact compiled handoff;
- an interactive evidence workbench with state filters, source inspection, a retained executed
  continuation report, practical client setup, and an explicitly labelled bundled fallback;
- automated lint, type, contract, property, coverage, and structure checks; and
- a verified local PostgreSQL, Redis, and object-store environment.

No hosted, adoption, accuracy, or production-readiness claim is made yet.

Threadline does not replace a coding agent, a general memory store, or a broad code graph explorer.
It runs beside the user's existing tool and specializes in one workflow: transferring verified,
current engineering work between sessions and agents without trusting a free-form summary.

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

Before recording or publishing a release checkpoint, run the single composite gate:

```bash
make release-check
```

It executes the complete backend, contract, coverage, foundation, frontend, build, rendered-page,
clean-install, and real stdio MCP checks in a fixed reviewable order.

To run the interactive evidence workbench, keep these in two terminals after `make demo`:

```bash
make api
make web
```

Open `http://localhost:3000`. The website connects to the read-only demo API at
`http://localhost:8000`; if that API is unavailable, it remains usable as an explicitly labelled
bundled synthetic snapshot. The executed-proof section reads the retained eleven-case report from
`evals/results/continuation-benchmark-v0.2.json`; it does not turn that synthetic report into an
external accuracy, adoption, or production claim.

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

If a tracked path should never enter evidence, retrieval, the code graph, or citations, add a
reviewable repository-relative glob to `evidence_exclusions` in `threadline.json`, then commit the
manifest. Included text passes through bounded known-secret redaction before evidence content is
stored or served. MCP evidence is always labelled as untrusted repository data, and instruction-like
text cannot alter the server's task, repository, policy, permission, or approval scope. The local
scanner covers known credential shapes; it is not a replacement for a maintained provider scanner or
hosted quarantine workflow.

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

For the shortest explicit setup, write only the profile you intend to use:

```bash
/path/to/threadline/.venv/bin/threadline connect codex .
# or: claude, cursor, vscode, antigravity
```

This touches only that client's project file. It preserves unrelated JSON MCP servers and refuses
to replace an existing Codex Threadline section. Review and commit the generated project file only
if you want the team to share it; Threadline never changes global client settings.

Diagnose whether the repository, database, and compiled handoff agree:

```bash
/path/to/threadline/.venv/bin/threadline doctor .
```

When an agent or developer reaches a handoff point, record the observation and next action without
pretending the statement is verified:

```bash
/path/to/threadline/.venv/bin/threadline checkpoint . \
  --statement "The parser change is implemented; integration coverage is still missing" \
  --next-action "Add and run the whitespace integration test"
```

Threadline marks this text `ASSERTED`, lists the code and manifest paths that should be reviewed and
committed together, and does not stage or commit anything. After that commit, sync and print a
client-neutral handoff for a terminal or any model:

```bash
/path/to/threadline/.venv/bin/threadline sync .
/path/to/threadline/.venv/bin/threadline handoff .
# add --format json for machine-readable output
```

For checks that must become stronger than an agent observation, run the real command through
Threadline and name the files its result covers:

```bash
/path/to/threadline/.venv/bin/threadline check . \
  --scope FULL \
  --include src/parser.py \
  --include tests/test_parser.py \
  -- python -m pytest -q
```

The command writes a reviewable report containing the exit status, duration, runner, output digest,
and exact hashes of the included files. Raw stdout, stderr, environment values, likely secret
arguments, and inline command bodies are not persisted. The report becomes verifiable evidence only
after it is committed with those exact files and Threadline synchronizes that commit. A focused
check remains insufficient for an “all tests passed” claim, and a failed command remains visibly
contradicted.

Every client can call `get_workspace_status` first to discover the bound task, branch, commit, and
handoff freshness. The remaining tools require that exact identity and refuse another task or stale
commit. Threadline also re-reads the live Git state on every tool call. Uncommitted edits force
abstention, and a moved branch head remains stale until Threadline synchronizes and recompiles the
handoff.

The demo command seeds and compiles a real unfinished-task handoff. `make mcp-check` then starts
Threadline over stdio, connects with the official MCP client, discovers eight read-only tools, and
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

`make phase2-graph-eval` measures the retained code-graph layer on the same synthetic repository.
The frozen query asks which test constructs `RetryPolicy`. The lexical baseline can retrieve
relevant evidence but cannot return a typed symbol relationship; the bounded graph returns the
test-to-class `CONSTRUCTS` edge with exact source citations. The raw point-in-time report is retained
in [`evals/results/phase2-graph-ablation.json`](./evals/results/phase2-graph-ablation.json). Its
single synthetic case is not presented as a general accuracy or scale claim.

`make continuation-benchmark` executes eleven synthetic regression cases across five temporary Git
repositories. The primary case has Agent B consume the handoff through the official MCP client,
change code, run the full suite, commit, observe refusal of the old handoff, and receive a current
verified handoff. The remaining cases exercise unsupported completion, citation resolution, dirty
and moved repository abstention, passing and failing command evidence, typed graph recovery,
wrong-task scope denial, known-secret redaction, and repository-instruction boundary signals. Raw
per-case outcomes, baseline failures, denominators, and limitations are retained in
[`evals/results/continuation-benchmark-v0.2.json`](./evals/results/continuation-benchmark-v0.2.json).
This is a deterministic synthetic regression benchmark, not an external accuracy or adoption claim.

## Threadline on Threadline

This repository owns a committed `threadline.json` task contract. Release evidence can therefore be
recorded through the same public workflow used by another repository: execute `make release-check`
through `threadline check`, review and commit the generated content-bound report, synchronize the
commit, then inspect the handoff through the CLI or MCP. The self-hosted report is evidence for that
exact commit only; it is not a hosted-production or user-adoption claim.

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
