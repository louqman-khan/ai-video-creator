import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { isActive } from "../api/types";
import { ProgressBar } from "../components/ProgressBar";
import { CaptionEditor } from "../components/CaptionEditor";
import { ExportPanel } from "../components/ExportPanel";
import { SceneList } from "../components/SceneList";
import { StatusBadge } from "../components/StatusBadge";
import { useProjects } from "../store/projects";
import { useProject } from "../hooks";

export function EditorPage() {
  const { id } = useParams();
  const { project, error, refresh } = useProject(id);
  const upsert = useProjects((s) => s.upsert);

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
  const playerVersion = isActive(project) ? "rendering" : project.updated_at;

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
          {/* key: reload the player once a re-render has finished (not on every progress update) */}
          <video key={playerVersion} className="player" controls preload="metadata"
            src={api.videoUrl(project.id, playerVersion)} />
          <p className="muted small">Preview (low resolution). Edits re-render it in a few seconds.</p>
        </div>
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
    </section>
  );
}
