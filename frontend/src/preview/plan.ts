// What the live preview shows at a given frame: pure functions of the timeline document, mirroring the rules of
// the FFmpeg renderer (backend/app/timeline/render.py): stacking in track order, looping offsets, the Ken Burns
// zoom, muted tracks hidden, volume and linear fades.

import type { Doc } from "../timeline/ops";
import type { Key } from "./chromakey";
import { clipEnd } from "../timeline/ops";
import type { TimelineClip } from "../api/types";

export interface Layer {
  clip: TimelineClip;
  /** the outgoing picture kept alive underneath a transition */
  ghost: boolean;
  /** turn (degrees, clockwise), crop (left, top, right, bottom as fractions) and how the picture meets the frame */
  rotation: number;
  crop: [number, number, number, number];
  fit: "fill" | "fit" | "blur";
  key: Key | null;
  /** seconds into the source file */
  time: number;
  opacity: number;
  /** 1 = the picture exactly covers the frame; Ken Burns zooms in from there */
  zoom: number;
  /** picture-in-picture: size (1 = fills the frame) and offset of the centre, as fractions of the frame */
  scale: number;
  x: number;
  y: number;
  /** transition: extra horizontal shift in frame widths, and extra size factor (slide / zoom) */
  dx: number;
  zoomMul: number;
  /** colour and blur effects, as the editor stores them (-100..100) */
  fx: { brightness: number; contrast: number; saturation: number; blur: number };
}

const active = (c: TimelineClip, frame: number) => c.start <= frame && frame < clipEnd(c);

function mutedTracks(doc: Doc): Set<string> {
  return new Set(doc.tracks.filter((t) => t.muted).map((t) => t.id));
}

/** Source time of a clip at a timeline frame; a looping clip wraps around its media. */
export function sourceSeconds(doc: Doc, c: TimelineClip, frame: number): number {
  let f = c.in_point + (frame - c.start);
  const len = c.asset ? doc.assets[c.asset]?.duration : undefined;
  if (c.kind === "video" && len) f = c.loop ? f % len : Math.min(f, len - 1); // a video that ran out shows its last frame
  return f / doc.fps;
}

/** Ken Burns: the renderer zooms from 1 to 1 + value/100 over the whole clip, around the centre (still images only). */
export function kenBurnsZoom(c: TimelineClip, frame: number): number {
  if (c.kind !== "image") return 1;
  const kb = c.effects.find((e) => e.type === "kenburns");
  return kb ? 1 + (kb.value / 100) * ((frame - c.start) / c.duration) : 1;
}

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

/**
 * A transition needs the outgoing picture for as long as it lasts; the clip before the incoming one ends exactly where
 * it starts, so it is carried on underneath ("ghost") for the length of the transition. Mirrors `ghosts` in render.py.
 */
export function ghostsOf(doc: Doc, pictures: TimelineClip[]): TimelineClip[] {
  const byEnd = new Map(pictures.map((c) => [`${c.track}:${clipEnd(c)}`, c]));
  const out: TimelineClip[] = [];
  for (const b of pictures) {
    const t = b.transition_in;
    const a = t ? byEnd.get(`${b.track}:${b.start}`) : undefined;
    if (!t || !a || a.id === b.id) continue;
    const d = Math.min(t.duration, b.duration);
    const len = a.asset ? doc.assets[a.asset]?.duration : undefined;
    let pos = a.in_point + a.duration;
    if (a.kind === "video" && len) pos = a.loop ? pos % len : Math.min(pos, len - 1);
    out.push({ ...a, id: `${a.id}~out`, start: b.start, duration: d, in_point: a.kind === "video" ? pos : 0, fade_in: 0, fade_out: 0, transition_in: null,
      meta: { ghost: true, trans: [t.type, t.duration] } });
  }
  return out;
}

/** How a picture looks `F` frames after its clip started: opacity factor, shift and size factor. Mirrors `_timing` in render.py. */
export function appearance(c: TimelineClip, F: number): { alpha: number; dx: number; zoomMul: number } {
  let alpha = 1;
  let dx = 0;
  let zoomMul = 1;
  const t = c.transition_in;
  if (t) {
    const p = clamp01(F / t.duration);
    if (t.type === "crossfade") alpha *= p;
    else if (t.type === "dip") alpha *= clamp01(2 * p - 1);
    else if (t.type === "slide") dx = 1 - p;
    else if (t.type === "zoom") { alpha *= p; zoomMul = 1 + 0.5 * (1 - p); }
  }
  const ghost = c.meta["trans"] as [string, number] | undefined;
  if (ghost && ghost[0] === "dip") alpha *= clamp01(1 - 2 * clamp01(F / ghost[1]));
  if (c.fade_in) alpha *= clamp01(F / c.fade_in);
  if (c.fade_out) alpha *= clamp01((c.duration - F) / c.fade_out);
  return { alpha, dx, zoomMul };
}

