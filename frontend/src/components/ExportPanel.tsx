import { useState } from "react";
import { api } from "../api/client";
import { isActive, type Project } from "../api/types";

type Aspect = "16:9" | "9:16";
const LABEL: Record<Aspect, string> = {
  "16:9": "Landscape 16:9 (1920×1080)",
  "9:16": "Vertical 9:16 (1080×1920)",
};

interface Props {
  project: Project;
  /** called with the project returned by the export request (it is now queued) */
  onStarted: (p: Project) => void;
}

export function ExportPanel({ project, onStarted }: Props) {
  const initial: Aspect = project.aspect === "9:16" ? "9:16" : "16:9";
  const [aspect, setAspect] = useState<Aspect>(initial);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busy = isActive(project) || starting;

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      onStarted(await api.exportProject(project.id, aspect));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setStarting(false);
    }
  };

  return (
    <div className="panel export-panel" aria-label="Export">
      <h2>Export</h2>
      <p className="muted small">
        The player above is a quick low-resolution preview. Export renders the full-quality video to publish.
      </p>
      {project.export_ready && (
        <p className="export-ready" role="status">
          ✓ Full-quality export ready ({project.export_aspect ?? project.aspect}, 1080p)
        </p>
      )}
      {!project.export_ready && (
        <p className="muted small">No export yet, or you edited the project since the last one.</p>
      )}
      <div className="row-inline export-row">
        <label className="field">
          <span className="label">Format</span>
          <select value={aspect} disabled={busy} onChange={(e) => setAspect(e.target.value as Aspect)}>
            {(Object.keys(LABEL) as Aspect[]).map((a) => (
              <option key={a} value={a}>{LABEL[a]}</option>
            ))}
          </select>
        </label>
        <button className="btn btn-primary" type="button" disabled={busy} onClick={() => void start()}>
          {starting ? "Starting…" : project.export_ready ? "Export again" : "Export full quality"}
        </button>
        {project.export_ready && (
          <a className="btn" href={api.exportUrl(project.id)} download>Download</a>
        )}
        <a className="btn" href={api.creditsUrl(project.id)} target="_blank" rel="noreferrer">Media credits</a>
      </div>
      {aspect !== project.aspect && (
        <p className="muted small">
          This project was made for {project.aspect}. Other formats centre-crop the same visuals, so some of the picture is cut off.
        </p>
      )}
      {error && <p className="alert small" role="alert">{error}</p>}
    </div>
  );
}
