# ADR-012: Stable context identity and semantic differences

- **Status:** Accepted
- **Date:** 2026-08-12
- **Owners:** Deepak Kumar

## Context

Threadline publishes a new handoff after repository evidence changes, but generated database UUIDs
cannot explain what changed. Re-ingesting the same commit creates fresh entity and evidence IDs,
and each MCP request has fresh request and trace IDs. Comparing those transport identifiers would
report noise instead of project meaning.

A second coding agent needs a stable answer to two different questions: whether an identical
selection is the same context version, and which claims, constraints, decisions, or observations
meaningfully changed between two versions.

## Decision

Every selected context item has a type-qualified logical key that is independent of its database
identity. The compiler creates a canonical semantic projection containing the repository version,
task and purpose, retrieval query and budget, ranker configuration, logical keys, statements,
epistemic states, authority explanations, and citation locators. Volatile request, trace, entity,
evidence, and handoff IDs are excluded.

The canonical projection produces both a content root hash and a deterministic UUIDv5 context
version identifier within the tenant, workspace, and task scope. Publishing the same semantic input
is idempotent and returns the original stored context-version record.

The read-only `compare_context_versions` MCP tool compares stored context packs by logical key and
classifies each material difference as `ADDED`, `REMOVED`, `CHANGED`, `STALE`, `CONTRADICTED`, or
`SUPERSEDED`. It returns the before and after items with citations and explicit reasons. Both
versions must belong to the same authorized tenant, workspace, and task, and the live repository
must still match the active snapshot before the comparison is served.

## Alternatives

- **Compare database UUIDs:** rejected because deterministic re-ingestion may generate different
  storage identities for the same project meaning.
- **Compare serialized handoffs byte for byte:** rejected because request, trace, publication, and
  evidence IDs are intentionally volatile.
- **Ask an LLM to summarize differences:** rejected as the primary mechanism because classifications
  would be nondeterministic and could omit contradictions.
- **Reuse the latest timestamp as identity:** rejected because time does not establish semantic
  equality or ordering authority.

## Consequences

- Producers must maintain collision-resistant logical-key rules for every entity type.
- Any semantic input that can change an agent decision must appear in the canonical projection.
- Repeated compilation can create new handoff envelopes while correctly referencing the same
  immutable context version.
- Selection changes caused by a query or token budget remain visible rather than being confused
  with repository changes.
- Historical graph projections are still future work; this decision compares immutable compiled
  context packs already retained by the handoff store.

## Security impact

Deterministic IDs include tenant, workspace, and task scope, preventing equal content in different
authorized scopes from sharing an identifier. Comparison queries are scope-filtered before content
is loaded. The tool returns only evidence already present in the two authorized handoffs and accepts
no repository path from the caller.

## Reversal or evolution

The canonical projection is versioned by the ranker configuration. A future schema can introduce a
new namespace or configuration version while retaining old context versions for exact comparison.
Logical keys may gain explicit schema versions if richer symbol, dependency, or deployment entities
need different identity rules.

## What breaks without it

Agents see false changes after harmless re-ingestion, real contradictions disappear inside prose,
and operators cannot reproduce why a continuation recommendation changed between commits. An
interviewer or user also cannot distinguish a genuine evidence transition from regenerated IDs.
