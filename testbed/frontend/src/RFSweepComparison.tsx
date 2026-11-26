import { useState } from "react";

type Range = { count: number; min: number; median: number; max: number };
type Repetition = {
  case_id: string;
  repetition: number;
  values: Record<string, number | null>;
};
type Change = {
  before: number | null;
  after: number | null;
  delta: number | null;
};

export type SweepComparison = {
  factor: string;
  security: string;
  metrics: Record<string, string>;
  settings: {
    direction: string;
    value: number;
    repetitions: Repetition[];
    ranges: Record<string, Range | null>;
  }[];
  baselines: {
    direction: string;
    repetition: number;
    settings_matched: boolean;
    changes: Record<string, Change>;
  }[];
};

const formatValue = (value: number | null | undefined) =>
  value == null
    ? "—"
    : value.toLocaleString(undefined, { maximumFractionDigits: 2 });

function settingLabel(factor: string, value: number) {
  if (factor === "spreading_factor") return `SF${value}`;
  if (factor === "bandwidth_hz") return `${value / 1000} kHz`;
  if (factor === "coding_rate_denominator") return `4/${value}`;
  return `${value} dBm`;
}

export default function RFSweepComparison({ data }: { data: SweepComparison }) {
  const [metric, setMetric] = useState("delivery_percent");
  const measurements = data.settings.flatMap((row) => {
    const range = row.ranges[metric];
    return range ? [range.min, range.max] : [];
  });
  const minimum =
    metric === "delivery_percent"
      ? 0
      : Math.floor(Math.min(...measurements, Infinity));
  const maximum =
    metric === "delivery_percent"
      ? 100
      : Math.ceil(Math.max(...measurements, -Infinity));
  const position = (value: number) =>
    maximum > minimum ? ((value - minimum) * 100) / (maximum - minimum) : 50;
  const directions = [...new Set(data.settings.map((row) => row.direction))];

  return (
    <section className="rf-sweep-comparison" aria-label="RF comparison">
      <div className="rf-sweep-controls">
        <h4>RF comparison</h4>
        <label>
          Metric
          <select
            value={metric}
            onChange={(event) => setMetric(event.target.value)}
          >
            {Object.entries(data.metrics).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {directions.map((direction) => (
        <figure key={direction} className="rf-sweep-plot">
          <figcaption>
            {direction.replace("_TO_", " → ")} ·{" "}
            {data.security === "aes128_gcm" ? "AES-128-GCM" : "Unprotected"}
          </figcaption>
          {measurements.length > 0 && (
            <div className="rf-sweep-axis" aria-hidden="true">
              <span />
              <span>
                <span>{formatValue(minimum)}</span>
                <span>{formatValue(maximum)}</span>
              </span>
            </div>
          )}
          <ol>
            {data.settings
              .filter((row) => row.direction === direction)
              .map((row) => {
                const range = row.ranges[metric];
                return (
                  <li key={row.value} className="rf-sweep-row">
                    <strong>{settingLabel(data.factor, row.value)}</strong>
                    <div className="rf-sweep-track" aria-hidden="true">
                      {range && (
                        <>
                          <span
                            className="rf-sweep-range"
                            style={{
                              left: `${position(range.min)}%`,
                              width: `${position(range.max) - position(range.min)}%`,
                            }}
                          />
                          {row.repetitions.map((trial) => {
                            const value = trial.values[metric];
                            return value == null ? null : (
                              <span
                                key={trial.case_id}
                                className="rf-sweep-point"
                                style={{ left: `${position(value)}%` }}
                                title={`Repetition ${trial.repetition} · ${formatValue(value)}`}
                              />
                            );
                          })}
                        </>
                      )}
                    </div>
                    <span>
                      {range
                        ? `Median ${formatValue(range.median)} · ${formatValue(range.min)}–${formatValue(range.max)} · ${range.count}/${row.repetitions.length} repeats`
                        : `0/${row.repetitions.length} repeats with this measurement`}
                    </span>
                  </li>
                );
              })}
          </ol>
        </figure>
      ))}
      {data.baselines.length > 0 && (
        <details>
          <summary>Before and after baselines</summary>
          <table>
            <thead>
              <tr>
                <th>Direction</th>
                <th>Repeat</th>
                <th>Before</th>
                <th>After</th>
                <th>Change</th>
              </tr>
            </thead>
            <tbody>
              {data.baselines.map((pair) => {
                const change = pair.changes[metric];
                return (
                  <tr key={`${pair.direction}-${pair.repetition}`}>
                    <td>{pair.direction.replace("_TO_", " → ")}</td>
                    <td>{pair.repetition}</td>
                    <td>{formatValue(change?.before)}</td>
                    <td>{formatValue(change?.after)}</td>
                    <td>
                      {pair.settings_matched
                        ? formatValue(change?.delta)
                        : "Pair unavailable"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </details>
      )}
    </section>
  );
}
