# ADR-002: PostgreSQL is canonical; search and graph are projections

- **Status:** Accepted
- **Date:** 2026-08-11
- **Owners:** Deepak Kumar

## Context

Threadline needs transactional identity, tenancy, immutable provenance, state transitions, relational integrity, textual search, and future vector/graph queries. Early pilots do not justify multiple canonical databases.

## Decision

Use PostgreSQL 16 as the canonical metadata/context store. Keep large immutable payloads in content-addressed object storage. PostgreSQL FTS/pgvector and typed edge tables are the initial search and graph implementation. Any future OpenSearch, vector service, or graph database is a rebuildable projection fed through an outbox.

## Alternatives

- **Document database:** weaker relational and cross-entity integrity for the central trust path.
- **Graph database as primary:** premature operational complexity and awkward transactional control-plane data.
- **Search engine as primary:** unsuitable for approvals, strong invariants, and canonical mutation history.
- **Multiple primary stores:** rejected because dual-write inconsistency undermines evidence trust.

## Consequences

- One transactional boundary covers raw-event metadata, normalized context, verification, and outbox publication.
- Search scale is initially bounded by PostgreSQL; measured triggers determine extraction later.
- Projection rebuild and consistency checks must be first-class.

## Security impact

Row-level security and composite tenant foreign keys provide defense in depth. Application roles never own/bypass RLS. Object-store references retain tenant and sensitivity metadata.

## Reversal or evolution

Partition tables, add replicas, or introduce dedicated search when p95 latency, storage, maintenance, or ranking requirements cannot be met after tuning. The migration uses outbox replay and consistency hashes.

## What breaks without it

Without one canonical transactional store, claims, evidence, verifications, approvals, and index state can diverge with no authoritative recovery path.
