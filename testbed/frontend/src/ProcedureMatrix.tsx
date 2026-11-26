import { useState } from "react";
import ModelComparison, { type ModelComparisonData } from "./ModelComparison";
import RFSweepComparison, { type SweepComparison } from "./RFSweepComparison";

export type MatrixOption = {
  groups: string[];
  kind:
    | "serial"
    | "local"
    | "link"
    | "campaign"
    | "memory"
    | "voice"
    | "voice_local";
  choose_security: boolean;
};

export type MatrixRunSummary = {
  id: string;
  catalog_id: string;
  status: string;
  assessment: string;
  procedure_revision?: string | null;
  case_count?: number;
  completed_cases?: number;
};

type SerialTransport = "native_usb" | "uart";

const transportLabels: Record<SerialTransport, string> = {
  native_usb: "Native USB",
  uart: "UART",
};

type MatrixCase = {
  id: string;
  group: string;
  variant: string;
  repetition: number;
  role: string;
  target_role?: string;
  transport?: SerialTransport;
  message_bytes?: number;
  message_count?: number;
  echo_count?: number;
  echo_blockers?: string[];
  cycles?: number;
  iterations?: number;
  planned_campaign_cases?: number;
  observation_s?: number;
  radio_load_period_s?: number | null;
  measurements?: {
    unique_original_delivery_ratio?: number | null;
    unresolved_messages?: number;
    matched_rtt?: { verified: number; timeouts: number; unresolved: number };
    capacity?: { finding: string };
    delivery?: { verified_messages: number | null };
    export?: string;
    health?: Record<string, { samples: number; reasons: string[] }>;
    planned_loads?: number;
    verified_loads?: number;
    original?: { id: string; cleanup: { confirmed: boolean } };
    recovery?: { id: string };
    fault_to_cleanup_ms?: number;
    faulted_radio_run?: string;
    recovery_radio_run?: string;
    reset_proof?: { procedure_id: string; case_id: string };
  };
  ready: boolean;
  blockers: string[];
  status?: string;
  assessment?: string;
  reason?: string;
};

type MatrixPlan = {
  sha256: string;
  case_count: number;
  ready_case_count: number;
  full_plan: boolean;
  cases: MatrixCase[];
};

type MatrixRun = MatrixPlan &
  MatrixRunSummary & {
    hardware_validated: boolean;
    reason: string | null;
    sweep_comparison?: SweepComparison;
    model_comparison?: ModelComparisonData;
  };

type Props = {
  catalogId: string;
  option: MatrixOption;
  active: MatrixRunSummary | null;
  saved: MatrixRunSummary[];
  request: (path: string, options?: RequestInit) => Promise<unknown>;
  pending: boolean;
  online: boolean;
  benchBusy: boolean;
  references: { id: string; name: string; sample_count: number }[];
};

const perPage = 12;
const endpoint = "/api/procedures/matrix";
const runPath = (id: string) =>
  `/api/procedures/runs/${encodeURIComponent(id)}`;

