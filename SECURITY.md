# Security policy

Threadline is currently a local-development project and must not ingest private external repositories until the hosted tenancy and authorization gates are implemented and reviewed.

## Reporting a vulnerability

Do not open a public issue containing credentials, private source, exploit details, or user data. Until a dedicated security address exists, report privately to the repository owner through an agreed private channel.

## Non-negotiable rules

- Never commit or paste real credentials into source, fixtures, logs, screenshots, prompts, or eval reports.
- Authorization must be resolved before lexical, vector, graph, cache, or model retrieval.
- Missing identity or policy context fails closed.
- LLM output cannot grant access, approve a canonical decision, or certify its own claim.
- Cross-tenant/repository disclosure is a P0 incident.
- Public demo data must be synthetic and isolated from pilot tenants.

See `docs/threat-model/THREAT_MODEL_V1.md` for the current threat model and limitations.
