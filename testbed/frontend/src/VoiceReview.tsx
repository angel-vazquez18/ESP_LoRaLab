import { useState } from "react";
import type { Request } from "./NodeArtifacts";
import VoiceWaveform, { type WaveBin } from "./VoiceWaveform";

type Candidate = {
  id: string;
  created_at: string;
  sender: string;
  receiver: string;
};
type Rating = {
  listener_id: string;
  clip_code: string;
  audio_sha256: string;
  score: number;
  notes: string;
};
type Clip = { index: number; code: string; wav: string; sha256: string };
type Stage = {
  source: string;
  direction: string;
  stage: string;
  role: string;
  n: number;
  minimum_us: number;
  median_us: number;
  p95_us: number;
  maximum_us: number;
  radio_and_link: {
    radio: {
      spreading_factor?: number;
      bandwidth_hz?: number;
      tx_power_dbm?: number;
    };
    link: { ack_mode?: string };
  };
  samples: { run_id: string; duration_us: number }[];
};
type Report = {
  presentation_order: Clip[];
  clip_key: Record<string, { waveform: WaveBin[] | null }>;
  stage_distributions: Stage[];
  exclusions: { run_id: string; reason: string }[];
  rubric: Record<string, string>;
};

const pretty = (text: string) => text.replaceAll("_", " ");
const ms = (value: number) =>
  (value / 1000).toLocaleString(undefined, {
    maximumFractionDigits: 3,
  });

