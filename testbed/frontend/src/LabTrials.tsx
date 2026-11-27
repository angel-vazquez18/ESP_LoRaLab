import { useState } from "react";
import { FlaskConical, Square } from "lucide-react";
import type { Request } from "./NodeArtifacts";
import "./radio-link.css";

const actions = {
  drop: ["Drop a fragment", "rx_before_reassembly"],
  drop_ack: ["Suppress an ACK", "tx_before_radio"],
  duplicate: ["Duplicate a fragment", "tx_schedule"],
  reverse_block: ["Reverse a fragment block", "tx_schedule"],
  xor_byte: ["Change a protected byte", "tx_after_protect"],
  replay: ["Repeat a protected frame", "tx_retained"],
} as const;

type Action = keyof typeof actions;
type Check = {
  code: string;
  outcome: "pass" | "fail" | "inconclusive";
  evidence: { role: string; name: string; event_seq: number }[];
};
type Trial = {
  id: string;
  created_at: string;
  status: string;
  stage: string;
  outcome: Check["outcome"];
  reason: string | null;
  request: {
    injection: { action: Action; fragment_index: number; injection_id: string };
  };
  children: Partial<Record<"before" | "fault" | "after", string>>;
  checks: Check[];
};
export type LabState = { active_id: string | null; trials: Trial[] };

const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

function injectionId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20),
  ].join("-");
}

