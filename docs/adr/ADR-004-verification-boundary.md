# ADR-004: Deterministic and authorized-human verification boundary

- **Status:** Accepted
- **Date:** 2026-08-11
- **Owners:** Deepak Kumar

## Context

LLMs are useful for extracting and explaining project information, but model confidence cannot prove that code exists, is reachable, passed tests, is deployed, or is authorized. Letting an agent certify its own completion recreates the problem Threadline exists to solve.

## Decision

LLMs may create proposed claims, entity/edge extractions, search queries, explanations, and next actions. Only a versioned deterministic verifier or an explicitly authorized human may produce a verification capable of changing a claim to `VERIFIED` or `CONTRADICTED`. Verification persists inputs, tool/version, evidence, result, time, and hashes.

Canonical/irreversible decisions require an approval distinct from the proposing actor. Static code reachability is supporting evidence and is not silently promoted to runtime behavior proof.

## Alternatives

- **LLM-as-judge for all facts:** rejected due to self-consistency bias, hallucination, and non-reproducibility.
- **Human review of every retrieval:** rejected as unscalable and poor product value.
- **Trust source labels:** rejected because a test name or README can itself overclaim.

## Consequences

- Some facts remain `UNKNOWN` until a verifier exists or evidence is supplied.
- Verifier plugins and their false-positive behavior become important product assets.
- Generated explanations remain useful but never expand authority.

## Security impact

Model text cannot grant permissions, approve writes, or certify evidence. Verifiers execute with the minimum read scope and never receive unrelated tenant data.

## Reversal or evolution

Probabilistic verifiers may contribute evidence if calibrated and labeled, but cannot become sole authority for security, permissions, deployment, or irreversible actions without a superseding ADR and safety evaluation.

## What breaks without it

An agent can mark its own incomplete work complete, convert a README claim into “truth,” or mistake an unused adapter for functioning behavior.
