"use client";

import { useEffect, useMemo, useState } from "react";
import {
  bundledDecision,
  bundledDemo,
  bundledEvidence,
  type Citation,
  type ContextItem,
  type DemoPayload,
  type EpistemicState,
} from "./demo-snapshot";

type ConnectionState = "connecting" | "live" | "snapshot";
type Filter = "all" | "risk" | "verified" | "human";

type EvidenceDetail = {
  kind: "evidence";
  evidence_id: string;
  locator: Citation["locator"];
  content: string;
};

type DecisionDetail = {
  kind: "decision";
  decision_key: string;
  epistemic_state: "ASSERTED";
  statement: string;
  rationale: string;
  source_asserted_approver: string | null;
  warning: string;
};

type InspectorDetail = EvidenceDetail | DecisionDetail;

const API_URL =
  process.env.NEXT_PUBLIC_THREADLINE_API_URL ?? "http://localhost:8000";

const stateCopy: Record<EpistemicState, string> = {
  VERIFIED: "Proved at this commit",
  OBSERVED: "Directly witnessed",
  ASSERTED: "Source says so",
  UNKNOWN: "Not enough evidence",
  CONTRADICTED: "Evidence disagrees",
};

const filters: Array<{ id: Filter; label: string }> = [
  { id: "all", label: "All context" },
  { id: "risk", label: "Needs proof" },
  { id: "verified", label: "Verified" },
  { id: "human", label: "Human context" },
];

function shortId(value: string, length = 8) {
  return value.length > length ? value.slice(0, length) : value;
}

