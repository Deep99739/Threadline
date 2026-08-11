# Evaluation baseline definitions

All baselines receive the same task, exact repository version, allowed evidence scope, and output schema. They are evaluated on identical cases. Permission filtering is a safety invariant and is never removed merely to improve a baseline score.

## B0 — Full transcript

Supply the complete chronological task transcript within the model limit. No claim/evidence separation, typed precedence, or staleness processing is performed.

## B1 — LLM transcript summary

Generate one free-form summary from the transcript, then ask a fresh model/client to continue from it. The summary is not allowed hidden access to Threadline labels.

## B2 — Lexical evidence retrieval

Retrieve authorized evidence using exact identifiers and lexical ranking. Return citations, but do not use dense retrieval, graph expansion, typed precedence, or deterministic verification.

## B3 — Vector-only retrieval

Retrieve authorized evidence using semantic vectors only. This baseline will be added after embeddings are introduced and is not a current implementation claim.

## B4 — Full Threadline

Use authorization-safe candidate generation, verified evidence, typed precedence, staleness, graph relationships, and the sectioned context compiler. Each component is separately ablated before being retained.

## Reporting contract

Report per case type and overall:

- evidence precision, recall, and F1;
- expected next-action accuracy;
- unsupported-completion false acceptance;
- stale-context usage/detection;
- required abstention accuracy;
- citation validity;
- cross-scope leakage;
- token count, latency, and cost; and
- failure-layer attribution.

Publish raw counts and failed examples alongside any aggregate. The dataset labels are frozen before implementation tuning.
