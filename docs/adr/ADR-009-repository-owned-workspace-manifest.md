# ADR-009: Use a committed repository manifest for local workspace context

- **Status:** Accepted
- **Date:** 2026-08-12
- **Owners:** Deepak Kumar

## Context

The first continuation slice proved exact-commit ingestion and MCP consumption against a synthetic
repository, but the ingestor knew that repository's filenames, task, decision, and verifier set.
Keeping those assumptions in product code would make Threadline a scripted demo rather than a tool
another repository could adopt.

A local client also needs a stable workspace identity and task identifier without treating either
as a secret or asking each coding agent to invent them. The context definition must move with the
repository, while database files and credentials must remain local.

## Decision

Each adopted repository owns a strict, versioned `threadline.json` manifest. It contains:

- a stable repository and task identifier;
- the active objective, status, next action, and retrieval query;
- sourced decisions, constraints, and observations; and
- an explicit allowlist of deterministic verifier configurations.

The manifest is read from `HEAD`, not inferred from the working tree or a chat transcript. Sync
refuses an uncommitted or modified manifest. All referenced paths must be repository-relative,
present in the same committed snapshot, and converted into cited evidence.

Local tenant, workspace, and actor identifiers are deterministic UUIDs derived from a fixed
Threadline namespace and the manifest repository identifier. They are isolation keys, not
authentication credentials. Hosted identity will replace this derivation without changing the
manifest's repository and task semantics.

Local adoption defaults to a repository-private SQLite database under `.threadline/`. PostgreSQL
remains the deployable canonical-store path. Starting the repository MCP process synchronizes and
compiles the exact current commit before exposing the same read-only, scope-bound tools.

## Alternatives

- **Infer context from transcripts:** rejected because prose cannot authenticate decisions or prove
  implementation and test claims.
- **Keep a global mutable workspace file:** rejected because it can drift from the repository and
  is easy to bind to the wrong clone.
- **Hard-code repository adapters:** rejected because each new user would require a product-code
  change.
- **Auto-discover and certify arbitrary claims:** rejected because discovery is not verification.
- **Require PostgreSQL for every local user:** rejected because it adds infrastructure before a
  single-repository user can inspect the trust model.

## Consequences

- A repository must commit `threadline.json` before Threadline will serve it.
- The default manifest creates task context but no verified claims; users must deliberately add
  supported verifier configurations.
- Configuration changes create a visible Git review trail and naturally invalidate old handoffs.
- A clone can use Threadline without API keys or a separately provisioned database.
- Multi-user approval identity and hosted tenancy remain future control-plane work.

## Security impact

Path traversal and unknown configuration fields are rejected. An agent-authored observation cannot
self-certify as `VERIFIED`. Repository approval metadata remains asserted, and the manifest never
contains provider tokens or database passwords. Client tools remain read-only after synchronization.

## Reversal or evolution

A later manifest version can add verifier families, multiple tasks, signed approvals, or hosted
workspace references. Migration must be explicit, and old versions remain readable until their
documented support window ends.

## What breaks without it

Threadline could appear to support arbitrary repositories while actually serving one synthetic
layout, bind an agent to uncommitted context, accept unsafe evidence paths, or silently reuse stale
task metadata after the repository changes.
