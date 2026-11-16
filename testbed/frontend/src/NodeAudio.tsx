import { useState } from "react";
import { Mic, Play, Square } from "lucide-react";
import type { HardwareNode } from "./HardwareBench";
import type { ArtifactState, Request } from "./NodeArtifacts";
import "./node-audio.css";

type Listening = { heard: string; notes: string; recorded_at: string | null };
export type AudioOperation = {
  id: string;
  role: string;
  action: string;
  artifact_id: string;
  sample_count: number;
  status: string;
  stage: string;
  error: string | null;
  cleanup: string | null;
  transfer_id: string | null;
  identity: { device_id: string; boot_id: string };
  listening: Listening;
  node_result: {
    status: string;
    result: {
      samples_completed: number;
      samples_requested: number;
      dma_frames: number;
      underflows: number;
      overflows?: number;
      raw_left_nonzero_samples?: number;
      raw_right_nonzero_samples?: number;
    } | null;
  } | null;
  clip: {
    sample_count: number;
    raw_bytes: number;
    duration_s: number;
    pcm_sha256: string;
    peak_abs: number;
    rms: number;
    clipped_samples: number;
    all_zero: boolean;
    near_silence: boolean;
    signal_warning: string | null;
    waveform: { min: number; max: number }[];
  } | null;
};
export type AudioState = {
  active_id: string | null;
  operations: AudioOperation[];
};
const post = (value: unknown = {}) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(value),
});

function ListeningNotes({
  record,
  request,
  pending,
}: {
  record: AudioOperation;
  request: Request;
  pending: boolean;
}) {
  const [heard, setHeard] = useState(record.listening.heard);
  const [notes, setNotes] = useState(record.listening.notes);
  return (
    <details className="audio-listening">
      <summary>
        Operator listening: {record.listening.heard.replaceAll("_", " ")}
      </summary>
      <label>
        Speaker observation
        <select
          aria-label="Speaker observation"
          value={heard}
          onChange={(e) => setHeard(e.target.value)}
        >
          <option value="not_checked">Not checked</option>
          <option value="heard">Heard on the node</option>
          <option value="not_heard">Not heard on the node</option>
        </select>
      </label>
      <label>
        Listening notes
        <textarea
          aria-label="Listening notes"
          maxLength={1000}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </label>
      <button
        className="button secondary"
        disabled={pending || record.status === "running"}
        onClick={() =>
          request(
            `/api/audio/operations/${record.id}/listening`,
            post({ heard, notes }),
          )
        }
      >
        Save listening observation
      </button>
      <p>These notes are separate from the node driver result.</p>
    </details>
  );
}