function Cases({ rows, runId }: { rows: MatrixCase[]; runId?: string }) {
  const [page, setPage] = useState(0);
  const first = page * perPage;
  return (
    <>
      <ol className="matrix-cases" start={first + 1}>
        {rows.slice(first, first + perPage).map((row) => (
          <li key={row.id}>
            <strong>
              {row.group} · {row.variant.replaceAll("_", " ")} ·{" "}
              {row.role.replace("_TO_", " → ")}
              {row.transport && (
                <> · {transportLabels[row.transport] ?? row.transport}</>
              )}{" "}
              · repeat {row.repetition}
            </strong>
            <span>
              {row.status
                ? `${row.status} · ${row.assessment}`
                : row.ready
                  ? "Ready"
                  : "Blocked"}
              {typeof row.measurements?.unique_original_delivery_ratio ===
              "number"
                ? ` · ${(100 * row.measurements.unique_original_delivery_ratio).toFixed(1)}% delivered`
                : ""}
              {row.measurements?.unresolved_messages
                ? ` · ${row.measurements.unresolved_messages} unresolved`
                : ""}
              {row.message_bytes ? ` · ${row.message_bytes} bytes` : ""}
              {row.message_count && row.message_count > 1
                ? ` · ${row.message_count} messages`
                : ""}
              {Boolean(row.echo_count) && (
                <>
                  {" "}
                  ·{" "}
                  {row.measurements?.matched_rtt
                    ? `${row.measurements.matched_rtt.verified}/${row.echo_count} RTT samples`
                    : `${row.echo_count} planned echoes`}
                </>
              )}
              {row.cycles && row.cycles > 1 ? ` · ${row.cycles} cycles` : ""}
              {row.iterations ? ` · ${row.iterations} iterations` : ""}
              {row.observation_s
                ? ` · ${row.observation_s} seconds of health telemetry`
                : ""}
              {row.radio_load_period_s
                ? ` · Transfer every ${row.radio_load_period_s} seconds`
                : ""}
              {row.planned_campaign_cases
                ? ` · ${row.planned_campaign_cases} campaign cases`
                : ""}
            </span>
            {row.observation_s && row.measurements?.health && (
              <span>
                {Object.entries(row.measurements.health)
                  .map(
                    ([role, health]) =>
                      `Node ${role} · ${health.samples} health samples`,
                  )
                  .join(" · ")}
                {row.measurements.planned_loads
                  ? ` · ${row.measurements.verified_loads}/${row.measurements.planned_loads} transfers verified`
                  : ""}
              </span>
            )}
            {row.measurements?.capacity && (
              <span>
                Queue assessment{" "}
                {row.measurements.capacity.finding.replaceAll("_", " ")}
                {row.measurements.delivery?.verified_messages != null &&
                  ` · ${row.measurements.delivery.verified_messages} verified messages`}
              </span>
            )}
            {row.measurements?.export && (
              <a href={row.measurements.export}>Source assessment</a>
            )}
            {row.target_role && <span>Interrupt Node {row.target_role}</span>}
            {row.measurements?.faulted_radio_run &&
              row.measurements.recovery_radio_run && (
                <>
                  <span>
                    Peer cleanup confirmed in{" "}
                    {row.measurements.fault_to_cleanup_ms?.toFixed(1)} ms
                  </span>
                  <a
                    href={`/api/radio/runs/${row.measurements.faulted_radio_run}/export`}
                  >
                    Interrupted transfer archive
                  </a>
                  <a
                    href={`/api/radio/runs/${row.measurements.recovery_radio_run}/export`}
                  >
                    Recovery transfer archive
                  </a>
                </>
              )}
            {row.measurements?.original && row.measurements.recovery && (
              <>
                <span>
                  Original cleanup{" "}
                  {row.measurements.original.cleanup.confirmed
                    ? "confirmed"
                    : "unconfirmed"}
                </span>
                <a
                  href={`/api/physical-campaigns/executions/${row.measurements.original.id}/export`}
                >
                  Interrupted campaign evidence
                </a>
                <a
                  href={`/api/physical-campaigns/executions/${row.measurements.recovery.id}/export`}
                >
                  Recovery campaign evidence
                </a>
              </>
            )}
            {row.measurements?.reset_proof && (
              <a
                href={`${runPath(row.measurements.reset_proof.procedure_id)}/evidence?case_id=${encodeURIComponent(row.measurements.reset_proof.case_id)}`}
              >
                Stale-boot rejection evidence
              </a>
            )}
            {(row.reason || row.blockers.length > 0) && (
              <span>{row.reason || row.blockers.join(" · ")}</span>
            )}
            {Boolean(row.echo_blockers?.length) && (
              <span>
                Matched RTT unavailable · {row.echo_blockers?.join(" · ")}
              </span>
            )}
            {runId && (
              <a
                href={`${runPath(runId)}/evidence?case_id=${encodeURIComponent(row.id)}`}
              >
                Case evidence
              </a>
            )}
          </li>
        ))}
      </ol>
      {rows.length > perPage && (
        <div className="matrix-pagination">
          <button
            className="button secondary"
            disabled={page === 0}
            onClick={() => setPage(page - 1)}
          >
            Previous cases
          </button>
          <span>
            {first + 1}–{Math.min(first + perPage, rows.length)} of{" "}
            {rows.length}
          </span>
          <button
            className="button secondary"
            disabled={first + perPage >= rows.length}
            onClick={() => setPage(page + 1)}
          >
            Next cases
          </button>
        </div>
      )}
    </>
  );
}