function displayUri(uri: string) {
  return uri.replace(/^repo:\/\/[^/]+\//, "");
}

function displayStatement(statement: string) {
  if (statement.startsWith("run_job retries_preserve_original_idempotency_key")) {
    return "Retry behavior preserves the original idempotency key.";
  }
  if (statement.startsWith("test_suite all_tests_passed")) {
    return "The complete test suite passes at this commit.";
  }
  if (statement === "run_job references:RetryPolicy False") {
    return "run_job calls RetryPolicy.";
  }
  if (statement === "RetryPolicy exists_at_commit True") {
    return "RetryPolicy exists at the captured commit.";
  }
  return statement;
}

function matchesFilter(item: ContextItem, filter: Filter) {
  if (filter === "risk") {
    return item.epistemic_state === "UNKNOWN" || item.epistemic_state === "CONTRADICTED";
  }
  if (filter === "verified") return item.epistemic_state === "VERIFIED";
  if (filter === "human") {
    return item.epistemic_state === "ASSERTED" || item.epistemic_state === "OBSERVED";
  }
  return true;
}

function stateClass(state: EpistemicState) {
  return `state-${state.toLowerCase()}`;
}

function EvidenceState({ state }: { state: EpistemicState }) {
  return (
    <span className={`evidence-state ${stateClass(state)}`}>
      <span className="state-dot" aria-hidden="true" />
      {state}
    </span>
  );
}

export function ThreadlineDemo() {
  const [payload, setPayload] = useState<DemoPayload>(bundledDemo);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [filter, setFilter] = useState<Filter>("all");
  const [selectedId, setSelectedId] = useState("snapshot-wiring-claim");
  const [detail, setDetail] = useState<InspectorDetail>({
    kind: "evidence",
    evidence_id: "snapshot-job-source",
    ...bundledEvidence["snapshot-job-source"],
  });
  const [inspectorBusy, setInspectorBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();

    async function connect() {
      try {
        const response = await fetch(`${API_URL}/api/demo`, {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("demo API is not ready");
        const livePayload = (await response.json()) as DemoPayload;
        setPayload(livePayload);
        setConnection("live");
        setSelectedId(
          livePayload.items.find((item) => item.epistemic_state === "CONTRADICTED")
            ?.entity_id ?? livePayload.items[0]?.entity_id,
        );
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setConnection("snapshot");
        }
      }
    }

    void connect();
    return () => controller.abort();
  }, []);

  const visibleItems = useMemo(
    () => payload.items.filter((item) => matchesFilter(item, filter)),
    [filter, payload.items],
  );

  const selectedItem =
    payload.items.find((item) => item.entity_id === selectedId) ?? payload.items[0];

  useEffect(() => {
    if (!selectedItem) return;
    let cancelled = false;

    async function inspect() {
      setInspectorBusy(true);
      try {
        if (connection === "live") {
          if (selectedItem.entity_type === "decision") {
            const response = await fetch(
              `${API_URL}/api/decisions/${selectedItem.entity_id}`,
              { cache: "no-store" },
            );
            if (!response.ok) throw new Error("decision detail unavailable");
            const value = (await response.json()) as Omit<DecisionDetail, "kind">;
            if (!cancelled) setDetail({ kind: "decision", ...value });
            return;
          }

          const citation = selectedItem.citations[0];
          if (!citation) throw new Error("no citation was attached");
          const response = await fetch(
            `${API_URL}/api/evidence/${citation.evidence_id}`,
            { cache: "no-store" },
          );
          if (!response.ok) throw new Error("evidence detail unavailable");
          const value = (await response.json()) as Omit<EvidenceDetail, "kind">;
          if (!cancelled) setDetail({ kind: "evidence", ...value });
          return;
        }

        if (selectedItem.entity_type === "decision") {
          if (!cancelled) setDetail({ kind: "decision", ...bundledDecision });
          return;
        }
        const evidenceId = selectedItem.citations[0]?.evidence_id;
        const evidence = evidenceId ? bundledEvidence[evidenceId] : undefined;
        if (evidence && !cancelled) {
          setDetail({ kind: "evidence", evidence_id: evidenceId, ...evidence });
        }
      } catch {
        const citation = selectedItem.citations[0];
        if (citation && !cancelled) {
          setDetail({
            kind: "evidence",
            evidence_id: citation.evidence_id,
            locator: citation.locator,
            content:
              "The source is cited in this handoff, but the local evidence service is not reachable.",
          });
        }
      } finally {
        if (!cancelled) setInspectorBusy(false);
      }
    }

    void inspect();
    return () => {
      cancelled = true;
    };
  }, [connection, selectedItem]);

  async function openCitation(citation: Citation) {
    setInspectorBusy(true);
    try {
      if (connection === "live") {
        const response = await fetch(
          `${API_URL}/api/evidence/${citation.evidence_id}`,
          { cache: "no-store" },
        );
        if (!response.ok) throw new Error("evidence detail unavailable");
        const value = (await response.json()) as Omit<EvidenceDetail, "kind">;
        setDetail({ kind: "evidence", ...value });
      } else {
        const evidence = bundledEvidence[citation.evidence_id];
        if (evidence) {
          setDetail({
            kind: "evidence",
            evidence_id: citation.evidence_id,
            ...evidence,
          });
        }
      }
    } finally {
      setInspectorBusy(false);
    }
  }

  function chooseFilter(nextFilter: Filter) {
    setFilter(nextFilter);
    const nextItem = payload.items.find((item) => matchesFilter(item, nextFilter));
    if (nextItem) setSelectedId(nextItem.entity_id);
  }

  return (
    <main className="site-shell">
      <header className="site-header">
        <a className="wordmark" href="#top" aria-label="Threadline home">
          <span className="wordmark-mark" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <span>threadline</span>
        </a>
        <nav aria-label="Primary navigation">
          <a href="#product">Product</a>
          <a href="#contract">Evidence contract</a>
          <a href="#architecture">Architecture</a>
        </nav>
        <a className="header-cta" href="#workbench">
          Open the handoff <span aria-hidden="true">↘</span>
        </a>
      </header>

      <section className="hero" id="top">
        <div className="hero-copy">
          <p className="eyebrow">Versioned engineering context</p>
          <h1>Resume engineering work from evidence, not summaries.</h1>
          <p className="hero-lede">
            Threadline binds code, tests, decisions, and prior claims to one
            versioned handoff. The next person or agent can see what is proven,
            what is uncertain, and what should happen next.
          </p>
          <div className="hero-actions">
            <a className="primary-action" href="#workbench">
              Inspect the handoff <span aria-hidden="true">→</span>
            </a>
            <a className="text-action" href="#architecture">
              See how evidence flows
            </a>
          </div>
        </div>

        <div className="hero-proof" aria-label="Threadline product principles">
          <div className="proof-entry">
            <span>01</span>
            <div>
              <strong>Bound to a commit</strong>
              <p>No floating summary detached from repository state.</p>
            </div>
          </div>
          <div className="proof-entry">
            <span>02</span>
            <div>
              <strong>Uncertainty stays visible</strong>
              <p>Unknown and contradicted claims remain first-class context.</p>
            </div>
          </div>
          <div className="proof-entry">
            <span>03</span>
            <div>
              <strong>Every claim can be opened</strong>
              <p>Citations lead back to the source and its content hash.</p>
            </div>
          </div>
        </div>
      </section>

      <section className="product-intro" id="product">
        <p className="section-kicker">Live product</p>
        <div>
          <h2>Inspect the work before you continue it.</h2>
          <p>
            The demo uses a synthetic retry task with deliberately conflicting
            evidence. Select a claim, open its source, and see why Threadline
            blocks an unsafe handoff.
          </p>
        </div>
      </section>

      <section className="workbench-frame" id="workbench" aria-label="Threadline demo">
        <div className="workbench-topbar">
          <div className="workspace-crumbs">
            <span>queue-runner</span>
            <b>/</b>
            <span>{payload.repository.branch}</span>
          </div>
          <div
            className={`connection-state connection-${connection}`}
            aria-live="polite"
          >
            <span aria-hidden="true" />
            {connection === "live"
              ? "Live local evidence"
              : connection === "connecting"
                ? "Checking local evidence"
                : "Bundled synthetic snapshot"}
          </div>
        </div>

        <div className="workbench-summary">
          <div className="task-heading">
            <span className="task-state">{payload.task.state.replaceAll("_", " ")}</span>
            <h3>{payload.task.objective}</h3>
          </div>
          <div className="commit-lockup">
            <span>captured state</span>
            <code>{payload.repository.branch}</code>
            <code>@ {shortId(payload.repository.commit)}</code>
          </div>
        </div>

        <div className="lineage-strip" aria-label="Handoff lineage">
          <div className="lineage-step lineage-complete">
            <span>01</span>
            <div>
              <small>Repository</small>
              <strong>{shortId(payload.repository.commit)}</strong>
            </div>
          </div>
          <div className="lineage-arrow" aria-hidden="true">→</div>
          <div className="lineage-step lineage-complete">
            <span>02</span>
            <div>
              <small>Verification</small>
              <strong>{payload.items.length} context items</strong>
            </div>
          </div>
          <div className="lineage-arrow" aria-hidden="true">→</div>
          <div className="lineage-step lineage-active">
            <span>03</span>
            <div>
              <small>Handoff</small>
              <strong>{shortId(payload.context_version)}</strong>
            </div>
          </div>
        </div>

        <div className="workbench-grid">
          <aside className="context-sidebar" aria-label="Context filters">
            <div className="panel-label">
              <span>Context pack</span>
              <b>{payload.items.length}</b>
            </div>
            <div className="filter-list" role="list">
              {filters.map((entry) => {
                const count = payload.items.filter((item) =>
                  matchesFilter(item, entry.id),
                ).length;
                return (
                  <button
                    className={filter === entry.id ? "filter-active" : undefined}
                    key={entry.id}
                    onClick={() => chooseFilter(entry.id)}
                    type="button"
                  >
                    <span>{entry.label}</span>
                    <b>{count}</b>
                  </button>
                );
              })}
            </div>

            <div className="risk-summary">
              <p>Continuation gate</p>
              <strong>{payload.status === "partial" ? "Evidence incomplete" : "Ready"}</strong>
              <span>
                {payload.conflicts.length} contradiction · {payload.unknowns.length} unknown
              </span>
            </div>
          </aside>

          <section className="handoff-panel" aria-label="Compiled handoff">
            <div className="next-action-card">
              <div className="next-action-index">NEXT / SAFE</div>
              <div>
                <p>Recommended continuation</p>
                <h4>{payload.next_action}</h4>
              </div>
              <span className="next-action-arrow" aria-hidden="true">↗</span>
            </div>

            <div className="handoff-heading">
              <div>
                <span>Evidence-ranked context</span>
                <p>Open any row to inspect the source behind it.</p>
              </div>
              <code>{visibleItems.length} shown</code>
            </div>

            <div className="context-list">
              {visibleItems.map((item, index) => (
                <button
                  className={`context-row ${
                    selectedItem?.entity_id === item.entity_id ? "context-row-active" : ""
                  }`}
                  key={item.entity_id}
                  onClick={() => setSelectedId(item.entity_id)}
                  type="button"
                >
                  <span className="row-index">{String(index + 1).padStart(2, "0")}</span>
                  <span className="row-content">
                    <span className="row-meta">
                      <EvidenceState state={item.epistemic_state} />
                      <span>{item.entity_type}</span>
                    </span>
                    <strong>{displayStatement(item.statement)}</strong>
                    <small>{item.selection_reason}</small>
                  </span>
                  <span className="citation-count">
                    {item.citations.length} source{item.citations.length === 1 ? "" : "s"}
                    <i aria-hidden="true">→</i>
                  </span>
                </button>
              ))}
            </div>
          </section>

          <aside className="inspector" aria-label="Evidence inspector">
            <div className="inspector-heading">
              <div>
                <span>Trace inspector</span>
                <p>{inspectorBusy ? "Resolving source…" : "Exact source context"}</p>
              </div>
              <span className="read-only-badge">READ ONLY</span>
            </div>

            {selectedItem && (
              <div className="selected-summary">
                <EvidenceState state={selectedItem.epistemic_state} />
                <p>{stateCopy[selectedItem.epistemic_state]}</p>
              </div>
            )}

            {detail.kind === "decision" ? (
              <div className="decision-detail">
                <span className="detail-kind">DECISION / {detail.decision_key}</span>
                <h5>{detail.statement}</h5>
                <p>{detail.rationale}</p>
                <div className="warning-note">
                  <span aria-hidden="true">!</span>
                  <p>{detail.warning}</p>
                </div>
              </div>
            ) : (
              <div className="evidence-detail">
                <div className="source-path">
                  <span>Source</span>
                  <code>{displayUri(detail.locator.uri)}</code>
                </div>
                <pre className={inspectorBusy ? "detail-loading" : undefined}>
                  <code>{detail.content}</code>
                </pre>
                <div className="content-hash">
                  <span>CONTENT HASH</span>
                  <code>{detail.locator.content_hash.replace("sha256:", "")}</code>
                </div>
              </div>
            )}

            {selectedItem && selectedItem.citations.length > 0 && (
              <div className="citation-stack">
                <span>Cited sources</span>
                {selectedItem.citations.map((citation) => (
                  <button
                    key={citation.evidence_id}
                    onClick={() => void openCitation(citation)}
                    type="button"
                  >
                    <span>{displayUri(citation.locator.uri)}</span>
                    <code>{shortId(citation.locator.content_hash.replace("sha256:", ""), 7)}</code>
                  </button>
                ))}
              </div>
            )}
          </aside>
        </div>
      </section>

      <section className="contract-section" id="contract">
        <div className="contract-copy">
          <p className="section-kicker">The evidence contract</p>
          <h2>Five states. Five distinct levels of trust.</h2>
          <p>
            Threadline does not collapse every claim into “done.” Each state tells
            the next worker what the evidence supports and where verification is
            still required.
          </p>
        </div>
        <div className="state-ledger">
          {(Object.keys(stateCopy) as EpistemicState[]).map((state, index) => (
            <article key={state}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <EvidenceState state={state} />
              <p>{stateCopy[state]}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="architecture-section" id="architecture">
        <div className="architecture-heading">
          <p className="section-kicker">System shape</p>
          <h2>Every layer exists to keep a handoff honest.</h2>
        </div>
        <div className="architecture-flow" aria-label="Threadline architecture flow">
          <article>
            <span>INGEST</span>
            <h3>Code + human context</h3>
            <p>Git state, tests, decisions, constraints, and attributed observations.</p>
          </article>
          <div aria-hidden="true">→</div>
          <article>
            <span>VERIFY</span>
            <h3>Deterministic checks</h3>
            <p>Call sites, symbol existence, test scope, and content freshness.</p>
          </article>
          <div aria-hidden="true">→</div>
          <article>
            <span>COMPILE</span>
            <h3>Versioned context pack</h3>
            <p>Risk-ranked claims with citations, unknowns, and contradictions intact.</p>
          </article>
          <div aria-hidden="true">→</div>
          <article>
            <span>SERVE</span>
            <h3>Read-only handoff</h3>
            <p>A product UI and scoped MCP tools bound to the exact task and commit.</p>
          </article>
        </div>
      </section>

      <footer>
        <a className="wordmark" href="#top" aria-label="Threadline home">
          <span className="wordmark-mark" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <span>threadline</span>
        </a>
        <p>Evidence-bound engineering context.</p>
        <a href="#workbench">Return to the handoff ↑</a>
      </footer>
    </main>
  );
}
