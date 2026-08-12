# ADR-015: Record command-executed evidence without storing terminal output

- **Status:** Accepted
- **Date:** 2026-08-12
- **Owners:** Deepak Kumar

## Context

Threadline can verify a structured test report against the hashes of files in a committed Git
snapshot. A user or agent could still create that report by hand. Requiring everyone to build a CI
connector before a local handoff would preserve rigor at the cost of making the core workflow
impractical.

Running a command introduces a second risk: stdout, stderr, environment values, and command-line
arguments can contain credentials or private data. A trustworthy local evidence command must prove
what executed and what content it covered without turning Threadline into a terminal transcript
archive.

## Decision

`threadline check` executes one explicit command supplied after `--` in the target repository. The
caller must list each file whose current content the result is intended to cover and declare the
scope as `FULL` or `FOCUSED`.

The generated `threadline/test-report.json` stores:

- command exit status and declared scope;
- exact SHA-256 hashes for every included file;
- duration and output byte count;
- a digest of the captured output rather than the output itself;
- truncation status and runner version; and
- a redacted argument vector.

Inline command bodies and token-, secret-, password-, or API-key-like values are redacted. The
process inherits the caller's environment for compatibility, but environment values are never
serialized. The report is registered through a deterministic `test_report_scope` verifier in the
reviewable manifest. Threadline does not stage or commit the result.

`FULL` with exit code zero can become a verified all-tests-passed claim only after the report and
all hashed files exist together in a committed snapshot. A non-zero exit becomes contradicted.
`FOCUSED` or stale hashes remain insufficient evidence.

## Alternatives

- **Trust an agent-written “tests passed” observation:** rejected because a statement is not
  execution evidence.
- **Persist complete stdout and stderr:** rejected because logs frequently contain credentials,
  customer data, and large unrelated output.
- **Infer changed files automatically:** rejected because changed files are not necessarily the
  complete behavioral scope of a test command.
- **Require hosted CI for every user:** rejected for the local product; CI provenance remains the
  stronger hosted evidence path.

## Consequences

- Local users can produce materially stronger evidence with no provider account or API key.
- The report proves execution metadata and content binding, not that the command is a complete or
  well-designed test suite; scope remains an explicit reviewed assertion.
- Reproduction uses the recorded command and committed content, while sensitive raw logs remain
  outside Threadline.

## Security impact

Command execution is never triggered through the read-only MCP server. It is an explicit local CLI
action with a bounded timeout. Raw output and environment values are not persisted; likely secret
arguments and inline command bodies are redacted. Users remain responsible for reviewing the
command before running it.

## What breaks without it

The next agent must either trust an unsupported test claim or rerun every command. A manually typed
report could be mistaken for executed evidence, and storing complete terminal logs would create an
unnecessary credential and privacy surface.
