import { useState } from "react";

export type MatrixOption = {
  groups: string[];
  kind: "serial" | "local" | "link" | "campaign" | "memory";
  choose_security: boolean;
};

export type MatrixRunSummary = {
  id: string;
  catalog_id: string;
  status: string;
  assessment: string;
  procedure_revision?: string | null;
  case_count?: number;
  completed_cases?: number;
};

type MatrixCase = {
  id: string;
  group: string;
  variant: string;
  repetition: number;
  role: string;
  message_bytes?: number;
  ready: boolean;
  blockers: string[];
  status?: string;
  assessment?: string;
  reason?: string;
};

type MatrixPlan = {
  sha256: string;
  case_count: number;
  ready_case_count: number;
  full_plan: boolean;
  cases: MatrixCase[];
};

type MatrixRun = MatrixPlan &
  MatrixRunSummary & { hardware_validated: boolean; reason: string | null };

type Props = {
  catalogId: string;
  option: MatrixOption;
  active: MatrixRunSummary | null;
  saved: MatrixRunSummary[];
  request: (path: string, options?: RequestInit) => Promise<unknown>;
  pending: boolean;
  online: boolean;
  benchBusy: boolean;
};

const perPage = 12;
const endpoint = "/api/procedures/matrix";
const runPath = (id: string) =>
  `/api/procedures/runs/${encodeURIComponent(id)}`;

function Cases({ rows, runId }: { rows: MatrixCase[]; runId?: string }) {
  const [page, setPage] = useState(0);
  const first = page * perPage;
  return (
    <>
      <ol className="matrix-cases" start={first + 1}>
        {rows.slice(first, first + perPage).map((row) => (
          <li key={row.id}>
            <strong>
              {row.group} · {row.variant.replaceAll("_", " ")} ·{" "}
              {row.role.replace("_TO_", " → ")} · repeat {row.repetition}
            </strong>
            <span>
              {row.status
                ? `${row.status} · ${row.assessment}`
                : row.ready
                  ? "Ready"
                  : "Blocked"}
              {row.message_bytes ? ` · ${row.message_bytes} bytes` : ""}
            </span>
            {(row.reason || row.blockers.length > 0) && (
              <span>{row.reason || row.blockers.join(" · ")}</span>
            )}
            {runId && (
              <a
                href={`${runPath(runId)}/evidence?case_id=${encodeURIComponent(row.id)}`}
              >
                Case evidence
              </a>
            )}
          </li>
        ))}
      </ol>
      {rows.length > perPage && (
        <div className="matrix-pagination">
          <button
            className="button secondary"
            disabled={page === 0}
            onClick={() => setPage(page - 1)}
          >
            Previous cases
          </button>
          <span>
            {first + 1}–{Math.min(first + perPage, rows.length)} of{" "}
            {rows.length}
          </span>
          <button
            className="button secondary"
            disabled={first + perPage >= rows.length}
            onClick={() => setPage(page + 1)}
          >
            Next cases
          </button>
        </div>
      )}
    </>
  );
}

