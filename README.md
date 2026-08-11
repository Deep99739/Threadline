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

The repository currently contains the trustworthy foundation:

- strict context-domain contracts;
- explicit epistemic states;
- tenant, workspace, repository, branch, and commit invariants;
- deterministic verification boundaries;
- typed precedence and contradiction rules;
- external JSON Schema contracts;
- thirty frozen continuation, safety, and reliability cases;
- a deterministic synthetic demo repository;
- six architecture decision records and a threat model;
- automated lint, type, contract, property, coverage, and structure checks; and
- a verified local PostgreSQL, Redis, and object-store environment.

The first complete ingestion → verification → retrieval → handoff → MCP workflow is under development. No hosted, adoption, accuracy, or production-readiness claim is made yet.

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
```

Later runs:

```bash
make check
make local-up
```

Stop local services:

```bash
make local-down
```

Threadline uses dedicated local host ports so it does not collide with common local services:

- PostgreSQL: `55432`
- Redis: `56379`
- object-store API: `59000`
- object-store console: `59001`

## Repository map

```text
packages/context-model/   immutable domain contracts and invariants
packages/contracts/       public JSON Schemas and examples
evals/                    frozen cases and baseline definitions
demo/                     deterministic synthetic continuation scenario
docs/adr/                 architectural decisions and tradeoffs
docs/threat-model/        security boundaries and known limitations
scripts/                  contract and repository quality gates
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
