# Threadline threat model v1

**Status:** Initial baseline
**Date:** 2026-08-11
**Scope:** local vertical slice through future hosted pilot
**Review trigger:** before Phase 4 external access, after any identity/storage boundary change, and after every P0 incident

## 1. Protected assets

- private source, issues, pull requests, tests, CI, deployment, and decision evidence;
- tenant, workspace, repository, actor, and permission metadata;
- credentials, OAuth tokens, webhook secrets, encryption keys, and provider keys;
- canonical claims, verifications, decisions, approvals, context versions, and audit logs;
- prompt/model/index/ranker/policy configuration;
- external-user identity and usage data; and
- availability and integrity of handoffs consumed by coding agents.

## 2. Trust boundaries

1. Browser/IDE/agent client → API or MCP.
2. GitHub/provider → signed ingestion gateway.
3. Gateway → raw object store/PostgreSQL outbox.
4. Queue → normalization, parsing, verification, and indexing workers.
5. Canonical PostgreSQL → derivative search/graph/cache.
6. Authorized candidates → optional external model/embedding provider.
7. Control-plane identity/policy → all data-plane queries.
8. Operator/admin access → audit and tenant data.

Repository files, comments, issue text, model output, webhook payloads, and client-provided observations are untrusted.

## 3. Threat actors

- unauthenticated external attacker;
- authorized member exceeding repository scope;
- malicious or compromised tenant member;
- compromised agent/MCP token;
- malicious repository contributor;
- spoofed/replayed provider webhook;
- compromised dependency or build artifact;
- mistaken or malicious operator; and
- noisy tenant exhausting shared capacity.

## 4. Abuse cases and required controls

| Threat | Impact | Required controls | Initial verification |
|---|---|---|---|
| Cross-tenant edge or query | Confidentiality breach | tenant on every row/edge; RLS; composite keys; scoped queries | property/unit tests now; DB adversarial suite Phase 4 |
| Post-retrieval permission filtering | Candidate/model/cache leak | resolve provider ACL before every retriever | architecture test and retriever interface review |
| Prompt injection in code/README/issue | Policy bypass, unsafe write | treat evidence as data; tool policy outside model; approval boundary | injection eval cases 016–017; executed local boundary case |
| Secret enters index/log/model | Credential compromise | exclusions, scanner, quarantine, redaction, minimal telemetry | secret eval case 018; executed local redaction case |
| Agent self-verifies completion | Incorrect context/unsafe continuation | deterministic/human verifier only; persisted evidence | context invariant tests and cases 002–003 |
| Webhook spoof/replay/order | Corrupt project state | signature/timestamp, idempotency, raw immutable event, reconciliation | cases 019–022; integration tests Phase 3 |
| Cache key omits scope/version | Data leak or stale context | tenant/repo/actor/policy/version-qualified keys | cache isolation tests Phase 4 |
| Revoked user reuses handoff | Continued unauthorized access | short authorization cache; revocation invalidates packs | eval case 015; hosted test Phase 4 |
| Forged evidence/citation | False verification | content hashes, immutable payloads, exact locators, verifier input hash | model/contract tests now; object-store test Phase 3 |
| Cost/queue exhaustion | Denial of service | size/rate/job quotas, backpressure, per-tenant concurrency | load tests Phase 5 |
| Admin/audit tampering | Lost accountability | least privilege, append-only audit, restricted export | pilot control review Phase 4 |
| Dependency compromise | Code/data compromise | lockfiles, scanning, signed images, minimal dependencies | CI scans from the first implementation onward |

## 5. Security invariants

- Missing tenant, repository, actor, or policy scope yields denial—not a default scope.
- Unauthorized content never enters candidate sets, models, caches, traces, errors, or citations.
- `VERIFIED` always links to an allowed verifier result and evidence at the same version.
- LLM output cannot grant permissions, approve decisions, or invoke an unallowed tool.
- Controlled writes require identity, scope, idempotency, audit, and approval where defined.
- Published context is immutable and content-hashed.
- Real credentials never enter Git, fixtures, screenshots, test reports, or model prompts.

## 6. Privacy and retention baseline

Store only evidence required for declared engineering workflows. Prefer content hashes and provider pointers when raw duplication is unnecessary. Classify evidence sensitivity, allow path/file exclusions, redact telemetry, and define export/deletion before external pilots. Synthetic public-demo tenancy contains no copied private data.

## 7. Incident severity

- **P0:** cross-tenant/repository disclosure, unauthorized mutation, active credential exposure, or canonical-evidence corruption.
- **P1:** widespread wrong/stale context, broken revocation, or prolonged service/ingestion outage without confirmed sensitive exposure.
- **P2:** bounded incorrect result or degraded component with safe fallback.

P0 handling: immediately contain serving/credentials, preserve audit evidence, determine scope, notify according to policy, repair, add adversarial regression, and publish an honest postmortem where appropriate.

## 8. Known current limitations

- No hosted authentication, database RLS, provider connector, remote MCP, maintained provider-grade secret scanner, or quarantine workflow exists yet.
- The local slice now has reviewable path exclusions, bounded known-secret redaction, served-content hashes, and explicit untrusted-repository instruction signals.
- The threat controls above are design requirements, not deployed claims.
- The current foundation proves in-memory cross-entity invariants and freezes security eval cases.
- External or private repositories must not be connected until the Phase 4 gates pass.
