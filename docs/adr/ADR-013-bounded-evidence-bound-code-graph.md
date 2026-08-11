# ADR-013: Bounded evidence-bound code graph

- **Status:** Accepted
- **Date:** 2026-08-12
- **Owners:** Deepak Kumar

## Context

A continuation handoff can retrieve a file or claim by name and still omit the relationship that
matters. A test may construct a class, an entry point may call a helper, or one module may import
another. Requiring every next agent to reopen those files and reconstruct the same path wastes
tokens and creates another opportunity for an unsupported inference.

Threadline is not intended to compete with broad codebase graph explorers. Its narrower need is to
show the small code path behind a continuation claim while preserving the exact repository version,
tenant scope, source lines, and unresolved ambiguity.

## Decision

Threadline parses committed Python, JavaScript, JSX, TypeScript, and TSX files with packaged
Tree-sitter grammars. It creates stable module, class, function, and method symbols plus typed
`IMPORTS`, `CALLS`, and `CONSTRUCTS` dependencies. Every symbol and relationship points to the
evidence object created from the same Git commit. Grammar packages are installed with Threadline;
the runtime never downloads parser code.

Name resolution is deliberately conservative. A unique local target or same-scope target is linked.
External, dynamic, or ambiguous targets remain unresolved and visible. Files containing syntax
errors receive a persisted `PARTIAL` diagnostic, and nodes inside error regions are not indexed.

The read-only `trace_code_symbol` MCP tool accepts a stable logical key or unambiguous qualified
name. Traversal is authorization-scoped before lookup, bidirectional, limited to depth 0 through 5
and 1 through 100 nodes, and refused when the live repository differs from the synchronized commit.
Responses include exact line citations, parse warnings, unresolved relationships, and truncation.

Lexical retrieval remains the default handoff layer. The graph is invoked for relationship
questions. The executable Phase 2 ablation must continue to show a relationship that lexical
context alone cannot return before this layer is retained.

## Alternatives

- **Regex extraction:** rejected because it cannot reliably distinguish definitions, calls, imports,
  comments, and malformed syntax across the supported languages.
- **LLM-generated relationships:** rejected as canonical code evidence because the result is
  nondeterministic and may invent edges.
- **NetworkX or a graph database:** deferred because the current bounded projection fits in the
  canonical store and has not earned another operational dependency.
- **Embeddings before graph traversal:** deferred because exact symbols and typed edges already
  answer the first measured relationship case at zero model cost.
- **Index every language now:** rejected because unsupported breadth would weaken correctness and
  increase the test surface before demand is observed.

## Consequences

- Python and JavaScript-family dependencies gain deterministic structural context with no API key.
- Dynamic dispatch, aliases, re-exports, and framework wiring can remain unresolved; the product
  must disclose this rather than overstate call-graph completeness.
- A committed source change creates new versioned symbol identities and invalidates the old active
  projection through the existing repository-drift boundary.
- More languages can be added only with grammar packaging, fixture coverage, and an ablation that
  demonstrates a real query class.
- The current one-case ablation is retention evidence, not a general accuracy or scale claim.

## Security impact

Parsing reads only the already authorized committed snapshot. Tree-sitter grammars run locally and
do not execute repository code. All entities retain tenant, workspace, task, repository, branch,
commit, and evidence scope. Traversal cannot accept an arbitrary repository path, is bounded against
resource amplification, and fails closed when scope or live Git state does not match.

## Reversal or evolution

The code graph is a derived projection. It can be rebuilt from Git evidence, replaced by a more
precise language index, or removed without changing claims, decisions, verifications, and handoff
history. If measured repositories require richer resolution, a new ADR must define confidence,
incremental invalidation, storage, latency, and fallback behavior.

## What breaks without it

An agent can retrieve that `RetryPolicy` and its test exist but cannot see the typed edge proving
which test constructs the class. It must reread source and infer that relationship on every session.
The continuation remains cited at file level but loses the small, inspectable code path that makes
the evidence operational.
