# ADR-014: Make local adoption explicit, reviewable, and client-neutral

- **Status:** Accepted
- **Date:** 2026-08-12
- **Owners:** Deepak Kumar

## Context

Threadline already produced an exact-commit handoff and generated configuration shapes for five
MCP-capable clients. A new user still had to understand several low-level commands, merge the
configuration manually, and interpret whether their local database contained a current handoff.
Terminal users also lacked a compact handoff format independent of an editor.

Reducing this friction must not weaken the trust boundary. Automatically editing global settings,
capturing unreviewed agent text as verified truth, or serving a handoff over a dirty repository
would make setup simpler by removing the properties Threadline exists to provide.

## Decision

Expose four product workflows over the existing local engine:

- `threadline doctor` inspects the committed manifest, live Git state, local store, and handoff
  freshness without mutating any state;
- `threadline connect <client>` writes only the explicitly selected project profile, preserves
  unrelated JSON servers, refuses to replace an existing Codex Threadline section, and never
  touches global settings;
- `threadline checkpoint` adds one reviewable `ASSERTED` human or agent observation and updates the
  next action in `threadline.json`; the user must commit it with the work it describes before sync;
- `threadline handoff` synchronizes the clean exact commit and emits either JSON or compact Markdown
  with epistemic states and evidence URIs.

Checkpoint creation may begin while other worktree files are dirty because that is when a handoff
is needed. It refuses an already-modified `threadline.json` and returns the complete set of paths
that should be reviewed and committed together. It never runs `git add` or `git commit` itself.

## Alternatives

- **Watch every editor transcript automatically:** rejected because proprietary clients expose
  different data, transcripts contain secrets and untrusted instructions, and prose cannot prove
  repository behavior.
- **Write every supported client configuration at once:** rejected because users should approve
  only the local server they intend to execute.
- **Store checkpoints beneath `.git` only:** rejected because the statement would not travel with
  the exact code commit and would have no review trail.
- **Allow checkpoints to declare `VERIFIED`:** rejected because only deterministic verifiers or an
  authenticated human approval boundary may certify a claim.

## Consequences

- A developer can adopt Threadline from a terminal or one supported coding client without an API
  key or external database.
- Configuration changes remain visible repository changes and can be reviewed by the team.
- Proprietary client trust prompts still require a real manual acceptance test.
- Agent checkpoint text remains useful context while visibly retaining its asserted state.

## Security impact

No global setting, token, API key, database URL, Git index, or commit is mutated. Existing JSON
profiles are structurally merged, and existing Codex Threadline configuration is not replaced
automatically. The live server remains read-only and exact-commit-bound.

## What breaks without it

Users can connect the wrong repository, overwrite unrelated MCP servers, assume an old handoff is
current, or paste a free-form agent summary into the next session with no visible evidence or
epistemic state.
