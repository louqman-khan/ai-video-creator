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

export function Inspector({ clip: c, doc, onApply }: { clip: TimelineClip; doc: ops.Doc; onApply: (r: ops.Result) => void }) {
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
        <p className="muted small">Put a clip on a higher video track and make it smaller to get a picture-in-picture.</p>
      </fieldset>
    );
  }
  return null;
}