const effectValue = (c: TimelineClip, type: string) => c.effects.find((e) => e.type === type)?.value ?? 0;

/** Pictures to draw, bottom first (a ghost lies under the clip it hands over to). */
export function layersAt(doc: Doc, frame: number): Layer[] {
  const hidden = mutedTracks(doc);
  const rank = new Map(doc.tracks.map((t, i) => [t.id, i]));
  const pictures = doc.clips.filter((c) => (c.kind === "video" || c.kind === "image") && !hidden.has(c.track));
  return [...pictures, ...ghostsOf(doc, pictures)]
    .filter((c) => active(c, frame))
    .sort((a, b) => (rank.get(a.track) ?? 0) - (rank.get(b.track) ?? 0) || (b.meta["ghost"] ? 1 : 0) - (a.meta["ghost"] ? 1 : 0) || a.start - b.start)
    .map((clip) => {
      const look = appearance(clip, frame - clip.start);
      return {
        clip, ghost: !!clip.meta["ghost"], time: sourceSeconds(doc, clip, frame), opacity: clip.transform.opacity * look.alpha, zoom: kenBurnsZoom(clip, frame),
        scale: clip.transform.scale, x: clip.transform.x, y: clip.transform.y, dx: look.dx, zoomMul: look.zoomMul,
        rotation: clip.transform.rotation, crop: clip.transform.crop, fit: clip.fit ?? "fill", key: clip.key ?? null,
        fx: { brightness: effectValue(clip, "brightness"), contrast: effectValue(clip, "contrast"), saturation: effectValue(clip, "saturation"), blur: effectValue(clip, "blur") },
      };
    });
}

/** Audio clips that sound at this frame. */
export function audioAt(doc: Doc, frame: number): { clip: TimelineClip; time: number; gain: number }[] {
  const hidden = mutedTracks(doc);
  return doc.clips
    .filter((c) => c.kind === "audio" && active(c, frame) && !hidden.has(c.track))
    .map((clip) => ({ clip, time: sourceSeconds(doc, clip, frame), gain: audioGain(clip, frame) * (duckedTracks(doc).has(clip.track) ? duckFactor(doc, frame) : 1) }));
}

/** Volume with the linear fade-in/out applied at a timeline frame. */
export function audioGain(c: TimelineClip, frame: number): number {
  const into = frame - c.start;
  const left = c.start + c.duration - frame;
  let g = c.volume;
  if (c.fade_in > 0 && into < c.fade_in) g *= Math.max(0, into / c.fade_in);
  if (c.fade_out > 0 && left < c.fade_out) g *= Math.max(0, left / c.fade_out);
  return g;
}

/** The caption shown at this frame (the top-most visible one). */
export function captionAt(doc: Doc, frame: number): string | null {
  const hidden = mutedTracks(doc);
  const hit = doc.clips.filter((c) => c.kind === "caption" && active(c, frame) && !hidden.has(c.track)).sort((a, b) => b.start - a.start)[0];
  return hit?.text ?? null;
}

/** Level of a ducked track while the others speak. The renderer uses a side-chain compressor (about -12 dB); the
 *  live preview approximates it from the narration's word times (or the clip's extent when it has no words). */
export const DUCK_GAIN = 0.25;
const duckedTracks = (doc: Doc) => new Set(doc.tracks.filter((t) => t.duck && !t.muted).map((t) => t.id));

export function duckFactor(doc: Doc, frame: number): number {
  const ducked = duckedTracks(doc);
  const hidden = mutedTracks(doc);
  const margin = Math.round(doc.fps * 0.15); // the compressor reacts a moment before and lets go a moment after
  for (const c of doc.clips) {
    if (c.kind !== "audio" || ducked.has(c.track) || hidden.has(c.track) || !active(c, frame)) continue;
    if (c.words.length === 0) return DUCK_GAIN;
    const t = c.in_point + (frame - c.start);
    if (c.words.some((w) => w.start - margin <= t && t <= w.end + margin * 2)) return DUCK_GAIN;
  }
  return 1;
}