function TrialDetails({ trial }: { trial: Trial }) {
  return (
    <div className="radio-record">
      <p className="radio-byte-result">
        {trial.status === "running"
          ? `Running ${trial.stage} case`
          : `${trial.status} · ${trial.outcome}`}
      </p>
      <p>
        {actions[trial.request.injection.action][0]} · Fragment{" "}
        {trial.request.injection.fragment_index}
      </p>
      <code>{trial.request.injection.injection_id}</code>
      {trial.reason && <p className="radio-error">{trial.reason}</p>}
      <div className="radio-actions">
        {Object.entries(trial.children).map(([stage, id]) => (
          <a key={stage} href={`/api/radio/runs/${id}/export`}>
            {stage} evidence bundle
          </a>
        ))}
      </div>
      {trial.checks.length > 0 && (
        <ul className="lab-checks">
          {trial.checks.map((check) => (
            <li key={check.code}>
              <strong>{check.outcome}</strong> ·{" "}
              {check.code.replaceAll("_", " ")}
              {check.evidence.length > 0 && trial.children.fault && (
                <details>
                  <summary>Evidence records</summary>
                  <ul>
                    {check.evidence.map((record) => (
                      <li key={`${record.role}-${record.event_seq}`}>
                        Node {record.role} · {record.name} · Event{" "}
                        {record.event_seq}
                      </li>
                    ))}
                  </ul>
                  <a
                    href={`/api/radio/runs/${trial.children.fault}/content/wire`}
                  >
                    Download fault records
                  </a>
                </details>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function LabTrials({
  state,
  online,
  benchBusy,
  pending,
  request,
}: {
  state?: LabState;
  online: boolean;
  benchBusy: boolean;
  pending: boolean;
  request: Request;
}) {
  const [action, setAction] = useState<Action>("drop");
  const [direction, setDirection] = useState("A_TO_B");
  const [form, setForm] = useState({
    length: "321",
    capacity: "160",
    fragment: "1",
    block: "2",
    byte: "40",
    retries: "1",
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [ready, setReady] = useState<{
    key: string;
    body: object;
    ready: boolean;
    blockers: string[];
  } | null>(null);
  const [error, setError] = useState("");
  const key = JSON.stringify([action, direction, form]);
  const active = state?.active_id;
  const history = state?.trials ?? [];
  const trial =
    history.find((entry) => entry.id === (active || selected)) ?? history[0];
  const disabled = !online || pending || benchBusy;
  const applicable = ["drop", "drop_ack"].includes(action);
  const currentReady = ready?.key === key ? ready : null;

  async function check() {
    const max_retries = applicable ? Number(form.retries) : 0;
    const body = {
      direction,
      security: "aes128_gcm",
      message_bytes: Number(form.length),
      link: {
        fragment_payload_bytes: Number(form.capacity),
        ack_mode: max_retries > 0 ? "stop_wait" : "none",
        max_retries,
      },
      injection: {
        injection_id: injectionId(),
        stage: actions[action][1],
        action,
        message_id: 1,
        fragment_index: Number(form.fragment),
        attempt_index: 1,
        byte_offset: action === "xor_byte" ? Number(form.byte) : null,
        xor_mask: action === "xor_byte" ? 1 : null,
        block_size: action === "reverse_block" ? Number(form.block) : null,
      },
    };
    setReady(null);
    setError("");
    const result = await request("/api/lab/preflight", post(body));
    if (result)
      setReady({ body, key, ready: result.ready, blockers: result.blockers });
    else setError("Preflight failed. Check the selected settings.");
  }

  async function start() {
    if (disabled || !currentReady?.ready) return;
    const result = await request("/api/lab/trials", post(currentReady.body));
    if (result?.id) {
      setSelected(result.id);
      setReady(null);
    }
  }

  function field(
    name: keyof typeof form,
    label: string,
    min: number,
    max: number,
  ) {
    return (
      <label>
        {label}
        <input
          type="number"
          min={min}
          max={max}
          required
          value={form[name]}
          onChange={(e) =>
            setForm((old) => ({ ...old, [name]: e.target.value }))
          }
        />
      </label>
    );
  }

  return (
    <section className="panel radio-link" aria-label="Controlled lab trial">
      <div className="radio-heading">
        <div>
          <h2>
            <FlaskConical size={20} /> Controlled lab trial
          </h2>
          <p>
            Run an intact message, apply one selected fault, then run an intact
            recovery. Both nodes need matching lab firmware.
          </p>
        </div>
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void check();
        }}
      >
        <fieldset disabled={disabled}>
          <div className="radio-fields">
            <label>
              Fault
              <select
                value={action}
                onChange={(e) => {
                  const next = e.target.value as Action;
                  setAction(next);
                  if (next === "drop_ack" && form.retries === "0") {
                    setForm((old) => ({ ...old, retries: "1" }));
                  }
                }}
              >
                {Object.entries(actions).map(([value, [label]]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Direction
              <select
                value={direction}
                onChange={(e) => setDirection(e.target.value)}
              >
                <option value="A_TO_B">A → B</option>
                <option value="B_TO_A">B → A</option>
              </select>
            </label>
            {field("length", "Message bytes", 1, 65536)}
            {field("capacity", "Fragment payload bytes", 1, 199)}
            {field("fragment", "Target fragment index (from 0)", 0, 4095)}
            {action === "reverse_block" &&
              field("block", "Frames to reverse", 2, 32)}
            {action === "xor_byte" &&
              field("byte", "Frame byte offset", 40, 254)}
            {applicable &&
              field(
                "retries",
                "Maximum retries",
                action === "drop_ack" ? 1 : 0,
                2,
              )}
          </div>
          <div className="radio-actions">
            <button type="submit">Check lab readiness</button>
            <button
              type="button"
              disabled={!currentReady?.ready}
              onClick={() => void start()}
            >
              Start trial
            </button>
          </div>
        </fieldset>
      </form>
      {active && (
        <div className="radio-actions">
          <button
            disabled={!online || pending}
            onClick={() =>
              void request(`/api/lab/trials/${active}/stop`, post({}))
            }
          >
            <Square size={14} /> Stop lab trial
          </button>
        </div>
      )}
      <div className="radio-readiness" aria-live="polite">
        {error}
        {currentReady &&
          (currentReady.ready ? (
            <p>Ready for the selected trial.</p>
          ) : (
            <ul>
              {currentReady.blockers.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          ))}
      </div>
      {trial && (
        <div className="radio-results">
          <div className="radio-history">
            {history.map((entry) => (
              <button
                key={entry.id}
                onClick={() => setSelected(entry.id)}
                className={entry.id === trial.id ? "selected" : ""}
              >
                {actions[entry.request.injection.action][0]}
                <small>{new Date(entry.created_at).toLocaleString()}</small>
              </button>
            ))}
          </div>
          <TrialDetails trial={trial} />
        </div>
      )}
    </section>
  );
}
