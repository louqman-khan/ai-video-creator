import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { isActive, type CaptionsView, type CaptionStyle, type Project } from "../api/types";
import { FONT_SUGGESTIONS, LOOKS, lookIsActive, sameStyle, toForm, toPayload } from "../captionStyle";
import { formatTime } from "../format";
import { useCaptionPreview } from "../hooks";

interface Props {
  project: Project;
  /** called with the project returned by Apply/Reset (it is now queued and will re-render) */
  onChanged: (p: Project) => void;
  previewDebounceMs?: number;
}

/** A cue whose least certain word is below this is marked "please check". */
const UNSURE = 0.6;
const messageOf = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

export function CaptionEditor({ project, onChanged, previewDebounceMs = 400 }: Props) {
  const [data, setData] = useState<CaptionsView | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [onlyUncertain, setOnlyUncertain] = useState(false);
  const [texts, setTexts] = useState<Record<number, string>>({});
  const [style, setStyle] = useState<CaptionStyle | null>(null);
  const [selected, setSelected] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busy = isActive(project);

  // (re)load when the project is finished, and after every re-render
  useEffect(() => {
    if (project.status !== "done") return;
    let live = true;
    api.getCaptions(project.id).then(
      (d) => {
        if (!live) return;
        setData(d);
        setTexts(Object.fromEntries(d.cues.map((c) => [c.id, c.text])));
        setStyle(toForm(d.style));
        setSelected((s) => Math.min(s, Math.max(0, d.cues.length - 1)));
        setLoadError(null);
      },
      (e) => live && setLoadError(messageOf(e)),
    );
    return () => {
      live = false;
    };
  }, [project.id, project.status, project.updated_at]);

  const changedIds = useMemo(
    () => (data ? data.cues.filter((c) => (texts[c.id] ?? c.text) !== c.text).map((c) => c.id) : []),
    [data, texts],
  );
  const styleChanged = !!(data && style && !sameStyle(style, toForm(data.style)));
  const dirty = changedIds.length > 0 || styleChanged;

  const cue = data?.cues[selected];
  const previewRequest = useMemo(
    () => (data && style && cue ? { cue_id: cue.id, text: texts[cue.id] ?? cue.text, style: toPayload(style) } : null),
    [data, style, cue, texts],
  );
  const preview = useCaptionPreview(project.id, previewRequest, previewDebounceMs);

  if (loadError) return <p className="alert" role="alert">{loadError}</p>;
  if (!data || !style) return busy ? null : <p className="muted">Loading captions…</p>;
  const isUncertain = (c: { confidence?: number | null }) => c.confidence != null && c.confidence < UNSURE;
  const uncertainCount = data.cues.filter(isUncertain).length;
  if (data.cues.length === 0) return <p className="muted">This video has no captions.</p>;

  const set = <K extends keyof CaptionStyle>(key: K, value: CaptionStyle[K]) => setStyle({ ...style, [key]: value });
  const num = (key: "size_pct" | "outline_width" | "margin_pct" | "words_per_line" | "max_chars", raw: string) => {
    const n = Number(raw);
    if (raw.trim() === "") set(key, (key === "size_pct" ? null : style[key]) as never);
    else if (Number.isFinite(n)) set(key, n as never);
  };

  const apply = async () => {
    setSaving(true);
    setError(null);
    try {
      const body: Parameters<typeof api.updateCaptions>[1] = {};
      if (changedIds.length) body.cues = data.cues.map((c) => ({ id: c.id, text: texts[c.id] ?? c.text }));
      if (styleChanged) body.style = toPayload(style);
      onChanged(await api.updateCaptions(project.id, body));
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  const resetEdits = async () => {
    if (!window.confirm("Discard all your text edits and go back to the original captions?")) return;
    setSaving(true);
    setError(null);
    try {
      onChanged(await api.resetCaptions(project.id));
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  const revert = () => {
    setTexts(Object.fromEntries(data.cues.map((c) => [c.id, c.text])));
    setStyle(toForm(data.style));
  };

  const disabled = busy || saving;

  return (
    <section aria-label="Captions" className="captions">
      <h2>Captions</h2>
      <div className="captions-grid">
        <div className="captions-side">
          <div className="preview-box">
            {preview.url ? (
              <img src={preview.url} alt="Caption preview" className={preview.loading ? "preview-img stale" : "preview-img"} />
            ) : (
              <div className="preview-empty muted small">{preview.error ?? "Rendering preview…"}</div>
            )}
            {preview.loading && <span className="preview-badge small">Updating…</span>}
          </div>
          {preview.error && preview.url && <p className="alert small" role="status">{preview.error}</p>}
          <p className="muted small">The preview is rendered by the same engine as the final video.</p>

          <fieldset className="style-form" disabled={disabled}>
            <legend>Style</legend>
            <div className="looks" role="group" aria-label="Caption looks">
              {LOOKS.map((l) => (
                <button key={l.id} type="button" className={`look${lookIsActive(style, l) ? " look-on" : ""}`} aria-pressed={lookIsActive(style, l)}
                  onClick={() => setStyle({ ...style, ...l.values })}>
                  <span className="look-aa" style={{ color: l.values.color, fontWeight: l.values.bold ? 700 : 500,
                    WebkitTextStroke: l.values.outline_width ? `${Math.min(2.5, l.values.outline_width / 2)}px ${l.values.outline_color}` : undefined, paintOrder: "stroke fill" }}>Aa</span>
                  <span className="look-name">{l.name}</span>
                </button>
              ))}
            </div>
            <label className="field">
              <span className="label">Font</span>
              <input type="text" list="font-suggestions" value={style.font ?? ""} placeholder="Automatic"
                maxLength={60} onChange={(e) => set("font", e.target.value)} />
              <datalist id="font-suggestions">{FONT_SUGGESTIONS.map((f) => <option key={f} value={f} />)}</datalist>
            </label>
            <div className="row">
              <label className="field">
                <span className="label">Size (% of height)</span>
                <input type="number" min={2} max={30} step={0.5} value={style.size_pct ?? ""} placeholder="Automatic"
                  onChange={(e) => num("size_pct", e.target.value)} />
              </label>
              <div className="field" role="group" aria-label="Position">
                <span className="label">Position</span>
                <div className="seg">
                  {([["top", "Top"], ["center", "Middle"], ["bottom", "Bottom"]] as const).map(([v, label]) => (
                    <button key={v} type="button" aria-pressed={style.position === v} className={`seg-b${style.position === v ? " seg-on" : ""}`} onClick={() => set("position", v)}>
                      <span className={`seg-ico seg-${v}`} aria-hidden="true" />{label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="row">
              <label className="field">
                <span className="label">Text colour</span>
                <input type="color" value={style.color} onChange={(e) => set("color", e.target.value.toUpperCase())} />
                <span className="swatches" role="group" aria-label="Quick text colours">
                  {["#FFFFFF", "#FFF3D6", "#FFE066", "#BCE9D8", "#172321"].map((c) => (
                    <button key={c} type="button" className={`swatch${style.color.toUpperCase() === c ? " swatch-on" : ""}`} style={{ background: c }} aria-label={`Text colour ${c}`} aria-pressed={style.color.toUpperCase() === c} onClick={() => set("color", c)} />
                  ))}
                </span>
              </label>
              <label className="field">
                <span className="label">Outline colour</span>
                <input type="color" value={style.outline_color} onChange={(e) => set("outline_color", e.target.value.toUpperCase())} />
              </label>
              <label className="field">
                <span className="label">Outline width</span>
                <input type="number" min={0} max={20} step={0.5} value={style.outline_width}
                  onChange={(e) => num("outline_width", e.target.value)} />
              </label>
            </div>
            <div className="row">
              <label className="field">
                <span className="label">Words per line</span>
                <input type="number" min={1} max={30} value={style.words_per_line} disabled={data.edited}
                  onChange={(e) => num("words_per_line", e.target.value)} />
              </label>
              <label className="check"><input type="checkbox" checked={style.bold} onChange={(e) => set("bold", e.target.checked)} /> Bold</label>
            </div>
            {data.edited && <p className="muted small">Line breaks are fixed once you edit text. Reset the text edits to change words per line.</p>}
          </fieldset>
        </div>

        <div className="captions-main">
          {uncertainCount > 0 && (
            <label className="small" style={{ display: "block", marginBottom: "0.5rem" }}>
              <input type="checkbox" checked={onlyUncertain} onChange={(e) => setOnlyUncertain(e.target.checked)} /> Show only the {uncertainCount} cue{uncertainCount === 1 ? "" : "s"} to check
            </label>
          )}
          <ol className="cue-list" tabIndex={0} aria-label="Caption cues">
            {data.cues.filter((c) => !onlyUncertain || isUncertain(c)).map((c) => {
              const value = texts[c.id] ?? c.text;
              const changed = value !== c.text;
              return (
                <li key={c.id} className={`cue${c.id === selected ? " cue-selected" : ""}${changed ? " cue-changed" : ""}${isUncertain(c) ? " cue-uncertain" : ""}`}>
                  <label htmlFor={`cue-${c.id}`} className="muted small">
                    {formatTime(c.start)} – {formatTime(c.end)}{changed ? " · edited" : ""}
                    {isUncertain(c) && <strong className="cue-check" title="The recogniser was not sure about a word here"> · please check</strong>}
                  </label>
                  <textarea id={`cue-${c.id}`} rows={2} dir="auto" maxLength={300} value={value} disabled={disabled}
                    onFocus={() => setSelected(c.id)}
                    onChange={(e) => setTexts({ ...texts, [c.id]: e.target.value })} />
                </li>
              );
            })}
          </ol>
        </div>
      </div>

      {error && <p className="alert" role="alert">{error}</p>}
      <div className="card-actions">
        <button className="btn btn-primary" type="button" disabled={!dirty || disabled} onClick={() => void apply()}>
          {saving ? "Applying…" : "Apply and re-render"}
        </button>
        <button className="btn" type="button" disabled={!dirty || disabled} onClick={revert}>Undo changes</button>
        {data.edited && <button className="btn btn-danger" type="button" disabled={disabled} onClick={() => void resetEdits()}>Reset text edits</button>}
        {dirty && <span className="muted small">
          {changedIds.length > 0 && `${changedIds.length} caption${changedIds.length > 1 ? "s" : ""} edited`}
          {changedIds.length > 0 && styleChanged && " · "}
          {styleChanged && "style changed"}
        </span>}
      </div>
    </section>
  );
}
