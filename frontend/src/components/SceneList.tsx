import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { isActive, type Asset, type Project, type Scene } from "../api/types";
import { formatTime, safeHref } from "../format";

interface Props {
  project: Project;
  /** called with the project returned by a swap (it is now queued and will re-render) */
  onSwapped: (p: Project) => void;
}

const messageOf = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

export function SceneList({ project, onSwapped }: Props) {
  const [scenes, setScenes] = useState<Scene[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const busy = isActive(project);

  // load when the project is finished, and again after every re-render (updated_at changes)
  useEffect(() => {
    if (project.status !== "done") return;
    let live = true;
    api.getScenes(project.id).then(
      (s) => live && (setScenes(s), setError(null)),
      (e) => live && setError(messageOf(e)),
    );
    return () => {
      live = false;
    };
  }, [project.id, project.status, project.updated_at]);

  if (error) return <p className="alert" role="alert">{error}</p>;
  if (!scenes) return busy ? null : <p className="muted">Loading scenes…</p>;

  return (
    <section aria-label="Scenes">
      <h2>Scenes</h2>
      <ol className="scenes">
        {scenes.map((s) => (
          <li key={s.id} className="scene">
            <SceneCard scene={s} project={project} busy={busy} isOpen={open === s.id}
              onToggle={() => setOpen(open === s.id ? null : s.id)}
              onSwapped={(p) => { setOpen(null); onSwapped(p); }} />
          </li>
        ))}
      </ol>
    </section>
  );
}

function SceneCard({ scene, project, busy, isOpen, onToggle, onSwapped }: {
  scene: Scene; project: Project; busy: boolean; isOpen: boolean; onToggle: () => void; onSwapped: (p: Project) => void;
}) {
  const a = scene.asset;
  const href = a ? safeHref(a.page_url) : undefined;
  return (
    <div className="scene-card">
      {scene.has_thumb && a ? (
        <img className="thumb" alt={`Visual for scene ${scene.id}`} loading="lazy"
          src={api.thumbUrl(project.id, scene.id, a.id)} />
      ) : (
        <div className="thumb thumb-empty" aria-label={`Scene ${scene.id} has no visual`}>No visual</div>
      )}
      <div className="scene-body">
        <p className="muted small">
          Scene {scene.id} · {formatTime(scene.start)} – {formatTime(scene.end)}
        </p>
        <p className="scene-text" dir="auto">{scene.text}</p>
        <p className="small muted">
          Search: <em>{scene.query_en || "–"}</em>
        </p>
        {a && (
          <p className="small">
            {a.kind === "video" ? "Video" : "Image"} from {href ? <a href={href} target="_blank" rel="noreferrer noopener">{a.source}</a> : a.source}
            {" · "}{a.license}
            {a.attribution_required && a.author ? ` · by ${a.author}` : ""}
          </p>
        )}
        <button className="btn" type="button" onClick={onToggle} disabled={busy} aria-expanded={isOpen}>
          {isOpen ? "Close" : "Swap visual"}
        </button>
        {isOpen && <SwapPanel scene={scene} project={project} onSwapped={onSwapped} />}
      </div>
    </div>
  );
}

function SwapPanel({ scene, project, onSwapped }: { scene: Scene; project: Project; onSwapped: (p: Project) => void }) {
  const [query, setQuery] = useState(scene.query_en);
  const [results, setResults] = useState<Asset[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [choosing, setChoosing] = useState<string | null>(null);

  const search = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setError(null);
    try {
      setResults(await api.getCandidates(project.id, scene.id, query.trim()));
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSearching(false);
    }
  };

  // first search happens right away with the scene's own query
  useEffect(() => {
    void search();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const choose = async (a: Asset) => {
    setChoosing(a.id);
    setError(null);
    try {
      onSwapped(await api.swapVisual(project.id, scene.id, a.id));
    } catch (err) {
      setError(messageOf(err));
      setChoosing(null);
    }
  };

  return (
    <div className="swap-panel">
      <form className="row-inline" onSubmit={search} role="search">
        <label className="sr-only" htmlFor={`q-${scene.id}`}>What should this scene show?</label>
        <input id={`q-${scene.id}`} type="text" value={query} maxLength={100}
          onChange={(e) => setQuery(e.target.value)} placeholder="e.g. mountain river at sunrise" />
        <button className="btn" type="submit" disabled={searching || !query.trim()}>{searching ? "Searching…" : "Search"}</button>
      </form>
      {error && <p className="alert small" role="alert">{error}</p>}
      {results && results.length === 0 && !searching && <p className="muted small">Nothing found. Try other words (English works best).</p>}
      <ul className="candidates">
        {results?.map((a) => (
          <li key={a.id}>
            <button type="button" className="candidate" disabled={choosing !== null}
              onClick={() => void choose(a)} title={`${a.title || a.id} · ${a.license}`}
              aria-label={`Use this ${a.kind} from ${a.source}`}>
              {/* referrerPolicy: do not tell the stock site which page we are on */}
              {safeHref(a.thumb_url) ? <img src={a.thumb_url} alt="" loading="lazy" referrerPolicy="no-referrer" /> : <span className="thumb-empty">No preview</span>}
              <span className="candidate-label">
                {a.kind === "video" ? `▶ ${a.duration ? Math.round(a.duration) + "s" : "video"}` : "Image"} · {a.source}
              </span>
              {choosing === a.id && <span className="candidate-label">Applying…</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
