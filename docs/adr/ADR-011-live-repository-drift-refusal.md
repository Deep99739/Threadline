# ADR-011: Refuse continuation after live repository drift

- **Status:** Accepted
- **Date:** 2026-08-12
- **Owners:** Deepak Kumar

## Context

Threadline compiles a handoff from committed evidence at one exact branch and commit. A coding
client can keep the MCP server open while an engineer or another agent edits the same working tree.
Checking only the branch and commit supplied by the caller would allow an old handoff to appear
current after uncommitted edits or a new commit.

This is especially dangerous for long-running agent sessions. The server process can be healthy,
the stored snapshot can be internally consistent, and the caller can repeat the original commit,
while the files the next action will modify no longer match that evidence.

## Decision

Every read-only MCP tool re-reads the repository's live Git state from the server-bound path. The
server compares the live branch and `HEAD` with the stored snapshot and separately checks for
tracked or untracked working-tree changes.

- A dirty working tree makes `get_workspace_status` report `dirty` and makes context, decision,
  selection, and evidence tools abstain.
- A live branch or `HEAD` mismatch makes the workspace report `stale` and makes those tools
  abstain.
- `list_stale_context` reports runtime drift without claiming source-level invalidation details
  that have not yet been ingested.
- Continuation resumes only after the user commits or reverts edits and Threadline synchronizes
  the new repository version.

The caller cannot override the repository path, task, or observed live version through MCP
arguments.

## Alternatives

- **Trust the caller-supplied commit:** rejected because an agent can repeat an old identifier
  while operating on changed files.
- **Check Git only at server startup:** rejected because it leaves a time-of-check/time-of-use gap
  for every long-running session.
- **Automatically ingest every file-system change:** rejected because uncommitted work has no
  immutable identity and can change while verification runs.
- **Serve the old snapshot with a warning:** rejected because a warning does not prevent an agent
  from acting on stale instructions.

## Consequences

- MCP reads perform small local Git queries before returning authorized context.
- Active coding temporarily blocks continuation until work is committed or reverted.
- Runtime drift and ingested source invalidation remain distinct: the former is detected
  immediately, while the latter is explained after synchronization.
- A missing or unreadable bound repository fails closed as a tool error rather than serving the
  stored handoff without a live check.

## Security impact

The repository path is fixed when the server starts, and Git state is read locally without accepting
caller-provided paths. Untracked paths are disclosed only within that already authorized local
workspace. No file contents are read from the working tree for this check.

## Reversal or evolution

A future watcher may cache Git state between file-system events, but every response must preserve
the same fail-closed freshness guarantee. A controlled draft-work mode could be added only with an
explicit non-commit identity and separate evidence semantics.

## What breaks without it

An agent can receive a validly cited handoff for commit A after the working tree or branch has moved
to state B. It may then repeat obsolete work, violate a changed constraint, cite evidence that no
longer describes the files it edits, or claim verification against the wrong repository state.
