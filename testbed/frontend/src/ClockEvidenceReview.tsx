import { useState } from "react";

type Observation = {
  frame_id: string;
  sender_role: "A" | "B";
  valid: boolean;
  reason: string | null;
  uncertainty_us?: number;
  tx_command_to_rx_done_us: number | null;
  tx_command_to_application_accept_us: number | null;
};

type Report = {
  calibration_id: string;
  input_sha256: string;
  eligible: boolean;
  reason: string | null;
  mapping: { residual_us: number; base_uncertainty_us: number | null } | null;
  observations: Observation[];
};

const rowsPerPage = 32;
const maxBytes = 1_048_576;
const reasonLabel = (reason: string) => reason.replaceAll("_", " ");
const duration = (value?: number | null) =>
  value == null
    ? "Unavailable"
    : `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} µs`;

export default function ClockEvidenceReview({ online }: { online: boolean }) {
  const [evidence, setEvidence] = useState<File | null>(null);
  const [result, setResult] = useState<{
    report: Report;
    response: string;
  } | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [page, setPage] = useState(0);

  async function evaluate() {
    if (!evidence) return;
    setPending(true);
    setError("");
    setResult(null);
    setPage(0);
    try {
      const response = await fetch("/api/procedures/clock/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: evidence,
      });
      const raw = await response.text();
      const report = JSON.parse(raw);
      if (!response.ok)
        throw new Error(
          report.detail ?? "Clock evidence could not be evaluated",
        );
      setResult({ report, response: raw });
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Clock assessment failed",
      );
    } finally {
      setPending(false);
    }
  }

  function download() {
    if (!result) return;
    // Use the response bytes to preserve exact large counters and rational coefficients.
    const url = URL.createObjectURL(
      new Blob([result.response], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `clock-${result.report.calibration_id}.json`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  const report = result?.report;
  const first = page * rowsPerPage;
  const total = report?.observations.length ?? 0;
  const valid = report?.observations.filter((row) => row.valid).length ?? 0;
  return (
    <section
      className="panel physical-check"
      aria-label="Offline clock evidence"
    >
      <h3>Review saved pulse evidence</h3>
      <form
        className="physical-controls"
        onSubmit={(event) => {
          event.preventDefault();
          void evaluate();
        }}
      >
        <label>
          Clock evidence JSON
          <input
            type="file"
            accept=".json,application/json"
            disabled={pending}
            onChange={(event) => {
              const file = event.target.files?.[0] ?? null;
              setResult(null);
              const oversized = file != null && file.size > maxBytes;
              setEvidence(oversized ? null : file);
              setError(oversized ? "Clock evidence exceeds 1 MiB" : "");
            }}
          />
        </label>
        <button
          className="button primary"
          disabled={!online || !evidence || pending}
        >
          {pending ? "Evaluating" : "Evaluate evidence"}
        </button>
      </form>
      {error && <p role="alert">{error}</p>}
      {report && (
        <div className="matrix-plan">
          <div role="status">
            <strong>
              {report.eligible ? "Eligible calibration" : "Timing unavailable"}
            </strong>
            {report.reason && <p>{reasonLabel(report.reason)}</p>}
            <p>
              {valid} of {total} frame observations valid
            </p>
          </div>
          <p>
            Input SHA-256 <code>{report.input_sha256}</code>
          </p>
          {report.mapping && (
            <p>
              Fit residual {duration(report.mapping.residual_us)}
              {" · "}Base uncertainty{" "}
              {duration(report.mapping.base_uncertainty_us)}
            </p>
          )}
          {total > 0 && (
            <table>
              <thead>
                <tr>
                  <th scope="col">Frame</th>
                  <th scope="col">Direction</th>
                  <th scope="col">Command to receive</th>
                  <th scope="col">Command to application</th>
                  <th scope="col">Uncertainty</th>
                  <th scope="col">Finding</th>
                </tr>
              </thead>
              <tbody>
                {report.observations
                  .slice(first, first + rowsPerPage)
                  .map((row, index) => (
                    <tr key={`${row.frame_id}-${first + index}`}>
                      <th scope="row">{row.frame_id}</th>
                      <td>{row.sender_role === "A" ? "A → B" : "B → A"}</td>
                      <td>{duration(row.tx_command_to_rx_done_us)}</td>
                      <td>
                        {duration(row.tx_command_to_application_accept_us)}
                      </td>
                      <td>{duration(row.uncertainty_us)}</td>
                      <td>{row.reason ? reasonLabel(row.reason) : "Valid"}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
          {total > rowsPerPage && (
            <div className="matrix-pagination">
              <button
                className="button secondary"
                disabled={page === 0}
                onClick={() => setPage(page - 1)}
              >
                Previous observations
              </button>
              <span>
                {first + 1}–{Math.min(first + rowsPerPage, total)} of {total}
              </span>
              <button
                className="button secondary"
                disabled={first + rowsPerPage >= total}
                onClick={() => setPage(page + 1)}
              >
                Next observations
              </button>
            </div>
          )}
          <button className="button secondary" onClick={download}>
            Download timing report
          </button>
        </div>
      )}
    </section>
  );
}
