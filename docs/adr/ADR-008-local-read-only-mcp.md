# ADR-008: Bind local MCP tools to one read-only authorized workspace

- **Status:** Accepted
- **Date:** 2026-08-12
- **Owners:** Deepak Kumar

## Context

A coding agent needs structured access to a handoff, decision provenance, selection reasons, and
evidence. Letting a local MCP caller supply tenant identifiers would turn untrusted tool arguments
into an authorization decision. Exposing write tools before authenticated identities, approvals,
idempotency, and concurrency controls exist would overstate the authority of the local slice.

## Decision

The local stdio server is constructed with one trusted tenant/workspace/repository scope. Tool
arguments cannot select or override that scope. Every tool also requires an exact task, branch, and
commit; a version mismatch returns an abstention rather than context from another version.

The initial tools are read-only:

- `get_task_context` returns the latest cited handoff;
- `trace_decision` returns source provenance and labels repository approval metadata as asserted;
- `explain_context_selection` exposes deterministic selection reasons and ranker version; and
- `get_evidence` returns content only when the evidence belongs to the authorized task snapshot.

Every response shares request, trace, context-version, repository-version, status, data, citation,
unknown, conflict, and warning fields. The official SDK client must pass both an in-process contract
test and a spawned stdio end-to-end check.

## Alternatives

- **Tenant and workspace tool parameters:** rejected because identifiers are not authorization.
- **Unscoped local server:** rejected because local software can still contain multiple private
  repositories.
- **Write tools in the first slice:** rejected until authenticated approval, idempotency, audit, and
  optimistic concurrency boundaries are implemented.
- **Inspector-only validation:** rejected because it does not prove a real client can consume the
  server.

## Consequences

- One server process serves one trusted local workspace.
- Changing workspace requires starting a separately scoped process.
- Repository-source approval metadata remains `ASSERTED` until an authenticated connector or human
  approval record verifies it.
- Hosted remote MCP requires a separate authorization design and transport decision.

## Security impact

Scope is closed over by the server instead of accepted from tool input. Evidence membership is
checked against the authorized snapshot before content is read. Missing scope fails closed, stale
versions abstain, and every tool declares read-only, non-destructive behavior.

## Reversal or evolution

Remote streamable HTTP may replace the local process boundary after OAuth/OIDC identity, per-client
tool allowlists, revocation, tenant isolation tests, and audit logging exist. The same pre-retrieval
scope and exact-version checks remain mandatory.

## What breaks without it

A caller could request a guessed tenant or evidence identifier, receive context from the wrong
workspace, mutate canonical state without approval, or silently continue from a stale commit.