export default function ProcedureMatrix({
  catalogId,
  option,
  active,
  saved,
  request,
  pending,
  online,
  benchBusy,
  references,
}: Props) {
  const [group, setGroup] = useState("");
  const [role, setRole] = useState("both");
  const [transport, setTransport] = useState<SerialTransport | "both">(
    "native_usb",
  );
  const [direction, setDirection] = useState("both");
  const [security, setSecurity] = useState("none");
  const [size, setSize] = useState("quick");
  const [echoMode, setEchoMode] = useState("default");
  const [restartEvidence, setRestartEvidence] = useState("");
  const [usbEvidence, setUsbEvidence] = useState("");
  const [resetEvidence, setResetEvidence] = useState("");
  const [evidenceError, setEvidenceError] = useState("");
  const rfSweep = /^RF-0[1-4]$/.test(catalogId);
  const [referenceIds, setReferenceIds] = useState<string[]>([]);
  const [preview, setPreview] = useState<{
    plan: MatrixPlan;
    body: string;
  } | null>(null);
  const [inspected, setInspected] = useState<MatrixRun | null>(null);
  const memory = option.kind === "memory";
  const local =
    option.kind === "serial" ||
    option.kind === "local" ||
    option.kind === "voice_local" ||
    (memory && (group === "C1" || group === "C3"));
  const fixedSource = catalogId === "VOICE-03";
  const referenceLimit = fixedSource ? 1 : 3;
  const voice =
    (option.kind === "voice" && (fixedSource || group !== "C2")) ||
    (option.kind === "voice_local" && (!group || group === "C3"));
  const stability = catalogId === "OPS-01" && group === "C6";
  const restart = catalogId === "OPS-01" && (!group || group === "C3");
  const usb = catalogId === "OPS-01" && (!group || group === "C1");
  const reset = catalogId === "OPS-01" && (!group || group === "C2");
  const selectDirection =
    option.kind === "link" ||
    option.kind === "voice" ||
    (memory && !local) ||
    stability;
  const recent = saved.filter(
    (run) =>
      run.catalog_id === catalogId &&
      run.procedure_revision &&
      run.id !== active?.id,
  );

  async function previewCases() {
    const evidence: Record<string, unknown[]> = {};
    for (const [field, source] of [
      ["ops_restart_evidence", restart ? restartEvidence : ""],
      ["ops_usb_evidence", usb ? usbEvidence : ""],
      ["ops_reset_evidence", reset ? resetEvidence : ""],
    ]) {
      if (!source.trim()) continue;
      try {
        const rows: unknown = JSON.parse(source);
        if (!Array.isArray(rows) || !rows.length) {
          throw new Error("Expected a nonempty JSON array");
        }
        evidence[field] = rows;
      } catch {
        setEvidenceError("Enter the saved evidence as a nonempty JSON array.");
        return;
      }
    }
    setEvidenceError("");
    const document = {
      catalog_id: catalogId,
      ...(group && { groups: [group] }),
      ...(local && role !== "both" && { roles: [role] }),
      ...(option.kind === "serial" && {
        transports: transport === "both" ? ["native_usb", "uart"] : [transport],
      }),
      ...(selectDirection &&
        direction !== "both" && { directions: [direction] }),
      ...(option.choose_security && { rf_security: security }),
      ...(rfSweep &&
        echoMode !== "default" && {
          rf_echoes_per_case:
            echoMode === "skip" ? 0 : size === "quick" ? 1 : 100,
        }),
      ...(voice &&
        referenceIds.length > 0 && { voice_reference_ids: referenceIds }),
      ...evidence,
      ...(size === "quick" && {
        repetitions: 1,
        ...(catalogId === "OPS-01" && { ops_observation_s: 10 }),
        ...(option.kind === "serial"
          ? { valid_cycles: 1 }
          : option.kind === "local"
            ? { diagnostic_iterations: 10 }
            : memory
              ? { memory_window_ms: 1000 }
              : { messages_per_case: 1 }),
      }),
    };
    const body = JSON.stringify(document);
    const plan = (await request(`${endpoint}/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    })) as MatrixPlan | null;
    setPreview(plan ? { plan, body } : null);
  }

  async function startCases() {
    if (!preview) return;
    const run = await request(
      `${endpoint}?expected_plan_sha256=${preview.plan.sha256}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: preview.body,
      },
    );
    if (run) {
      setPreview(null);
      setInspected(null);
    }
  }

  async function inspect(id: string) {
    const result = (await request(runPath(id))) as MatrixRun | null;
    if (result) setInspected(result);
  }

  return (
    <section
      className="panel physical-check matrix-panel"
      aria-label="Procedure matrix"
    >
      <h3>Procedure matrix</h3>
      <form
        className="physical-controls"
        onChange={() => setPreview(null)}
        onSubmit={(event) => {
          event.preventDefault();
          void previewCases();
        }}
      >
        <label>
          Case group
          <select
            value={group}
            disabled={pending}
            onChange={(event) => setGroup(event.target.value)}
          >
            <option value="">All groups</option>
            {option.groups.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          Workload
          <select
            value={size}
            disabled={pending}
            onChange={(event) => setSize(event.target.value)}
          >
            <option value="quick">Quick check</option>
            <option value="default">Procedure defaults</option>
          </select>
        </label>
        {restart && (
          <label>
            Saved restart evidence (JSON)
            <textarea
              value={restartEvidence}
              onChange={(event) => {
                setEvidenceError("");
                setRestartEvidence(event.target.value);
              }}
              disabled={pending}
              rows={3}
              maxLength={4096}
            />
          </label>
        )}
        {usb && (
          <label>
            Saved USB recovery evidence (JSON)
            <textarea
              value={usbEvidence}
              onChange={(event) => {
                setEvidenceError("");
                setUsbEvidence(event.target.value);
              }}
              disabled={pending}
              rows={3}
              maxLength={4096}
            />
          </label>
        )}
        {reset && (
          <label>
            Saved reset recovery evidence (JSON)
            <textarea
              value={resetEvidence}
              onChange={(event) => {
                setEvidenceError("");
                setResetEvidence(event.target.value);
              }}
              disabled={pending}
              rows={3}
              maxLength={4096}
            />
          </label>
        )}
        {evidenceError && <span role="alert">{evidenceError}</span>}
        {local && (
          <label>
            Node
            <select
              value={role}
              disabled={pending}
              onChange={(event) => setRole(event.target.value)}
            >
              <option value="both">A and B</option>
              <option value="A">A</option>
              <option value="B">B</option>
            </select>
          </label>
        )}
        {option.kind === "serial" && (
          <label>
            Transport
            <select
              value={transport}
              disabled={pending}
              onChange={(event) => {
                setTransport(event.target.value as SerialTransport | "both");
                setPreview(null);
              }}
            >
              <option value="native_usb">Native USB</option>
              <option value="uart">UART</option>
              <option value="both">Both transports</option>
            </select>
          </label>
        )}
        {selectDirection && (
          <label>
            Direction
            <select
              value={direction}
              disabled={pending}
              onChange={(event) => setDirection(event.target.value)}
            >
              <option value="both">Both directions</option>
              <option value="A_TO_B">A → B</option>
              <option value="B_TO_A">B → A</option>
            </select>
          </label>
        )}
        {voice && (
          <fieldset className="matrix-references">
            <legend>
              {fixedSource
                ? "Three-second reference clip"
                : "Three-second reference clips"}
            </legend>
            {references.filter((entry) => entry.sample_count === 24000)
              .length === 0 && (
              <p>Upload a 24,000-sample reference in Voice workspace.</p>
            )}
            {references
              .filter((entry) => entry.sample_count === 24000)
              .map((entry) => (
                <label key={entry.id}>
                  <input
                    type="checkbox"
                    checked={referenceIds.includes(entry.id)}
                    disabled={
                      pending ||
                      (referenceIds.length >= referenceLimit &&
                        !referenceIds.includes(entry.id))
                    }
                    onChange={(event) =>
                      setReferenceIds(
                        event.target.checked
                          ? [...referenceIds, entry.id]
                          : referenceIds.filter((id) => id !== entry.id),
                      )
                    }
                  />
                  {entry.name}
                </label>
              ))}
          </fieldset>
        )}
        {rfSweep && (
          <label>
            Companion round trips
            <select
              value={echoMode}
              disabled={pending}
              onChange={(event) => setEchoMode(event.target.value)}
            >
              <option value="default">Procedure default</option>
              <option value="matched">Match workload count</option>
              <option value="skip">Skip</option>
            </select>
          </label>
        )}
        {option.choose_security && (
          <label>
            Security
            <select
              value={security}
              disabled={pending}
              onChange={(event) => setSecurity(event.target.value)}
            >
              <option value="none">Unprotected</option>
              <option value="aes128_gcm">AES-128-GCM</option>
            </select>
          </label>
        )}
        <button
          type="submit"
          className="button secondary"
          disabled={!online || pending}
        >
          Preview cases
        </button>
      </form>
      {preview && (
        <div className="matrix-plan">
          <p role="status">
            {preview.plan.ready_case_count} of {preview.plan.case_count} cases
            ready ·{" "}
            {preview.plan.full_plan ? "Procedure defaults" : "Selected subset"}
          </p>
          <Cases key={preview.plan.sha256} rows={preview.plan.cases} />
          <button
            className="button primary"
            disabled={
              !online ||
              pending ||
              benchBusy ||
              preview.plan.ready_case_count === 0
            }
            onClick={() => void startCases()}
          >
            Run ready cases
          </button>
        </div>
      )}
      {active?.catalog_id === catalogId && active.procedure_revision && (
        <div className="physical-history">
          <div>
            <strong role="status">Matrix running</strong>
            <span>
              {active.completed_cases} of {active.case_count} cases settled
            </span>
          </div>
          <button
            className="button secondary"
            disabled={!online || pending}
            onClick={() =>
              void request(
                `/api/procedures/stop?expected_run_id=${encodeURIComponent(active.id)}`,
                { method: "POST" },
              )
            }
          >
            Stop matrix
          </button>
        </div>
      )}
      {recent.length > 0 && (
        <>
          <h4>Saved runs</h4>
          {recent.map((run) => (
            <div key={run.id} className="physical-history">
              <div>
                <strong>{run.id.slice(0, 8)}</strong>
                <span>
                  {run.status} · {run.assessment}
                </span>
              </div>
              <button
                className="button secondary"
                disabled={pending}
                onClick={() => void inspect(run.id)}
              >
                Inspect cases
              </button>
              <a href={`${runPath(run.id)}/export/zip`}>Evidence ZIP</a>
            </div>
          ))}
        </>
      )}
      {inspected && (
        <div className="matrix-plan">
          <h4>Cases from {inspected.id.slice(0, 8)}</h4>
          {inspected.reason && <p>{inspected.reason}</p>}
          <p>
            Physical qualification{" "}
            {inspected.hardware_validated ? "recorded" : "pending"}
          </p>
          {inspected.sweep_comparison && (
            <>
              <RFSweepComparison
                key={`sweep-${inspected.id}`}
                data={inspected.sweep_comparison}
              />
              {Boolean(inspected.sweep_comparison.rtt_metrics?.length) && (
                <RFSweepComparison
                  key={`rtt-${inspected.id}`}
                  data={inspected.sweep_comparison}
                  timing
                />
              )}
            </>
          )}
          {inspected.model_comparison && (
            <ModelComparison
              key={`model-${inspected.id}`}
              data={inspected.model_comparison}
            />
          )}
          <Cases
            key={inspected.id}
            rows={inspected.cases}
            runId={inspected.id}
          />
        </div>
      )}
    </section>
  );
}
