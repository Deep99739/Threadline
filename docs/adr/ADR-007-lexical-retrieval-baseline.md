# ADR-007: Measure a lexical retrieval baseline before adding dense search

- **Status:** Accepted
- **Date:** 2026-08-12
- **Owners:** Deepak Kumar

## Context

Engineering handoffs contain exact symbols, filenames, test names, states, and decision language. A
dense retriever can help with paraphrases, but it also introduces embedding freshness, provider,
cost, projection, authorization, and evaluation failure modes. Threadline needs a reproducible
baseline before that complexity can be justified.

## Decision

The first retrieval path is deterministic lexical ranking over an already authorized context
snapshot. It scores exact and prefix matches, then applies explicit boosts for contradictions,
unknowns, stale claims, and high-severity constraints. Stable tie-breaking makes a handoff
reproducible for the same repository version, configuration, scope, and query.

Authorization is checked before candidates are constructed. Retrieval returns entity identifiers,
epistemic states, evidence identifiers, scores, and selection reasons so the compiler can preserve
citations and expose why each item was selected.

Dense retrieval is added only after a frozen comparison set shows a material improvement over this
baseline without weakening scope isolation, freshness, reproducibility, or latency targets.

## Alternatives

- **Dense retrieval first:** rejected because there would be no measured baseline and exact
  engineering identifiers may perform worse.
- **Hybrid retrieval immediately:** rejected because component contribution could not be isolated.
- **Transcript keyword search:** rejected because transcripts are not the canonical context model
  and do not preserve verification or precedence.
- **Graph-only traversal:** rejected because it cannot reliably resolve an unseen natural-language
  query to starting entities.

## Consequences

- The initial search surface is intentionally narrow and explainable.
- Synonyms and broad conceptual queries may have lower recall until measured dense retrieval earns
  inclusion.
- Every later retriever must be evaluated separately and in combination against this baseline.
- Ranking configuration becomes a versioned input to each published context version.

## Security impact

No unscoped corpus search is permitted. The lexical implementation accepts only a previously
authorized snapshot and rejects mismatched tenant or workspace scope before scoring. Query text and
selection traces must not bypass the same telemetry redaction rules as other context data.

## Reversal or evolution

PostgreSQL full-text search, dense embeddings, reranking, and graph expansion may supersede or
augment the in-memory scorer after evaluation. The lexical baseline remains available for
regression comparison and degraded operation.

## What breaks without it

Threadline could accumulate search infrastructure without knowing which layer improves task
continuation. Failures would be harder to attribute, exact technical queries could regress, and
public quality claims would lack a reproducible control.
