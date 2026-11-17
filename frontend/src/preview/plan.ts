// What the live preview shows at a given frame: pure functions of the timeline document, mirroring the rules of
// the FFmpeg renderer (backend/app/timeline/render.py): stacking in track order, looping offsets, the Ken Burns
// zoom, muted tracks hidden, volume and linear fades.

import type { Doc } from "../timeline/ops";
import { clipEnd } from "../timeline/ops";
import type { TimelineClip } from "../api/types";

export interface Layer {
  clip: TimelineClip;
  /** seconds into the source file */
  time: number;
  opacity: number;
  /** 1 = the picture exactly covers the frame; Ken Burns zooms in from there */
  zoom: number;
  /** picture-in-picture: size (1 = fills the frame) and offset of the centre, as fractions of the frame */
  scale: number;
  x: number;
  y: number;
}

const active = (c: TimelineClip, frame: number) => c.start <= frame && frame < clipEnd(c);

function mutedTracks(doc: Doc): Set<string> {
  return new Set(doc.tracks.filter((t) => t.muted).map((t) => t.id));
}

/** Source time of a clip at a timeline frame; a looping clip wraps around its media. */
export function sourceSeconds(doc: Doc, c: TimelineClip, frame: number): number {
  let f = c.in_point + (frame - c.start);
  const len = c.asset ? doc.assets[c.asset]?.duration : undefined;
  if (c.loop && c.kind === "video" && len) f %= len;
  return f / doc.fps;
}

/** Ken Burns: the renderer zooms from 1 to 1 + value/100 over the whole clip, around the centre (still images only). */
export function kenBurnsZoom(c: TimelineClip, frame: number): number {
  if (c.kind !== "image") return 1;
  const kb = c.effects.find((e) => e.type === "kenburns");
  return kb ? 1 + (kb.value / 100) * ((frame - c.start) / c.duration) : 1;
}

/** Pictures to draw, bottom first. */
export function layersAt(doc: Doc, frame: number): Layer[] {
  const hidden = mutedTracks(doc);
  const rank = new Map(doc.tracks.map((t, i) => [t.id, i]));
  return doc.clips
    .filter((c) => (c.kind === "video" || c.kind === "image") && active(c, frame) && !hidden.has(c.track))
    .sort((a, b) => (rank.get(a.track) ?? 0) - (rank.get(b.track) ?? 0) || a.start - b.start)
    .map((clip) => ({ clip, time: sourceSeconds(doc, clip, frame), opacity: clip.transform.opacity, zoom: kenBurnsZoom(clip, frame),
      scale: clip.transform.scale, x: clip.transform.x, y: clip.transform.y }));
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
