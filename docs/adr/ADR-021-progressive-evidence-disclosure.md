# ADR-021: Return a compact continuation brief before detailed evidence

- **Status:** Accepted
- **Date:** 2026-08-13
- **Owners:** Deepak Kumar

## Context

The initial MCP client opened every cited source before a coding agent could take the next action.
That proved citations were accessible, but it also transferred the full ranked context pack and all
source content on every continuation. The behavior made Threadline another large context loader and
weakened its reason to exist.

A continuation agent usually needs the exact repository version, objective, constraints, verified
completed work, next action, uncertainty, conflicts, and citation locators first. Ranking details and
source bodies are useful when the agent challenges a claim, investigates a conflict, or prepares a
change. They need not be paid for up front.

## Decision

`get_task_context` returns a compact continuation brief by default. It retains:

- exact repository, branch, commit, task context version, request, and trace identity;
- objective, constraints, verified completed work, and next action;
- unknowns, contradictions, warnings, and deduplicated citation locators.

The caller can set `include_items=true` to receive the full ranked context items. Source content
remains available one citation at a time through `get_evidence`. The reference continuation client
does not open all sources eagerly.

The executed benchmark records minified UTF-8 payload bytes for compact and expanded responses.
This is a context-size proxy, not a tokenizer-specific token, latency, cost, or user-adoption claim.

## Alternatives

- **Always return the full ranked pack:** rejected because selection explanations dominate routine
  continuation payloads.
- **Always return cited source bodies:** rejected because it recreates manual repository loading and
  treats every source as equally necessary.
- **Return an uncited free-form summary:** rejected because it loses the inspectability and trust
  boundary that differentiates Threadline.
- **Estimate token savings with one model tokenizer:** deferred because client models differ and a
  byte proxy is the honest portable measurement available today.

## Consequences

- A coding agent can begin from one smaller read and inspect only disputed or relevant evidence.
- Exact version, uncertainty, and citations remain present in the default response.
- Clients that need ranking explanations make one explicit expanded call.
- Context savings depend on the task and model; the synthetic fixture cannot establish general
  token or time savings.

## Security impact

Progressive disclosure reduces automatic exposure of repository source content. Authorization,
version checks, redaction, untrusted-content labels, and read-only tool annotations still apply to
every detailed evidence read.

## Reversal path

Clients can request `include_items=true` without changing the server contract. A future benchmark
may change the default only through a superseding ADR.

## What breaks without it

Threadline consumes nearly the same context it claims to organize, agents pay to read irrelevant
ranking detail, and the product cannot make a defensible efficiency claim.
