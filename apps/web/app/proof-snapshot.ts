export type BenchmarkCase = {
  id: string;
  title: string;
  passed: boolean;
  expected: string;
  observed: string;
  failure_layer: string | null;
};

export type BenchmarkMetric = {
  correct?: number;
  accepted?: number;
  total: number;
  rate: number;
};

export type ProofPayload = {
  report: string;
  dataset: string;
  sample_size: number;
  repository_count: number;
  cases: BenchmarkCase[];
  metrics: Record<string, BenchmarkMetric>;
  limits: string[];
  claim_boundary: string;
};

export const bundledProof: ProofPayload = {
  report: "threadline-executed-continuation-benchmark-v0.2",
  dataset: "executed-synthetic-v0.2",
  sample_size: 9,
  repository_count: 5,
  cases: [
    {
      id: "EXEC-001",
      title: "Continue the task through a second MCP agent",
      passed: true,
      expected: "change, full test, commit, stale refusal, current verified handoff",
      observed:
        "commit changed; full suite passed with 2 tests; old handoff refused; new handoff status ok",
      failure_layer: null,
    },
    {
      id: "EXEC-002",
      title: "Reject unsupported all-tests-passed assertion",
      passed: true,
      expected: "not VERIFIED",
      observed: "UNKNOWN",
      failure_layer: null,
    },
    {
      id: "EXEC-003",
      title: "Resolve every returned citation in scope",
      passed: true,
      expected: "6 evidence objects",
      observed: "6 evidence objects",
      failure_layer: null,
    },
    {
      id: "EXEC-004",
      title: "Abstain on a dirty worktree",
      passed: true,
      expected: "abstained",
      observed: "abstained",
      failure_layer: null,
    },
    {
      id: "EXEC-005",
      title: "Abstain after the branch head moves",
      passed: true,
      expected: "abstained",
      observed: "abstained",
      failure_layer: null,
    },
    {
      id: "EXEC-006",
      title: "Verify a committed full passing check",
      passed: true,
      expected: "VERIFIED",
      observed: "VERIFIED",
      failure_layer: null,
    },
    {
      id: "EXEC-007",
      title: "Contradict completion after a failed full check",
      passed: true,
      expected: "CONTRADICTED",
      observed: "CONTRADICTED",
      failure_layer: null,
    },
    {
      id: "EXEC-008",
      title: "Recover the typed test-to-class relationship",
      passed: true,
      expected: "cited CONSTRUCTS edge",
      observed: "2 typed edges and 7 citations",
      failure_layer: null,
    },
    {
      id: "EXEC-009",
      title: "Deny another task identifier",
      passed: true,
      expected: "denied or tool error",
      observed: "tool error",
      failure_layer: null,
    },
  ],
  metrics: {
    regression_cases_passed: { correct: 9, total: 9, rate: 1 },
    required_abstention_accuracy: { correct: 2, total: 2, rate: 1 },
    unsupported_completion_false_acceptance: { accepted: 0, total: 1, rate: 0 },
  },
  limits: [
    "All cases are deterministic and synthetic.",
    "Only one expected next-action case and one unsupported-completion case are measured.",
    "No external repository, human reviewer, or proprietary agent client was used.",
  ],
  claim_boundary:
    "Nine deterministic synthetic regression cases; not an external accuracy, adoption, or production claim.",
};
