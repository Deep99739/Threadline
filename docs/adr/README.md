# Architecture decision records

ADRs are immutable once accepted. A later decision supersedes an earlier record instead of rewriting its history. Every ADR must state the Threadline-specific need, alternatives, consequences, security impact, reversal path, and what fails without the chosen layer.

| ADR | Decision | Status |
|---|---|---|
| 001 | Typed context graph and explicit epistemic state | Accepted |
| 002 | PostgreSQL canonical store; derived search/graph projections | Accepted |
| 003 | Repository, branch, commit, and immutable context-version semantics | Accepted |
| 004 | Deterministic/human verification boundary; LLM proposals only | Accepted |
| 005 | Claim-type-specific precedence and preserved contradictions | Accepted |
| 006 | Tenant/repository authorization before every retrieval path | Accepted |
| 007 | Lexical baseline before dense retrieval | Accepted |
| 008 | Local read-only MCP bound to one authorized workspace | Accepted |
| 009 | Committed repository manifest for local workspace context | Accepted |
| 010 | Reviewable project client profiles and MCP bootstrap tool | Accepted |
| 011 | Refuse continuation after live repository drift | Accepted |
| 012 | Stable context identity and deterministic semantic differences | Accepted |
| 013 | Bounded evidence-bound code graph | Accepted |
| 014 | Explicit, reviewable, client-neutral local product workflows | Accepted |
| 015 | Command-executed, content-bound local evidence | Accepted |
| 016 | Redact stored evidence and label repository instructions untrusted | Accepted |
| 017 | Isolate native code parsing and fail with explicit unknowns | Accepted |
| 018 | One-command guarded local onboarding | Accepted |
| 019 | Separate context compilation from read-only consumption | Accepted |

ADRs 001–006 were accepted on 2026-08-11; ADRs 007–016 were accepted on 2026-08-12; ADR 017 was
accepted on 2026-08-13, followed by ADRs 018–019. These establish the current trust invariants;
measurements may cause later superseding ADRs.
