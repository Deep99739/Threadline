# ADR-010: Generate reviewable project client profiles and a bootstrap tool

- **Status:** Accepted
- **Date:** 2026-08-12
- **Owners:** Deepak Kumar

## Context

Threadline's local server uses standard MCP over stdio, but each coding client stores the launch
command in a different project configuration shape. A user should not need to reverse-engineer
Codex, Claude Code, Cursor, VS Code, or Antigravity configuration to test the same server.

At the same time, silently editing global client settings would be an unsafe adoption shortcut.
Local MCP commands execute code, configuration files may already contain other servers, and a
machine-specific Python environment should not be presented as a portable team configuration.

The first task-context tool also requires a task, branch, and commit. A newly connected client needs
a safe way to discover those server-bound values without guessing or reading a transcript.

## Decision

`threadline clients` emits one machine-readable bundle containing:

- the single stdio command for the current installed Python environment;
- project file paths and mergeable content for each supported client;
- official documentation links;
- optional Codex and Claude installation command arrays; and
- explicit flags stating that the output contains no secrets and writes no client configuration.

The output uses machine-local absolute paths and must be reviewed before it is merged. Threadline
does not create `.codex`, `.cursor`, `.vscode`, `.agents`, or `.mcp.json` files automatically.

The MCP server adds `get_workspace_status`, a no-argument read-only bootstrap tool. It returns the
server-bound task, objective, next action, exact repository version, and handoff freshness. Every
subsequent tool remains bound to that task and requires the exact branch and commit.

The launch command uses the virtual environment's original Python path with `python -m threadline`.
It deliberately preserves the virtual-environment symlink; resolving it to the base interpreter
would lose the installed Threadline environment.

## Alternatives

- **Document one generic JSON snippet:** rejected because Codex and VS Code use different top-level
  configuration structures.
- **Modify global settings automatically:** rejected because it expands scope, can overwrite user
  configuration, and bypasses client trust review.
- **Ship five protocol implementations:** rejected because the clients all consume the same MCP
  stdio server; only launch configuration differs.
- **Require users to copy task and commit identifiers into prompts:** rejected because discovery is
  a protocol concern and manual identifiers are easy to stale.

## Consequences

- One server implementation can serve all five client families.
- Generated profiles are immediately usable on the current machine but are not claimed portable
  across clone paths or Python environments.
- Proprietary client trust prompts and UI behavior remain acceptance checks outside Threadline's
  own test suite.
- The generated launch command is still proven through a spawned official MCP client session.

## Security impact

No token, API key, database URL, or global path is written to a client file. Users review the exact
executable and arguments before installation. The bootstrap tool exposes only metadata already in
the authorized snapshot, and callers cannot use another task identifier to cross the server scope.

## Reversal or evolution

A future installer may write or merge profiles after explicit confirmation and client-specific
schema validation. A signed portable launcher can replace absolute machine paths when distribution
and upgrade semantics are defined.

## What breaks without it

Users could configure the wrong repository, launch Threadline outside its environment, leak a
database credential into shared editor settings, overwrite unrelated MCP servers, or connect
successfully but have no reliable way to discover the current task and commit.
