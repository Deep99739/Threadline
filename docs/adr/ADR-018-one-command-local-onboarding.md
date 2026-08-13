# ADR-018: Onboard one repository and client in one guarded command

- **Status:** Accepted
- **Date:** 2026-08-13
- **Owners:** Deepak Kumar
- **Supersedes:** The initial-adoption and client-profile consequences in ADR-014

## Context

The explicit workflows in ADR-014 kept Threadline's trust boundary visible, but first use required
users to run initialization, manually commit the contract, synchronize, diagnose the workspace,
connect a client, and decide whether a machine-specific profile belonged in Git. That sequence made
correct setup depend on private product knowledge and encouraged users to skip the exact-commit
boundary.

The committed task contract and a clean repository remain non-negotiable. Reducing setup friction
must preserve both rather than making an uncommitted manifest look trustworthy.

## Decision

Add `threadline onboard`, which performs one guarded local transaction:

1. Require an existing Git repository with a clean working tree and an attached branch.
2. Create `threadline.json` only when no contract exists.
3. Commit only that generated contract with the user's configured Git identity.
4. Synchronize and compile the handoff at the resulting exact commit.
5. Write only the explicitly selected client profile.
6. Keep a newly generated machine-specific profile local through `.git/info/exclude`.
7. Run the same readiness inspection used by `threadline doctor` before reporting success.

Repeated onboarding with the same objective, next action, client, and runtime is idempotent. An
existing contract with different task intent is not overwritten; users update it through the
reviewable checkpoint workflow.

## Alternatives

- **Serve an uncommitted initial manifest:** rejected because the first handoff would not be bound
  to the repository commit it describes.
- **Ask the user to keep running every primitive command:** rejected because ceremony is not a
  trust boundary and made correct adoption unnecessarily fragile.
- **Commit every client profile:** rejected because absolute runtime paths are machine-specific and
  create broken shared configuration on another developer's checkout.
- **Edit global client configuration:** rejected because it widens the execution scope beyond the
  repository the user selected.
- **Commit while unrelated work exists:** rejected because an onboarding tool must never mix its
  generated contract with a user's staged, unstaged, or untracked work.

## Consequences

- An installed Threadline checkout reaches a current MCP-connected handoff with one command.
- The first context commit is explicit in Git history and attributed to the invoking user.
- Local profiles do not dirty the repository or leak absolute machine paths into public history.
- Advanced users retain the lower-level `init`, `sync`, `doctor`, `clients`, and `connect` commands.
- A missing Git identity, dirty tree, conflicting task, or conflicting client profile fails visibly
  instead of producing partial trusted context.

## Security impact

The workflow writes only `threadline.json`, one selected project client profile, repository-private
SQLite state, and a repository-local exclude entry. It does not read secrets, require an API key,
edit global client settings, or execute model-generated commands. The generated MCP server remains
read-only and refuses stale repository state.

## Reversal path

Remove the `onboard` orchestration command while retaining each primitive workflow. Existing
contracts, handoffs, and client profiles remain valid.

## What breaks without it

New users can omit the configuration commit, synchronize the wrong state, share a broken absolute
runtime path, or abandon setup before the first evidence-backed handoff.
