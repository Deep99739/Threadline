# ADR-016: Redact stored evidence and label repository instructions untrusted

- **Status:** Accepted
- **Date:** 2026-08-12
- **Owners:** Deepak Kumar

## Context

Threadline serves source evidence directly to coding agents. A tracked source file can contain an
accidental credential, and repository prose can contain instruction-shaped text that attempts to
override scope, approve its own proposal, or redirect an agent to another repository. Exact-commit
hashing proves where content came from; it does not make that content safe or authoritative.

## Decision

The committed `threadline.json` contract may define repository-relative `evidence_exclusions`.
Excluded files never enter the evidence snapshot, code graph, retrieval path, database, or citation
set. The manifest itself cannot be excluded.

For included text, Threadline deterministically redacts bounded known credential forms before raw
content is stored or served. Evidence keeps the original Git content hash as its immutable source
locator, while evidence reads also return a hash of the served representation. A redacted item is
marked `REDACTED`, and the API and MCP response disclose that the two hashes bind different forms.

Every MCP evidence response labels content `untrusted_repository_data`. Instruction-shaped text is
retained as evidence, flagged, and accompanied by an explicit warning that it cannot change scope,
permissions, policy, approval, or tool access. Tool scope and authorization remain outside repository
content and outside model discretion.

## Alternatives

- **Trust tracked files because Git recorded them:** rejected because provenance is not authority.
- **Drop every file containing a secret-like value:** rejected because adjacent non-secret evidence
  can remain useful after deterministic redaction.
- **Delete instruction-shaped prose:** rejected because it can be relevant evidence and deleting it
  hides the attack rather than preserving it as untrusted data.
- **Rely only on the consuming model:** rejected because prompt-injection resistance must not depend
  on model obedience.

## Consequences

- Common secret forms do not enter stored or served evidence in the tested local workflow.
- Teams can exclude generated, private, or irrelevant committed paths through reviewable Git state.
- Consumers can distinguish original Git identity from the representation they actually received.
- The bounded scanner is not a complete credential or personal-data classifier. Hosted use still
  requires a maintained scanner, quarantine workflow, retention controls, and incident response.

## Security impact

This closes the known-secret and repository-instruction boundary for the local product slice. It does
not establish hosted identity, provider ACL enforcement, database row-level security, model-level
injection immunity, or comprehensive personal-data detection.

## What breaks without it

A relevant file could silently transmit an embedded credential to the agent, and repository prose
could be presented without any machine-readable trust boundary. Reviewers could not tell whether a
served content hash referred to the original file or a redacted representation.
