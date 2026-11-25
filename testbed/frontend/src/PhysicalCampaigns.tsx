import { useEffect, useState } from "react";
import { Download, Pause, Play, RefreshCw, Square, Upload } from "lucide-react";
import type { HardwareNode } from "./HardwareBench";
import "./physical-campaigns.css";

type Ref = { service: string; id: string };
type Header = {
  id: string;
  name: string;
  plan_id: string;
  status: string;
  stage: string;
  created_at: string;
  updated_at?: string;
  case_count: number;
  case_counts: Record<string, number>;
  parent_execution_id?: string | null;
  reason?: string | null;
  reason_code?: string | null;
  active_case_id?: string | null;
  pause_requested?: boolean;
  cancel_requested?: boolean;
  pending_outcome?: string | null;
  cleanup?: { confirmed: boolean } | null;
  physical_bindings?: Record<
    string,
    { device_id: string; boot_id: string; connection_id: string }
  >;
};
export type CampaignState = {
  execution_available: boolean;
  active: Header | null;
  executions: {
    id: string;
    status: string;
    created_at: string;
    plan_id: string;
  }[];
};
type Plan = {
  id: string;
  name: string;
  case_count: number;
  batch_count: number;
  duration_bound_s: number;
  plan_sha256: string;
};
type Intent = {
  id: string;
  index: number;
  label: string;
  roles: string[];
  repetition: number;
  direction: string | null;
  case: Record<string, unknown>;
};
type Runtime = {
  case_id: string;
  index: number;
  status: string;
  intent: Intent;
  reason?: string | null;
  reason_code?: string | null;
  child: Ref | null;
  preflight?: { blockers: string[] };
};
type Page<T> = {
  rows: T[];
  offset: number;
  total: number;
  next_offset: number | null;
};
type PlanView = {
  record: Plan;
  cases: Page<Intent & { readiness: { ready: boolean; blockers: string[] } }>;
};
type ExecutionView = {
  record: Header;
  plan: Plan;
  cases: Page<Runtime>;
  active_case: Omit<Runtime, "intent"> | null;
};
type Request = (path: string, options?: RequestInit) => Promise<any>;
const terminal = new Set([
  "completed",
  "failed",
  "blocked",
  "cancelled",
  "interrupted",
]);
const root = "/api/physical-campaigns";
const storage = "loralab.physical-campaign.execution";
const label = (value: string) => value.replaceAll("_", " ");
const short = (value: string) => value.slice(0, 8);
const post = (body: unknown = {}) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
function stored(key = storage) {
  try {
    return sessionStorage.getItem(key) || "";
  } catch {
    return "";
  }
}
async function read(path: string, signal?: AbortSignal) {
  const response = await fetch(path, { signal });
  const value = await response.json();
  if (!response.ok)
    throw new Error(
      typeof value.detail === "string"
        ? value.detail
        : "Campaign view unavailable",
    );
  return value;
}
function Pager({
  page,
  change,
  busy,
  name,
}: {
  page: Page<unknown>;
  change: (value: number) => void;
  busy: boolean;
  name: string;
}) {
  return (
    <div className="pc-pager">
      <span>
        {page.total
          ? `${page.offset + 1}–${page.offset + page.rows.length} of ${page.total}`
          : "No cases"}
      </span>
      <button
        className="button secondary"
        aria-label={`Previous ${name}`}
        disabled={busy || !page.offset}
        onClick={() => change(Math.max(0, page.offset - 32))}
      >
        Previous
      </button>
      <button
        className="button secondary"
        aria-label={`Next ${name}`}
        disabled={busy || page.next_offset == null}
        onClick={() => change(page.next_offset!)}
      >
        Next
      </button>
    </div>
  );
}
function ChildLink({ child }: { child: Ref }) {
  const bases: Record<string, string> = {
    diagnostic: "/api/diagnostic-runs",
    procedure: "/api/procedures/runs",
    audio: "/api/audio/operations",
    radio: "/api/radio/runs",
    voice: "/api/voice/runs",
  };
  return (
    <a
      href={`${bases[child.service]}/${child.id}`}
      target="_blank"
      rel="noreferrer"
    >
      {child.service} · {short(child.id)}
    </a>
  );
}
export default function PhysicalCampaigns({
  state = { execution_available: false, active: null, executions: [] },
  nodes,
  online,
  benchBusy,
  pending,
  request,
}: {
  state: CampaignState;
  nodes: HardwareNode[];
  online: boolean;
  benchBusy: boolean;
  pending: boolean;
  request: Request;
}) {
  const [plans, setPlans] = useState<Plan[]>([]),
    [planId, setPlanId] = useState(() => stored(`${storage}.plan`));
  const [planView, setPlanView] = useState<PlanView | null>(null),
    [planOffset, setPlanOffset] = useState(0);
  const [selected, setSelected] = useState(stored),
    [view, setView] = useState<ExecutionView | null>(null);
  const [offset, setOffset] = useState(0),
    [picked, setPicked] = useState<Set<string>>(new Set());
  const [error, setError] = useState(""),
    [revision, setRevision] = useState(0);
  const [loadingPlan, setLoadingPlan] = useState(false),
    [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false),
    [downloaded, setDownloaded] = useState("");
  const active = state.active;
  const activeRevision =
    active?.id === selected
      ? active.updated_at
      : state.executions.find((row) => row.id === selected)?.status;
  const nodeRevision = nodes
    .map(
      (node) =>
        `${node.id}:${node.connection_id}:${node.connection_state}:${node.health?.state}`,
    )
    .join("|");
  const displayed = view?.record.id === selected ? view : null;
  const planDisplayed = planView?.record.id === planId ? planView : null;
  const record = displayed?.record;
  const isTerminal = !!record && terminal.has(record.status);
  const isActive = !!record && active?.id === record.id;
  const controls =
    online &&
    !pending &&
    isActive &&
    record?.stage !== "cleanup" &&
    !record?.cancel_requested;
  function choose(id: string) {
    setSelected(id);
    setOffset(0);
    setPicked(new Set());
    setView(null);
    setDownloaded("");
    setError("");
    try {
      sessionStorage.setItem(storage, id);
    } catch {
      /* Selection remains local when storage is unavailable. */
    }
  }
  useEffect(() => {
    try {
      sessionStorage.setItem(`${storage}.plan`, planId);
    } catch {
      /* Optional UI preference. */
    }
  }, [planId]);
  useEffect(() => {
    if (!selected && (active || state.executions.length))
      choose(active?.id || state.executions[0].id);
  }, [selected, active?.id, state.executions.length]);
  useEffect(() => {
    if (!online) return;
    const controller = new AbortController();
    read(`${root}/plans?limit=100`, controller.signal)
      .then((data) => {
        setPlans(data.plans);
        if (!planId && data.plans.length) setPlanId(data.plans[0].id);
      })
      .catch((cause) => {
        if (cause.name !== "AbortError") setError(String(cause));
      });
    return () => controller.abort();
  }, [online, revision]);
  useEffect(() => {
    if (!planId || !online) return;
    const controller = new AbortController();
    setLoadingPlan(true);
    read(`${root}/plans/${planId}/view?offset=${planOffset}`, controller.signal)
      .then(setPlanView)
      .catch((cause) => {
        if (cause.name !== "AbortError") {
          setPlanView(null);
          setError(String(cause));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingPlan(false);
      });
    return () => controller.abort();
  }, [planId, planOffset, online, nodeRevision, revision]);
  useEffect(() => {
    if (!selected || !online) return;
    const controller = new AbortController();
    setLoading(true);
    read(
      `${root}/executions/${selected}/view?offset=${offset}`,
      controller.signal,
    )
      .then(setView)
      .catch((cause) => {
        if (cause.name !== "AbortError") {
          setView(null);
          setError(String(cause));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [selected, offset, activeRevision, online, revision]);
  async function action(
    name: "start" | "pause" | "resume" | "cancel" | "rerun",
  ) {
    setError("");
    const path =
      name === "start"
        ? `${root}/executions`
        : `${root}/executions/${selected}/${name}`;
    const body =
      name === "start"
        ? { plan_id: planId }
        : name === "rerun"
          ? { case_ids: [...picked] }
          : {};
    const result = await request(path, post(body));
    if (result) {
      if (name === "start" || name === "rerun") choose(result.id);
      setRevision((value) => value + 1);
    }
  }
  async function exportEvidence() {
    if (!record) return;
    setError("");
    setDownloading(true);
    setDownloaded("");
    try {
      const response = await fetch(`${root}/executions/${record.id}/export`);
      if (!response.ok) {
        const value = await response.json();
        throw new Error(value.detail || "Campaign download failed");
      }
      const data = await response.arrayBuffer();
      const digest = [
        ...new Uint8Array(await crypto.subtle.digest("SHA-256", data)),
      ]
        .map((byte) => byte.toString(16).padStart(2, "0"))
        .join("");
      if (digest !== response.headers.get("X-Content-SHA256"))
        throw new Error("Campaign download hash differs");
      const url = URL.createObjectURL(
        new Blob([data], { type: "application/zip" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `campaign-${record.id}.zip`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setDownloaded(`Downloaded campaign-${record.id}.zip · SHA-256 ${digest}`);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Campaign export failed",
      );
    } finally {
      setDownloading(false);
    }
  }
  const done = record
    ? Object.entries(record.case_counts)
        .filter(([name]) => !["pending", "running"].includes(name))
        .reduce((sum, [, count]) => sum + count, 0)
    : 0;
  return (
    <div className="physical-campaigns">
      {!online && (
        <p className="pc-warning" role="status">
          Backend connection unavailable. Retained views stay visible; controls
          are disabled.
        </p>
      )}
      {active && active.id !== selected && (
        <div className="pc-owner">
          <strong>A campaign owns the bench · {label(active.status)}</strong>
          <button
            className="button secondary"
            onClick={() => choose(active.id)}
          >
            View active campaign
          </button>
        </div>
      )}
      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}
      <section className="panel pc-plans" aria-label="Saved physical plans">
        <div className="panel-heading">
          <div>
            <h2>Saved plans</h2>
            <p>
              Starting creates a new execution. Unavailable cases remain
              recorded as blocked.
            </p>
          </div>
          <button
            className="button secondary"
            disabled={!online || loadingPlan || loading}
            onClick={() => {
              setError("");
              setRevision((value) => value + 1);
            }}
          >
            <RefreshCw size={14} /> Refresh campaign views
          </button>
        </div>
        <div className="pc-toolbar">
          <label>
            Campaign plan
            <select
              aria-label="Campaign plan"
              value={planId}
              onChange={(event) => {
                setPlanId(event.target.value);
                setPlanOffset(0);
                setPlanView(null);
              }}
            >
              <option value="">Select a saved plan</option>
              {plans.map((plan) => (
                <option key={plan.id} value={plan.id}>
                  {plan.name} · {plan.case_count} cases
                </option>
              ))}
            </select>
          </label>
          <button
            className="button primary"
            disabled={
              !online ||
              pending ||
              benchBusy ||
              !planDisplayed ||
              !state.execution_available ||
              !nodes.some((node) => node.connection_state === "connected")
            }
            onClick={() => void action("start")}
          >
            <Play size={14} /> Start available cases
          </button>
          <label
            className={`button secondary pc-import ${pending || !online ? "disabled" : ""}`}
          >
            <Upload size={14} /> Import plan settings
            <input
              type="file"
              accept=".json,application/json"
              aria-label="Import campaign settings JSON"
              disabled={pending || !online}
              onChange={async (event) => {
                const input = event.currentTarget,
                  file = input.files?.[0];
                if (!file) return;
                try {
                  if (file.size > 1048576)
                    throw new Error("Campaign settings must fit within 1 MiB");
                  const spec = JSON.parse(await file.text());
                  const saved = await request(`${root}/plans`, post(spec));
                  if (saved) {
                    setPlanId(saved.id);
                    setPlanOffset(0);
                    setRevision((value) => value + 1);
                  }
                } catch (cause) {
                  setError(
                    cause instanceof Error
                      ? cause.message
                      : "Choose valid campaign settings JSON",
                  );
                } finally {
                  input.value = "";
                }
              }}
            />
          </label>
        </div>
        {benchBusy && (
          <p>
            The shared bench is owned. Finish or stop its active work before
            starting another execution.
          </p>
        )}
        {!nodes.some((node) => node.connection_state === "connected") && (
          <p>
            Connect a compatible node in Bench overview. Local cases need one
            node; link cases need distinct A and B devices.
          </p>
        )}
        {!plans.length && (
          <p>
            No saved plans. Import campaign settings or save a plan through the
            CLI.
          </p>
        )}
        {loadingPlan && <p role="status">Updating plan requirements…</p>}
        {planDisplayed && (
          <>
            <p>
              {planDisplayed.record.case_count} saved cases ·{" "}
              {planDisplayed.record.batch_count} linked batches ·{" "}
              {planDisplayed.record.duration_bound_s} s declared scheduling
              reserve, not measured duration.
            </p>
            <div className="pc-table">
              <table>
                <caption>
                  Saved case order and current page requirements
                </caption>
                <thead>
                  <tr>
                    <th>Order</th>
                    <th>Case</th>
                    <th>Node / repetition</th>
                    <th>Current requirements</th>
                  </tr>
                </thead>
                <tbody>
                  {planDisplayed.cases.rows.map((row) => (
                    <tr key={row.id}>
                      <td>{row.index + 1}</td>
                      <td>
                        {row.label}
                        <small>
                          {String(row.case.kind).replaceAll("_", " ")}
                        </small>
                      </td>
                      <td>
                        {row.direction || row.roles.join(", ")}
                        <small>Repetition {row.repetition}</small>
                      </td>
                      <td>
                        <span className="badge neutral">
                          {row.readiness.ready
                            ? "Requirements available"
                            : "Blocked"}
                        </span>
                        {row.readiness.blockers.map((reason) => (
                          <small key={reason}>{reason}</small>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager
              page={planDisplayed.cases}
              change={setPlanOffset}
              busy={loadingPlan}
              name="planned cases"
            />
            <p className="pc-note">
              Requirements shown here are advisory for this page. Every case
              repeats its checks at execution.
            </p>
          </>
        )}
      </section>
      <section
        className="panel pc-execution"
        aria-label="Physical campaign execution"
      >
        <div className="panel-heading">
          <div>
            <h2>Execution history</h2>
            <p>
              Outcomes, child assessments and physical qualification remain
              separate.
            </p>
          </div>
        </div>
        <label className="pc-select">
          Saved execution
          <select
            aria-label="Saved campaign execution"
            value={selected}
            onChange={(event) => choose(event.target.value)}
          >
            <option value="">Select an execution</option>
            {selected &&
              !state.executions.some((row) => row.id === selected) && (
                <option value={selected}>
                  Saved execution · {short(selected)}
                </option>
              )}
            {state.executions.map((row) => (
              <option key={row.id} value={row.id}>
                {new Date(row.created_at).toLocaleString()} ·{" "}
                {label(row.status)} · {short(row.id)}
              </option>
            ))}
          </select>
        </label>
        {!state.executions.length && !selected && (
          <p>No executions yet. Saving or importing a plan starts no work.</p>
        )}
        {loading && <p role="status">Updating the saved case ledger…</p>}
        {displayed && record && (
          <>
            <div className="pc-heading">
              <div>
                <h3>{record.name}</h3>
                <span className="badge neutral">{label(record.status)}</span>
                <span className="pc-stage">{label(record.stage)}</span>
              </div>
              <code>{record.id}</code>
            </div>
            {record.parent_execution_id && (
              <p>
                Selected-case rerun of{" "}
                <button
                  className="text-button"
                  onClick={() => choose(record.parent_execution_id!)}
                >
                  {record.parent_execution_id}
                </button>
                . The original history is retained.
              </p>
            )}
            {record.reason && (
              <p className="pc-warning">
                {record.reason}
                {record.reason_code ? ` · ${label(record.reason_code)}` : ""}
              </p>
            )}
            {record.status === "interrupted" && (
              <p className="pc-warning">
                This execution will not resume. Reconnect as needed, then
                explicitly start fresh work or rerun selected cases.
              </p>
            )}
            <div
              className="pc-progress"
              role="progressbar"
              aria-label="Campaign cases finished"
              aria-valuemin={0}
              aria-valuemax={record.case_count}
              aria-valuenow={done}
            >
              <span style={{ width: `${(done / record.case_count) * 100}%` }} />
            </div>
            <p>
              {done} of {record.case_count} cases finished ·{" "}
              {Object.entries(record.case_counts)
                .map(([status, count]) => `${count} ${label(status)}`)
                .join(" · ")}
            </p>
            <div className="pc-toolbar pc-actions">
              {record.pause_requested ? (
                <button
                  className="button secondary"
                  disabled={!controls}
                  onClick={() => void action("resume")}
                >
                  <Play size={14} />
                  {record.status === "paused"
                    ? "Resume campaign"
                    : "Keep running"}
                </button>
              ) : (
                <button
                  className="button secondary"
                  disabled={!controls}
                  onClick={() => void action("pause")}
                >
                  <Pause size={14} /> Pause after current case
                </button>
              )}
              <button
                className="button secondary"
                disabled={!controls}
                onClick={() => void action("cancel")}
              >
                <Square size={14} /> Stop campaign
              </button>
              <button
                className="button secondary"
                disabled={!online || !isTerminal || downloading}
                onClick={() => void exportEvidence()}
              >
                <Download size={14} />
                {downloading
                  ? "Preparing verified download…"
                  : "Export campaign evidence"}
              </button>
            </div>
            {record.stage === "cleanup" && (
              <p role="status">
                Finishing cleanup before publishing the outcome
                {record.pending_outcome
                  ? ` (${label(record.pending_outcome)})`
                  : ""}
                .
              </p>
            )}
            <p>
              Cleanup:{" "}
              {record.cleanup == null
                ? "not recorded yet"
                : record.cleanup.confirmed
                  ? "confirmed idle"
                  : "unconfirmed"}
              . Physical qualification remains separate.
            </p>
            {downloaded && (
              <p className="pc-hash" role="status">
                {downloaded}
              </p>
            )}
            {record.physical_bindings && (
              <details className="pc-details">
                <summary>Enrolled devices and cleanup</summary>
                {Object.entries(record.physical_bindings).map(
                  ([role, binding]) => (
                    <p key={role}>
                      {role}: {binding.device_id} · boot {binding.boot_id} ·
                      connection {binding.connection_id}
                    </p>
                  ),
                )}
                <pre>{JSON.stringify(record.cleanup, null, 2)}</pre>
              </details>
            )}
            <div className="pc-toolbar">
              <span>{picked.size} selected for a new linked execution</span>
              <button
                className="button secondary"
                disabled={!isTerminal || !online}
                onClick={() =>
                  setPicked(
                    new Set([
                      ...picked,
                      ...displayed.cases.rows.map((row) => row.case_id),
                    ]),
                  )
                }
              >
                Select this page
              </button>
              <button
                className="button secondary"
                disabled={!picked.size}
                onClick={() => setPicked(new Set())}
              >
                Clear selection
              </button>
              <button
                className="button primary"
                disabled={
                  !isTerminal || !picked.size || benchBusy || pending || !online
                }
                onClick={() => void action("rerun")}
              >
                Rerun selected cases
              </button>
            </div>
            <div className="pc-table">
              <table>
                <caption>Saved execution case ledger</caption>
                <thead>
                  <tr>
                    <th>Select</th>
                    <th>Order / case</th>
                    <th>Outcome</th>
                    <th>Child / evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {displayed.cases.rows.map((row) => (
                    <tr key={row.case_id}>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`Select case ${row.index + 1} ${row.intent.label}`}
                          disabled={!isTerminal}
                          checked={picked.has(row.case_id)}
                          onChange={(event) =>
                            setPicked((previous) => {
                              const next = new Set(previous);
                              if (event.target.checked) next.add(row.case_id);
                              else next.delete(row.case_id);
                              return next;
                            })
                          }
                        />
                      </td>
                      <td>
                        <strong>
                          {row.index + 1}. {row.intent.label}
                        </strong>
                        <small>
                          {row.intent.direction || row.intent.roles.join(", ")}{" "}
                          · repetition {row.intent.repetition}
                        </small>
                        <details>
                          <summary>Saved settings</summary>
                          <pre>{JSON.stringify(row.intent.case, null, 2)}</pre>
                        </details>
                      </td>
                      <td>
                        <span className="badge neutral">
                          {label(row.status)}
                        </span>
                        {row.reason && <small>{row.reason}</small>}
                        {row.reason_code && (
                          <small>{label(row.reason_code)}</small>
                        )}
                      </td>
                      <td>
                        {row.child ? (
                          <ChildLink child={row.child} />
                        ) : (
                          "No child started"
                        )}
                        <small>{short(row.case_id)}</small>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager
              page={displayed.cases}
              change={setOffset}
              busy={loading}
              name="execution cases"
            />
          </>
        )}
      </section>
    </div>
  );
}
