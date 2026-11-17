import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { isActive } from "../api/types";
import { ProgressBar } from "../components/ProgressBar";
import { CaptionEditor } from "../components/CaptionEditor";
import { CreditsPanel } from "../components/CreditsPanel";
import { ExportPanel } from "../components/ExportPanel";
import { SceneList } from "../components/SceneList";
import { StatusBadge } from "../components/StatusBadge";
import type { MediaView } from "../api/types";
import type { Doc } from "../timeline/ops";
import { Timeline } from "../timeline/Timeline";
import { LivePreview } from "../preview/LivePreview";
import type { LiveEngine } from "../preview/engine";
import { useProjects } from "../store/projects";
import { useProject } from "../hooks";

export function EditorPage() {
  const { id } = useParams();
  const { project, error, refresh } = useProject(id);
  const upsert = useProjects((s) => s.upsert);
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  const [mode, setMode] = useState<"live" | "rendered">("live");
  const [liveDoc, setLiveDoc] = useState<Doc | null>(null);
  const [engine, setEngine] = useState<LiveEngine | null>(null);
  const [mediaState, setMediaState] = useState<Record<string, MediaView>>({});
  const live = mode === "live" && liveDoc !== null;
  // the player keeps its place while an edit re-renders the preview; it reloads when the render has finished
  const settled = useRef<string>("");
  if (project && (!isActive(project) || !settled.current)) settled.current = project.updated_at;
  // once the timeline is open it stays open while a preview re-renders (it would lose the selection and the keyboard focus)
  const opened = useRef<string | null>(null);
  if (project && project.status === "done" && project.video_ready) opened.current = project.id;

  if (!project) {
    return error ? (
      <p className="alert" role="alert">
        {error} <Link to="/">Back to projects</Link>
      </p>
    ) : (
      <p className="muted">Loading…</p>
    );
  }

  // changes only when a render finishes (not on every progress update)
  const playerVersion = settled.current || project.updated_at;

  return (
    <section>
      <div className="page-head">
        <h1 dir="auto">{project.name}</h1>
        <StatusBadge status={project.status} />
      </div>

      {isActive(project) && (
        <div className="panel">
          <ProgressBar value={project.progress} label="Processing" />
          <p>{project.message || "Starting…"}</p>
        </div>
      )}
      {(project.status === "failed" || (project.error && !isActive(project))) && (
        <p className="alert" role="alert">
          {project.error ?? "Processing failed."}
        </p>
      )}
      {project.video_ready && (
        <div className="panel">
          <div className="tl-group" role="group" aria-label="Preview type">
            <button type="button" className="btn" aria-pressed={mode === "live"} onClick={() => setMode("live")} disabled={!liveDoc}>Live preview</button>
            <button type="button" className="btn" aria-pressed={mode === "rendered"} onClick={() => setMode("rendered")}>Rendered preview</button>
          </div>
          {live ? (
            <LivePreview projectId={project.id} doc={liveDoc} aspect={project.aspect} media={mediaState} onEngine={setEngine} />
          ) : (
            /* key: reload the player once a re-render has finished (not on every progress update) */
            <video key={playerVersion} ref={setVideo} className="player" controls preload="metadata"
              src={api.videoUrl(project.id, playerVersion)} />
          )}
          <p className="muted small">
            {live ? "Live preview: shows your edits instantly, using small proxy copies of the media. Captions are approximate; export is the exact result."
              : "Preview (low resolution). Edits re-render it in a few seconds."}
          </p>
        </div>
      )}
      {project.video_ready && (project.status === "done" || opened.current === project.id) && (
        <Timeline projectId={project.id} version={project.updated_at} video={live ? engine : video} onDoc={setLiveDoc} onMedia={setMediaState} onProject={(p) => { upsert(p); refresh(); }} />
      )}
      {project.video_ready && (
        <ExportPanel project={project} onStarted={(p) => { upsert(p); refresh(); }} />
      )}
      {(project.status === "done" || project.video_ready) && (
        <SceneList project={project} onSwapped={(p) => { upsert(p); refresh(); }} />
      )}
      {(project.status === "done" || project.video_ready) && project.options.captions !== false && (
        <CaptionEditor project={project} onChanged={(p) => { upsert(p); refresh(); }} />
      )}
      {(project.status === "done" || project.video_ready) && <CreditsPanel project={project} />}
    </section>
  );
}
