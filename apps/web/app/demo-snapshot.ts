export type EpistemicState =
  | "VERIFIED"
  | "OBSERVED"
  | "ASSERTED"
  | "UNKNOWN"
  | "CONTRADICTED";

export type Citation = {
  evidence_id: string;
  locator: {
    uri: string;
    content_hash: string;
    line_start: number | null;
    line_end: number | null;
  };
};

export type ContextItem = {
  entity_type: "task" | "decision" | "constraint" | "claim" | "observation";
  entity_id: string;
  statement: string;
  epistemic_state: EpistemicState;
  selection_reason: string;
  citations: Citation[];
};

export type DemoPayload = {
  status: "ok" | "partial";
  task: { id: string; objective: string; state: string };
  repository: { id: string; branch: string; commit: string };
  context_version: string;
  request_id: string;
  trace_id: string;
  next_action: string;
  constraints: string[];
  verified_completed_work: string[];
  unknowns: string[];
  conflicts: string[];
  items: ContextItem[];
};

const JOB_SOURCE = "snapshot-job-source";
const DECISION_SOURCE = "snapshot-decision-source";
const TEST_SOURCE = "snapshot-test-source";
const OBSERVATION_SOURCE = "snapshot-observation-source";

const locator = (evidenceId: string, uri: string, hash: string): Citation => ({
  evidence_id: evidenceId,
  locator: {
    uri,
    content_hash: hash,
    line_start: null,
    line_end: null,
  },
});

const jobCitation = locator(
  JOB_SOURCE,
  "repo://threadline-demo/src/job_runner.py",
  "sha256:fdd02a00d30b6aca27897cd64dd32e47f6b478c3eb689dc09bc6ddd79b7b3b0b",
);
const decisionCitation = locator(
  DECISION_SOURCE,
  "repo://threadline-demo/threadline/decision.json",
  "sha256:879675ccd756968e5a4a54c0d9f5dbd3890be3d30c01467df2d20b65422a89c6",
);
const testCitation = locator(
  TEST_SOURCE,
  "repo://threadline-demo/threadline/test-report.json",
  "sha256:6860c100c3a64e163797d50692eefdf1ecfd4b4aefd2ac71689c2b1d10aff6d4",
);
const observationCitation = locator(
  OBSERVATION_SOURCE,
  "repo://threadline-demo/threadline/observations.json",
  "sha256:a1e62895c4a158a973d8a54d7a0cbd9cdc2289d6e0a06e1d8080a0aaa6c98aa4",
);

