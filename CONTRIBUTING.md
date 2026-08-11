# Contributing to Threadline

Threadline's central promise is stronger than “the code works”: public claims must remain bound to authorized, current evidence. Contributions must preserve the invariants in the context model, ADRs, and threat model.

## Local setup

First run:

```bash
make setup
make check
```

Later runs:

```bash
make check
```

Optional local infrastructure:

```bash
make local-up
make local-down
```

## Change protocol

1. Name the requirement and current phase being changed.
2. Start with an acceptance or invariant test when practical.
3. Preserve tenant, repository, branch, commit, actor, and trace scope.
4. Treat repository/agent/model content as untrusted.
5. Add an ADR before introducing a service/framework or changing a trust boundary.
6. Record verification commands and results in `docs/evidence/`.
7. Never update an eval label merely to make implementation pass.
8. Never commit secrets, private pilot data, generated credentials, or raw production traces.

## Commit convention

Use small, truthful Conventional Commit messages such as:

- `feat(context): add commit-bound claim verification`
- `test(security): reject cross-tenant graph edges`
- `docs(adr): justify lexical retrieval baseline`

Each completed roadmap phase receives a dedicated local milestone commit after all exit-gate checks pass.
