import { useEffect, useMemo, useRef, useState } from "react";

type Point = {
  basis: "isolated_frame" | "sender_completion";
  direction: "A_TO_B" | "B_TO_A";
  configuration: string;
  security: "none" | "aes128_gcm";
  predicted_us: number;
  measured_us: number;
  residual_us: number;
};

export type ModelComparisonData = {
  points: Point[];
};

const WIDTH = 720;
const HEIGHT = 280;
const number = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });

function draw(canvas: HTMLCanvasElement, points: Point[], residual: boolean) {
  const context = canvas.getContext("2d");
  if (!context) return;
  context.clearRect(0, 0, WIDTH, HEIGHT);
  if (!points.length) return;

  const styles = getComputedStyle(canvas);
  const foreground = styles.getPropertyValue("--text").trim() || "#25334a";
  const grid = styles.getPropertyValue("--border").trim() || "#aab7c7";
  const left = 77;
  const right = WIDTH - 22;
  const top = 15;
  const bottom = HEIGHT - 51;
  const ordinate = (point: Point) =>
    (residual ? point.residual_us : point.measured_us) / 1000;
  const limitX = Math.max(
    1,
    ...points.map((point) => point.predicted_us / 1000),
  );
  const minimumY = residual ? Math.min(0, ...points.map(ordinate)) : 0;
  const maximumY = Math.max(
    1,
    ...(residual ? [] : [limitX]),
    ...points.map(ordinate),
  );
  const x = (value: number) => left + ((right - left) * value) / limitX;
  const y = (value: number) =>
    bottom - ((bottom - top) * (value - minimumY)) / (maximumY - minimumY);

  context.font = "12px system-ui";
  context.strokeStyle = grid;
  context.fillStyle = foreground;
  for (let tick = 0; tick <= 4; tick += 1) {
    const time = (limitX * tick) / 4;
    const vertical = minimumY + ((maximumY - minimumY) * tick) / 4;
    context.beginPath();
    context.moveTo(x(time), top);
    context.lineTo(x(time), bottom);
    context.moveTo(left, y(vertical));
    context.lineTo(right, y(vertical));
    context.stroke();
    context.textAlign = "center";
    context.fillText(number.format(time), x(time), bottom + 17);
    context.textAlign = "right";
    context.fillText(number.format(vertical), left - 8, y(vertical) + 4);
  }

  context.beginPath();
  context.strokeStyle = foreground;
  context.setLineDash([5, 4]);
  context.moveTo(x(0), y(0));
  context.lineTo(x(limitX), y(residual ? 0 : limitX));
  context.stroke();
  context.setLineDash([]);

  for (const point of points) {
    context.fillStyle = point.direction === "A_TO_B" ? "#4a9df0" : "#ea9660";
    context.beginPath();
    context.arc(
      x(point.predicted_us / 1000),
      y(ordinate(point)),
      3,
      0,
      2 * Math.PI,
    );
    context.fill();
  }
  context.fillStyle = foreground;
  context.textAlign = "center";
  context.fillText("Predicted (ms)", (left + right) / 2, HEIGHT - 12);
  context.save();
  context.translate(15, (top + bottom) / 2);
  context.rotate(-Math.PI / 2);
  context.fillText(residual ? "Residual (ms)" : "Observed (ms)", 0, 0);
  context.restore();
}

export default function ModelComparison({
  data,
}: {
  data: ModelComparisonData;
}) {
  const bases = [...new Set(data.points.map((point) => point.basis))];
  const [basis, setBasis] = useState(bases[0]);
  const [view, setView] = useState("comparison");
  const [configuration, setConfiguration] = useState("");
  const [security, setSecurity] = useState("");
  const canvas = useRef<HTMLCanvasElement>(null);
  const cohort = useMemo(
    () => data.points.filter((point) => point.basis === basis),
    [data.points, basis],
  );
  const configurations = [
    ...new Set(cohort.map((point) => point.configuration)),
  ];
  const points = cohort.filter(
    (point) =>
      (!configuration || configuration === point.configuration) &&
      (!security || point.security === security),
  );
  const residual = view === "residual";
  const low = Math.min(...points.map((point) => point.residual_us)) / 1000;
  const high = Math.max(...points.map((point) => point.residual_us)) / 1000;
  const range =
    low === high
      ? number.format(low)
      : `${number.format(low)} to ${number.format(high)}`;

  useEffect(() => {
    if (canvas.current) draw(canvas.current, points, residual);
  }, [points, residual]);

  return (
    <section
      className="rf-sweep-comparison model-comparison"
      aria-label="Airtime model comparison"
    >
      <h4>Airtime model comparison</h4>
      <div className="physical-controls">
        <label>
          Observation
          <select
            value={basis}
            onChange={(event) => {
              setBasis(event.target.value as Point["basis"]);
              setConfiguration("");
              setSecurity("");
            }}
          >
            {bases.map((value) => (
              <option key={value} value={value}>
                {value === "isolated_frame"
                  ? "Isolated frame"
                  : "Message completion"}
              </option>
            ))}
          </select>
        </label>
        <label>
          Plot
          <select
            value={view}
            onChange={(event) => setView(event.target.value)}
          >
            <option value="comparison">Predicted and observed</option>
            <option value="residual">Residuals</option>
          </select>
        </label>
        <label>
          Configuration
          <select
            value={configuration}
            onChange={(event) => setConfiguration(event.target.value)}
          >
            <option value="">All configurations</option>
            {configurations.map((value) => (
              <option key={value} value={value}>
                {value.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </label>
        <label>
          Protection
          <select
            value={security}
            onChange={(event) => setSecurity(event.target.value)}
          >
            <option value="">All recorded profiles</option>
            <option value="none">Unprotected</option>
            <option value="aes128_gcm">AES-128-GCM</option>
          </select>
        </label>
      </div>
      <figure>
        <figcaption>
          {basis === "isolated_frame"
            ? "Observed TX command to completion includes radio and interrupt delay."
            : "Observed sender completion uses first TX through final TX or accepted ACK. The nominal model excludes drain."}
        </figcaption>
        {points.length > 0 ? (
          <>
            <canvas
              ref={canvas}
              width={WIDTH}
              height={HEIGHT}
              role="img"
              aria-label={
                residual
                  ? "Signed residuals by predicted duration"
                  : "Observed versus predicted duration"
              }
            />
            <p className="model-directions">
              <span>A → B</span>
              <span>B → A</span>
            </p>
            <p>
              {points.length}{" "}
              {points.length === 1 ? "observation" : "observations"} · residual{" "}
              {range} ms. Instrumented airtime agreement is pending.
            </p>
          </>
        ) : (
          <p>
            No observed values match the selected configuration and protection.
          </p>
        )}
      </figure>
    </section>
  );
}
