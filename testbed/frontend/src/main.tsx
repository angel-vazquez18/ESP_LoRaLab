import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  AudioLines,
  BarChart3,
  Check,
  ChevronRight,
  CircleHelp,
  Cpu,
  FlaskConical,
  Layers,
  Moon,
  Radio,
  Square,
  Sun,
  Upload,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import "./styles.css";
import "./theme.css";
import "./physical.css";
import { useTheme } from "./theme";
import HardwareBench from "./HardwareBench";
import type { HardwareNode } from "./HardwareBench";
import KnownDataPreview from "./KnownDataPreview";
import RunComparison from "./RunComparison";

type View = "bench" | "experiments" | "campaigns" | "voice" | "results";
type Metrics = {
  sent: number;
  received: number;
  missing: number;
  duplicates: number;
  useful_bytes: number;
  pdr: number | null;
  throughput_bps: number | null;
  rssi_dbm: number | null;
  snr_db: number | null;
  timing_basis: string;
};
type Sample = Metrics & { elapsed_s: number };
export type Run = {
  id: string;
  created_at: string;
  finished_at: string | null;
  mode: string;
  status: string;
  assessment: string;
  campaign_id?: string;
  repetition?: number;
  reason: string | null;
  metrics: Metrics;
  samples: Sample[];
  spec: {
    name: string;
    catalog_id: string;
    direction: string;
    packet_count: number;
    payload_bytes: number;
    radio: Record<string, number>;
  };
  applied_settings: Record<string, unknown>;
};
type Reference = {
  id: string;
  name: string;
  duration_s: number;
  raw_bytes: number;
  peaks: number[];
  sample_count: number;
  sha256: string;
};
type Preflight = {
  ready: boolean;
  roles: string[];
  required_nodes: number;
  blockers: string[];
  scope: string;
};
type Entry = {
  id: string;
  group: string;
  title: string;
  available: boolean;
  scope: string;
  required_nodes: number;
  node_requirement: string;
  preflight: Preflight;
};
type Procedure = {
  id: string;
  catalog_id: string;
  status: string;
  mode: string;
  assessment: string;
  created_at: string;
  scope?: string;
  finished_at: string | null;
  full_procedure_passed: boolean;
};
type Historical = {
  id: string;
  mode: string;
  status: string;
  created_at: string;
  assessment?: string;
};
type State = {
  version: string;
  mode: "hardware";
  hardware_nodes: HardwareNode[];
  catalog: Entry[];
  procedures: {
    active_run:
      (Procedure & { completed_cases: number; case_count: number }) | null;
    runs: Procedure[];
  };
  v2_execution: { runs: Historical[]; campaigns: Historical[] };
  runs: Run[];
  campaigns: Historical[];
  references: Reference[];
};
const empty: State = {
  version: "0.1.0",
  mode: "hardware",
  hardware_nodes: [],
  catalog: [],
  procedures: { active_run: null, runs: [] },
  v2_execution: { runs: [], campaigns: [] },
  runs: [],
  campaigns: [],
  references: [],
};
const navigation: { id: View; label: string; icon: LucideIcon }[] = [
  { id: "bench", label: "Bench overview", icon: Layers },
  { id: "experiments", label: "Experiments", icon: FlaskConical },
  { id: "campaigns", label: "Campaigns", icon: Activity },
  { id: "voice", label: "Voice workspace", icon: AudioLines },
  { id: "results", label: "Results & exports", icon: BarChart3 },
];
const number = (value: number | null | undefined, digits = 0) =>
  value == null
    ? "—"
    : value.toLocaleString(undefined, { maximumFractionDigits: digits });
