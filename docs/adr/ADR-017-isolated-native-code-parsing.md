# ADR-017: Isolate native code parsing and fail with explicit unknowns

- **Status:** Accepted
- **Date:** 2026-08-13
- **Owners:** Deepak Kumar

## Context

Threadline parses code supplied by repositories that it does not control. Tree-sitter and its
language grammars cross a native extension boundary. A malformed file, an incompatible runtime and
grammar combination, or a binding defect can terminate the Python process instead of raising an
exception. A continuation product cannot allow optional structural enrichment to take down the
handoff path or silently disappear from its trust report.

## Decision

Pin the Python Tree-sitter runtime to the tested `0.25.2` compatibility line and parse each supported
file in a spawned worker process with a bounded timeout. The worker returns plain Threadline data and
exits only after the parent acknowledges receipt. A crash, timeout, or raised exception produces a
`FAILED` parse diagnostic and no inferred symbols or relationships for that file.

Tree traversal copies native node facts into immutable Python values before graph logic uses them.
Incomplete syntax remains `PARTIAL`; it is never promoted to complete. Every non-complete diagnostic
is included in the compiled handoff's unknowns so a receiving agent can distinguish absent structural
evidence from a verified empty result.

## Alternatives

- **Parse in the API or CLI process:** rejected because a native crash would terminate the product.
- **Retry after a native failure:** rejected because repeating an unsafe deterministic input can
  repeat the crash and conceal a compatibility defect.
- **Drop failed files without a diagnostic:** rejected because absence would look like verified
  evidence.
- **Remove structural parsing:** rejected because commit-bound symbols and call paths materially
  improve continuation and failure attribution when they are available.

## Consequences

- One repository file cannot terminate the caller or corrupt another file's graph result.
- The compatible path returns complete symbols and dependencies for the large Python and TSX product
  surfaces in the regression suite.
- Process creation adds bounded ingestion latency and should later be replaced by a supervised worker
  pool after equivalent crash isolation is measured.
- A failed file lowers evidence completeness and is visible to both humans and agents.

## Security impact

Native parsing is now treated as untrusted computation with a process and time boundary. This limits
availability impact but is not an operating-system sandbox: hosted deployments still need resource
limits, patched native dependencies, and worker-level monitoring.

## Reversal path

Replace per-file workers with a supervised parser service or crash-isolated worker pool only after
the same complete, partial, crash, timeout, and handoff-unknown tests pass. The public diagnostic
contract must remain stable.

## What breaks without it

A repository can terminate Threadline during ingestion, or structural evidence can disappear without
changing the handoff status. Either outcome makes the continuation artifact untrustworthy.
