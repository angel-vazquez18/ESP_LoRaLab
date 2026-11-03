import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  Cable,
  Check,
  Cpu,
  HardDrive,
  Radio,
  RefreshCw,
  Unplug,
  X,
} from "lucide-react";
import "./hardware.css";

type Heap = {
  free_bytes: number;
  minimum_free_bytes: number;
  largest_free_bytes: number;
};
type Capability = Record<string, boolean | number | object>;
export type HardwareNode = {
  id: "A" | "B";
  connected: boolean;
  connection_state: string;
  port: string | null;
  last_seen_age_s: number | null;
  error: string | null;
  event_gaps: number;
  framing_errors: number;
  startup_records: number;
  identity: null | {
    device_id: string;
    boot_id: string;
    chip_model: string;
    board_model: string | null;
    firmware_version: string;
    firmware_build_id: string;
    idf_version: string;
    contract_version: string;
    capabilities: Capability;
  };
  health: null | {
    uptime_us: number;
    reset_cause: string;
    state: string;
    memory: { internal: Heap; psram: Heap | null; allocation_failures: number };
    telemetry_drops: number;
  };
  samples: (Heap & { uptime_us: number })[];
  diagnostics: { at: number; code: string; message: string }[];
};
type Port = {
  device: string;
  description: string;
  serial_number: string | null;
  vid: number | null;
};
type Request = (path: string, options?: RequestInit) => Promise<any>;
const post = (value: unknown) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(value),
});
const kb = (value: number | undefined) =>
  value == null ? "—" : `${(value / 1024).toFixed(1)} KiB`;