export default function ProcedureMatrix({
  catalogId,
  option,
  active,
  saved,
  request,
  pending,
  online,
  benchBusy,
}: Props) {
  const [group, setGroup] = useState("");
  const [role, setRole] = useState("both");
  const [direction, setDirection] = useState("both");
  const [security, setSecurity] = useState("none");
  const [size, setSize] = useState("quick");
  const [preview, setPreview] = useState<{
    plan: MatrixPlan;
    body: string;
  } | null>(null);
  const [inspected, setInspected] = useState<MatrixRun | null>(null);
  const memory = option.kind === "memory";
  const local =
    option.kind === "serial" ||
    option.kind === "local" ||
    (memory && group === "C1");
  const selectDirection = option.kind === "link" || (memory && !local);
  const recent = saved.filter(
    (run) =>
      run.catalog_id === catalogId &&
      run.procedure_revision &&
      run.id !== active?.id,
  );

  async function previewCases() {
    const document = {
      catalog_id: catalogId,
      ...(group && { groups: [group] }),
      ...(local && role !== "both" && { roles: [role] }),
      ...(selectDirection &&
        direction !== "both" && { directions: [direction] }),
      ...(option.choose_security && { rf_security: security }),
      ...(size === "quick" && {
        repetitions: 1,
        ...(option.kind === "serial"
          ? { valid_cycles: 1 }
          : option.kind === "local"
            ? { diagnostic_iterations: 10 }
            : memory
              ? { memory_window_ms: 1000 }
              : { messages_per_case: 1 }),
      }),
    };
    const body = JSON.stringify(document);
    const plan = (await request(`${endpoint}/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    })) as MatrixPlan | null;
    setPreview(plan ? { plan, body } : null);
  }

  async function startCases() {
    if (!preview) return;
    const run = await request(
      `${endpoint}?expected_plan_sha256=${preview.plan.sha256}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: preview.body,
      },
    );
    if (run) {
      setPreview(null);
      setInspected(null);
    }
  }

  async function inspect(id: string) {
    const result = (await request(runPath(id))) as MatrixRun | null;
    if (result) setInspected(result);
  }

  return (
    <section
      className="panel physical-check matrix-panel"
      aria-label="Procedure matrix"
    >
      <h3>Procedure matrix</h3>
      <form
        className="physical-controls"
        onChange={() => setPreview(null)}
        onSubmit={(event) => {
          event.preventDefault();
          void previewCases();
        }}
      >
        <label>
          Case group
          <select
            value={group}
            disabled={pending}
            onChange={(event) => setGroup(event.target.value)}
          >
            <option value="">All groups</option>
            {option.groups.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          Workload
          <select
            value={size}
            disabled={pending}
            onChange={(event) => setSize(event.target.value)}
          >
            <option value="quick">Quick check</option>
            <option value="default">Procedure defaults</option>
          </select>
        </label>
        {local && (
          <label>
            Node
            <select
              value={role}
              disabled={pending}
              onChange={(event) => setRole(event.target.value)}
            >
              <option value="both">A and B</option>
              <option value="A">A</option>
              <option value="B">B</option>
            </select>
          </label>
        )}
        {selectDirection && (
          <label>
            Direction
            <select
              value={direction}
              disabled={pending}
              onChange={(event) => setDirection(event.target.value)}
            >
              <option value="both">Both directions</option>
              <option value="A_TO_B">A → B</option>
              <option value="B_TO_A">B → A</option>
            </select>
          </label>
        )}
        {option.choose_security && (
          <label>
            Security
            <select
              value={security}
              disabled={pending}
              onChange={(event) => setSecurity(event.target.value)}
            >
              <option value="none">Unprotected</option>
              <option value="aes128_gcm">AES-128-GCM</option>
            </select>
          </label>
        )}
        <button
          type="submit"
          className="button secondary"
          disabled={!online || pending}
        >
          Preview cases
        </button>
      </form>
      {preview && (
        <div className="matrix-plan">
          <p role="status">
            {preview.plan.ready_case_count} of {preview.plan.case_count} cases
            ready ·{" "}
            {preview.plan.full_plan ? "Procedure defaults" : "Selected subset"}
          </p>
          <Cases key={preview.plan.sha256} rows={preview.plan.cases} />
          <button
            className="button primary"
            disabled={
              !online ||
              pending ||
              benchBusy ||
              preview.plan.ready_case_count === 0
            }
            onClick={() => void startCases()}
          >
            Run ready cases
          </button>
        </div>
      )}
      {active?.catalog_id === catalogId && active.procedure_revision && (
        <div className="physical-history">
          <div>
            <strong role="status">Matrix running</strong>
            <span>
              {active.completed_cases} of {active.case_count} cases settled
            </span>
          </div>
          <button
            className="button secondary"
            disabled={!online || pending}
            onClick={() =>
              void request(
                `/api/procedures/stop?expected_run_id=${encodeURIComponent(active.id)}`,
                { method: "POST" },
              )
            }
          >
            Stop matrix
          </button>
        </div>
      )}
      {recent.length > 0 && (
        <>
          <h4>Saved runs</h4>
          {recent.map((run) => (
            <div key={run.id} className="physical-history">
              <div>
                <strong>{run.id.slice(0, 8)}</strong>
                <span>
                  {run.status} · {run.assessment}
                </span>
              </div>
              <button
                className="button secondary"
                disabled={pending}
                onClick={() => void inspect(run.id)}
              >
                Inspect cases
              </button>
              <a href={`${runPath(run.id)}/export/zip`}>Evidence ZIP</a>
            </div>
          ))}
        </>
      )}
      {inspected && (
        <div className="matrix-plan">
          <h4>Cases from {inspected.id.slice(0, 8)}</h4>
          {inspected.reason && <p>{inspected.reason}</p>}
          <p>
            Physical qualification{" "}
            {inspected.hardware_validated ? "recorded" : "pending"}
          </p>
          <Cases
            key={inspected.id}
            rows={inspected.cases}
            runId={inspected.id}
          />
        </div>
      )}
    </section>
  );
}