function useHost() {
  const [state, setState] = useState<State>(empty);
  const [online, setOnline] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const refresh = useCallback(async () => {
    const response = await fetch("/api/state");
    if (!response.ok) throw new Error("Could not read the host state");
    setState(await response.json());
  }, []);
  useEffect(() => {
    let disposed = false;
    let socket: WebSocket | undefined;
    let timer: ReturnType<typeof setTimeout>;
    void refresh().catch(() =>
      setError("The backend is unavailable. Start it with lora-testbed serve."),
    );
    function connect() {
      if (disposed) return;
      socket = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/live`,
      );
      socket.onopen = () => {
        if (!disposed) setOnline(true);
      };
      socket.onmessage = (event) => {
        if (!disposed) setState(JSON.parse(event.data));
      };
      socket.onclose = () => {
        if (!disposed) {
          setOnline(false);
          timer = setTimeout(connect, 1500);
        }
      };
      socket.onerror = () => socket?.close();
    }
    connect();
    return () => {
      disposed = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, [refresh]);
  async function request(path: string, options: RequestInit = {}) {
    setPending(true);
    setError("");
    try {
      const response = await fetch(path, options);
      if (!response.ok) {
        const body = await response.json();
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : Array.isArray(body.detail)
              ? body.detail
                  .slice(0, 3)
                  .map((item: { msg: string }) =>
                    item.msg.replace(/^Value error, /, ""),
                  )
                  .join("; ")
              : "Check the experiment settings.",
        );
      }
      const result = await response.json();
      await refresh();
      return result;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The request failed.");
      return null;
    } finally {
      setPending(false);
    }
  }
  return {
    state,
    online,
    error,
    pending,
    request,
    clearError: () => setError(""),
  };
}
export type Host = ReturnType<typeof useHost>;
const jsonPost = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

function Status({ value }: { value: string }) {
  return (
    <span className={`status status-${value}`}>
      <i />
      {value.replaceAll("_", " ")}
    </span>
  );
}

function Heading({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="heading-actions">{children}</div>
    </div>
  );
}

function DiagnosticCheck({ host }: { host: Host }) {
  const [role, setRole] = useState("auto");
  const [cycles, setCycles] = useState(3);
  const roles =
    role === "auto" ? undefined : role === "both" ? ["A", "B"] : [role];
  const selected =
    roles ??
    host.state.catalog.find((e) => e.id === "IF-01")?.preflight.roles ??
    [];
  const ready =
    selected.length > 0 &&
    selected.every((r) => {
      const n = host.state.hardware_nodes.find((n) => n.id === r);
      return (
        n?.connected &&
        n.connection_state === "connected" &&
        n.health?.state === "idle"
      );
    });
  return (
    <section className="panel physical-check">
      <h2>IF-01 diagnostic check</h2>
      <p>
        Identity, ownership, status and advancing uptime on one node at a time.
        Full IF-01 framing, fault and recovery qualification remains open.
      </p>
      <div className="physical-controls">
        <label>
          Node selection
          <select
            aria-label="Diagnostic node selection"
            value={role}
            onChange={(e) => setRole(e.target.value)}
          >
            <option value="auto">Connected node automatically</option>
            <option value="A">Node A</option>
            <option value="B">Node B</option>
            <option value="both">A then B</option>
          </select>
        </label>
        <label>
          Status cycles
          <input
            aria-label="Status cycles"
            type="number"
            min="1"
            max="10"
            value={cycles}
            onChange={(e) => setCycles(Number(e.target.value))}
          />
        </label>
        <button
          className="button primary"
          disabled={
            !ready || host.pending || !!host.state.procedures.active_run
          }
          onClick={() =>
            host.request("/api/procedures/serial", jsonPost({ roles, cycles }))
          }
        >
          Start diagnostic check
        </button>
      </div>
      {!ready && (
        <p role="status">
          Connect the selected node with compatible diagnostic firmware. A
          second node is optional.
        </p>
      )}
    </section>
  );
}

function Experiments({ host }: { host: Host }) {
  const [selected, setSelected] = useState("IF-01");
  const [filter, setFilter] = useState("");
  const entry = host.state.catalog.find((e) => e.id === selected);
  return (
    <>
      <Heading
        eyebrow="PHYSICAL TEST PROCEDURES"
        title="Experiments"
        description="Local checks use one node. Link tests require two distinct physical nodes."
      />
      <label className="physical-search">
        Find a test
        <input
          aria-label="Find a test"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Name, ID or category"
        />
      </label>
      <div className="physical-experiments">
        <section
          className="panel physical-catalog"
          aria-label="Experiment catalog"
        >
          {host.state.catalog
            .filter((e) =>
              `${e.id} ${e.title} ${e.group}`
                .toLowerCase()
                .includes(filter.toLowerCase()),
            )
            .map((e) => (
              <button
                className={e.id === selected ? "selected" : ""}
                key={e.id}
                onClick={() => setSelected(e.id)}
              >
                <strong>
                  {e.id} · {e.title}
                </strong>
                <span>{e.node_requirement}</span>
                <small>
                  {e.preflight.ready
                    ? "Diagnostic check ready"
                    : e.available
                      ? "Connect a node"
                      : "Implementation pending"}
                </small>
              </button>
            ))}
        </section>
        <div>
          {entry && (
            <section className="panel physical-check">
              <span className="eyebrow">
                {entry.group} · {entry.id}
              </span>
              <h2>{entry.title}</h2>
              <p>
                <strong>{entry.node_requirement}</strong>
              </p>
              <p>{entry.scope}</p>
              {entry.preflight.blockers.length > 0 && (
                <ul>
                  {entry.preflight.blockers.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              )}
              {entry.id !== "IF-01" && (
                <button className="button secondary" disabled>
                  Physical runner unavailable
                </button>
              )}
            </section>
          )}
          {selected === "IF-01" && <DiagnosticCheck host={host} />}
          {selected === "IF-02" && (
            <KnownDataPreview request={host.request} pending={host.pending} />
          )}
        </div>
      </div>
    </>
  );
}

function History({
  rows,
  base,
  label,
}: {
  rows: Historical[];
  base: string;
  label: string;
}) {
  return (
    <section className="panel physical-check">
      <h2>{label}</h2>
      {rows.length === 0 ? (
        <p>No saved records.</p>
      ) : (
        rows.map((r) => (
          <div className="physical-history" key={r.id}>
            <div>
              <strong>{r.id.slice(0, 8)}</strong>
              <span>
                {r.mode} · {r.status} · assessment:{" "}
                {r.assessment ?? "not assessed"}
              </span>
            </div>
            <a href={`${base}/${r.id}`} target="_blank" rel="noreferrer">
              Details
            </a>
            {(["json", "csv", "jsonl", "zip"] as const)
              .filter(
                (f) =>
                  base.includes("procedures") ||
                  base.includes("v2") ||
                  f !== "zip",
              )
              .map((f) => (
                <a key={f} href={`${base}/${r.id}/export/${f}`}>
                  {f.toUpperCase()}
                </a>
              ))}
          </div>
        ))
      )}
    </section>
  );
}

function Results({ host }: { host: Host }) {
  return (
    <>
      <Heading
        eyebrow="RETAINED EVIDENCE"
        title="Results & exports"
        description="Execution outcome, assessment and physical qualification remain separate. Historical records retain their original provenance."
      />
      <History
        rows={host.state.procedures.runs}
        base="/api/procedures/runs"
        label="Diagnostic and historical procedure records"
      />
      <History
        rows={host.state.v2_execution.runs}
        base="/api/v2/runs"
        label="Historical v2 runs"
      />
      <History
        rows={host.state.runs}
        base="/api/runs"
        label="Historical legacy runs"
      />
      {host.state.runs.length > 0 && <RunComparison runs={host.state.runs} />}
    </>
  );
}

function Campaigns({ host }: { host: Host }) {
  return (
    <>
      <Heading
        eyebrow="CAMPAIGNS"
        title="Physical campaigns"
        description="Campaign execution requires a physical execution adapter and supporting firmware. Node requirements will follow the tests in each campaign."
      />
      <section className="panel physical-check">
        <h2>Execution unavailable</h2>
        <p>
          All 23 procedures remain in scope. Local tests can be qualified on
          each device separately; RF cases require both devices. Saved campaigns
          remain available below.
        </p>
      </section>
      {[
        { rows: host.state.campaigns, base: "/api/campaigns" },
        { rows: host.state.v2_execution.campaigns, base: "/api/v2/campaigns" },
      ].map(({ rows, base }) => (
        <section className="panel physical-check" key={base}>
          <h2>Saved {base.includes("v2") ? "v2" : "legacy"} campaigns</h2>
          {!rows.length && <p>No saved campaigns.</p>}
          {rows.map((r) => (
            <div className="physical-history" key={r.id}>
              <span>
                {r.id.slice(0, 8)} · {r.mode} · {r.status}
              </span>
              <a href={`${base}/${r.id}`}>Details</a>
              <a href={`${base}/${r.id}/export/zip`}>Evidence ZIP</a>
            </div>
          ))}
        </section>
      ))}
    </>
  );
}
function Waveform({ peaks }: { peaks: number[] }) {
  return (
    <svg
      className="waveform"
      viewBox="0 0 640 120"
      role="img"
      aria-label="Reference audio amplitude waveform"
    >
      <line x1="0" y1="60" x2="640" y2="60" stroke="var(--waveform-baseline)" />
      {peaks.map((peak, i) => (
        <line
          key={i}
          x1={(i / peaks.length) * 640 + 2}
          x2={(i / peaks.length) * 640 + 2}
          y1={60 - Math.max(1, peak * 50)}
          y2={60 + Math.max(1, peak * 50)}
          stroke="var(--waveform-line)"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      ))}
    </svg>
  );
}

function Voice({ host }: { host: Host }) {
  const { state, request, pending } = host;
  const [id, setId] = useState("");
  const reference =
    state.references.find((r) => r.id === id) ?? state.references[0];
  return (
    <>
      <Heading
        eyebrow="SHORT CLIPS. COMPLETE MEASUREMENTS."
        title="Voice workspace"
        description="Prepare repeatable references and follow the full node-to-node audio path."
      />
      <div className="voice-pipeline">
        {[
          "Capture",
          "Encode",
          "RF transfer",
          "Reassemble",
          "Decode & play",
        ].map((stage, i) => (
          <div key={stage}>
            <span className="stage-number">0{i + 1}</span>
            <strong>{stage}</strong>
            <span>Firmware support pending</span>
            {i < 4 && <ArrowRight size={15} />}
          </div>
        ))}
      </div>
      <div className="notice">
        <AudioLines size={20} />
        <div>
          <strong>Voice is in scope.</strong>
          <span>
            {" "}
            Reference preparation works now. Node capture, codec, playback and
            RF voice require firmware and physical validation. Local VOICE-01
            checks need one node; RF voice needs two.
          </span>
        </div>
      </div>
      <div className="workspace-grid voice-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Reference audio</h2>
              <p>8 kHz · 16-bit PCM · mono · up to 3 seconds</p>
            </div>
          </div>
          <label className={`upload-zone ${pending ? "disabled" : ""}`}>
            <span className="soft-icon">
              <Upload size={24} />
            </span>
            <strong>Bring a voice reference to the bench</strong>
            <span>Choose a WAV file to validate, save, and preview.</span>
            <span className="upload-button">
              Choose WAV file <ArrowUpRight size={14} />
            </span>
            <input
              type="file"
              accept=".wav,audio/wav"
              disabled={pending}
              aria-label="Upload reference WAV"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const saved = await request(
                  `/api/audio/references?name=${encodeURIComponent(file.name)}`,
                  {
                    method: "POST",
                    headers: { "Content-Type": "audio/wav" },
                    body: file,
                  },
                );
                if (saved) setId(saved.id);
                e.target.value = "";
              }}
            />
          </label>
          {reference && (
            <div className="audio-preview">
              <div className="split">
                <h3>{reference.name}</h3>
                <span className="badge green">VALIDATED REFERENCE</span>
              </div>
              <Waveform peaks={reference.peaks} />
              <audio
                key={reference.id}
                controls
                src={`/api/audio/references/${reference.id}/wav`}
              />
              <div className="audio-stats">
                <span>{number(reference.duration_s, 2)} sec</span>
                <span>{number(reference.sample_count)} samples</span>
                <span>{number(reference.raw_bytes)} PCM bytes</span>
              </div>
              <p className="mono artifact-hash">SHA-256 {reference.sha256}</p>
            </div>
          )}
        </section>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Reference library</h2>
              <p>Saved locally for repeatable comparisons.</p>
            </div>
            <span className="count">{state.references.length}</span>
          </div>
          {state.references.length ? (
            <div className="reference-list">
              {state.references.map((r) => (
                <button
                  key={r.id}
                  className={
                    r.id === reference?.id
                      ? "reference-item selected"
                      : "reference-item"
                  }
                  onClick={() => setId(r.id)}
                >
                  <AudioLines size={20} />
                  <span>
                    <strong>{r.name}</strong>
                    <small>
                      {number(r.duration_s, 2)}s · {number(r.raw_bytes)} bytes ·
                      PCM16
                    </small>
                  </span>
                  {r.id === reference?.id && <Check size={16} />}
                </button>
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <AudioLines size={28} />
              <strong>Your reference library starts here</strong>
              <p>Upload a clip to inspect its waveform and sample count.</p>
            </div>
          )}
          <div className="voice-baseline">
            <span className="eyebrow">CDR BASELINE</span>
            <h3>3 seconds, measured end to end.</h3>
            <p>
              24,000 samples · 48,000 raw bytes. Compression and protected
              fragment counts will use the actual codec output, not this raw
              buffer size.
            </p>
            <span className="badge neutral">
              CODEC 2 · MODE 3200 · INTEGRATION PENDING
            </span>
          </div>
        </section>
      </div>
    </>
  );
}

function App() {
  const host = useHost();
  const { theme, toggleTheme } = useTheme();
  const [view, setView] = useState<View>("bench");
  const navigate = (next: View) => {
    location.hash = next;
    setView(next);
    window.scrollTo(0, 0);
  };
  useEffect(() => {
    const read = () => {
      const id = location.hash.slice(1);
      if (navigation.some((n) => n.id === id)) setView(id as View);
    };
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);
  const active = host.state.procedures.active_run;
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#bench" onClick={() => navigate("bench")}>
          <div className="brand-mark">
            <Radio size={24} />
          </div>
          <span>
            LoRa<span className="brand-light">Lab</span>
            <small>COMMUNICATIONS TESTBED</small>
          </span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {navigation.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={view === id ? "nav-item active" : "nav-item"}
              onClick={() => navigate(id)}
            >
              <Icon size={19} />
              <span>{label}</span>
              {id === "experiments" && <small>23</small>}
            </button>
          ))}
        </nav>
        <div className="sidebar-project">
          <div className="project-icon">
            <Cpu size={18} />
          </div>
          <div>
            <strong>ESP-IDF nodes</strong>
            <span>One node locally · two for RF</span>
          </div>
        </div>
        <div className="sidebar-footer">
          <a href="/api/protocol/v2" target="_blank" rel="noreferrer">
            <CircleHelp size={17} />
            <span>Protocol & documentation</span>
            <ArrowUpRight size={13} />
          </a>
          <span className="version">
            LOCAL WORKSPACE <i /> v{host.state.version}
          </span>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <ChevronRight size={13} />
            <strong>Communications testbed</strong>
          </div>
          <div className="topbar-status">
            <button
              className="button secondary theme-toggle"
              aria-label="Dark mode"
              aria-pressed={theme === "dark"}
              onClick={toggleTheme}
            >
              {theme === "dark" ? <Moon size={15} /> : <Sun size={15} />}
              <span>{theme === "dark" ? "Dark" : "Light"}</span>
            </button>
            <span className={`live-indicator ${host.online ? "online" : ""}`}>
              <i />
              {host.online ? "Host connected" : "Reconnecting"}
            </span>
            <span className="badge neutral">Hardware bench</span>
          </div>
        </header>
        <main>
          {active && (
            <div className="notice" role="status">
              <span>
                Diagnostic check · {active.completed_cases} /{" "}
                {active.case_count} nodes · <Status value={active.status} />
              </span>
              <button
                className="button secondary"
                disabled={host.pending}
                onClick={() =>
                  host.request("/api/procedures/stop", jsonPost({}))
                }
              >
                <Square size={14} /> Stop and save evidence
              </button>
            </div>
          )}
          {host.error && (
            <div className="error-banner" role="alert">
              <span>{host.error}</span>
              <button
                className="icon-button"
                onClick={host.clearError}
                aria-label="Dismiss error"
              >
                <X size={16} />
              </button>
            </div>
          )}
          {view === "bench" && (
            <>
              <HardwareBench
                nodes={host.state.hardware_nodes}
                pending={host.pending || !!active}
                request={host.request}
                error={host.error}
              />
              <DiagnosticCheck host={host} />
            </>
          )}
          {view === "experiments" && <Experiments host={host} />}
          {view === "campaigns" && <Campaigns host={host} />}
          {view === "voice" && <Voice host={host} />}
          {view === "results" && <Results host={host} />}
          <footer className="main-footer">
            <span>LoRa-Based Encryption & Communications Testbed</span>
            <span>EN.525.743 · Fall 2026</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
