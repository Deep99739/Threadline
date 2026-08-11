# ADR-003: Repository, branch, commit, and context-version semantics

- **Status:** Accepted
- **Date:** 2026-08-11
- **Owners:** Deepak Kumar

## Context

“Current project state” is ambiguous across repositories, branches, commits, force pushes, deployments, and task sessions. Reusing evidence from the wrong version is a core Threadline failure.

## Decision

Every material software claim is scoped to an immutable repository commit plus the branch observed at capture time, or declares a narrowly defined version-independent scope. A published `ContextVersion` binds tenant, workspace, repository, branch, commit, configuration version, and a content root hash. Handoffs reference one immutable context version and are superseded rather than edited.

Branch movement does not mutate old context. It may mark a handoff stale and schedule revalidation. Force pushes preserve orphaned history for audit while blocking it as current branch context. Deployment evidence names its environment and deployed commit separately from the default branch.

## Alternatives

- **Default branch only:** rejected because feature work and deployments diverge.
- **Latest timestamp wins:** rejected because recency is not lineage or authority.
- **Mutable task summary:** rejected because old actions cannot be reproduced/audited.

## Consequences

- More precise cache keys, queries, and user prompts are required.
- Context is reproducible and semantic diffs have exact endpoints.
- Some requests must abstain until the caller chooses a branch/commit.

## Security impact

Repository version is resolved only after repository authorization. Branch names and commit existence are not disclosed across access boundaries.

## Reversal or evolution

Additional version domains (deployment, package, infrastructure) may be linked explicitly. Commit binding remains for source claims unless superseded by a new trust model with equivalent reproducibility.

## What breaks without it

Threadline can serve passing tests from one commit alongside code from another, resurrect superseded work after a force push, and falsely report a merged change as deployed.