const uptime = (us: number | undefined) => {
  if (us == null) return "—";
  const s = Math.floor(us / 1e6);
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m ${s % 60}s`;
};
const resetCause = (raw: string | undefined) => {
  const reasons = [
    "Unknown",
    "Power on",
    "External reset",
    "Software reset",
    "Firmware exception",
    "Interrupt watchdog",
    "Task watchdog",
    "Watchdog",
    "Deep-sleep wake",
    "Brownout",
    "SDIO reset",
    "USB reset",
    "JTAG reset",
    "eFuse error",
    "Power glitch",
    "CPU lockup",
  ];
  const match = raw?.match(/^esp_reset_reason_(\d+)$/);
  return match ? (reasons[Number(match[1])] ?? raw) : (raw ?? "—");
};

function HeapChart({ node }: { node: HardwareNode | undefined }) {
  const points = node?.samples ?? [];
  if (points.length < 2)
    return (
      <div className="hw-chart-empty">
        <Activity size={24} />
        <strong>Waiting for live samples</strong>
        <p>Internal RAM history appears after connecting a node.</p>
      </div>
    );
  const low = Math.min(...points.map((p) => p.free_bytes)) * 0.98;
  const high = Math.max(...points.map((p) => p.free_bytes)) * 1.02;
  const start = points[0].uptime_us,
    duration = Math.max(1, points.at(-1)!.uptime_us - start);
  const x = (p: (typeof points)[number]) =>
    54 + ((p.uptime_us - start) / duration) * 568;
  const y = (p: (typeof points)[number]) =>
    155 - ((p.free_bytes - low) / Math.max(1, high - low)) * 120;
  return (
    <div className="hw-chart">
      <svg
        viewBox="0 0 650 200"
        role="img"
        aria-label={`Node ${node?.id} internal free memory over the last ${Math.round(duration / 1e6)} seconds`}
      >
        {[0, 1, 2].map((i) => (
          <g key={i}>
            <line x1="54" x2="622" y1={35 + i * 60} y2={35 + i * 60} />
            <text x="46" y={39 + i * 60} textAnchor="end">
              {((high - ((high - low) * i) / 2) / 1024).toFixed(0)}
            </text>
          </g>
        ))}
        <path
          d={`M${x(points[0])},155 ${points.map((p) => `L${x(p)},${y(p)}`).join(" ")} L${x(points.at(-1)!)},155 Z`}
          className="hw-chart-area"
        />
        <polyline points={points.map((p) => `${x(p)},${y(p)}`).join(" ")} />
        {points.map((p, i) => (
          <circle key={i} cx={x(p)} cy={y(p)} r="4">
            <title>
              {uptime(p.uptime_us)} · {kb(p.free_bytes)} free
            </title>
          </circle>
        ))}
        <text x="54" y="185">
          −{Math.round(duration / 1e6)}s
        </text>
        <text x="622" y="185" textAnchor="end">
          Latest sample
        </text>
      </svg>
      <span className="hw-chart-caption">
        Internal free heap · KiB · {points.length} measured samples · hover for
        values
      </span>
    </div>
  );
}

function Details({ node, close }: { node: HardwareNode; close: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  const identity = node.identity,
    health = node.health;
  const fields = [
    ["Device identity", identity?.device_id ?? "No device connected"],
    ["USB port", node.port ?? "—"],
    [
      "Chip / board",
      `${identity?.chip_model ?? "—"} / ${identity?.board_model ?? "Board model unverified"}`,
    ],
    ["Firmware", identity?.firmware_version ?? "—"],
    ["Build identity", identity?.firmware_build_id ?? "—"],
    ["ESP-IDF", identity?.idf_version ?? "—"],
    ["Contract", identity?.contract_version ?? "—"],
    ["Boot identity", identity?.boot_id ?? "—"],
    ["Uptime", uptime(health?.uptime_us)],
    ["Reset cause", resetCause(health?.reset_cause)],
    [
      "Internal free / boot minimum",
      `${kb(health?.memory.internal.free_bytes)} / ${kb(health?.memory.internal.minimum_free_bytes)}`,
    ],
    ["Largest internal block", kb(health?.memory.internal.largest_free_bytes)],
    ["PSRAM free", kb(health?.memory.psram?.free_bytes)],
    [
      "Telemetry drops / event gaps",
      `${health?.telemetry_drops ?? "—"} / ${node.event_gaps}`,
    ],
    ["Protocol framing faults", String(node.framing_errors)],
    ["Startup text records", String(node.startup_records)],
  ];
  return (
    <dialog
      ref={dialog}
      className="hw-drawer"
      onCancel={close}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="hw-drawer-heading">
        <div>
          <span className="eyebrow">PHYSICAL DEVICE</span>
          <h2>Node {node.id} details</h2>
        </div>
        <button
          className="icon-button"
          aria-label="Close node details"
          onClick={close}
        >
          <X size={20} />
        </button>
      </div>
      <dl className="hw-detail-list">
        {fields.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <h3>Advertised capabilities</h3>
      <div className="hw-capabilities">
        {Object.entries(identity?.capabilities ?? {})
          .filter(([, v]) => typeof v === "boolean")
          .map(([key, value]) => (
            <span key={key} className={value ? "supported" : ""}>
              {value && <Check size={12} />}
              {key.replaceAll("_", " ")}: {value ? "ready" : "unavailable"}
            </span>
          ))}
      </div>
      <h3>Session diagnostics</h3>
      <div className="hw-diagnostics">
        {node.diagnostics.length ? (
          node.diagnostics.map((d, i) => (
            <p key={i}>
              <strong>{d.code}</strong>
              {d.message}
            </p>
          ))
        ) : (
          <p>No session diagnostics.</p>
        )}
      </div>
    </dialog>
  );
}

export default function HardwareBench({
  nodes,
  pending,
  request,
}: {
  nodes: HardwareNode[];
  pending: boolean;
  request: Request;
}) {
  const [ports, setPorts] = useState<Port[]>([]);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [detail, setDetail] = useState<string | null>(null);
  const [chartRole, setChartRole] = useState("A");
  async function refreshPorts() {
    const result = await request("/api/ports");
    if (result) {
      setPorts(result.ports);
      setSelected((current) => ({
        ...current,
        A:
          current.A ||
          nodes[0]?.port ||
          result.ports.find((p: Port) => p.vid === 0x303a)?.device ||
          "",
      }));
    }
  }
  useEffect(() => {
    void refreshPorts();
  }, []);
  const connected = nodes.filter((n) => n.connected);
  const live = nodes.find((n) => n.id === chartRole);
  const focused = nodes.find((n) => n.id === detail);
  return (
    <div className="hw-workspace">
      <div className="page-heading">
        <div>
          <span className="eyebrow">LIVE HARDWARE WORKSPACE</span>
          <h1>Your bench, connected.</h1>
          <p>Inspect your ESP32, follow its health, and prepare the link.</p>
        </div>
        <button
          className="button secondary"
          onClick={refreshPorts}
          disabled={pending}
        >
          <RefreshCw size={15} />
          Refresh ports
        </button>
      </div>
      <div className="hw-topology">
        <div className="hw-host">
          <div className="hw-topology-icon">
            <Cable size={22} />
          </div>
          <strong>Local host</strong>
          <span>USB control & telemetry</span>
        </div>
        <div className="hw-topology-path">
          <span />
          <ArrowRight size={16} />
        </div>
        <div className="hw-topology-nodes">
          {nodes.map((n) => (
            <div
              key={n.id}
              className={
                n.connected ? "hw-topology-node live" : "hw-topology-node"
              }
            >
              <i />
              <strong>Node {n.id}</strong>
              <span>
                {n.connected ? n.identity?.chip_model : "Awaiting device"}
              </span>
            </div>
          ))}
        </div>
        <div className="hw-link-note">
          <Radio size={17} />
          <span>
            RF link awaits
            <br />
            two radio-enabled nodes
          </span>
        </div>
      </div>
      <div className="hw-summary">
        <span>
          <i className={connected.length ? "hw-dot live" : "hw-dot"} />
          <strong>{connected.length}</strong> physical node
          {connected.length === 1 ? "" : "s"} connected · second node optional
          for local checks
        </span>
        <span>
          Contract v2.0 <i>·</i> Live identity & health <i>·</i> Saved locally
        </span>
      </div>
      <div className="hw-node-grid">
        {nodes.map((node) => (
          <section
            className={`hw-node ${node.connected ? "is-connected" : ""}`}
            key={node.id}
          >
            <div className="hw-node-heading">
              <div className="hw-node-avatar">
                <Cpu size={25} />
              </div>
              <div>
                <h2>Node {node.id}</h2>
                <span>{node.identity?.chip_model ?? "Connect your ESP32"}</span>
              </div>
              <span className={`hw-state ${node.connection_state}`}>
                {node.connection_state}
              </span>
            </div>
            <div className="hw-port-row">
              <label>
                <span>USB serial port</span>
                <select
                  aria-label={`Node ${node.id} serial port`}
                  value={selected[node.id] ?? ""}
                  disabled={node.connected || pending}
                  onChange={(e) =>
                    setSelected((s) => ({ ...s, [node.id]: e.target.value }))
                  }
                >
                  <option value="">Select a device…</option>
                  {ports.map((p) => (
                    <option key={p.device} value={p.device}>
                      {p.device} · {p.description}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className={
                  node.connected ? "button secondary" : "button primary"
                }
                disabled={pending || (!node.connected && !selected[node.id])}
                onClick={() =>
                  request(
                    `/api/nodes/${node.id}/connection`,
                    post({ port: node.connected ? null : selected[node.id] }),
                  )
                }
              >
                {node.connected ? <Unplug size={15} /> : <Cable size={15} />}
                {node.connected ? "Disconnect" : "Connect"}
              </button>
            </div>
            {node.error && (
              <p className="hw-error" role="status">
                {node.error}
              </p>
            )}
            {node.identity ? (
              <>
                <div className="hw-identity">
                  <span className="mono">{node.identity.device_id}</span>
                  <span>Firmware {node.identity.firmware_version}</span>
                </div>
                <div className="hw-stats">
                  <div>
                    <span>Uptime</span>
                    <strong>{uptime(node.health?.uptime_us)}</strong>
                  </div>
                  <div>
                    <span>Internal free</span>
                    <strong>
                      {kb(node.health?.memory.internal.free_bytes)}
                    </strong>
                  </div>
                  <div>
                    <span>PSRAM free</span>
                    <strong>{kb(node.health?.memory.psram?.free_bytes)}</strong>
                  </div>
                </div>
                <div className="hw-node-bottom">
                  <span>
                    {node.connected
                      ? `Last health ${node.last_seen_age_s ?? "—"}s ago`
                      : "Last recorded values"}
                  </span>
                  <button
                    className="text-button"
                    onClick={() => setDetail(node.id)}
                  >
                    Inspect node <ArrowRight size={14} />
                  </button>
                </div>
              </>
            ) : (
              <div className="hw-empty-node">
                <Cpu size={25} />
                <strong>
                  {node.id === "A"
                    ? "Start with one board"
                    : "Room for your second node"}
                </strong>
                <p>
                  {node.id === "A"
                    ? "Connect compatible diagnostic firmware to see actual device data."
                    : "Your first ESP32 works independently. Add a second radio node for RF experiments."}
                </p>
              </div>
            )}
          </section>
        ))}
      </div>
      <div className="hw-bottom-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Live memory</h2>
              <p>Measured on the ESP32 · recent internal RAM history</p>
            </div>
            <div className="hw-chart-selector">
              {nodes.map((n) => (
                <button
                  key={n.id}
                  onClick={() => setChartRole(n.id)}
                  aria-pressed={chartRole === n.id}
                  className={chartRole === n.id ? "active" : ""}
                >
                  {n.id}
                </button>
              ))}
            </div>
          </div>
          <HeapChart node={live} />
        </section>
        <section className="panel hw-readiness">
          <div className="hw-readiness-icon">
            <HardDrive size={23} />
          </div>
          <span className="eyebrow">BENCH READINESS</span>
          <h2>Bring each stage online.</h2>
          <div>
            <Check size={15} />
            <span>
              USB identity & live health
              <strong>
                {connected.length
                  ? "Active on connected nodes"
                  : "Connect a device to begin"}
              </strong>
            </span>
          </div>
          <div>
            <Radio size={15} />
            <span>
              Known-data radio link
              <strong>Needs two nodes with RF firmware</strong>
            </span>
          </div>
          <div>
            <Activity size={15} />
            <span>
              Voice capture & playback
              <strong>Needs audio firmware and peripherals</strong>
            </span>
          </div>
          <p>
            Memory and identity are real measurements. Radio and audio
            capabilities come from each node's firmware.
          </p>
        </section>
      </div>
      {focused && <Details node={focused} close={() => setDetail(null)} />}
    </div>
  );
}
