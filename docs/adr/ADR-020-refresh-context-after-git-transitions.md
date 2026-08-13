# ADR-020: Refresh context after repository transitions through guarded local hooks

- **Status:** Accepted
- **Date:** 2026-08-13
- **Owners:** Deepak Kumar

## Context

ADR-019 made context compilation explicit and consumption read-only. That removed hidden mutations,
but a developer still had to remember `threadline sync` after every commit, checkout, merge, or
rebase. Forgetting created a correct but stale handoff and made Threadline feel like ceremony rather
than part of the coding workflow.

Git already exposes exact transition boundaries after the repository reaches a committed state.
Those boundaries can trigger the same explicit synchronization workflow without granting MCP tools
write access.

## Decision

During onboarding, install repository-local managed hooks for `post-commit`, `post-checkout`,
`post-merge`, and `post-rewrite`.

- Each hook invokes the installed Threadline runtime for that exact repository.
- Hooks are machine-local Git metadata and are never committed.
- Refresh failure never blocks the Git operation; it is written to
  `.git/threadline/hook-errors.log`, and stale MCP reads still fail closed.
- Existing unmanaged hooks and a configured `core.hooksPath` are never changed. Threadline reports
  the conflict and requires manual synchronization for that repository.
- Re-running onboarding recognizes current managed hooks and does not rewrite them.

## Alternatives

- **Make MCP reads synchronize automatically:** rejected by ADR-019 because consumers would regain
  hidden write side effects.
- **Require manual synchronization forever:** rejected because correctness depended on memory and
  imposed recurring friction on every supported client.
- **Replace or concatenate existing hooks:** rejected because arbitrary hook composition can alter
  another tool's execution guarantees and quoting behavior.
- **Block a commit when refresh fails:** rejected because derived context must not prevent users
  from recording source history.
- **Run a permanent filesystem watcher:** rejected because it adds process lifecycle, battery, and
  platform complexity before Git transition hooks have proven insufficient.

## Consequences

- The usual workflow is onboard once, then commit normally.
- Codex, Claude, Cursor, VS Code, Antigravity, and terminal consumers see context for the latest
  clean commit without a repeated setup command.
- Repositories with existing hook management retain their setup and receive an explicit fallback.
- Updating or removing the installed Threadline runtime can make a hook refresh fail, but cannot
  corrupt or block Git; consumers expose the stale handoff until the runtime is repaired.

## Security impact

Hooks execute only the locally installed Threadline module with a fixed `sync` command and absolute
repository path. They do not interpolate commit messages, filenames, model output, or repository
content into the command. Existing hook trust boundaries are preserved.

## Reversal path

Remove only hooks containing the Threadline managed marker. The lower-level explicit
`threadline sync` workflow remains sufficient.

## What breaks without it

Users routinely encounter stale context after ordinary commits, learn to ignore the MCP status,
or abandon the product because maintaining the handoff costs more attention than it saves.
