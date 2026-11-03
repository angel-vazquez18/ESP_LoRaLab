import { useState } from "react";

type Preview = {
  plan_sha256: string;
  first_message_sha256: string;
  fragmentation: { fragments_per_message: number; total_useful_bytes: number };
  timing: { worst_case_duration_us: number; fits_selected_duration: boolean };
};
export default function KnownDataPreview({
  request,
  pending,
}: {
  request: (path: string, options?: RequestInit) => Promise<any>;
  pending: boolean;
}) {
  const [count, setCount] = useState(100);
  const [size, setSize] = useState(64);
  const [sf, setSf] = useState(7);
  const [result, setResult] = useState<Preview | null>(null);
  return (
    <section className="panel physical-check">
      <h2>Known-data budget calculator</h2>
      <p>
        Calculate fragmentation and airtime before connecting radios. These are
        predictions; no test is executed.
      </p>
      <div className="physical-controls">
        <label>
          Messages
          <input
            type="number"
            min="1"
            max="1000"
            value={count}
            onChange={(e) => {
              setCount(Number(e.target.value));
              setResult(null);
            }}
          />
        </label>
        <label>
          Message bytes
          <input
            type="number"
            min="1"
            max="65536"
            value={size}
            onChange={(e) => {
              setSize(Number(e.target.value));
              setResult(null);
            }}
          />
        </label>
        <label>
          Spreading factor
          <select
            value={sf}
            onChange={(e) => {
              setSf(Number(e.target.value));
              setResult(null);
            }}
          >
            {[7, 8, 9, 10, 11, 12].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <button
          className="button secondary"
          disabled={pending}
          onClick={async () => {
            setResult(
              await request("/api/experiments/v2/known-data/preview", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  spec: { message_count: count, message_bytes: size },
                  radio: { spreading_factor: sf },
                }),
              }),
            );
          }}
        >
          Calculate budget
        </button>
      </div>
      {result && (
        <div>
          <p>
            {result.fragmentation.fragments_per_message} fragments/message ·{" "}
            {result.fragmentation.total_useful_bytes.toLocaleString()} useful
            bytes
          </p>
          <p>
            Worst-case duration:{" "}
            {(result.timing.worst_case_duration_us / 1e6).toFixed(2)} seconds ·{" "}
            {result.timing.fits_selected_duration
              ? "Within selected budget"
              : "Increase duration or split the workload"}
          </p>
          <p className="mono artifact-hash">
            Plan SHA-256 {result.plan_sha256}
          </p>
        </div>
      )}
    </section>
  );
}
