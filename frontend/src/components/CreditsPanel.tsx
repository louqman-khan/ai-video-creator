import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Attribution, Project } from "../api/types";
import { safeHref } from "../format";

const messageOf = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

export function CreditsPanel({ project }: { project: Project }) {
  const [items, setItems] = useState<Attribution[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [manualText, setManualText] = useState<string | null>(null);

  // reload after every re-render: a swapped visual changes the credits
  useEffect(() => {
    if (project.status !== "done") return;
    let live = true;
    api.getAttributions(project.id).then(
      (a) => live && (setItems(a), setError(null)),
      (e) => live && setError(messageOf(e)),
    );
    return () => {
      live = false;
    };
  }, [project.id, project.status, project.updated_at]);

  const copy = async () => {
    setCopied(false);
    setManualText(null);
    let text = "";
    try {
      text = await api.getCreditsText(project.id);
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch (e) {
      // clipboard blocked: show the text so it can be selected by hand
      if (text) setManualText(text);
      else setError(messageOf(e));
    }
  };

  if (error) return <p className="alert" role="alert">{error}</p>;
  if (!items) return null;

  const required = items.filter((i) => i.asset.attribution_required).length;

  return (
    <section aria-label="Credits" className="credits">
      <h2>Credits</h2>
      {items.length === 0 ? (
        <p className="muted">This video uses no stock visuals, so there is nothing to credit.</p>
      ) : (
        <>
          {required > 0 ? (
            <p className="notice" role="note">
              {required} of {items.length} visual{items.length > 1 ? "s" : ""} need{required === 1 ? "s" : ""} a credit
              (Creative Commons). Paste the credits into your video description.
            </p>
          ) : (
            <p className="muted small">
              None of these visuals legally require a credit, but crediting the creators is appreciated.
            </p>
          )}
          <ul className="credit-list">
            {items.map(({ asset: a, scenes }) => {
              const page = safeHref(a.page_url);
              const licence = safeHref(a.license_url);
              return (
                <li key={a.id} className="credit">
                  <p className="small muted">Scene{scenes.length > 1 ? "s" : ""} {scenes.join(", ")}</p>
                  <p>
                    {a.kind === "video" ? "Video" : "Image"}
                    {a.title ? <> “<span dir="auto">{a.title}</span>”</> : null}
                    {a.author ? <> by <span dir="auto">{a.author}</span></> : null}
                    {" on "}
                    {page ? <a href={page} target="_blank" rel="noreferrer noopener">{a.source}</a> : a.source}
                  </p>
                  <p className="small">
                    License:{" "}
                    {licence ? <a href={licence} target="_blank" rel="noreferrer noopener">{a.license}</a> : a.license}
                    {a.attribution_required && <span className="badge badge-failed credit-badge">Credit required</span>}
                  </p>
                </li>
              );
            })}
          </ul>
          <div className="card-actions">
            <button className="btn btn-primary" type="button" onClick={() => void copy()}>
              {copied ? "Copied ✓" : "Copy credits text"}
            </button>
            <a className="btn" href={api.creditsUrl(project.id)} download="credits.txt">Download credits.txt</a>
          </div>
          {manualText && (
            <label className="field">
              <span className="label">Your browser blocked copying. Select and copy this text:</span>
              <textarea readOnly rows={Math.min(10, manualText.split("\n").length + 1)} value={manualText}
                onFocus={(e) => e.currentTarget.select()} />
            </label>
          )}
        </>
      )}
    </section>
  );
}
