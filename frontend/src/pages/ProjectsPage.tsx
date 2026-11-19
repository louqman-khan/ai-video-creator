import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { isActive } from "../api/types";
import { Icon } from "../components/Icon";
import { ProgressBar } from "../components/ProgressBar";
import { StatusBadge } from "../components/StatusBadge";
import { SetupBanner } from "../components/SetupBanner";
import { StoragePanel } from "../components/StoragePanel";
import { useAuth } from "../store/auth";
import { useProjects } from "../store/projects";

function greeting(now = new Date()): string {
  const h = now.getHours();
  return h < 5 ? "Working late?" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}
function ago(iso: string, now = Date.now()): string {
  const m = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  return d === 1 ? "yesterday" : `${d} days ago`;
}
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

export function ProjectsPage() {
  const admin = useAuth((s) => !!s.account?.user?.admin);  // the disk of the whole server is for its administrator (always true in the single-user desktop app)
  const { projects, loading, error, load, remove } = useProjects();

  useEffect(() => {
    void load();
    void useAuth.getState().load();   // refresh the credit balance (a failed video gives its credits back)
  }, [load]);

  // refresh while anything is still processing
  const anyActive = projects.some(isActive);
  useEffect(() => {
    if (!anyActive) return;
    const t = setInterval(() => void load(), 3000);
    return () => clearInterval(t);
  }, [anyActive, load]);

  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"new" | "old" | "name">("new");
  const [tab, setTab] = useState<"all" | "recent" | "progress">("all");
  const shown = projects
    .filter((p) => p.name.toLowerCase().includes(query.trim().toLowerCase()))
    .filter((p) => tab === "all" || (tab === "progress" ? isActive(p) || p.status === "failed" : Date.now() - new Date(p.created_at).getTime() < 14 * 864e5))
    .sort((a, b) => (sort === "name" ? a.name.localeCompare(b.name) : sort === "old" ? a.created_at.localeCompare(b.created_at) : b.created_at.localeCompare(a.created_at)));

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Your studio, in motion</p>
          <h1>{greeting()}. Start with a <span className="hl">first frame.</span></h1>
          <p className="page-sub">Turn the words in your head into something people can see.</p>
        </div>
        <Link className="btn btn-primary" to="/new"><Icon name="plus" />Create a video</Link>
      </div>

      <SetupBanner />
      <section className="hero" aria-label="Start a video">
        <p className="eyebrow">A little magic, a lot less work</p>
        <h2>Your voice. Your story.<span>Every language in between.</span></h2>
        <p>Start with a script or a recording. We find the pictures, time them and add captions in English or Urdu.</p>
        <div className="hero-actions">
          <Link to="/new" className="btn btn-primary"><Icon name="mic" />Start with a voiceover</Link>
          <Link to="/new?source=script" className="btn"><Icon name="text" />Write a script</Link>
        </div>
      </section>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {loading && projects.length === 0 && <p className="muted">Loading…</p>}
      {!loading && !error && projects.length === 0 && (
        <div className="empty">
          <Icon name="film" size={32} />
          <h2>No projects yet</h2>
          <p className="muted">Create one from an audio file or a typed script.</p>
          <Link className="btn btn-primary" to="/new"><Icon name="plus" />Create your first video</Link>
        </div>
      )}

      {admin && <StoragePanel />}
      {projects.length > 0 && (
        <div className="section-head"><h2>Your projects</h2><span className="count">{projects.length}</span></div>
      )}
      {projects.length > 0 && (
        <div className="toolbar">
          <div className="tabs" role="tablist" aria-label="Filter projects">
            {([["all", "All projects"], ["recent", "Recent"], ["progress", "In progress"]] as const).map(([id, label]) => (
              <button key={id} type="button" role="tab" aria-selected={tab === id} className={`tab${tab === id ? " tab-on" : ""}`} onClick={() => setTab(id)}>{label}</button>
            ))}
          </div>
          <label className="search">
            <Icon name="search" />
            <input type="text" placeholder="Search projects" aria-label="Search projects" value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <span className="muted small">{shown.length} of {projects.length}</span>
          <label className="sort">
            <span className="muted small">Sort</span>
            <select aria-label="Sort projects" value={sort} onChange={(e) => setSort(e.target.value as "new" | "old" | "name")}>
              <option value="new">Newest first</option><option value="old">Oldest first</option><option value="name">Name</option>
            </select>
          </label>
        </div>
      )}
      <ul className="proj-grid">
        {shown.map((p) => (
          <li key={p.id} className="proj">
            <Link to={`/projects/${p.id}`} className="proj-thumb" tabIndex={-1} aria-hidden="true">
              <span className="proj-ph"><Icon name="film" size={30} /></span>
              {p.video_ready && <img src={api.thumbUrl(p.id, 1, p.updated_at)} alt="" loading="lazy" onError={(e) => (e.currentTarget.style.display = "none")} />}
              <StatusBadge status={p.status} />
              {p.duration ? <span className="proj-len"><Icon name="play" size={10} />{clock(p.duration)}</span> : null}
            </Link>
            <div className="proj-body">
              <div className="proj-title">
                <Link to={`/projects/${p.id}`} dir="auto">{p.name}</Link>
                <details className="menu">
                  <summary aria-label={`More actions for ${p.name}`}><Icon name="more" /></summary>
                  <div className="menu-list">
                    <button
                      className="btn btn-danger"
                      disabled={isActive(p)}
                      onClick={() => {
                        if (window.confirm(`Delete “${p.name}”? This cannot be undone.`)) void remove(p.id);
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </details>
              </div>
              <p className="proj-sub">{p.language === "ur" ? "Urdu" : p.language === "en" ? "English" : "Auto language"}</p>
              {isActive(p) && (
                <>
                  <ProgressBar value={p.progress} label={`${p.name} progress`} />
                  <p className="small">{p.message}</p>
                </>
              )}
              {p.status === "failed" && p.error && <p className="alert small">{p.error}</p>}
              <div className="proj-foot"><span>Edited {ago(p.updated_at)}</span><span>{p.aspect}</span></div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
