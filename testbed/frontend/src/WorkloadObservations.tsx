import { memo, useEffect, useState } from "react";
import { Activity, Download, RefreshCw } from "lucide-react";
import type { HardwareNode } from "./HardwareBench";
import "./workload-observations.css";

type Point = {
  index: number;
  elapsed_us: number;
  segment: number;
  stage?: string;
  values: Record<string, number | null>;
};
type Page<T> = {
  rows: T[];
  offset: number;
  total: number;
  next_offset: number | null;
};
type Series = {
  points: Point[];
  total_samples: number;
  plotted_samples: number;
  downsampled: boolean;
  gap_count: number;
  omitted_segments: number;
  bounds_us: [number, number] | null;
  clock: {
    basis: string;
    origin_us: number | null;
    unavailable_reason?: string | null;
  };
  gaps: Page<{ from_us: number; to_us: number; reasons: string[] }>;
};
type Heap = {
  sampled_min_free_bytes: number | null;
  boot_minimum_free_bytes: number | null;
  availability: string;
};
type MemoryView = Series & {
  summary: {
    assessment: string;
    reasons: string[];
    observed: { internal: Heap; psram: Heap };
    true_peak: { value: null; reason: string };
    reported_workload_minimum: {
      minimum: { internal_free_bytes: number; psram_free_bytes: number | null };
    } | null;
  };
  stages: Page<{
    stage: string;
    workload_id: string | null;
    sample_count: number;
    first_observed_us: number;
    last_observed_us: number;
  }>;
  buffers: Page<{
    name: string;
    generation: number;
    region: string;
    requested_bytes: number;
    first_retained_sample_us: number;
    last_retained_sample_us: number;
    first_absent_sample_us: number | null;
  }>;
};
type SourceView = Series & {
  policy: { queue_bytes_including_active_and_partial: number };
  summary: {
    execution_status: string;
    capacity: {
      finding: string;
      assessment: string;
      reasons: string[];
      cohort_source_rate_bps: number | null;
    };
    accounting: {
      status: string;
      totals: {
        produced_bytes: number;
        admitted_bytes: number;
        overflow_dropped_bytes: number;
        sent_bytes: number;
      };
    };
    intervals: {
      startup: { nominal_interval_us: number[] };
      production: { nominal_interval_us: number[]; produced_bytes: number };
      drain: { nominal_interval_us: number[] };
    };
    delivery: {
      assessment: string;
      reported_bytes: number | null;
      verified_bytes: number | null;
      rate_in_sender_window_bps: null;
      clock_reason: string;
      reasons: string[];
    };
  };
};
type View = {
  record: {
    id: string;
    created_at: string;
    origin: string;
    document_sha256: string;
    hardware_qualified: boolean;
  };
  memory: MemoryView | null;
  source: SourceView | null;
  export_path: string;
};
type Summary = { id: string; created_at: string; origin: string };
type Request = (path: string, options?: RequestInit) => Promise<any>;
type Line = { key: string; label: string; color: string; dashed?: boolean };
const post = (body: unknown = {}) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
const n = (value: number | null | undefined) =>
  value == null ? "Unavailable" : value.toLocaleString();
const bytes = (value: number | null | undefined) =>
  value == null ? "Unavailable" : `${n(value)} B`;