export default function VoiceReview({
  candidates,
  request,
  disabled,
}: {
  candidates: Candidate[];
  request: Request;
  disabled: boolean;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [seed, setSeed] = useState(743);
  const [listener, setListener] = useState("");
  const [clipIndex, setClipIndex] = useState(0);
  const [score, setScore] = useState("");
  const [notes, setNotes] = useState("");
  const [ratings, setRatings] = useState<Rating[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  if (!candidates.length) return null;

  async function submit(rows: Rating[]) {
    setBusy(true);
    try {
      const result = (await request("/api/voice/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_ids: selected, seed, ratings: rows }),
      })) as Report | null;
      if (result) {
        setReport(result);
        setRatings(rows);
      }
    } finally {
      setBusy(false);
    }
  }

  const clip = report?.presentation_order[clipIndex];
  const currentRating = ratings.find(
    (row) =>
      row.listener_id === listener.trim() && row.clip_code === clip?.code,
  );

  function exportReport() {
    if (!report) return;
    const blob = new Blob([JSON.stringify(report, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const download = document.createElement("a");
    download.href = url;
    download.download = `voice-review-${seed}.json`;
    download.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <section className="voice-review" aria-label="Saved listening review">
      <h3>Saved listening review</h3>
      {!report && (
        <form
          className="physical-controls"
          onSubmit={(event) => {
            event.preventDefault();
            setClipIndex(0);
            void submit([]);
          }}
        >
          <fieldset
            className="voice-review-selection"
            disabled={disabled || busy}
          >
            <legend>Verified voice runs</legend>
            {candidates.map((run) => (
              <label key={run.id}>
                <input
                  type="checkbox"
                  checked={selected.includes(run.id)}
                  onChange={(event) =>
                    setSelected((current) =>
                      event.target.checked
                        ? [...current, run.id]
                        : current.filter((id) => id !== run.id),
                    )
                  }
                />
                {run.sender} → {run.receiver} ·{" "}
                {new Date(run.created_at).toLocaleString()} ·{" "}
                {run.id.slice(0, 8)}
              </label>
            ))}
          </fieldset>
          <label>
            Order seed
            <input
              required
              type="number"
              min="0"
              max="4294967295"
              disabled={disabled || busy}
              value={seed}
              onChange={(event) => setSeed(Number(event.target.value))}
            />
          </label>
          <button
            className="button secondary"
            disabled={disabled || busy || !selected.length}
          >
            Prepare review
          </button>
        </form>
      )}
      {report && (
        <>
          {report.exclusions.map((row) => (
            <p key={row.run_id}>
              {row.run_id.slice(0, 8)} · {row.reason}
            </p>
          ))}
          {clip && (
            <form
              className="voice-review-clip"
              onSubmit={(event) => {
                event.preventDefault();
                const next = {
                  listener_id: listener.trim(),
                  clip_code: clip.code,
                  audio_sha256: clip.sha256,
                  score: Number(score),
                  notes: notes.trim(),
                };
                void submit([
                  ...ratings.filter((row) => row !== currentRating),
                  next,
                ]);
              }}
            >
              <label>
                Clip
                <select
                  value={clipIndex}
                  disabled={busy}
                  onChange={(event) => {
                    setClipIndex(Number(event.target.value));
                    setScore("");
                    setNotes("");
                  }}
                >
                  {report.presentation_order.map((item, index) => (
                    <option key={item.code} value={index}>
                      {item.index} · {item.code}
                    </option>
                  ))}
                </select>
              </label>
              {report.clip_key[clip.code]?.waveform && (
                <VoiceWaveform
                  bins={report.clip_key[clip.code].waveform!}
                  label="Listening clip waveform"
                />
              )}
              <audio
                key={clip.code}
                controls
                preload="none"
                src={clip.wav}
                aria-label="Listening clip"
              />
              <div className="physical-controls">
                <label>
                  Listener ID
                  <input
                    required
                    maxLength={64}
                    value={listener}
                    onChange={(event) => setListener(event.target.value)}
                  />
                </label>
                <label>
                  Intelligibility
                  <select
                    required
                    value={score}
                    onChange={(event) => setScore(event.target.value)}
                  >
                    <option value="">Select a score</option>
                    {Object.entries(report.rubric).map(([value, label]) => (
                      <option key={value} value={value}>
                        {value} · {label}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className="button secondary"
                  disabled={disabled || busy || !listener.trim() || !score}
                >
                  Record score
                </button>
              </div>
              <label>
                Listening notes
                <textarea
                  maxLength={1000}
                  rows={2}
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                />
              </label>
              {currentRating && (
                <p>
                  Recorded score {currentRating.score}/5 for this listener and
                  clip.
                </p>
              )}
            </form>
          )}
          <p>
            {ratings.length} {ratings.length === 1 ? "score" : "scores"} in this
            review. Download the report to retain them.
          </p>
          <div className="physical-controls">
            <button
              type="button"
              className="button secondary"
              onClick={exportReport}
            >
              Download review JSON
            </button>
            <button
              type="button"
              className="button secondary"
              disabled={busy}
              onClick={() => {
                setReport(null);
                setRatings([]);
              }}
            >
              Start a new review
            </button>
          </div>
          {report.stage_distributions.length > 0 && (
            <details>
              <summary>Stage duration distributions</summary>
              {report.stage_distributions.map((entry) => {
                const { radio, link } = entry.radio_and_link;
                return (
                  <figure
                    key={JSON.stringify([
                      entry.source,
                      entry.direction,
                      entry.stage,
                      entry.radio_and_link,
                    ])}
                  >
                    <figcaption>
                      {pretty(entry.stage)} · Node {entry.role} ·{" "}
                      {entry.direction.replace("_TO_", " → ")} · {entry.source}{" "}
                      · SF{radio.spreading_factor} ·{" "}
                      {radio.bandwidth_hz && radio.bandwidth_hz / 1000} kHz ·{" "}
                      {radio.tx_power_dbm} dBm · {link.ack_mode}
                    </figcaption>
                    <div
                      className="voice-duration-plot"
                      aria-label="Individual durations by node-local milliseconds"
                    >
                      {entry.samples.map((sample) => (
                        <span
                          key={sample.run_id}
                          style={{
                            left: `${entry.maximum_us ? (100 * sample.duration_us) / entry.maximum_us : 0}%`,
                          }}
                          title={`${ms(sample.duration_us)} ms`}
                        />
                      ))}
                    </div>
                    <p>
                      n = {entry.n} · {ms(entry.minimum_us)}–
                      {ms(entry.maximum_us)} ms · median {ms(entry.median_us)}{" "}
                      ms · p95 {ms(entry.p95_us)} ms
                    </p>
                  </figure>
                );
              })}
            </details>
          )}
        </>
      )}
    </section>
  );
}
