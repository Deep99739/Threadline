# ADR-019: Separate context compilation from read-only consumption

- **Status:** Accepted
- **Date:** 2026-08-13
- **Owners:** Deepak Kumar
- **Supersedes:** MCP startup behavior in ADR-008 and handoff behavior in ADR-014

## Context

Threadline initially synchronized repository evidence when the MCP server started or a terminal
handoff was requested. That kept context fresh with fewer visible commands, but a read operation
could migrate a database, ingest files, replace stored entities, and compile a new artifact. It
also made repeated reads difficult to reason about and allowed client startup to hide a stale
handoff instead of exposing it.

An evidence system must make mutation boundaries inspectable. Consumers should receive the exact
artifact that was explicitly compiled for the repository commit, or a clear refusal.

## Decision

- `threadline sync` and `threadline onboard` are the only local workflows that compile a handoff.
- `threadline handoff` reads an existing handoff without mutating repository or database state.
- Workspace MCP startup opens existing local state without ingesting or compiling anything.
- Both consumers compare the stored branch and commit with the live clean repository and refuse
  missing or stale context with an instruction to run `threadline sync`.
- Entity, edge, context-version, and handoff identities are deterministic for the same committed
  input. Repeating an explicit sync is idempotent.

## Alternatives

- **Synchronize before every read:** rejected because reads would have hidden side effects and MCP
  startup could silently redefine the artifact a user intended to inspect.
- **Serve the latest stored handoff even after Git moved:** rejected because a plausible stale
  summary is more dangerous than an explicit absence of context.
- **Use timestamps as entity identity:** rejected because repeated ingestion would accumulate
  duplicates and prevent byte-stable handoffs.
- **Delete all historical context during sync:** rejected because semantic comparison and audit
  history require older commit-bound versions.

## Consequences

- Repeated handoff and MCP reads are side-effect free.
- A moved branch head produces a visible stale-context failure until the user synchronizes.
- Storage growth reflects new repository commits, not repeated reads or repeated syncs.
- Onboarding still reaches first value in one command because it performs one explicit compilation
  before connecting the client.

## Security impact

Untrusted client startup cannot trigger repository ingestion or database migration. Consumers are
restricted to an existing tenant-, workspace-, task-, branch-, and commit-scoped artifact. Missing
state fails closed.

## Reversal path

An explicit opt-in watcher could call the existing synchronization workflow after observing a Git
commit. It must remain separate from MCP tool reads and expose its mutation lifecycle.

## What breaks without it

A user cannot distinguish “read the reviewed handoff” from “recompute project truth now,” repeated
reads can grow or alter local state, and stale context may be replaced before its failure is seen.
