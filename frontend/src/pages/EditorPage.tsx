import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { Icon } from "../components/Icon";
import { ThemeToggle } from "../components/ThemeToggle";
import { isActive } from "../api/types";
import { ProgressBar } from "../components/ProgressBar";
import { CaptionEditor } from "../components/CaptionEditor";
import { AvatarPanel } from "../components/AvatarPanel";
import { CreditsPanel } from "../components/CreditsPanel";
import { ExportPanel } from "../components/ExportPanel";
import { SceneList } from "../components/SceneList";
import { StatusBadge } from "../components/StatusBadge";
import type { MediaView, Project } from "../api/types";
import type { Doc } from "../timeline/ops";
import { Timeline } from "../timeline/Timeline";
import { LivePreview } from "../preview/LivePreview";
import type { LiveEngine } from "../preview/engine";
import { useProjects } from "../store/projects";
import { useProject } from "../hooks";

type Tab = "scenes" | "captions" | "avatar" | "export" | "credits";

export function EditorPage() {
  const { id } = useParams();
  const { project, error, refresh } = useProject(id);
  const upsert = useProjects((s) => s.upsert);
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  const [mode, setMode] = useState<"live" | "rendered">("live");
  const [liveDoc, setLiveDoc] = useState<Doc | null>(null);
  const [engine, setEngine] = useState<LiveEngine | null>(null);
  const [overlayHost, setOverlayHost] = useState<HTMLElement | null>(null);
  const [inspectorHost, setInspectorHost] = useState<HTMLElement | null>(null);   // the settings of the selected clip are drawn here, beside the preview
  const [mediaState, setMediaState] = useState<Record<string, MediaView>>({});
  const live = mode === "live" && liveDoc !== null;
  const [tab, setTab] = useState<Tab>("scenes");
  const [tlHeight, setTlHeight] = useState(340);   // the timeline's height in px; dragged with the bar above it
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
  const ready = project.status === "done" || project.video_ready;
  const tabs: { id: Tab; label: string; icon: string; show: boolean }[] = [
    { id: "scenes", label: "Scenes", icon: "image", show: ready },
    { id: "captions", label: "Captions", icon: "caption", show: ready && project.options.captions !== false },
    { id: "avatar", label: "Avatar", icon: "avatar", show: project.video_ready && project.status === "done" },
    { id: "export", label: "Export", icon: "export", show: project.video_ready },
    { id: "credits", label: "Credits", icon: "credit", show: ready },
  ];
  const visible = tabs.filter((t) => t.show);
  const active = visible.some((t) => t.id === tab) ? tab : visible[0]?.id;
  const changed = (p: Project) => { upsert(p); refresh(); };
  const [aw, ah] = (liveDoc?.aspect ?? project.aspect ?? "16:9").split(":").map(Number);
  const ratio = aw && ah ? aw / ah : 16 / 9;   // the shape of the picture: the stage fits it into the space it has

  const dragTimeline = (e: ReactPointerEvent) => {
    e.preventDefault();
    const y0 = e.clientY, h0 = tlHeight;
    const move = (ev: PointerEvent) => setTlHeight(Math.min(Math.max(h0 + (y0 - ev.clientY), 180), Math.round(window.innerHeight * 0.7)));
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div className="ws" style={{ ["--tl-h" as string]: `${tlHeight}px` }}>
      <header className="ws-top">
        <Link to="/" className="ws-back" aria-label="Back to projects"><Icon name="back" /></Link>
        <Link to="/" className="ws-crumb">Projects</Link>
        <Icon name="chevron" size={14} />
        <h1 dir="auto" className="ws-title">{project.name}</h1>
        <StatusBadge status={project.status} />
        <span className="ws-spacer" />
        <ThemeToggle />
        {project.video_ready && (
          <button type="button" className="btn btn-primary" onClick={() => setTab("export")}><Icon name="export" />Export</button>
        )}
      </header>

      <div className="ws-body">
        <nav className="ws-rail" role="tablist" aria-label="Editor panels" aria-orientation="vertical">
          {visible.map((t) => (
            <button key={t.id} type="button" role="tab" aria-selected={active === t.id} className={`ws-tab${active === t.id ? " ws-tab-on" : ""}`} onClick={() => setTab(t.id)}>
              <Icon name={t.icon} size={20} />
              <span>{t.label}</span>
            </button>
          ))}
        </nav>

        <div className="ws-panel" role="tabpanel" aria-label={tabs.find((t) => t.id === active)?.label}>
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
          {active === "scenes" && ready && <SceneList project={project} onSwapped={changed} />}
          {active === "captions" && ready && project.options.captions !== false && <CaptionEditor project={project} onChanged={changed} />}
          {active === "avatar" && project.video_ready && project.status === "done" && <AvatarPanel project={project} onStarted={changed} />}
          {active === "export" && project.video_ready && <ExportPanel project={project} onStarted={changed} />}
          {active === "credits" && ready && <CreditsPanel project={project} />}
          {!ready && !isActive(project) && <p className="muted">Nothing to edit yet.</p>}
        </div>

        <section className="ws-stage" aria-label="Preview">
          {project.video_ready ? (
            <>
              <div className="ws-modes tl-group" role="group" aria-label="Preview type">
                <button type="button" className="btn" aria-pressed={mode === "live"} onClick={() => setMode("live")} disabled={!liveDoc}>Live preview</button>
                <button type="button" className="btn" aria-pressed={mode === "rendered"} onClick={() => setMode("rendered")}>Rendered preview</button>
              </div>
              <div className="ws-canvas" style={{ ["--ar" as string]: String(ratio) }}>
                {live ? (
                  <div className="live-host" ref={setOverlayHost}><LivePreview projectId={project.id} doc={liveDoc} aspect={liveDoc.aspect ?? project.aspect} media={mediaState} onEngine={setEngine} /></div>
                ) : (
                  /* key: reload the player once a re-render has finished (not on every progress update) */
                  <video key={playerVersion} ref={setVideo} className="player" controls preload="metadata"
                    src={api.videoUrl(project.id, playerVersion)} />
                )}
              </div>
              <p className="muted small ws-note">
                {live ? "Live preview: shows your edits instantly, using small proxy copies of the media. Captions are approximate; export is the exact result."
                  : "Preview (low resolution). Edits re-render it in a few seconds."}
              </p>
            </>
          ) : (
            <div className="ws-wait"><Icon name="film" size={36} /><p>{isActive(project) ? "Your video is being made…" : "No video yet."}</p></div>
          )}
        </section>

        {project.video_ready && <aside className="ws-inspector" ref={setInspectorHost} aria-label="Selected clip settings" />}
      </div>

      {project.video_ready && (project.status === "done" || opened.current === project.id) && (
        <>
          <div className="ws-split" role="separator" aria-orientation="horizontal" aria-label="Resize the timeline" onPointerDown={dragTimeline} />
          <div className="ws-timeline">
            <Timeline projectId={project.id} version={playerVersion} video={live ? engine : video} onDoc={setLiveDoc} onMedia={setMediaState} overlayHost={live ? overlayHost : null} inspectorHost={inspectorHost} sampler={live && engine ? (id, x, y) => engine.pickColor(id, x, y) : null}
              focusSampler={live && engine ? (id, x, y) => engine.pickFocus(id, x, y) : null} onProject={changed} />
          </div>
        </>
      )}
    </div>
  );
}
