import { useEffect, useState } from "react";
import { api } from "../api/client";
import { isActive, type AvatarCorner, type Project } from "../api/types";

const CORNERS: [AvatarCorner, string][] = [["bottom-right", "Bottom right"], ["bottom-left", "Bottom left"], ["top-right", "Top right"], ["top-left", "Top left"]];

interface Props {
  project: Project;
  /** called with the project returned by the request (it is now queued) */
  onStarted: (p: Project) => void;
}

/** Pick a character; it speaks the narration and appears on the timeline as a small clip you can move, resize, trim or delete. */
export function AvatarPanel({ project, onStarted }: Props) {
  const [avatars, setAvatars] = useState<{ id: string; name: string }[] | null>(null);
  const [chosen, setChosen] = useState<string>("");
  const [corner, setCorner] = useState<AvatarCorner>("bottom-right");
  const [size, setSize] = useState(0.3);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.avatars().then((a) => { if (live) { setAvatars(a); setChosen((c) => c || a[0]?.id || ""); } }, () => live && setAvatars([]));
    return () => { live = false; };
  }, []);

  if (!avatars || avatars.length === 0) return null;
  const working = busy || isActive(project);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      onStarted(await api.addAvatar(project.id, { avatar: chosen, corner, size }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <details className="panel avatar-panel">
      <summary>Talking avatar</summary>
      <p className="muted small">A character that speaks your narration, added to the timeline as a small clip (its mouth follows the loudness of the voice). Move, resize, trim or delete it like any other clip.</p>
      <div role="radiogroup" aria-label="Avatar" className="avatar-grid">
        {avatars.map((a) => (
          <label key={a.id} className={`avatar-choice${chosen === a.id ? " avatar-chosen" : ""}`}>
            <input type="radio" name="avatar" value={a.id} checked={chosen === a.id} disabled={working} onChange={() => setChosen(a.id)} />
            <img src={api.avatarThumbUrl(a.id)} alt="" width={96} height={96} />
            <span>{a.name}</span>
          </label>
        ))}
      </div>
      <div className="row-inline">
        <label className="field">
          <span className="label">Corner</span>
          <select value={corner} disabled={working} onChange={(e) => setCorner(e.target.value as AvatarCorner)}>
            {CORNERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="field">
          <span className="label">Size ({Math.round(size * 100)}%)</span>
          <input type="range" min={0.15} max={0.7} step={0.05} value={size} disabled={working} onChange={(e) => setSize(Number(e.target.value))} />
        </label>
        <button className="btn btn-primary" type="button" disabled={working || !chosen} onClick={() => void start()}>{busy ? "Starting…" : "Add avatar to the video"}</button>
      </div>
      {error && <p className="alert small" role="alert">{error}</p>}
    </details>
  );
}
