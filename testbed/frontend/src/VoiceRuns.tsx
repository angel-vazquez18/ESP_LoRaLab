import { useEffect, useMemo, useState } from "react";
import { AudioLines, Play, Square } from "lucide-react";
import type { HardwareNode } from "./HardwareBench";
import type { Request } from "./NodeArtifacts";
import VoiceReview from "./VoiceReview";
import VoiceWaveform from "./VoiceWaveform";
import "./voice-runs.css";

type Listening = { heard: string; notes: string; recorded_at: string | null };
type VoiceRecord = {
  id: string;
  created_at: string;
  finished_at: string | null;
  status: string;
  stage: string;
  sender: string;
  receiver: string;
  request: { source: string; direction: string; include_comparisons: boolean };
  sample_count: number;
  delivery_verified: boolean;
  playback_completed: boolean;
  listening: Listening;
  hardware_qualified: boolean;
  cleanup: {
    confirmed: boolean;
    reason?: string;
    nodes?: Record<string, string>;
  } | null;
  error: string | null;
  failure_stage?: string | null;
};
export type VoiceState = { active_id: string | null; runs: VoiceRecord[] };
type FileView = {
  available: boolean;
  error?: string;
  length_bytes?: number;
  sha256?: string;
  manifest?: {
    artifact_id: string;
    format: string;
    source_artifact_id?: string | null;
  };
  pcm?: {
    sample_count: number;
    duration_s: number;
    signal_warning: string | null;
    waveform: { min: number; max: number }[];
  } | null;
};
type Stage = {
  name: string;
  job_id: string | null;
  status: string;
  error: string | null;
  result: Record<string, unknown> | null;
  timing: {
    basis: string;
    role: string;
    device_id: string;
    boot_id: string;
    started_us: number | null;
    finished_us: number | null;
    duration_us: number | null;
    components_us: Record<string, number>;
  };
  host_created_at: string | null;
  host_finished_at: string | null;
};
type RadioView = {
  id: string;
  status: string;
  verification: {
    bytes_equal: boolean;
    length_bytes: number;
    sha256: string;
  } | null;
  accounting: {
    evidence_complete: boolean;
    data_attempts?: number;
    data_retries?: number;
    accepted_fragments?: number;
  } | null;
  summaries: Record<string, unknown>;
  rf_window_closed_at: string | null;
  error: string | null;
};
type Inspection = {
  record: VoiceRecord;
  files: Record<string, FileView>;
  stages: Stage[];
  radio: RadioView | null;
  comparisons: Record<string, { message_bytes: number; run: RadioView | null }>;
  encoded_integrity: { verified: boolean; basis: string };
  one_way_latency: { valid: boolean; value_us: number | null; reason: string };
};
const post = (body: unknown = {}): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
async function json(response: Response) {
  const value = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(value.detail)
      ? value.detail
          .map((item: { msg: string }) =>
            item.msg.replace(/^Value error, /, ""),
          )
          .join("; ")
      : value.detail;
    throw new Error(
      typeof detail === "string" ? detail : "Voice inspection is unavailable.",
    );
  }
  return value;
}
const labels: Record<string, string> = {
  capture: "Microphone capture",
  encode: "Sender encode",
  sender_decode_check: "Sender decode check",
  receiver_decode: "Receiver decode",
  playback: "Receiver playback",
  source: "Source PCM",
  encoded: "Sent Codec 2",
  recovered: "Recovered Codec 2",
  decoded: "Receiver PCM",
};
const n = (value: number | null | undefined) =>
  value == null ? "Unavailable" : value.toLocaleString();

function ListeningNotes({
  record,
  request,
  pending,
}: {
  record: VoiceRecord;
  request: Request;
  pending: boolean;
}) {
  const [heard, setHeard] = useState(record.listening.heard);
  const [notes, setNotes] = useState(record.listening.notes);
  useEffect(() => {
    setHeard(record.listening.heard);
    setNotes(record.listening.notes);
  }, [record.listening.heard, record.listening.notes]);
  return (
    <section
      className="voice-listening"
      aria-label="Receiver listening observation"
    >
      <h3>Physical listening</h3>
      <p>
        Driver completion and intelligible speech are separate findings. No
        physical qualification is inferred.
      </p>
      <label>
        Receiver speaker observation
        <select value={heard} onChange={(e) => setHeard(e.target.value)}>
          <option value="not_checked">Not checked</option>
          <option value="heard">Heard on receiver</option>
          <option value="not_heard">Not heard on receiver</option>
        </select>
      </label>
      <label>
        Voice listening notes
        <textarea
          maxLength={1000}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </label>
      <button
        className="button secondary"
        disabled={
          pending || record.status === "running" || !record.playback_completed
        }
        onClick={() =>
          request(
            `/api/voice/runs/${record.id}/listening`,
            post({ heard, notes }),
          )
        }
      >
        Save voice listening notes
      </button>
      <p>
        {record.listening.recorded_at
          ? `Saved ${new Date(record.listening.recorded_at).toLocaleString()}`
          : "No listening observation saved."}
      </p>
    </section>
  );
}

