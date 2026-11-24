import { useEffect, useMemo, useState } from "react";
import { Check, Download, Radio, Square } from "lucide-react";
import type { HardwareNode } from "./HardwareBench";
import type { Request } from "./NodeArtifacts";
import "./radio-link.css";

type Signal = {
  role: string;
  rssi_dbm: number;
  snr_db: number;
  rx_done_us: number;
  frame_type?: string | null;
};
type Identity = { device_id: string; boot_id: string };
type Verification = {
  bytes_equal: boolean;
  length_bytes: number;
  sha256: string;
  sample_hex: string;
};
type Accounting =
  | {
      evidence_complete: true;
      data_originals: number;
      data_attempts: number;
      data_retries: number;
      accepted_fragments: number;
      delivered_messages: number;
      ack_transmissions: number;
      valid_ack_observations: number;
      unique_original_delivery_ratio: number;
      receiver_duplicates: number;
    }
  | { evidence_complete: false; reason: string };
type MissingEvidence =
  | {
      ranges_complete: true;
      missing_indexes: number[];
      accepted_fragments: number;
      fragment_count: number;
      part_count: number;
      scope: string;
    }
  | { ranges_complete: false; reason: string };
export type RadioRun = {
  id: string;
  created_at: string;
  finished_at: string | null;
  status: string;
  stage: string;
  sender: string;
  receiver: string;
  session_id: string;
  hardware_qualified: boolean;
  plan: {
    radio: Record<string, unknown>;
    link: Record<string, unknown>;
    spec: { message_bytes: number; direction: string };
  };
  identities: Record<string, Identity>;
  verification: Verification | null;
  accounting?: Accounting | null;
  missing_evidence?: MissingEvidence | null;
  error: string | null;
  cleanup: { confirmed: boolean; nodes?: Record<string, string> } | null;
  signal?: Signal[];
  applied_settings?: Record<string, unknown>;
  summaries?: Record<string, unknown>;
  available_content?: string[];
};
export type RadioState = {
  active_id: string | null;
  active?: RadioRun | null;
  runs: RadioRun[];
};
const empty: RadioState = { active_id: null, active: null, runs: [] };
const post = (body: unknown = {}): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
const stages: Record<string, string> = {
  configuring: "Applying matching settings",
  preparing: "Preparing both nodes",
  arming: "Arming the receiver",
  transmitting: "Sending message fragments",
  retrieving: "Verifying recovered bytes",
  stopping: "Closing node sessions",
  finished: "Finished",
};
const number = (text: string) => (text.trim() === "" ? null : Number(text));
async function json(response: Response) {
  const body = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(body.detail)
      ? body.detail
          .map((x: { msg: string }) => x.msg.replace(/^Value error, /, ""))
          .join("; ")
      : body.detail;
    throw new Error(
      typeof detail === "string" ? detail : "The radio check is unavailable.",
    );
  }
  return body;
}