export const bundledDemo: DemoPayload = {
  status: "partial",
  task: {
    id: "20000000-0000-4000-8000-000000000001",
    objective:
      "Add bounded retries to run_job without changing its idempotency key between attempts.",
    state: "IN_PROGRESS",
  },
  repository: {
    id: "60000000-0000-4000-8000-000000000004",
    branch: "feature/retry-jobs",
    commit: "32a7b542259a9ca66bc30d1c989a67affd2d5755",
  },
  context_version: "snapshot-ce933155",
  request_id: "snapshot-request",
  trace_id: "snapshot-trace",
  next_action:
    "Wire RetryPolicy into run_job while reusing the original idempotency key, then add an integration test and run the complete suite.",
  constraints: ["Every retry attempt must reuse the original idempotency key."],
  verified_completed_work: ["RetryPolicy exists at the captured commit."],
  unknowns: [
    "Whether retries preserve the original idempotency key.",
    "Whether the complete test suite passes.",
  ],
  conflicts: ["run_job does not reference RetryPolicy."],
  items: [
    {
      entity_type: "decision",
      entity_id: "snapshot-decision",
      statement:
        "Every retry attempt must reuse the original idempotency key. A new key per attempt can duplicate externally visible side effects.",
      epistemic_state: "ASSERTED",
      selection_reason: "decision relevance with source provenance",
      citations: [decisionCitation],
    },
    {
      entity_type: "constraint",
      entity_id: "snapshot-constraint",
      statement: "Every retry attempt must reuse the original idempotency key.",
      epistemic_state: "ASSERTED",
      selection_reason: "high-severity task constraint with source provenance",
      citations: [decisionCitation],
    },
    {
      entity_type: "claim",
      entity_id: "snapshot-idempotency-claim",
      statement: "Retry behavior preserves the original idempotency key.",
      epistemic_state: "UNKNOWN",
      selection_reason: "epistemic risk priority",
      citations: [jobCitation, decisionCitation],
    },
    {
      entity_type: "claim",
      entity_id: "snapshot-suite-claim",
      statement: "The complete test suite passes at this commit.",
      epistemic_state: "UNKNOWN",
      selection_reason: "test scope is focused, not repository-wide",
      citations: [testCitation],
    },
    {
      entity_type: "claim",
      entity_id: "snapshot-wiring-claim",
      statement: "run_job calls RetryPolicy.",
      epistemic_state: "CONTRADICTED",
      selection_reason: "verified call-site contradiction",
      citations: [jobCitation],
    },
    {
      entity_type: "claim",
      entity_id: "snapshot-existence-claim",
      statement: "RetryPolicy exists at the captured commit.",
      epistemic_state: "VERIFIED",
      selection_reason: "symbol verifier at exact commit",
      citations: [jobCitation],
    },
    {
      entity_type: "observation",
      entity_id: "snapshot-runner-observation",
      statement: "One focused RetryPolicy unit test passed.",
      epistemic_state: "OBSERVED",
      selection_reason: "attributed test-runner observation",
      citations: [observationCitation, testCitation],
    },
    {
      entity_type: "observation",
      entity_id: "snapshot-agent-observation",
      statement: "Implemented retries and all tests pass.",
      epistemic_state: "ASSERTED",
      selection_reason: "agent-authored statement without supporting evidence",
      citations: [observationCitation],
    },
  ],
};

export const bundledEvidence: Record<
  string,
  { locator: Citation["locator"]; content: string }
> = {
  [JOB_SOURCE]: {
    locator: jobCitation.locator,
    content: `@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.25

    def delays(self) -> tuple[float, ...]:
        return tuple(
            self.base_delay_seconds * 2**attempt
            for attempt in range(self.max_attempts - 1)
        )

def run_job(operation, idempotency_key):
    """Run once; retry integration is intentionally absent."""
    return operation(idempotency_key)`,
  },
  [DECISION_SOURCE]: {
    locator: decisionCitation.locator,
    content: `{
  "decision_key": "retry-idempotency-v1",
  "status": "APPROVED",
  "statement": "Every retry attempt must reuse the original idempotency key.",
  "rationale": "A new key per attempt can duplicate externally visible side effects.",
  "approved_by": "repository-authored identifier"
}`,
  },
  [TEST_SOURCE]: {
    locator: testCitation.locator,
    content: `{
  "suite": "test_retry_policy_builds_bounded_exponential_delays",
  "scope": "FOCUSED",
  "status": "PASSED",
  "passed": 1,
  "does_not_prove": [
    "RetryPolicy is called by run_job",
    "all tests pass",
    "idempotency keys are preserved"
  ]
}`,
  },
  [OBSERVATION_SOURCE]: {
    locator: observationCitation.locator,
    content: `[
  {
    "actor_type": "AGENT",
    "statement": "Implemented retries and all tests pass.",
    "state": "ASSERTED",
    "evidence": []
  },
  {
    "actor_type": "TEST_RUNNER",
    "statement": "One focused RetryPolicy unit test passed.",
    "state": "OBSERVED"
  }
]`,
  },
};

export const bundledDecision = {
  decision_key: "retry-idempotency-v1",
  epistemic_state: "ASSERTED" as const,
  statement: "Every retry attempt must reuse the original idempotency key.",
  rationale: "A new key per attempt can duplicate externally visible side effects.",
  source_asserted_approver: "repository-authored identifier",
  warning: "Repository metadata does not authenticate the asserted approver.",
};
