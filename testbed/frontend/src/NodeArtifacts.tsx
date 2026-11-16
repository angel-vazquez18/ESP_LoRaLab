import { useEffect, useRef, useState } from "react";
import { Download, RefreshCw, Square, Trash2, Upload } from "lucide-react";
import type { HardwareNode } from "./HardwareBench";
import "./node-artifacts.css";

export type ArtifactManifest = {
  artifact_id: string;
  kind: string;
  format: string;
  length_bytes: number;
  next_offset: number;
  state: string;
  in_use: boolean;
  sha256: string;
};
export type ArtifactTransfer = {
  id: string;
  role: string;
  direction: string;
  artifact_id: string;
  name: string;
  status: string;
  stage: string;
  bytes_total: number;
  bytes_transferred: number;
  verification_bytes: number;
  error: string | null;
  cleanup: string | null;
  expected_sha256: string | null;
  actual_sha256: string | null;
  identity: { device_id: string; boot_id: string };
  manifest: ArtifactManifest | null;
};
export type ArtifactState = {
  active_id: string | null;
  transfers: ArtifactTransfer[];
};
export type Request = (path: string, options?: RequestInit) => Promise<any>;
const post = (body: unknown = {}) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export default function NodeArtifacts({
  node,
  transfers,
  request,
  pending,
  hostError,
}: {
  node: HardwareNode;
  transfers: ArtifactState;
  request: Request;
  pending: boolean;
  hostError: string;
}) {
  const [files, setFiles] = useState<ArtifactManifest[]>([]);
  const [selected, setSelected] = useState<File | null>(null);
  const [format, setFormat] = useState("known_data");
  const [error, setError] = useState("");
  const generation = useRef(0);
  const [listing, setListing] = useState(false);
  const commands = node.artifact_support?.commands ?? [];
  const canList = node.connected && commands.includes("artifact.list");
  const canUpload = ["begin", "put", "commit", "list", "get", "delete"].every(
    (n) => commands.includes(`artifact.${n}`),
  );
  const busy =
    pending ||
    !!transfers.active_id ||
    !!node.active_operation ||
    node.health?.state !== "idle";
  const maxBytes = node.artifact_support?.limits?.max_artifact_bytes ?? 131072;
  const recent = transfers.transfers
    .filter((t) => t.role === node.id)
    .slice(0, 5);
  const running = recent.find((t) => t.id === transfers.active_id);
  const latest = recent[0];

  async function refresh() {
    const current = ++generation.current;
    setListing(true);
    try {
      const response = await fetch(`/api/nodes/${node.id}/artifacts`);
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail);
      if (generation.current === current) setFiles(value.artifacts);
    } catch (cause) {
      if (generation.current === current) setError(String(cause));
    } finally {
      if (generation.current === current) setListing(false);
    }
  }

  useEffect(() => {
    generation.current++;
    setFiles([]);
    setListing(false);
    setSelected(null);
    setError("");
  }, [node.id, node.identity?.boot_id]);
  useEffect(() => {
    if (
      canList &&
      !transfers.active_id &&
      !node.active_operation &&
      node.health?.state === "idle" &&
      !pending
    )
      void refresh();
  }, [
    node.id,
    node.identity?.boot_id,
    canList,
    transfers.active_id,
    node.active_operation?.operation_id,
    node.health?.state,
    latest?.id,
    latest?.status,
    pending,
  ]);

  async function upload() {
    setError("");
    if (!selected || !selected.size || selected.size > maxBytes) {
      setError(`Choose a file of 1–${maxBytes} bytes.`);
      return;
    }
    if (
      format === "pcm_s16le_8000_mono" &&
      (selected.size % 2 || selected.size > 48000)
    ) {
      setError(
        "Raw PCM needs complete 16-bit samples and at most three seconds.",
      );
      return;
    }
    try {
      const bytes = new Uint8Array(await selected.arrayBuffer());
      let binary = "";
      for (let i = 0; i < bytes.length; i += 8192)
        binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      await request(
        `/api/nodes/${node.id}/artifacts`,
        post({
          data_b64: btoa(binary),
          format,
          kind: "source",
          name: selected.name,
        }),
      );
    } catch (cause) {
      setError(String(cause));
    }
  }
  async function save(transfer: ArtifactTransfer) {
    setError("");
    try {
      const response = await fetch(
        `/api/artifact-transfers/${transfer.id}/content`,
      );
      if (!response.ok) throw new Error((await response.json()).detail);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `${transfer.id}.bin`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (cause) {
      setError(String(cause));
    }
  }
  return (
    <section className="node-artifacts" aria-label={`Node ${node.id} files`}>
      <div className="node-file-heading">
        <div>
          <h3>Node files</h3>
          <p>RAM files clear on reboot. Verified host copies stay saved.</p>
        </div>
        <button
          className="button secondary"
          disabled={!canList || busy || listing}
          onClick={refresh}
        >
          <RefreshCw size={14} /> Refresh files
        </button>
      </div>
      {!canList && (
        <p role="status">
          {node.connected
            ? "This firmware’s file interface is unavailable or incompatible."
            : "Connect the node to manage its files. Previous transfer findings remain below."}
        </p>
      )}
      <div className="node-file-upload">
        <label>
          File to upload
          <input
            key={node.identity?.boot_id}
            aria-label="File to upload"
            type="file"
            disabled={!canUpload || busy}
            onChange={(e) => {
              setSelected(e.target.files?.[0] ?? null);
              setError("");
            }}
          />
        </label>
        <label>
          File format
          <select
            aria-label="File format"
            value={format}
            disabled={!canUpload || busy}
            onChange={(e) => setFormat(e.target.value)}
          >
            <option value="known_data">Known data / binary</option>
            <option value="pcm_s16le_8000_mono">
              Raw PCM · 8 kHz, 16-bit mono
            </option>
          </select>
        </label>
        <button
          className="button primary"
          disabled={!canUpload || busy || !selected}
          onClick={upload}
        >
          <Upload size={14} /> Upload and verify
        </button>
      </div>
      {!canUpload && canList && (
        <p>
          Upload is unavailable in this firmware. Existing files can still be
          inspected.
        </p>
      )}
      {canList && !files.length && (
        <p className="node-file-empty">No files observed on this boot.</p>
      )}
      <ul className="node-file-list">
        {files.map((file) => (
          <li key={file.artifact_id}>
            <div>
              <strong>
                {file.length_bytes.toLocaleString()} bytes · {file.format}
              </strong>
              <span>
                {file.state}
                {file.in_use ? " · in use" : ""} ·{" "}
                {file.next_offset.toLocaleString()} bytes received
              </span>
              <code>{file.artifact_id}</code>
              <code>SHA-256 {file.sha256}</code>
            </div>
            <div className="node-file-actions">
              <button
                className="button secondary"
                disabled={
                  busy ||
                  !commands.includes("artifact.get") ||
                  file.state !== "committed"
                }
                onClick={() =>
                  request(
                    `/api/nodes/${node.id}/artifacts/${file.artifact_id}/download`,
                    post(),
                  )
                }
              >
                <Download size={14} /> Retrieve
              </button>
              {file.format === "pcm_s16le_8000_mono" && (
                <>
                  <button
                    className="button secondary"
                    disabled={
                      busy ||
                      file.state !== "committed" ||
                      file.in_use ||
                      !(node.audio_support?.commands ?? []).includes(
                        "audio.play",
                      )
                    }
                    onClick={() =>
                      request(
                        `/api/nodes/${node.id}/audio/play`,
                        post({ artifact_id: file.artifact_id }),
                      )
                    }
                  >
                    Play file on node
                  </button>
                  <button
                    className="button secondary"
                    disabled={
                      busy ||
                      file.state !== "committed" ||
                      !commands.includes("artifact.get")
                    }
                    onClick={() =>
                      request(
                        `/api/nodes/${node.id}/audio/retrieve`,
                        post({ artifact_id: file.artifact_id }),
                      )
                    }
                  >
                    Inspect PCM as WAV
                  </button>
                </>
              )}
              <button
                className="button secondary"
                disabled={
                  busy || !commands.includes("artifact.delete") || file.in_use
                }
                onClick={async () => {
                  const value = await request(
                    `/api/nodes/${node.id}/artifacts/${file.artifact_id}`,
                    { method: "DELETE" },
                  );
                  if (value) await refresh();
                }}
              >
                <Trash2 size={14} /> Delete
              </button>
            </div>
          </li>
        ))}
      </ul>
      <h4>Recent transfers</h4>
      {!recent.length && <p>No transfers recorded for this role.</p>}
      {recent.map((transfer) => (
        <article
          key={transfer.id}
          className={`node-transfer ${transfer.status}`}
        >
          <div className="node-file-heading">
            <strong>
              {transfer.direction === "upload"
                ? transfer.name
                : "Node download"}
            </strong>
            <span>
              {transfer.status} · {transfer.stage}
            </span>
          </div>
          {transfer.status === "running" && (
            <progress
              aria-label="File transfer progress"
              max={Math.max(
                1,
                transfer.bytes_total *
                  (transfer.direction === "upload" ? 2 : 1),
              )}
              value={
                transfer.bytes_transferred +
                (transfer.direction === "upload"
                  ? transfer.verification_bytes
                  : 0)
              }
            />
          )}
          <p>
            {transfer.bytes_transferred.toLocaleString()} /{" "}
            {transfer.bytes_total.toLocaleString()} bytes transferred ·{" "}
            {transfer.verification_bytes.toLocaleString()} bytes verified
          </p>
          {transfer.error && <p role="alert">{transfer.error}</p>}
          {transfer.cleanup && <p>{transfer.cleanup}</p>}
          {transfer.status === "completed" && (
            <>
              <code>SHA-256 {transfer.actual_sha256}</code>
              <button
                className="button secondary"
                onClick={() => save(transfer)}
              >
                <Download size={14} /> Save verified bytes
              </button>
            </>
          )}
          {running?.id === transfer.id && (
            <button
              className="button secondary"
              onClick={() =>
                request(`/api/artifact-transfers/${transfer.id}/cancel`, post())
              }
            >
              <Square size={14} /> Cancel transfer
            </button>
          )}
          <details>
            <summary>Transfer identity</summary>
            <code>{transfer.id}</code>
            <code>
              {transfer.identity.device_id} · {transfer.identity.boot_id}
            </code>
          </details>
        </article>
      ))}
      {(error || hostError) && (
        <p role="alert" className="hw-error">
          {error || hostError}
        </p>
      )}
    </section>
  );
}