export default function NodeAudio({
  node,
  audio,
  transfers,
  request,
  pending,
  hostError,
}: {
  node: HardwareNode;
  audio: AudioState;
  transfers: ArtifactState;
  request: Request;
  pending: boolean;
  hostError: string;
}) {
  const support = node.audio_support;
  const capture =
    node.connected && (support?.commands ?? []).includes("audio.capture");
  const playback =
    node.connected && (support?.commands ?? []).includes("audio.play");
  const busy =
    pending ||
    !!audio.active_id ||
    !!transfers.active_id ||
    !!node.active_operation ||
    node.health?.state !== "idle";
  const recent = audio.operations.filter((r) => r.role === node.id).slice(0, 5);
  const limits = support?.limits;
  return (
    <section className="node-audio" aria-label={`Node ${node.id} local audio`}>
      <div className="node-file-heading">
        <div>
          <h3>Local audio</h3>
          <p>Record, inspect, then play. One step runs at a time.</p>
        </div>
        <button
          className="button primary"
          disabled={!capture || busy}
          onClick={() =>
            request(
              `/api/nodes/${node.id}/audio/capture`,
              post({ sample_count: 24000 }),
            )
          }
        >
          <Mic size={14} />
          Capture 3 seconds
        </button>
      </div>
      {!capture && (
        <p role="status">
          {node.connected
            ? "Capture is unavailable in this firmware or board configuration."
            : "Connect a node with audio enabled. Saved findings remain below."}
        </p>
      )}
      {!playback && node.connected && (
        <p>
          Node playback is unavailable. Check that output wiring is present
          before enabling it.
        </p>
      )}
      {limits && (
        <p className="audio-configuration">
          Configured {limits.sample_rate_hz.toLocaleString()} Hz · 16-bit mono
          <br />
          Output volume{" "}
          {Math.round(
            ((100 * limits.output_gain_numerator) /
              limits.output_gain_denominator) *
              10,
          ) / 10}
          % · amplifier gain {limits.hardware_gain_db} dB
        </p>
      )}
      <p className="audio-evidence-note">
        Driver completion does not confirm heard sound. Sample clocks and the
        power rail still need physical checks.
      </p>
      {!recent.length && <p>No local audio findings saved for this role.</p>}
      {recent.map((record) => {
        const result = record.node_result?.result;
        const transfer = transfers.transfers.find(
          (t) => t.id === record.transfer_id,
        );
        const currentBoot = record.identity.boot_id === node.identity?.boot_id;
        return (
          <article key={record.id} className={`audio-record ${record.status}`}>
            <div className="node-file-heading">
              <strong>
                {record.action === "capture"
                  ? "Microphone capture"
                  : record.action === "play"
                    ? "Node playback"
                    : "PCM inspection"}
              </strong>
              <span>
                {record.status} · {record.stage.replaceAll("_", " ")}
              </span>
            </div>
            {record.status === "running" && (
              <div className="audio-running">
                <p role="status">
                  {record.stage === "retrieving"
                    ? `Retrieving and verifying ${transfer?.bytes_transferred.toLocaleString() ?? 0} bytes`
                    : record.stage === "capturing"
                      ? "Recording the finite clip after microphone startup"
                      : "Waiting for the node driver result"}
                </p>
                <button
                  className="button secondary"
                  onClick={() =>
                    request(`/api/audio/operations/${record.id}/stop`, post())
                  }
                >
                  <Square size={14} />
                  Stop audio
                </button>
              </div>
            )}
            {result && (
              <p>
                {result.samples_completed.toLocaleString()} /{" "}
                {result.samples_requested.toLocaleString()} samples · DMA frames{" "}
                {result.dma_frames.toLocaleString()} · missed deadlines{" "}
                {result.overflows ?? result.underflows}
              </p>
            )}
            {record.error && (
              <p role="alert" className="hw-error">
                {record.error}
              </p>
            )}
            {record.cleanup && <p>{record.cleanup}</p>}
            {record.clip && (
              <>
                <p>
                  {record.clip.duration_s.toFixed(3)} seconds ·{" "}
                  {record.clip.sample_count.toLocaleString()} samples ·{" "}
                  {record.clip.raw_bytes.toLocaleString()} verified bytes
                </p>
                {record.clip.signal_warning && (
                  <p role="alert" className="audio-signal-warning">
                    {record.clip.signal_warning}
                  </p>
                )}
                <svg
                  viewBox="0 0 360 90"
                  role="img"
                  aria-label="Captured PCM waveform"
                  className="audio-waveform"
                >
                  <line x1="0" y1="45" x2="360" y2="45" />
                  {record.clip.waveform.map((p, i) => (
                    <line
                      key={i}
                      className="audio-wave-bin"
                      x1={(i * 360) / record.clip!.waveform.length}
                      x2={(i * 360) / record.clip!.waveform.length}
                      y1={45 - p.max * 42}
                      y2={45 - p.min * 42}
                    />
                  ))}
                </svg>
                <p>
                  Peak {record.clip.peak_abs.toLocaleString()} · RMS{" "}
                  {record.clip.rms.toFixed(1)} · clipped samples{" "}
                  {record.clip.clipped_samples.toLocaleString()}
                </p>
                <code>PCM SHA-256 {record.clip.pcm_sha256}</code>
                <div className="audio-controls">
                  <button
                    className="button secondary"
                    disabled={!playback || busy || !currentBoot}
                    onClick={() =>
                      request(
                        `/api/nodes/${node.id}/audio/play`,
                        post({ artifact_id: record.artifact_id }),
                      )
                    }
                  >
                    <Play size={14} />
                    Play clip on node
                  </button>
                  <a
                    className="button secondary"
                    href={`/api/audio/operations/${record.id}/wav`}
                    download={`${record.id}.wav`}
                  >
                    Save verified WAV
                  </a>
                </div>
                <label className="audio-preview">
                  Listen on this computer
                  <audio
                    controls
                    preload="none"
                    src={`/api/audio/operations/${record.id}/wav`}
                  />
                </label>
                {!currentBoot && (
                  <p>
                    This clip belongs to an earlier boot. Its saved WAV is
                    retained; node playback needs a current node file.
                  </p>
                )}
              </>
            )}
            <ListeningNotes
              record={record}
              request={request}
              pending={pending}
            />
            <details>
              <summary>Audio identity and driver details</summary>
              <code>{record.id}</code>
              <code>Node file {record.artifact_id}</code>
              <code>
                {record.identity.device_id} · {record.identity.boot_id}
              </code>
              {result?.raw_left_nonzero_samples != null && (
                <p>
                  Raw input nonzero samples: left{" "}
                  {result.raw_left_nonzero_samples}, right{" "}
                  {result.raw_right_nonzero_samples}
                </p>
              )}
              <p>Hardware qualification remains incomplete.</p>
            </details>
          </article>
        );
      })}
      {hostError && (
        <p role="alert" className="hw-error">
          {hostError}
        </p>
      )}
    </section>
  );
}
