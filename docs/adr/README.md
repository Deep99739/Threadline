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

Acceptance date: 2026-08-11. These establish the initial trust invariants; measurements may cause later superseding ADRs.