function ClipFile({
  file,
  kind,
  id,
}: {
  file: FileView;
  kind: string;
  id: string;
}) {
  const path = `/api/voice/runs/${id}/artifacts/${kind}`;
  return (
    <article className="voice-file" aria-label={labels[kind]}>
      <h3>{labels[kind]}</h3>
      {!file.available ? (
        <p>{file.error || "No verified file yet."}</p>
      ) : (
        <>
          <p>
            {n(file.length_bytes)} bytes
            {file.pcm
              ? ` · ${n(file.pcm.sample_count)} samples`
              : ` · ${n((file.length_bytes || 0) / 8)} frames`}
          </p>
          <code>Node artifact {file.manifest?.artifact_id}</code>
          {file.manifest?.source_artifact_id && (
            <code>Derived from {file.manifest.source_artifact_id}</code>
          )}
          <code>SHA-256 {file.sha256}</code>
          {file.pcm && (
            <>
              <VoiceWaveform
                bins={file.pcm.waveform}
                label={`${labels[kind]} waveform`}
              />
              <audio
                key={`${id}:${kind}`}
                controls
                preload="none"
                src={`${path}?as_wav=true`}
                aria-label={`${labels[kind]} laptop preview`}
              />
              {file.pcm.signal_warning && (
                <p className="voice-warning">{file.pcm.signal_warning}</p>
              )}
              <a href={`${path}?as_wav=true`} download={`${id}-${kind}.wav`}>
                Download WAV
              </a>
              <p>Laptop preview · {file.pcm.duration_s.toFixed(3)} seconds</p>
            </>
          )}
          <a href={path} download={`${id}-${kind}.bin`}>
            Download exact bytes
          </a>
        </>
      )}
    </article>
  );
}

