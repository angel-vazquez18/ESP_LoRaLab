import { useEffect, useState } from "react";
import { ArrowDownToLine, BarChart3 } from "lucide-react";
import type { Run } from "./main";
import "./campaigns.css";

type Comparison = {
  runs: Run[];
  differences: { field: string; values: unknown[] }[];
  warnings: string[];
};
const display = (value: unknown) =>
  value == null
    ? "Not recorded"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
const format = (value: number, metric: string) =>
  metric === "pdr"
    ? `${(value * 100).toFixed(1)}%`
    : `${value.toLocaleString(undefined, { maximumFractionDigits: 0 })} bit/s`;

export function ResultBars({ runs }: { runs: Run[] }) {
  const [metric, setMetric] = useState<"pdr" | "throughput_bps">("pdr");
  const max =
    metric === "pdr"
      ? 1
      : Math.max(1, ...runs.map((run) => run.metrics[metric] ?? 0));
  return (
    <div className="comparison-chart">
      <div className="split">
        <h3>Individual run measurements</h3>
        <select
          aria-label="Comparison metric"
          value={metric}
          onChange={(e) => setMetric(e.target.value as typeof metric)}
        >
          <option value="pdr">Packet delivery (%)</option>
          <option value="throughput_bps">Useful throughput (bit/s)</option>
        </select>
      </div>
      <p>
        Each bar is one run. Hover or focus for details; values also appear
        beside each bar.
      </p>
      <div
        className="result-bars"
        role="list"
        aria-label="Individual run measurements"
      >
        {runs.map((run) => {
          const value = run.metrics[metric];
          return (
            <div className="result-bar-row" role="listitem" key={run.id}>
              <div className="result-bar-label">
                <strong>{run.id.slice(0, 8)}</strong>
                <span>
                  {run.spec.direction.replaceAll("_", " ")} ·{" "}
                  {run.spec.payload_bytes} B
                  {run.repetition ? ` · rep ${run.repetition}` : ""}
                </span>
              </div>
              <div
                className="result-bar-track"
                tabIndex={0}
                aria-label={`${run.id.slice(0, 8)}: ${value == null ? "No data" : format(value, metric)}`}
                title={`${run.spec.name} · ${run.status}\n${run.metrics.timing_basis}`}
              >
                {value != null && (
                  <div
                    className="result-bar-fill"
                    style={{ width: `${Math.max(0, (value / max) * 100)}%` }}
                  />
                )}
              </div>
              <span className="mono">
                {value == null ? "No data" : format(value, metric)}
              </span>
            </div>
          );
        })}
      </div>
      {!runs.length && <p>No completed measurements yet.</p>}
      <p className="measurement-note">
        Historical records retain their original measurement basis and
        provenance.
      </p>
    </div>
  );
}

export default function RunComparison({ runs }: { runs: Run[] }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [error, setError] = useState("");
  const ids = selected.join(",");
  // Reload after a selected live run finishes, while keeping form state during telemetry updates.
  const revisions = selected
    .map((id) => runs.find((run) => run.id === id)?.finished_at ?? "")
    .join(",");
  useEffect(() => {
    const controller = new AbortController();
    setComparison(null);
    setError("");
    if (!ids) return () => controller.abort();
    void fetch("/api/analysis/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_ids: ids.split(",") }),
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Could not load comparison");
        const result = await response.json();
        if (!controller.signal.aborted) setComparison(result);
      })
      .catch((cause) => {
        if (!controller.signal.aborted) setError(String(cause));
      });
    return () => controller.abort();
  }, [ids, revisions]);
  const download = () => {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(comparison, null, 2)], {
        type: "application/json",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "run-comparison.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <section className="panel run-comparison">
      <div className="panel-heading">
        <div>
          <h2>
            <BarChart3 size={17} /> Compare results
          </h2>
          <p>
            Select up to four runs. Review settings before comparing
            measurements.
          </p>
        </div>
        {comparison && (
          <button className="button secondary" onClick={download}>
            <ArrowDownToLine size={14} /> JSON
          </button>
        )}
      </div>
      {!!selected.length && (
        <button
          className="button secondary comparison-clear"
          onClick={() => setSelected([])}
        >
          Clear {selected.length} selected
        </button>
      )}
      <div className="comparison-picker">
        {runs.map((run) => (
          <label key={run.id}>
            <input
              type="checkbox"
              checked={selected.includes(run.id)}
              disabled={!selected.includes(run.id) && selected.length >= 4}
              onChange={(e) =>
                setSelected((current) =>
                  e.target.checked
                    ? [...current, run.id]
                    : current.filter((id) => id !== run.id),
                )
              }
            />
            <span>
              <strong>{run.spec.name}</strong>
              <small>
                {run.id.slice(0, 8)} · {run.spec.direction.replaceAll("_", " ")}{" "}
                · {run.status}
              </small>
            </span>
          </label>
        ))}
        {!runs.length && <p>No runs match the current filters.</p>}
      </div>
      {error && (
        <p role="alert" className="comparison-warning">
          {error}
        </p>
      )}
      {!!selected.length && !comparison && !error && (
        <p className="comparison-warning">Loading recorded results…</p>
      )}
      {comparison && (
        <>
          <div className="comparison-warnings">
            {comparison.warnings.map((w) => (
              <p key={w}>{w}</p>
            ))}
          </div>
          <details className="comparison-differences" open>
            <summary>
              Configuration and provenance differences (
              {comparison.differences.length})
            </summary>
            {comparison.differences.length ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Field</th>
                      {comparison.runs.map((run) => (
                        <th key={run.id}>{run.id.slice(0, 8)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.differences.map((d) => (
                      <tr key={d.field}>
                        <td className="mono">{d.field}</td>
                        {d.values.map((value, i) => (
                          <td key={i}>{display(value)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p>All recorded settings and provenance match.</p>
            )}
          </details>
          <ResultBars runs={comparison.runs} />
        </>
      )}
    </section>
  );
}
