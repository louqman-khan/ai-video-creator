import { useEffect, useId, useState } from "react";
import type { TimelineClip } from "../api/types";
import * as ops from "./ops";

/** A slider that previews while it moves and becomes ONE undo step when it is released. */
function Slider({ label, value, min, max, step, show, onCommit }: {
  label: string; value: number; min: number; max: number; step: number; show: (v: number) => string; onCommit: (v: number) => void;
}) {
  const id = useId();
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const commit = () => { if (v !== value) onCommit(v); };
  return (
    <div className="insp-row">
      <label htmlFor={id}>{label}</label>
      <input id={id} type="range" min={min} max={max} step={step} value={v} aria-valuetext={show(v)}
        onChange={(e) => setV(Number(e.target.value))} onPointerUp={commit} onKeyUp={commit} onBlur={commit} />
      <output htmlFor={id}>{show(v)}</output>
    </div>
  );
}

const PRESETS: { name: string; x: number; y: number; scale: number }[] = [
  { name: "Full frame", x: 0, y: 0, scale: 1 },
  { name: "Top left", x: -0.3, y: -0.3, scale: 0.35 },
  { name: "Top right", x: 0.3, y: -0.3, scale: 0.35 },
  { name: "Bottom left", x: -0.3, y: 0.3, scale: 0.35 },
  { name: "Bottom right", x: 0.3, y: 0.3, scale: 0.35 },
];

