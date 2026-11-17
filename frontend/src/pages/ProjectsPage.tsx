import { useEffect } from "react";
import { Link } from "react-router-dom";
import { isActive } from "../api/types";
import { ProgressBar } from "../components/ProgressBar";
import { StatusBadge } from "../components/StatusBadge";
import { StoragePanel } from "../components/StoragePanel";
import { useProjects } from "../store/projects";

export function ProjectsPage() {
  const { projects, loading, error, load, remove } = useProjects();

  useEffect(() => {
    void load();
  }, [load]);

  // refresh while anything is still processing
  const anyActive = projects.some(isActive);
  useEffect(() => {
    if (!anyActive) return;
    const t = setInterval(() => void load(), 3000);
    return () => clearInterval(t);
  }, [anyActive, load]);

  return (
    <section>
      <div className="page-head">
        <h1>Projects</h1>
        <Link className="btn btn-primary" to="/new">
          New project
        </Link>
      </div>

      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {loading && projects.length === 0 && <p className="muted">Loading…</p>}
      {!loading && !error && projects.length === 0 && (
        <p className="muted">No projects yet. Create one from an audio file.</p>
      )}

      <StoragePanel />
      <ul className="cards">
        {projects.map((p) => (
          <li key={p.id} className="card">
            <div className="card-top">
              <Link to={`/projects/${p.id}`} className="card-title" dir="auto">
                {p.name}
              </Link>
              <StatusBadge status={p.status} />
            </div>
            <p className="muted small">
              {p.aspect} · {p.language ?? "auto language"} · {new Date(p.created_at).toLocaleString()}
            </p>
            {isActive(p) && (
              <>
                <ProgressBar value={p.progress} label={`${p.name} progress`} />
                <p className="small">{p.message}</p>
              </>
            )}
            {p.status === "failed" && p.error && <p className="alert small">{p.error}</p>}
            <div className="card-actions">
              <Link className="btn" to={`/projects/${p.id}`}>
                Open
              </Link>
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
          </li>
        ))}
      </ul>
    </section>
  );
}