const seconds = (value: number) => `${(value / 1e6).toFixed(2)} s`;
async function read(path: string, signal?: AbortSignal) {
  const response = await fetch(path, { signal });
  const value = await response.json();
  if (!response.ok)
    throw new Error(
      typeof value.detail === "string"
        ? value.detail
        : "Observation view unavailable",
    );
  return value;
}
function Reasons({ values }: { values: string[] }) {
  return values.length ? (
    <ul className="obs-reasons">
      {values.map((reason, i) => (
        <li key={i}>{reason}</li>
      ))}
    </ul>
  ) : null;
}
function Stats({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="obs-stats">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
function Pager({
  page,
  change,
  busy,
  label,
}: {
  page: Page<unknown>;
  change: (offset: number) => void;
  busy: boolean;
  label: string;
}) {
  return (
    <div className="obs-pager">
      <span>
        {page.total
          ? `${page.offset + 1}–${page.offset + page.rows.length} of ${page.total}`
          : "No retained rows"}
      </span>
      <button
        className="button secondary"
        disabled={busy || page.offset === 0}
        aria-label={`Previous ${label}`}
        onClick={() => change(Math.max(0, page.offset - 32))}
      >
        Previous
      </button>
      <button
        className="button secondary"
        disabled={busy || page.next_offset == null}
        aria-label={`Next ${label}`}
        onClick={() => change(page.next_offset!)}
      >
        Next
      </button>
    </div>
  );
}
function Chart({
  view,
  lines,
  title,
  zero = false,
  max,
  phases,
}: {
  view: Series;
  lines: Line[];
  title: string;
  zero?: boolean;
  max?: number;
  phases?: [string, number, number][];
}) {
  const available = view.points.flatMap((point) =>
    lines
      .map((line) => point.values[line.key])
      .filter((value): value is number => value != null),
  );
  if (!available.length || !view.bounds_us)
    return (
      <div className="obs-empty" role="status">
        <strong>{title}</strong>
        <p>
          {view.clock.unavailable_reason ||
            "No coherent retained samples for this chart."}
        </p>
      </div>
    );
  const begin = Math.min(0, view.bounds_us[0]),
    end = Math.max(begin + 1, view.bounds_us[1]);
  const low = zero ? 0 : Math.min(...available) * 0.98;
  const high = Math.max(low + 1, max ?? Math.max(...available) * 1.02);
  const x = (time: number) => 64 + ((time - begin) / (end - begin)) * 660;
  const y = (value: number) => 204 - ((value - low) / (high - low)) * 164;
  function path(line: Line) {
    let result = "",
      pen = false,
      previous = -1;
    for (const point of view.points) {
      const value = point.values[line.key];
      if (value == null) {
        pen = false;
        continue;
      }
      result += `${pen && previous === point.segment ? "L" : "M"}${x(point.elapsed_us).toFixed(2)},${y(value).toFixed(2)} `;
      pen = true;
      previous = point.segment;
    }
    return result;
  }
  return (
    <figure className="obs-figure">
      <figcaption>{title}</figcaption>
      <div
        className="obs-plot-scroll"
        tabIndex={0}
        aria-label={`Scrollable ${title}`}
      >
        <svg
          className="obs-plot"
          viewBox="0 0 760 254"
          role="img"
          aria-label={`${title}, ${view.plotted_samples} retained observations displayed; ${view.gap_count} evidence gaps`}
        >
          {phases?.map(([label, start, finish], i) => (
            <rect
              key={label}
              className={`obs-phase obs-phase-${i}`}
              x={x(Math.min(end, Math.max(begin, start)))}
              y="32"
              width={Math.max(
                0,
                x(Math.min(end, finish)) -
                  x(Math.min(end, Math.max(begin, start))),
              )}
              height="172"
            >
              <title>
                {label}: {seconds(start)}–{seconds(finish)}
              </title>
            </rect>
          ))}
          {[0, 1, 2, 3].map((i) => {
            const value = low + ((high - low) * i) / 3;
            return (
              <g key={i}>
                <line
                  className="obs-grid"
                  x1="64"
                  x2="724"
                  y1={y(value)}
                  y2={y(value)}
                />
                <text x="56" y={y(value) + 4} textAnchor="end">
                  {(value / 1024).toFixed(1)}
                </text>
              </g>
            );
          })}
          {[0, 0.25, 0.5, 0.75, 1].map((i) => (
            <text
              key={i}
              x={x(begin + (end - begin) * i)}
              y="225"
              textAnchor="middle"
            >
              {((begin + (end - begin) * i) / 1e6).toFixed(1)}
            </text>
          ))}
          <text x="12" y="20">
            KiB
          </text>
          <text x="394" y="246" textAnchor="middle">
            Seconds in this observation clock
          </text>
          {lines.map((line) => (
            <path
              key={line.key}
              d={path(line)}
              fill="none"
              stroke={line.color}
              strokeWidth="2"
              strokeDasharray={line.dashed ? "5 4" : undefined}
            />
          ))}
          {view.points.map((point) => (
            <g key={`${point.segment}-${point.index}-${point.elapsed_us}`}>
              {lines.map((line) =>
                point.values[line.key] == null ? null : (
                  <circle
                    key={line.key}
                    cx={x(point.elapsed_us)}
                    cy={y(point.values[line.key]!)}
                    r="2.5"
                    fill={line.color}
                  >
                    <title>{`${seconds(point.elapsed_us)} · sample ${point.index}${point.stage ? ` · ${point.stage}` : ""} · ${line.label}: ${bytes(point.values[line.key])}`}</title>
                  </circle>
                ),
              )}
            </g>
          ))}
        </svg>
      </div>
      <div className="obs-legend">
        {lines.map((line) => (
          <span key={line.key}>
            <i style={{ background: line.color }} />
            {line.label}
          </span>
        ))}
      </div>
      <p>
        {view.plotted_samples} of {view.total_samples} retained samples shown.
        Lines stop at missing observations and null values.{" "}
        {view.downsampled &&
          "Display selection keeps actual bucket extrema; full export keeps every row."}
      </p>
      {view.omitted_segments > 0 && (
        <p className="obs-warning">
          {view.omitted_segments} short segments are outside the display
          selection. Export retains them.
        </p>
      )}
    </figure>
  );
}
function Memory({
  view,
  bufferOffset,
  stageOffset,
  busy,
}: {
  view: MemoryView;
  bufferOffset: (offset: number) => void;
  stageOffset: (offset: number) => void;
  busy: boolean;
}) {
  const [region, setRegion] = useState<"internal" | "psram">("internal");
  const heap = view.summary.observed[region];
  const workload =
    view.summary.reported_workload_minimum?.minimum[`${region}_free_bytes`];
  return (
    <div className="obs-detail">
      <div className="split">
        <h3>Sampled memory stages</h3>
        <select
          aria-label="Memory region"
          value={region}
          onChange={(event) =>
            setRegion(event.target.value as "internal" | "psram")
          }
        >
          <option value="internal">Internal RAM</option>
          <option value="psram">PSRAM</option>
        </select>
      </div>
      <p>
        {view.clock.basis}. {view.clock.unavailable_reason}
      </p>
      <Stats
        rows={[
          ["Boot minimum free", bytes(heap.boot_minimum_free_bytes)],
          ["Retained sample minimum", bytes(heap.sampled_min_free_bytes)],
          ["Reported workload minimum", bytes(workload)],
          ["True memory peak", "Unavailable"],
        ]}
      />
      <p className="obs-warning">{view.summary.true_peak.reason}</p>
      <span
        className={`badge ${view.summary.assessment === "consistent" ? "neutral" : "amber"}`}
      >
        {view.summary.assessment}
      </span>
      <Reasons values={view.summary.reasons} />
      {heap.availability === "unavailable" ? (
        <div className="obs-empty" role="status">
          Heap measurements for this region are unavailable. No free/block curve
          is inferred.
        </div>
      ) : (
        <>
          <Chart
            view={view}
            title={`${region === "internal" ? "Internal RAM" : "PSRAM"} free and largest block`}
            lines={[
              {
                key: `${region}_free_bytes`,
                label: "Free bytes",
                color: "#2978d8",
              },
              {
                key: `${region}_largest_free_bytes`,
                label: "Largest free block",
                color: "#9a6cce",
              },
              {
                key: `observation_${region}_minimum_bytes`,
                label: "Reported observation minimum",
                color: "#bf7326",
                dashed: true,
              },
            ]}
          />
        </>
      )}
      <Chart
        view={view}
        title="Known requested buffer bytes"
        zero
        lines={[
          {
            key: "known_internal_bytes",
            label: "Internal requested",
            color: "#2978d8",
          },
          {
            key: "known_psram_bytes",
            label: "PSRAM requested",
            color: "#398a68",
          },
          {
            key: "known_unknown_bytes",
            label: "Unknown region",
            color: "#b17935",
          },
        ]}
      />
      <p>
        Known buffers are a subset of allocations. Requested bytes exclude
        allocator overhead and untracked library/driver/task memory.
      </p>
      <h4>Observed stage intervals</h4>
      <div className="obs-table">
        <table>
          <thead>
            <tr>
              <th>Stage / workload</th>
              <th>Samples</th>
              <th>First observed (node µs)</th>
              <th>Last observed (node µs)</th>
            </tr>
          </thead>
          <tbody>
            {view.stages.rows.map((row, i) => (
              <tr key={i}>
                <td>
                  {row.stage}
                  <small>
                    {row.workload_id?.slice(0, 8) || "No active workload"}
                  </small>
                </td>
                <td>{n(row.sample_count)}</td>
                <td>{n(row.first_observed_us)}</td>
                <td>{n(row.last_observed_us)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pager
        page={view.stages}
        change={stageOffset}
        busy={busy}
        label="stages"
      />
      <h4>Observed buffer spans</h4>
      <p>
        First/last observations and later absence do not establish exact
        allocation or free times.
      </p>
      <div className="obs-table">
        <table>
          <thead>
            <tr>
              <th>Buffer / generation</th>
              <th>Region</th>
              <th>Requested</th>
              <th>First / last observed (node µs)</th>
              <th>First absent (node µs)</th>
            </tr>
          </thead>
          <tbody>
            {view.buffers.rows.map((row) => (
              <tr key={`${row.name}-${row.generation}`}>
                <td>
                  {row.name} / {row.generation}
                </td>
                <td>{row.region}</td>
                <td>{bytes(row.requested_bytes)}</td>
                <td>
                  {n(row.first_retained_sample_us)} /{" "}
                  {n(row.last_retained_sample_us)}
                </td>
                <td>{n(row.first_absent_sample_us)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pager
        page={view.buffers}
        change={bufferOffset}
        busy={busy}
        label="buffers"
      />
    </div>
  );
}
function Source({ view }: { view: SourceView }) {
  const result = view.summary,
    interval = result.intervals;
  const phases: [string, number, number][] = [
    ["Startup", ...interval.startup.nominal_interval_us] as [
      string,
      number,
      number,
    ],
    ["Assessment", ...interval.production.nominal_interval_us] as [
      string,
      number,
      number,
    ],
    ["Drain", ...interval.drain.nominal_interval_us] as [
      string,
      number,
      number,
    ],
  ];
  return (
    <div className="obs-detail">
      <h3>Fixed-rate source and consumer queue</h3>
      <p>{view.clock.basis}.</p>
      <div className="obs-phases">
        {phases.map(([name, begin, end], i) => (
          <span className={`obs-phase-label obs-phase-${i}`} key={name}>
            {name} [{begin / 1e6}, {end / 1e6}) s
          </span>
        ))}
      </div>
      <Stats
        rows={[
          ["Source execution outcome", result.execution_status],
          [
            "Capacity finding [3, 60) s",
            result.capacity.finding === "unsustainable"
              ? "Overload observed"
              : result.capacity.finding.replaceAll("_", " "),
          ],
          ["Assessment evidence", result.capacity.assessment],
          [
            "Retained cohort bytes [3, 60)",
            bytes(interval.production.produced_bytes),
          ],
        ]}
      />
      <Reasons values={result.capacity.reasons} />
      {result.capacity.finding === "unsustainable" && (
        <p className="obs-warning">
          Valid negative feasibility finding: this run's consumer did not keep
          up with the prescribed source. Consumer work includes radio and
          telemetry effects.
        </p>
      )}
      <Chart
        view={view}
        title="Queued payload, including active and partial messages"
        zero
        max={view.policy.queue_bytes_including_active_and_partial}
        phases={phases}
        lines={[
          { key: "occupancy_bytes", label: "Queue payload", color: "#2978d8" },
        ]}
      />
      <Chart
        view={view}
        title="Observed source byte counters"
        zero
        phases={phases}
        lines={[
          { key: "produced_bytes", label: "Produced", color: "#398a68" },
          { key: "admitted_bytes", label: "Admitted", color: "#2978d8" },
          {
            key: "overflow_dropped_bytes",
            label: "Whole-message overflow bytes",
            color: "#ce6547",
          },
          { key: "sent_bytes", label: "Sender completed", color: "#9a6cce" },
        ]}
      />
      <Stats
        rows={[
          [
            "Reported total produced",
            bytes(result.accounting.totals.produced_bytes),
          ],
          [
            "Reported total admitted",
            bytes(result.accounting.totals.admitted_bytes),
          ],
          [
            "Reported overflow bytes",
            bytes(result.accounting.totals.overflow_dropped_bytes),
          ],
          [
            "Sender completed bytes",
            bytes(result.accounting.totals.sent_bytes),
          ],
        ]}
      />
      <h4>Eventual receiver archive</h4>
      <Stats
        rows={[
          ["Reported delivery", bytes(result.delivery.reported_bytes)],
          ["Verified archive bytes", bytes(result.delivery.verified_bytes)],
          ["Delivery rate in sender window", "Unavailable"],
        ]}
      />
      <p>{result.delivery.clock_reason}</p>
      <Reasons values={result.delivery.reasons} />
    </div>
  );
}
const MemoryPlots = memo(Memory);
const SourcePlots = memo(Source);

export default function WorkloadObservations({
  nodes,
  request,
  pending,
}: {
  nodes: HardwareNode[];
  request: Request;
  pending: boolean;
}) {
  const [records, setRecords] = useState<Summary[]>([]),
    [selected, setSelected] = useState("");
  const [view, setView] = useState<View | null>(null),
    [error, setError] = useState("");
  const [loading, setLoading] = useState(false),
    [tab, setTab] = useState<"memory" | "source">("memory");
  const [bufferOffset, setBufferOffset] = useState(0),
    [stageOffset, setStageOffset] = useState(0);
  const [role, setRole] = useState("A"),
    [duration, setDuration] = useState(30000);
  const [observations, setObservations] = useState<
    Record<string, { id: string; started_us: number; connection_id: string }>
  >({});
  async function reload(preferred?: string) {
    try {
      const data = await read("/api/workload-assessments");
      setRecords(data.assessments);
      if (preferred) setSelected(preferred);
      else if (!selected && data.assessments.length)
        setSelected(data.assessments[0].id);
    } catch (cause) {
      setError(String(cause));
    }
  }
  useEffect(() => {
    void reload();
  }, []);
  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    read(
      `/api/workload-assessments/${selected}/plots?buffer_offset=${bufferOffset}&stage_offset=${stageOffset}`,
      controller.signal,
    )
      .then((value: View) => {
        setView(value);
        if (!value.memory) setTab("source");
        if (!value.source) setTab("memory");
      })
      .catch((cause) => {
        if (cause.name !== "AbortError") {
          setError(String(cause));
          setView(null);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [selected, bufferOffset, stageOffset]);
  const node = nodes.find((value) => value.id === role);
  const support = node?.memory_support;
  const last = node?.memory_observation?.last_sample;
  const accepted = observations[role];
  const acceptedCurrent =
    accepted && accepted.connection_id === node?.connection_id;
  const observation =
    last && (!acceptedCurrent || last.taken_us >= accepted.started_us)
      ? last.observation_id
      : acceptedCurrent
        ? accepted.id
        : undefined;
  async function observe(action: "start" | "save" | "stop") {
    try {
      setError("");
      if (action === "start") {
        const result = await request(
          `/api/nodes/${role}/memory-observation`,
          post({ duration_ms: duration }),
        );
        setObservations((value) => ({
          ...value,
          [role]: {
            id: result.observation_id,
            started_us: result.deadline_us - duration * 1000,
            connection_id: result.binding.connection_id,
          },
        }));
      } else {
        const result = await request(
          `/api/nodes/${role}/memory-observation/${observation}/collect?stop=${action === "stop"}`,
          post(),
        );
        setSelected(result.id);
        setBufferOffset(0);
        setStageOffset(0);
        setView(null);
        await reload(result.id);
      }
    } catch (cause) {
      setError(String(cause));
    }
  }
  const displayed = view?.record.id === selected ? view : null;
  const current = tab === "memory" ? displayed?.memory : displayed?.source;
  return (
    <section
      className="panel workload-observations"
      aria-label="Workload observations"
    >
      <div className="panel-heading">
        <div>
          <h2>
            <Activity size={19} /> Memory and source histories
          </h2>
          <p>
            Recorded samples, explicit gaps and independent full-resolution
            exports.
          </p>
        </div>
        <button
          className="button secondary"
          disabled={loading}
          onClick={() => void reload()}
        >
          <RefreshCw size={14} /> Refresh records
        </button>
      </div>
      <fieldset className="obs-controls">
        <legend>Finite node memory observation</legend>
        <label>
          Node
          <select
            aria-label="Observation node"
            value={role}
            onChange={(event) => setRole(event.target.value)}
          >
            <option>A</option>
            <option>B</option>
          </select>
        </label>
        <label>
          Duration (ms)
          <input
            aria-label="Observation duration"
            type="number"
            min="1000"
            max="300000"
            step="1000"
            value={duration}
            onChange={(event) => setDuration(Number(event.target.value))}
          />
        </label>
        <button
          className="button secondary"
          disabled={
            pending ||
            !support?.commands.includes("memory.start") ||
            duration < 1000 ||
            duration > 300000
          }
          onClick={() => void observe("start")}
        >
          Start observation
        </button>
        <button
          className="button secondary"
          disabled={
            pending ||
            !observation ||
            !support?.commands.includes("memory.status")
          }
          onClick={() => void observe("save")}
        >
          Save current samples
        </button>
        <button
          className="button secondary"
          disabled={
            pending ||
            !observation ||
            !support?.commands.includes("memory.stop")
          }
          onClick={() => void observe("stop")}
        >
          Stop and save
        </button>
      </fieldset>
      <p>
        {support?.commands.length
          ? `Node ${role}: ${node?.memory_observation?.fresh ? "fresh observation" : "no fresh sample"}${last ? ` · last sample ${last.sample_index}` : ""}. Saved records retain the full stored event history.`
          : `Node ${role} requires a connected, compatible memory observer.`}
      </p>
      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}
      <label className="obs-record-select">
        Saved observation
        <select
          aria-label="Saved observation"
          value={selected}
          onChange={(event) => {
            setSelected(event.target.value);
            setBufferOffset(0);
            setStageOffset(0);
            setView(null);
          }}
        >
          <option value="">Select a saved record</option>
          {records.map((record) => (
            <option key={record.id} value={record.id}>
              {new Date(record.created_at).toLocaleString()} ·{" "}
              {record.origin.replaceAll("_", " ")} · {record.id.slice(0, 8)}
            </option>
          ))}
        </select>
      </label>
      {!records.length && (
        <div className="obs-empty">
          <strong>No saved workload observations</strong>
          <p>
            Collect a compatible node observation or save a trace through the
            CLI. Missing data stays unavailable.
          </p>
        </div>
      )}
      {loading && <p role="status">Loading bounded plot data…</p>}
      {displayed && (
        <>
          <div className="obs-record-meta">
            <span className="badge amber">
              {displayed.record.origin.replaceAll("_", " ")}
            </span>
            <span>Physical qualification remains separate</span>
            <a className="button secondary" href={displayed.export_path}>
              <Download size={14} /> Export full evidence
            </a>
          </div>
          <p className="obs-hash" title={displayed.record.document_sha256}>
            Canonical document SHA-256: {displayed.record.document_sha256}
          </p>
          <div
            className="obs-tabs"
            role="tablist"
            aria-label="Observation view"
          >
            <button
              role="tab"
              aria-selected={tab === "memory"}
              disabled={!displayed.memory}
              onClick={() => setTab("memory")}
            >
              Memory stages
            </button>
            <button
              role="tab"
              aria-selected={tab === "source"}
              disabled={!displayed.source}
              onClick={() => setTab("source")}
            >
              Source and backlog
            </button>
          </div>
          {current && current.gap_count > 0 && (
            <div className="obs-gap-warning" role="status">
              <strong>
                {current.gap_count} observation gap
                {current.gap_count === 1 ? "" : "s"}
              </strong>
              <Reasons
                values={current.gaps.rows
                  .flatMap((gap) => gap.reasons)
                  .filter((value, index, all) => all.indexOf(value) === index)}
              />
              <p>
                Gaps remain disconnected in the chart. Full export includes all
                retained rows.
              </p>
            </div>
          )}
          {tab === "memory" && displayed.memory && (
            <MemoryPlots
              view={displayed.memory}
              bufferOffset={setBufferOffset}
              stageOffset={setStageOffset}
              busy={loading}
            />
          )}
          {tab === "source" && displayed.source && (
            <SourcePlots view={displayed.source} />
          )}
        </>
      )}
    </section>
  );
}
