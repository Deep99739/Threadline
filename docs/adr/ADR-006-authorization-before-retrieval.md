# ADR-006: Authorization before every retrieval path

- **Status:** Accepted
- **Date:** 2026-08-11
- **Owners:** Deepak Kumar

## Context

Filtering unauthorized vector/search results after retrieval can already leak document existence through candidates, ranks, caches, traces, errors, model prompts, or timing. Repository access also changes independently of Threadline membership.

## Decision

Authenticate the human/service/agent client, resolve tenant/workspace membership and current provider repository permission, then construct the allowed artifact/entity predicate before lexical, dense, graph, cache, or model access. Apply the predicate within every candidate query. Policy or identity uncertainty fails closed.

All storage/index/cache keys include tenant and repository scope. Remote MCP uses caller identity and per-client tool allowlists; read-only is the default. Revocation invalidates authorized context caches within the documented SLO.

## Alternatives

- **Retrieve then filter:** rejected because it leaks into intermediate systems.
- **Service account sees all installed repositories:** rejected for user-level reads; least privilege is required.
- **Long-lived permission cache:** rejected because revocation risk outweighs latency savings.

## Consequences

- Every retriever must accept an authorization scope; an unscoped search API is forbidden.
- Permission resolution affects availability and latency.
- Tests must cover DB, index, graph, cache, telemetry, and citation isolation.

## Security impact

This is the primary confidentiality boundary. A violation is a P0 incident requiring containment, evidence preservation, scope analysis, and regression expansion.

## Reversal or evolution

Policy implementation may move to a dedicated engine, but pre-retrieval enforcement and fail-closed behavior remain invariants. Cached authorization requires short TTL, revocation invalidation, and scoped proof.

## What breaks without it

Private source can influence an answer or appear in a model prompt even if the final citation is hidden. Threadline would be unsafe for real organizations.
