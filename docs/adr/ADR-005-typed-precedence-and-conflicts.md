# ADR-005: Claim-type-specific precedence and preserved contradictions

- **Status:** Accepted
- **Date:** 2026-08-11
- **Owners:** Deepak Kumar

## Context

Code, tests, runtime observations, issues, decisions, and chat answer different questions. A global ranking such as “newest wins” or “code always wins” produces incorrect project truth.

## Decision

Resolve authority by claim type:

- implementation existence: exact source/call path at commit;
- behavior: appropriate test/CI/runtime evidence at version;
- deployment: environment observation tied to deployed commit;
- decision rationale: active authorized decision and its revision chain;
- intended work: current approved requirement/task;
- permission: current policy and provider authorization.

Retrieval relevance selects candidates; typed precedence determines how their claims may be used. Credible contradictions are preserved, surfaced, and may block continuation. Recency is a freshness signal, not universal authority.

## Alternatives

- **Single source ranking:** rejected because sources have different semantic authority.
- **LLM resolves conflicts in prose:** rejected because it hides evidence and is not reproducible.
- **Always return all sources:** rejected due to token waste and unsafe ambiguity.

## Consequences

- Claim classification must be accurate or safely unknown.
- The ranking trace must expose relevance separately from authority.
- Conflict cases become explicit eval and UI elements.

## Security impact

Precedence operates only on already authorized candidates. An authoritative source outside caller scope cannot influence ranking, explanation, or timing.

## Reversal or evolution

Precedence rules are versioned policies and can evolve per claim type with regression evaluation. Old context records retain the policy version that produced them.

## What breaks without it

A recent comment can override an approved ADR, a passing unit test can prove deployment, or a semantic match can outrank exact contradictory code evidence.
