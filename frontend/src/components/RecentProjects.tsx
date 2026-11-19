import { useEffect } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useProjects } from "../store/projects";

/** The three newest projects, one click away from every page (sidebar). */
export function RecentProjects() {
  const { projects, load } = useProjects();
  useEffect(() => {
    void load();
  }, [load]);
  const recent = [...projects].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 3);
  if (recent.length === 0) return null;
  return (
    <nav className="recent" aria-label="Recent projects">
      <span className="side-label">Recent</span>
      {recent.map((p) => (
        <Link key={p.id} to={`/projects/${p.id}`} className="recent-item">
          <span className="recent-thumb">{p.video_ready && <img src={api.thumbUrl(p.id, 1, p.updated_at)} alt="" loading="lazy" onError={(e) => (e.currentTarget.style.display = "none")} />}</span>
          <span className="recent-name" dir="auto">{p.name}</span>
        </Link>
      ))}
    </nav>
  );
}