export default function VoiceRuns({
  state = { active_id: null, runs: [] },
  nodes,
  referenceId,
  benchBusy,
  online,
  request,
  pending,
}: {
  state?: VoiceState;
  nodes: HardwareNode[];
  referenceId?: string;
  benchBusy: boolean;
  online: boolean;
  request: Request;
  pending: boolean;
}) {
  const [form, setForm] = useState({
    source: "reference",
    direction: "A_TO_B",
    sample_count: "24000",
    timeout_ms: "30000",
    comparisons: true,
    sf: "7",
    bandwidth: "125000",
    coding_rate: "5",
    power: "2",
    ack: "none",
    retries: "0",
  });
  const [selected, setSelected] = useState<string | null>(() =>
    sessionStorage.getItem("loralab.voice.selected"),
  );
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [error, setError] = useState("");
  const [readiness, setReadiness] = useState<{
    key: string;
    ready: boolean;
    blockers: string[];
    encoded_bytes?: number;
  } | null>(null);
  const update = (key: keyof typeof form, value: string | boolean) =>
    setForm((old) => ({ ...old, [key]: value }));
  const body = useMemo(
    () =>
      JSON.stringify({
        source: form.source,
        reference_id: form.source === "reference" ? referenceId || null : null,
        direction: form.direction,
        sample_count: Number(form.sample_count),
        timeout_ms: Number(form.timeout_ms),
        include_comparisons: form.comparisons,
        security: "aes128_gcm",
        radio: {
          frequency_hz: 915000000,
          spreading_factor: Number(form.sf),
          bandwidth_hz: Number(form.bandwidth),
          coding_rate_denominator: Number(form.coding_rate),
          tx_power_dbm: Number(form.power),
        },
        link: {
          fragment_payload_bytes: 160,
          ack_mode: form.ack,
          max_retries: form.ack === "none" ? 0 : Number(form.retries),
        },
      }),
    [form, referenceId],
  );
  const availability = JSON.stringify(
    nodes.map((node) => [
      node.id,
      node.connected,
      node.identity?.boot_id,
      node.identity?.capabilities,
      node.health?.state,
      node.health?.capability_availability,
    ]),
  );
  const readyKey = `${body}:${availability}:${benchBusy}:${online}`;
  useEffect(() => {
    const controller = new AbortController();
    setReadiness(null);
    const timer = setTimeout(() => {
      if (!online) {
        setReadiness({
          key: readyKey,
          ready: false,
          blockers: ["The backend is offline."],
        });
        return;
      }
      void fetch("/api/voice/preflight", {
        ...post(JSON.parse(body)),
        signal: controller.signal,
      })
        .then(json)
        .then((value) => {
          if (!controller.signal.aborted)
            setReadiness({ ...value, key: readyKey });
        })
        .catch((cause) => {
          if (!controller.signal.aborted)
            setReadiness({
              key: readyKey,
              ready: false,
              blockers: [String(cause.message || cause)],
            });
        });
    }, 150);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [body, readyKey, online]);
  useEffect(() => {
    if (state.active_id) setSelected(state.active_id);
  }, [state.active_id]);
  useEffect(() => {
    if (!selected && state.runs[0]) setSelected(state.runs[0].id);
  }, [selected, state.runs]);
  useEffect(() => {
    if (selected) sessionStorage.setItem("loralab.voice.selected", selected);
  }, [selected]);
  const brief = state.runs.find((record) => record.id === selected);
  const detailKey = JSON.stringify(brief);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setError("");
    setInspection(null);
    if (!selected || !online) return () => controller.abort();
    const load = () => {
      void fetch(`/api/voice/runs/${selected}/inspection`, {
        signal: controller.signal,
      })
        .then(json)
        .then((value) => {
          if (!controller.signal.aborted) {
            setInspection(value);
            if (value.record.status === "running")
              timer = setTimeout(load, 1000);
          }
        })
        .catch((cause) => {
          if (!controller.signal.aborted)
            setError(String(cause.message || cause));
        });
    };
    load();
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [selected, detailKey, online]);
  const record = inspection?.record;
  const canStart =
    online &&
    !benchBusy &&
    !pending &&
    readiness?.key === readyKey &&
    readiness.ready;
  return (
    <section className="panel voice-runs" aria-label="Secure voice workflows">
      <div className="radio-heading">
        <div>
          <h2>
            <AudioLines size={20} /> Node-to-node voice
          </h2>
          <p>
            Prepare a finite clip, send protected encoded bytes, then decode and
            play on the receiver.
          </p>
        </div>
        <span className="radio-mode">AES-128-GCM · Codec 2 / 3200</span>
      </div>
      <fieldset disabled={pending || benchBusy} className="voice-form">
        <legend>Clip and direction</legend>
        <div className="voice-fields">
          <label>
            Voice source
            <select
              value={form.source}
              onChange={(e) => update("source", e.target.value)}
            >
              <option value="reference">Selected reference WAV</option>
              <option value="microphone">Sender microphone</option>
            </select>
          </label>
          <label>
            Voice direction
            <select
              value={form.direction}
              onChange={(e) => update("direction", e.target.value)}
            >
              <option value="A_TO_B">A → B</option>
              <option value="B_TO_A">B → A</option>
            </select>
          </label>
          <label>
            Microphone duration
            <select
              disabled={form.source !== "microphone"}
              value={form.sample_count}
              onChange={(e) => update("sample_count", e.target.value)}
            >
              <option value="8000">1 second</option>
              <option value="16000">2 seconds</option>
              <option value="24000">3 seconds</option>
            </select>
          </label>
        </div>
        <p>
          {form.source === "reference"
            ? referenceId
              ? `Selected reference: ${referenceId}`
              : "Choose or upload a reference below."
            : "Recording starts after source preparation. Speak when the capture stage appears."}
        </p>
        <label className="voice-checkbox">
          <input
            type="checkbox"
            checked={form.comparisons}
            onChange={(e) => update("comparisons", e.target.checked)}
          />
          Also run equal encoded bytes and standard 64-byte data comparisons
        </label>
        <details className="radio-settings">
          <summary>Radio and reliability settings</summary>
          <div className="voice-fields">
            <label>
              Voice spreading factor
              <select
                value={form.sf}
                onChange={(e) => update("sf", e.target.value)}
              >
                {[7, 8, 9, 10, 11, 12].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <label>
              Voice bandwidth
              <select
                value={form.bandwidth}
                onChange={(e) => update("bandwidth", e.target.value)}
              >
                {[125000, 250000, 500000].map((v) => (
                  <option key={v} value={v}>
                    {v / 1000} kHz
                  </option>
                ))}
              </select>
            </label>
            <label>
              Voice coding rate
              <select
                value={form.coding_rate}
                onChange={(e) => update("coding_rate", e.target.value)}
              >
                {[5, 6, 7, 8].map((v) => (
                  <option key={v} value={v}>
                    4/{v}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Voice requested power (dBm)
              <input
                type="number"
                min="-9"
                max="22"
                value={form.power}
                onChange={(e) => update("power", e.target.value)}
              />
            </label>
            <label>
              Voice RF maximum (ms)
              <input
                type="number"
                min="1000"
                max="3600000"
                value={form.timeout_ms}
                onChange={(e) => update("timeout_ms", e.target.value)}
              />
            </label>
            <label>
              Voice acknowledgments
              <select
                value={form.ack}
                onChange={(e) => update("ack", e.target.value)}
              >
                <option value="none">No ACK</option>
                <option value="stop_wait">Stop and wait</option>
              </select>
            </label>
            <label>
              Voice retries
              <input
                type="number"
                min="0"
                max="2"
                disabled={form.ack === "none"}
                value={form.retries}
                onChange={(e) => update("retries", e.target.value)}
              />
            </label>
          </div>
          <p>
            915 MHz · 160-byte fragments. The backend checks the finite budget
            and exact current capabilities.
          </p>
        </details>
      </fieldset>
      <div className="radio-actions">
        <button
          className="button primary"
          disabled={!canStart}
          onClick={async () => {
            const saved = await request(
              "/api/voice/runs",
              post(JSON.parse(body)),
            );
            if (saved) setSelected(saved.id);
          }}
        >
          <Play size={15} />
          Start secure voice clip
        </button>
        {state.active_id && (
          <button
            className="button secondary"
            disabled={pending}
            onClick={() =>
              request(`/api/voice/runs/${state.active_id}/stop`, post())
            }
          >
            <Square size={15} />
            Stop voice workflow
          </button>
        )}
      </div>
      <div className="radio-readiness" role="status">
        {readiness?.key !== readyKey ? (
          "Checking voice readiness…"
        ) : readiness.ready ? (
          `Ready · ${n(readiness.encoded_bytes)} encoded bytes planned. Physical validation remains open.`
        ) : (
          <ul>
            {readiness.blockers.map((blocker, i) => (
              <li key={i}>{blocker}</li>
            ))}
          </ul>
        )}
      </div>
      <div className="radio-results">
        <h3>Saved voice clips</h3>
        <div className="radio-history">
          {state.runs.map((run) => (
            <button
              key={run.id}
              className={selected === run.id ? "selected" : ""}
              onClick={() => setSelected(run.id)}
            >
              <strong>
                {run.sender} → {run.receiver} · {run.request.source}
              </strong>
              <span>
                {run.status} · {run.stage}
              </span>
              <small>
                {run.id.slice(0, 8)} ·{" "}
                {new Date(run.created_at).toLocaleString()}
              </small>
            </button>
          ))}
        </div>
        {!state.runs.length && <p>No node-to-node voice job has run yet.</p>}
        {error && (
          <p role="alert" className="hw-error">
            {error}
          </p>
        )}
        {record && inspection && (
          <div className="voice-inspection" key={record.id}>
            <div className="radio-heading">
              <div>
                <h3>
                  Clip {record.id.slice(0, 8)} · {record.sender} →{" "}
                  {record.receiver}
                </h3>
                <code>{record.id}</code>
              </div>
              <span className="radio-mode">
                {record.status} · {record.stage}
              </span>
            </div>
            {record.error && (
              <p role="alert" className="hw-error">
                {record.failure_stage && `${record.failure_stage}: `}
                {record.error}
              </p>
            )}
            <div className="voice-findings" aria-label="Voice findings">
              <p>
                <strong>Encoded integrity</strong>
                <span>
                  {inspection.encoded_integrity.verified
                    ? "Exact bytes and saved hashes verified"
                    : "Not currently verified"}
                </span>
              </p>
              <p>
                <strong>Receiver playback</strong>
                <span>
                  {record.playback_completed
                    ? "Driver completed"
                    : "No completed playback"}
                </span>
              </p>
              <p>
                <strong>One-way latency</strong>
                <span>Unavailable — {inspection.one_way_latency.reason}</span>
              </p>
              <p>
                <strong>Resource cleanup</strong>
                <span>
                  {record.cleanup
                    ? record.cleanup.confirmed
                      ? "Confirmed"
                      : "Unconfirmed"
                    : "Pending"}
                </span>
              </p>
            </div>
            {record.delivery_verified &&
              !inspection.encoded_integrity.verified && (
                <p className="voice-warning">
                  Historical delivery was verified. A saved file is now absent
                  or changed; current file integrity is unavailable.
                </p>
              )}
            <p>
              {n(record.sample_count)} source samples ·{" "}
              {(record.sample_count / 8000).toFixed(3)} seconds · lossy decoded
              PCM has its own hash.
            </p>
            <div className="voice-files">
              {["source", "encoded", "recovered", "decoded"].map((kind) => (
                <ClipFile
                  key={kind}
                  file={inspection.files[kind]}
                  kind={kind}
                  id={record.id}
                />
              ))}
            </div>
            <h3>Stages and local clocks</h3>
            <p>
              Each node's monotonic timestamps belong to its recorded boot. Host
              timestamps are observations. Subtracting clocks from different
              nodes does not produce valid one-way latency.
            </p>
            <div className="voice-stages">
              {inspection.stages.map((stage) => (
                <article key={stage.name}>
                  <div className="radio-heading">
                    <strong>{labels[stage.name]}</strong>
                    <span>
                      {stage.status === "not_started" &&
                      stage.name === "capture" &&
                      record.request.source === "reference"
                        ? "Reference source"
                        : stage.status}
                    </span>
                  </div>
                  <p>
                    Node {stage.timing.role} · {stage.timing.boot_id}
                  </p>
                  <p>
                    {stage.timing.basis === "node_monotonic_us"
                      ? `Node duration ${n(stage.timing.duration_us)} µs${stage.timing.started_us != null && stage.timing.finished_us != null ? ` · start ${n(stage.timing.started_us)} → finish ${n(stage.timing.finished_us)} µs` : " · endpoints not recorded"}`
                      : "Node interval unavailable in this stage's recorded result."}
                  </p>
                  {Object.keys(stage.timing.components_us).length > 0 && (
                    <p>
                      {Object.entries(stage.timing.components_us)
                        .map(
                          ([key, value]) =>
                            `${key.replace("_us", "")} ${n(value)} µs`,
                        )
                        .join(" · ")}
                    </p>
                  )}
                  {stage.host_created_at && (
                    <p>
                      Host job:{" "}
                      {new Date(stage.host_created_at).toLocaleString()} →{" "}
                      {stage.host_finished_at
                        ? new Date(stage.host_finished_at).toLocaleString()
                        : "in progress"}
                    </p>
                  )}
                  {stage.error && <p className="hw-error">{stage.error}</p>}
                  {stage.result && (
                    <details>
                      <summary>Node result and counts</summary>
                      <pre>{JSON.stringify(stage.result, null, 2)}</pre>
                    </details>
                  )}
                </article>
              ))}
            </div>
            {inspection.radio && (
              <details className="voice-radio">
                <summary>
                  Protected transfer · {inspection.radio.status}
                </summary>
                <p>
                  RF window closed at host observation{" "}
                  {inspection.radio.rf_window_closed_at || "unconfirmed"}.
                  Readback and receiver decode follow this boundary.
                </p>
                <pre>{JSON.stringify(inspection.radio, null, 2)}</pre>
              </details>
            )}
            <h3>Known-data comparisons</h3>
            {!Object.keys(inspection.comparisons).length && (
              <p>
                {record.request.include_comparisons
                  ? "No comparison has started."
                  : "Comparisons were not requested."}
              </p>
            )}
            {Object.entries(inspection.comparisons).map(
              ([basis, comparison]) => (
                <div key={basis} className="voice-comparison">
                  <strong>
                    {basis === "equal_encoded_bytes"
                      ? "Equal encoded bytes"
                      : "Standard 64-byte workload"}
                  </strong>
                  <span>
                    {comparison.message_bytes} bytes ·{" "}
                    {comparison.run?.status || "Pending"} ·{" "}
                    {comparison.run?.verification?.bytes_equal
                      ? "Exact content verified"
                      : "No verified delivery"}
                  </span>
                  <p>{comparison.run?.error}</p>
                </div>
              ),
            )}
            <ListeningNotes
              record={record}
              request={request}
              pending={pending || !online}
            />
            <details>
              <summary>Cleanup observations</summary>
              <pre>{JSON.stringify(record.cleanup, null, 2)}</pre>
            </details>
          </div>
        )}
      </div>
      <VoiceReview
        request={request}
        disabled={pending || !online}
        candidates={state.runs.filter(
          (run) =>
            run.status === "completed" &&
            run.delivery_verified &&
            run.playback_completed,
        )}
      />
    </section>
  );
}
