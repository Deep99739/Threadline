# ADR-001: Typed context graph and explicit epistemic state

- **Status:** Accepted
- **Date:** 2026-08-11
- **Owners:** Deepak Kumar

## Context

Transcripts and summaries collapse task intent, implementation, evidence, decisions, and uncertainty into prose. Threadline must preserve relationships and show whether a proposition is asserted, observed, verified, contradicted, stale, superseded, or unknown.

## Decision

Model project context as typed entities plus versioned, attributable edges. Store claims independently from evidence and verification. The vocabulary in `packages/context-model` is the executable source; additions require a schema change and migration. Epistemic state is an enum with explicit transition rules, not free-form model output.

## Alternatives

- **Transcript plus generated summary:** rejected because it loses authority, contradiction, and lineage.
- **Unstructured vector documents:** rejected as a canonical model; similarity does not express validity.
- **Immediate graph database:** deferred because current traversals fit relational edge tables and no measured workload requires another system.

## Consequences

- Retrieval and UI can explain lineage, conflicts, and version scope.
- More entities and state transitions must be validated than in a document-only design.
- Graph projections remain rebuildable; PostgreSQL records are canonical.

## Security impact

Every node and edge carries tenant/workspace scope. Cross-tenant edges are rejected before publication. Evidence content remains subject to artifact-level authorization.

## Reversal or evolution

The ontology can evolve with versioned migrations. A graph database may become a derived projection if measured multi-hop workloads justify it; it cannot replace canonical provenance without a new ADR.

## What breaks without it

Threadline becomes a memory summarizer. It cannot safely distinguish a claim from proof, preserve rejected decisions, propagate staleness, or explain why a handoff item is trustworthy.