export function Inspector({ clip: c, doc, onApply, cropMode = false, onCropMode, picking = false, onPick, pickingFocus = false, onPickFocus, onSuggestFocus }: {
  clip: TimelineClip; doc: ops.Doc; onApply: (r: ops.Result) => void; cropMode?: boolean; onCropMode?: (on: boolean) => void;
  /** the eyedropper: waiting for a click on the preview / start waiting (only offered while the live preview is showing) */
  picking?: boolean; onPick?: (on: boolean) => void;
  /** the focus: waiting for a click on the preview / start waiting / ask the server for a suggestion (the picker only with the live preview) */
  pickingFocus?: boolean; onPickFocus?: (on: boolean) => void; onSuggestFocus?: () => void;
}) {
  const fps = doc.fps;
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  const sec = (f: number) => `${(f / fps).toFixed(1)} s`;
  if (c.kind === "audio") {
    return (
      <fieldset className="insp" aria-label="Audio settings">
        <legend>Audio</legend>
        <Slider label="Volume" value={c.volume} min={0} max={2} step={0.05} show={pct} onCommit={(v) => onApply(ops.setVolume(doc, c.id, v))} />
        <Slider label="Fade in" value={c.fade_in} min={0} max={Math.min(c.duration, fps * 10)} step={1} show={sec} onCommit={(v) => onApply(ops.setFades(doc, c.id, { fade_in: v }))} />
        <Slider label="Fade out" value={c.fade_out} min={0} max={Math.min(c.duration, fps * 10)} step={1} show={sec} onCommit={(v) => onApply(ops.setFades(doc, c.id, { fade_out: v }))} />
      </fieldset>
    );
  }
  if (c.kind === "video" || c.kind === "image") {
    const t = c.transform;
    const fx = (type: ops.EffectType) => c.effects.find((e) => e.type === type)?.value ?? 0;
    const tr = c.transition_in;
    return (
      <fieldset className="insp" aria-label="Picture settings">
        <legend>Picture</legend>
        <Slider label="Opacity" value={t.opacity} min={0} max={1} step={0.05} show={pct} onCommit={(v) => onApply(ops.setPicture(doc, c.id, { opacity: v }))} />
        <Slider label="Size" value={t.scale} min={0.1} max={2} step={0.05} show={pct} onCommit={(v) => onApply(ops.setPicture(doc, c.id, { scale: v }))} />
        <div className="insp-row" role="group" aria-label="Position">
          <span>Position</span>
          {PRESETS.map((p) => (
            <button key={p.name} type="button" className="btn" aria-pressed={t.x === p.x && t.y === p.y && t.scale === p.scale}
              onClick={() => onApply(ops.setPicture(doc, c.id, p))}>{p.name}</button>
          ))}
        </div>
        <Slider label="Fade in" value={c.fade_in} min={0} max={Math.min(c.duration, fps * 5)} step={1} show={sec} onCommit={(v) => onApply(ops.setFades(doc, c.id, { fade_in: v }))} />
        <Slider label="Fade out" value={c.fade_out} min={0} max={Math.min(c.duration, fps * 5)} step={1} show={sec} onCommit={(v) => onApply(ops.setFades(doc, c.id, { fade_out: v }))} />
        <div className="insp-row" role="group" aria-label="Green screen">
          <input id={`${c.id}-key`} type="checkbox" checked={!!c.key} onChange={(e) => onApply(ops.setKey(doc, c.id, e.target.checked ? {} : null))} />
          <label htmlFor={`${c.id}-key`} style={{ width: "auto" }}>Green screen (remove a background colour)</label>
          {c.key && (
            <>
              <input type="color" aria-label="Colour to remove" value={c.key.color} onChange={(e) => onApply(ops.setKey(doc, c.id, { color: e.target.value }))} />
              <button type="button" className="btn" onClick={() => onApply(ops.setKey(doc, c.id, { color: "#00ff00" }))}>Green</button>
              <button type="button" className="btn" onClick={() => onApply(ops.setKey(doc, c.id, { color: "#0000ff" }))}>Blue</button>
              {onPick && <button type="button" className="btn" aria-pressed={picking} onClick={() => onPick(!picking)}>{picking ? "Click the preview…" : "Pick from the preview"}</button>}
            </>
          )}
        </div>
        {c.key && (
          <>
            <Slider label="Match" value={c.key.similarity} min={0} max={0.4} step={0.01} show={(v) => v.toFixed(2)} onCommit={(v) => onApply(ops.setKey(doc, c.id, { similarity: v }))} />
            <Slider label="Soft edge" value={c.key.blend} min={0} max={0.3} step={0.01} show={(v) => v.toFixed(2)} onCommit={(v) => onApply(ops.setKey(doc, c.id, { blend: v }))} />
            <div className="insp-row">
              <input id={`${c.id}-spill`} type="checkbox" checked={c.key.despill} onChange={(e) => onApply(ops.setKey(doc, c.id, { despill: e.target.checked }))} />
              <label htmlFor={`${c.id}-spill`} style={{ width: "auto" }}>Remove colour spill from the edges</label>
            </div>
          </>
        )}
        <div className="insp-row">
          <label htmlFor={`${c.id}-tr`}>Transition</label>
          <select id={`${c.id}-tr`} value={tr?.type ?? ""} onChange={(e) => onApply(ops.setTransition(doc, c.id, e.target.value ? { type: e.target.value as ops.TransitionType, duration: tr?.duration ?? Math.round(fps * 1) } : null))}>
            <option value="">None</option>
            <option value="crossfade">Crossfade</option>
            <option value="dip">Dip to black</option>
            <option value="slide">Slide in</option>
            <option value="zoom">Zoom in</option>
          </select>
        </div>
        {tr && <Slider label="Length" value={tr.duration} min={1} max={Math.min(c.duration, fps * 5)} step={1} show={sec} onCommit={(v) => onApply(ops.setTransition(doc, c.id, { type: tr.type as ops.TransitionType, duration: v }))} />}
        {tr && <p className="muted small">The picture before this one is kept on screen while the transition runs.</p>}
        <Slider label="Brightness" value={fx("brightness")} min={-100} max={100} step={5} show={(v) => `${v}`} onCommit={(v) => onApply(ops.setEffect(doc, c.id, "brightness", v))} />
        <Slider label="Contrast" value={fx("contrast")} min={-100} max={100} step={5} show={(v) => `${v}`} onCommit={(v) => onApply(ops.setEffect(doc, c.id, "contrast", v))} />
        <Slider label="Saturation" value={fx("saturation")} min={-100} max={100} step={5} show={(v) => `${v}`} onCommit={(v) => onApply(ops.setEffect(doc, c.id, "saturation", v))} />
        <Slider label="Blur" value={fx("blur")} min={0} max={100} step={5} show={(v) => `${v}`} onCommit={(v) => onApply(ops.setEffect(doc, c.id, "blur", v))} />
        <Slider label="Turn" value={t.rotation} min={-180} max={180} step={1} show={(v) => `${v}°`} onCommit={(v) => onApply(ops.setPicture(doc, c.id, { rotation: v }))} />
        {(["Left", "Top", "Right", "Bottom"] as const).map((name, i) => (
          <Slider key={name} label={`Crop ${name.toLowerCase()}`} value={t.crop[i]!} min={0} max={0.8} step={0.01} show={pct}
            onCommit={(v) => { const crop = [...t.crop] as [number, number, number, number]; crop[i] = v; onApply(ops.setPicture(doc, c.id, { crop })); }} />
        ))}
        <div className="insp-row">
          <label htmlFor={`${c.id}-fit`}>Fit to frame</label>
          <select id={`${c.id}-fit`} value={c.fit ?? "fill"} onChange={(e) => onApply(ops.setFit(doc, c.id, e.target.value as "fill" | "fit" | "blur"))}>
            <option value="fill">Fill (crop the edges)</option>
            <option value="fit">Fit (whole picture, bars)</option>
            <option value="blur">Fit over a blurred copy</option>
          </select>
          {onCropMode && <button type="button" className="btn" aria-pressed={cropMode} onClick={() => onCropMode(!cropMode)}>Crop on the preview</button>}
          <button type="button" className="btn" onClick={() => onApply(ops.setPicture(doc, c.id, { x: 0, y: 0, scale: 1, rotation: 0, crop: [0, 0, 0, 0] }))}>Reset position and size</button>
        </div>
        <div className="insp-row" role="group" aria-label="Focus">
          <span>Focus</span>
          <span className="muted small">{c.focus ? `kept in view: ${Math.round(c.focus[0] * 100)}% across, ${Math.round(c.focus[1] * 100)}% down` : "the middle (when the picture is cropped to fit the frame)"}</span>
          {onPickFocus && <button type="button" className="btn" aria-pressed={pickingFocus} onClick={() => onPickFocus(!pickingFocus)}>{pickingFocus ? "Click the preview…" : "Pick on the preview"}</button>}
          {onSuggestFocus && <button type="button" className="btn" onClick={onSuggestFocus} title="Looks for the most conspicuous part of the picture. A suggestion only: check it, it does not know faces.">Suggest</button>}
          {c.focus && <button type="button" className="btn" onClick={() => onApply(ops.setFocus(doc, c.id, null))}>Centre</button>}
        </div>
        <p className="muted small">Put a clip on a higher video track and make it smaller to get a picture-in-picture.</p>
      </fieldset>
    );
  }
  return null;
}