export default function RadioLink({
  state = empty,
  nodes,
  benchBusy,
  online,
  request,
  pending,
}: {
  state?: RadioState;
  nodes: HardwareNode[];
  benchBusy: boolean;
  online: boolean;
  request: Request;
  pending: boolean;
}) {
  const [form, setForm] = useState({
    direction: "A_TO_B",
    message_bytes: "64",
    timeout_ms: "10000",
    frequency_hz: "915000000",
    spreading_factor: "7",
    bandwidth_hz: "125000",
    coding_rate_denominator: "5",
    tx_power_dbm: "2",
    fragment_payload_bytes: "160",
    source_seed: "743",
    ack_mode: "none",
    max_retries: "0",
  });
  const [readiness, setReadiness] = useState<{
    key: string;
    ready: boolean;
    blockers: string[];
  } | null>(null);
  const [selected, setSelected] = useState<string | null>(
    state.active_id || state.runs[0]?.id || null,
  );
  const [detail, setDetail] = useState<RadioRun | null>(null);
  const [detailError, setDetailError] = useState("");
  const body = useMemo(
    () =>
      JSON.stringify({
        direction: form.direction,
        message_bytes: number(form.message_bytes),
        source_seed: number(form.source_seed),
        timeout_ms: number(form.timeout_ms),
        radio: {
          frequency_hz: number(form.frequency_hz),
          spreading_factor: number(form.spreading_factor),
          bandwidth_hz: number(form.bandwidth_hz),
          coding_rate_denominator: number(form.coding_rate_denominator),
          tx_power_dbm: number(form.tx_power_dbm),
        },
        link: {
          fragment_payload_bytes: number(form.fragment_payload_bytes),
          ack_mode: form.ack_mode,
          max_retries: number(form.max_retries),
        },
      }),
    [form],
  );
  const availability = JSON.stringify(
    nodes.map((n) => [
      n.id,
      n.connected,
      n.connection_state,
      n.identity?.boot_id,
      n.identity?.capabilities,
      n.health?.state,
      n.health?.capability_availability,
      n.artifact_support?.commands,
    ]),
  );
  const readyKey = `${body}:${availability}:${benchBusy}:${online}`;
  useEffect(() => {
    const controller = new AbortController();
    setReadiness(null);
    if (!online) {
      setReadiness({
        key: readyKey,
        ready: false,
        blockers: ["The backend is offline."],
      });
      return () => controller.abort();
    }
    const timer = setTimeout(() => {
      void fetch("/api/radio/preflight", {
        ...post(JSON.parse(body)),
        signal: controller.signal,
      })
        .then(json)
        .then((value) => {
          if (!controller.signal.aborted)
            setReadiness({
              key: readyKey,
              ready: value.ready,
              blockers: value.blockers,
            });
        })
        .catch((error) => {
          if (!controller.signal.aborted)
            setReadiness({
              key: readyKey,
              ready: false,
              blockers: [String(error.message || error)],
            });
        });
    }, 150);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [readyKey, body, online]);
  useEffect(() => {
    if (state.active_id) setSelected(state.active_id);
  }, [state.active_id]);
  useEffect(() => {
    if (!selected && state.runs[0]) setSelected(state.runs[0].id);
  }, [selected, state.runs]);
  const brief =
    state.active?.id === selected
      ? state.active
      : state.runs.find((r) => r.id === selected);
  const detailKey = JSON.stringify([
    selected,
    brief?.status,
    brief?.stage,
    brief?.verification?.sha256,
    brief?.error,
    brief?.cleanup,
  ]);
  useEffect(() => {
    const controller = new AbortController();
    setDetailError("");
    if (!selected || !online) {
      setDetail(null);
      return () => controller.abort();
    }
    void fetch(`/api/radio/runs/${selected}`, { signal: controller.signal })
      .then(json)
      .then((value) => {
        if (!controller.signal.aborted) setDetail(value);
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setDetailError(String(error.message || error));
      });
    return () => controller.abort();
  }, [selected, detailKey, online]);
  const update = (key: keyof typeof form, value: string) =>
    setForm((old) => ({ ...old, [key]: value }));
  const ready = readiness?.key === readyKey && readiness.ready;
  const record =
    detail?.id === selected
      ? { ...detail, ...brief, identities: detail.identities }
      : brief;
  const signals = brief?.signal || [];
  const canStart = ready && !pending && !benchBusy && online;
  function input(
    key: keyof typeof form,
    label: string,
    min: number,
    max: number,
    step = 1,
  ) {
    return (
      <label>
        {label}
        <input
          type="number"
          aria-label={`Radio ${label.toLowerCase()}`}
          min={min}
          max={max}
          step={step}
          required
          value={form[key]}
          onChange={(e) => update(key, e.target.value)}
        />
      </label>
    );
  }
  function select(
    key: keyof typeof form,
    label: string,
    values: number[],
    format = (value: number) => String(value),
    disabled = false,
  ) {
    return (
      <label>
        {label}
        <select
          aria-label={`Radio ${label.toLowerCase()}`}
          value={form[key]}
          disabled={disabled}
          onChange={(e) => update(key, e.target.value)}
        >
          {values.map((value) => (
            <option key={value} value={value}>
              {format(value)}
            </option>
          ))}
        </select>
      </label>
    );
  }
  return (
    <section className="panel radio-link" aria-label="Known-data radio link">
      <div className="radio-heading">
        <div>
          <span className="eyebrow">TWO-NODE LINK CHECK</span>
          <h2>
            <Radio size={20} /> Known-data radio link
          </h2>
          <p>Send one unencrypted message and compare the recovered bytes.</p>
        </div>
        <span className="radio-mode">Unencrypted</span>
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (canStart)
            void request("/api/radio/runs", { ...post(), body }).then(
              (result) => {
                if (result?.id) setSelected(result.id);
              },
            );
        }}
      >
        <fieldset disabled={pending || benchBusy}>
          <div className="radio-fields">
            <label>
              Direction
              <select
                aria-label="Radio direction"
                value={form.direction}
                onChange={(e) => update("direction", e.target.value)}
              >
                <option value="A_TO_B">A → B</option>
                <option value="B_TO_A">B → A</option>
              </select>
            </label>
            {input("message_bytes", "Message bytes", 1, 65536)}
            {input("timeout_ms", "Run window (ms)", 1000, 3600000)}
          </div>
          <details className="radio-settings">
            <summary>Modem and source settings</summary>
            <div className="radio-fields">
              {input(
                "frequency_hz",
                "Frequency (Hz)",
                902000000,
                928000000,
                1000,
              )}
              {select(
                "spreading_factor",
                "Spreading factor",
                [7, 8, 9, 10, 11, 12],
                (value) => `SF${value}`,
              )}
              {select(
                "bandwidth_hz",
                "Bandwidth",
                [125000, 250000, 500000],
                (value) => `${value / 1000} kHz`,
              )}
              {select(
                "coding_rate_denominator",
                "Coding rate",
                [5, 6, 7, 8],
                (value) => `4/${value}`,
              )}
              {input("tx_power_dbm", "SX1262 power (dBm)", 2, 20)}
              {input("fragment_payload_bytes", "Fragment capacity", 16, 215)}
              <label>
                Acknowledgments
                <select
                  aria-label="Radio acknowledgments"
                  value={form.ack_mode}
                  onChange={(event) =>
                    setForm((old) => ({
                      ...old,
                      ack_mode: event.target.value,
                      max_retries: event.target.value === "none" ? "0" : "2",
                    }))
                  }
                >
                  <option value="none">Disabled</option>
                  <option value="stop_wait">Stop and wait</option>
                </select>
              </label>
              {select(
                "max_retries",
                "Retry limit",
                [0, 1, 2],
                String,
                form.ack_mode === "none",
              )}
              {input("source_seed", "Source seed", 0, 4294967295)}
            </div>
            <p>
              Power is the configured SX1262 setting. Antenna output still needs
              measurement.
            </p>
          </details>
        </fieldset>
        <div className="radio-actions">
          <button
            className="button primary"
            type="submit"
            disabled={!canStart}
            aria-describedby="radio-readiness"
          >
            <Radio size={16} /> Start radio check
          </button>
          <button
            className="button secondary"
            type="button"
            disabled={!state.active_id || pending || !online}
            onClick={() =>
              void request(`/api/radio/runs/${state.active_id}/stop`, post())
            }
          >
            <Square size={15} /> Stop radio check
          </button>
          <a href="#bench">Open bench overview</a>
        </div>
        <div id="radio-readiness" className="radio-readiness" role="status">
          {state.active ? (
            stages[state.active.stage] || state.active.stage
          ) : readiness?.key !== readyKey ? (
            "Checking node readiness…"
          ) : ready ? (
            "Both nodes are ready. The receiver will be armed first."
          ) : (
            <ul>
              {readiness.blockers.map((reason) => (
                <li key={reason}>
                  {reason.replace(
                    /(?:MISSING_CAPABILITY|UNSUPPORTED_VERSION): /g,
                    "",
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </form>
      {state.runs.length > 0 && (
        <div className="radio-results">
          <div className="radio-history" aria-label="Radio run history">
            {state.runs.slice(0, 8).map((run) => (
              <button
                key={run.id}
                className={selected === run.id ? "selected" : ""}
                aria-label={`Inspect radio run ${run.id}`}
                aria-pressed={selected === run.id}
                onClick={() => setSelected(run.id)}
              >
                <span>
                  {run.sender} → {run.receiver} · {run.plan.spec.message_bytes}{" "}
                  bytes
                </span>
                <strong>{run.status}</strong>
                <small>{new Date(run.created_at).toLocaleString()}</small>
              </button>
            ))}
          </div>
          <div className="radio-record" aria-live="polite">
            {detailError && <p role="alert">{detailError}</p>}
            {record && (
              <>
                <div className="radio-heading">
                  <h3>
                    {record.sender} → {record.receiver}
                  </h3>
                  <span className="radio-mode">{record.status}</span>
                </div>
                <p className="radio-byte-result">
                  {record.verification?.bytes_equal ? (
                    <>
                      <Check size={17} />
                      {record.status === "completed"
                        ? "Exact bytes verified"
                        : "Bytes verified; run incomplete"}
                    </>
                  ) : record.status === "running" ? (
                    "Waiting for verified readback"
                  ) : (
                    "Delivery not verified"
                  )}
                </p>
                {record.error && (
                  <p className="radio-error" role="alert">
                    {record.error}
                  </p>
                )}
                {record.verification && (
                  <>
                    <p>
                      {record.verification.length_bytes} received bytes ·
                      SHA-256
                    </p>
                    <code>{record.verification.sha256}</code>
                    <p>Received preview</p>
                    <code>{record.verification.sample_hex}</code>
                  </>
                )}
                {record.accounting?.evidence_complete && (
                  <div
                    className="radio-accounting"
                    aria-label="Reconciled radio accounting"
                  >
                    {[
                      [
                        "Confirmed DATA originals",
                        record.accounting.data_originals,
                      ],
                      ["DATA attempts", record.accounting.data_attempts],
                      ["Retries", record.accounting.data_retries],
                      [
                        "Unique accepted fragments",
                        record.accounting.accepted_fragments,
                      ],
                      [
                        "Delivered messages",
                        record.accounting.delivered_messages,
                      ],
                      [
                        "Receiver duplicates",
                        record.accounting.receiver_duplicates,
                      ],
                      [
                        "ACK transmissions",
                        record.accounting.ack_transmissions,
                      ],
                      [
                        "Matched ACK observations",
                        record.accounting.valid_ack_observations,
                      ],
                      [
                        "Original delivery ratio",
                        `${(100 * record.accounting.unique_original_delivery_ratio).toFixed(1)}%`,
                      ],
                    ].map(([label, value]) => (
                      <div key={label}>
                        <span>{label}</span>
                        <strong>{value}</strong>
                      </div>
                    ))}
                  </div>
                )}
                {record.accounting?.evidence_complete === false && (
                  <p>
                    Frame accounting is incomplete. {record.accounting.reason}
                  </p>
                )}
                {record.missing_evidence && (
                  <details className="radio-settings">
                    <summary>Missing fragment evidence</summary>
                    {record.missing_evidence.ranges_complete ? (
                      <>
                        <p>
                          {record.missing_evidence.accepted_fragments} of{" "}
                          {record.missing_evidence.fragment_count} fragments
                          inserted; all {record.missing_evidence.part_count}{" "}
                          range parts retained.
                        </p>
                        <pre>
                          {record.missing_evidence.missing_indexes.join(", ") ||
                            "No missing indexes; inspect the failure reason."}
                        </pre>
                        <p>{record.missing_evidence.scope}</p>
                      </>
                    ) : (
                      <p>{record.missing_evidence.reason}</p>
                    )}
                  </details>
                )}
                <div className="radio-signal">
                  <strong>Observed receive signal</strong>
                  {signals.length ? (
                    signals.map((signal, index) => (
                      <span key={index}>
                        Node {signal.role} ·{" "}
                        {signal.frame_type?.toUpperCase() ||
                          "unclassified frame"}
                        : {signal.rssi_dbm.toFixed(1)} dBm RSSI ·{" "}
                        {signal.snr_db.toFixed(2)} dB SNR
                      </span>
                    ))
                  ) : (
                    <span>No RX signal observation was retained.</span>
                  )}
                </div>
                {record.cleanup && (
                  <p className={record.cleanup.confirmed ? "" : "radio-error"}>
                    {record.cleanup.confirmed
                      ? Object.keys(record.cleanup.nodes || {}).length
                        ? "Node sessions closed; idle confirmed."
                        : "No node sessions remained open."
                      : "Cleanup is unconfirmed. Inspect the details before starting again."}
                  </p>
                )}
                <p className="radio-qualification">
                  Hardware qualification:{" "}
                  {record.hardware_qualified ? "recorded" : "pending"}
                </p>
                <div className="radio-actions">
                  <a
                    className="button secondary"
                    href={`/api/radio/runs/${record.id}/export`}
                  >
                    <Download size={15} /> Export evidence
                  </a>
                  {record.available_content?.includes("source") && (
                    <a
                      href={`/api/radio/runs/${record.id}/content/source`}
                      download
                    >
                      Source bytes
                    </a>
                  )}
                  {record.available_content?.includes("recovered") && (
                    <a
                      href={`/api/radio/runs/${record.id}/content/recovered`}
                      download
                    >
                      Recovered bytes
                    </a>
                  )}
                </div>
                <details className="radio-settings">
                  <summary>Identities, settings and node summaries</summary>
                  <pre>
                    {JSON.stringify(
                      {
                        session_id: record.session_id,
                        identities: record.identities,
                        requested: record.plan,
                        applied: record.applied_settings,
                        summaries: record.summaries,
                        cleanup: record.cleanup,
                      },
                      null,
                      2,
                    )}
                  </pre>
                </details>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
