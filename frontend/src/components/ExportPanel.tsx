import { useEffect, useState } from "react";
import { api } from "../api/client";
import { isActive, type Aspect, type ExportEncoder, type ExportPreset, type Project } from "../api/types";

const LABEL: Record<Aspect, string> = {
  "16:9": "Landscape 16:9",
  "9:16": "Vertical 9:16",
  "1:1": "Square 1:1",
  "4:5": "Portrait 4:5",
};
const SIZES: Record<ExportPreset, number> = { "720p": 720, "1080p": 1080, "4k": 2160 };
const PRESET_LABEL: Record<ExportPreset, string> = { "720p": "720p (small file, quick)", "1080p": "1080p (recommended)", "4k": "4K (large and slow)" };

/** "1920×1080" for a shape and a preset (the short side is 720 / 1080 / 2160). */
const dims = (aspect: Aspect, preset: ExportPreset): string => {
  const base = { "16:9": [16, 9], "9:16": [9, 16], "1:1": [1, 1], "4:5": [4, 5] }[aspect]!;
  const k = SIZES[preset] / Math.min(...base);
  return `${Math.round((base[0]! * k) / 2) * 2}×${Math.round((base[1]! * k) / 2) * 2}`;
};
const human = (s: number): string => (s < 90 ? `${s} seconds` : `${Math.round(s / 60)} minutes`);

interface Props {
  project: Project;
  /** called with the project returned by the export request (it is now queued) */
  onStarted: (p: Project) => void;
}

export function ExportPanel({ project, onStarted }: Props) {
  const initial: Aspect = (["16:9", "9:16", "1:1", "4:5"] as const).find((a) => a === project.aspect) ?? "16:9";
  const [aspect, setAspect] = useState<Aspect>(initial);
  const [preset, setPreset] = useState<ExportPreset>("1080p");
  const [encoder, setEncoder] = useState<ExportEncoder>("software");
  const [hardware, setHardware] = useState(false);
  const [estimate, setEstimate] = useState<{ seconds: number; learned: boolean } | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busy = isActive(project) || starting;

  useEffect(() => {
    let live = true;
    api.health().then((h) => live && setHardware(!!h.hardware_encoder), () => undefined);
    return () => { live = false; };
  }, []);
  useEffect(() => {
    let live = true;
    setEstimate(null);
    api.exportEstimate(project.id, aspect, preset, encoder).then((e) => live && setEstimate(e), () => undefined);
    return () => { live = false; };
  }, [project.id, aspect, preset, encoder, project.updated_at]);

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      onStarted(await api.exportProject(project.id, aspect, preset, encoder));
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
          ✓ Full-quality export ready ({project.export_aspect ?? project.aspect}, {project.export_preset ?? "1080p"}
          {project.export_encoder === "hardware" ? ", hardware encoder" : ""})
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
              <option key={a} value={a}>{LABEL[a]} ({dims(a, preset)})</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="label">Size</span>
          <select value={preset} disabled={busy} onChange={(e) => setPreset(e.target.value as ExportPreset)}>
            {(Object.keys(PRESET_LABEL) as ExportPreset[]).map((p) => <option key={p} value={p}>{PRESET_LABEL[p]}</option>)}
          </select>
        </label>
        <label className="field">
          <span className="label">Encoder</span>
          <select value={encoder} disabled={busy} onChange={(e) => setEncoder(e.target.value as ExportEncoder)}>
            <option value="software">Best quality (slower)</option>
            {hardware && <option value="hardware">Fast (this computer's video chip, bigger file)</option>}
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
      {estimate && (
        <p className="muted small" aria-label="Time estimate">
          About {human(estimate.seconds)} on this computer{estimate.learned ? "" : " (a rough guess until you have exported once)"}.
        </p>
      )}
      {aspect !== project.aspect && (
        <p className="muted small">
          This project was made for {project.aspect}. Other formats centre-crop the same visuals, so some of the picture is cut off.
        </p>
      )}
      {error && <p className="alert small" role="alert">{error}</p>}
    </div>
  );
}
