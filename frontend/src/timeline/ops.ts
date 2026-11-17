// Editing operations on a timeline document: pure, immutable, no DOM.
//
// Every operation returns {doc, ids?} on success, or {doc: <the SAME document>, error} when it cannot be done:
// a refused operation never leaves a half-edited document behind. The results always satisfy the server's rules
// (backend/app/timeline/validate.py): no overlaps on a track, clips inside their media, integer frames, and so on.
// All positions are integer frames.

import type { TimelineAsset, TimelineClip, TimelineTrack } from "../api/types";

export interface Doc {
  fps: number;
  tracks: TimelineTrack[];
  clips: TimelineClip[];
  assets: Record<string, TimelineAsset>;
  caption_style: Record<string, unknown> | null;
}
export interface Result {
  doc: Doc;
  ids?: string[]; // clips created or changed, for selection
  error?: string;
}

const ACCEPTS: Record<TimelineTrack["kind"], TimelineClip["kind"][]> = {
  video: ["video", "image"], audio: ["audio"], caption: ["caption"],
};
const MAX_TEXT = 300;

export const clipEnd = (c: TimelineClip): number => c.start + c.duration;
const ok = (doc: Doc, ids?: string[]): Result => ({ doc, ids });
const refuse = (doc: Doc, error: string): Result => ({ doc, error });
const replaceClip = (doc: Doc, c: TimelineClip): Doc => ({ ...doc, clips: doc.clips.map((x) => (x.id === c.id ? c : x)) });
const findClip = (doc: Doc, id: string) => doc.clips.find((c) => c.id === id);
const trackOf = (doc: Doc, id: string) => doc.tracks.find((t) => t.id === id);
export const isLocked = (doc: Doc, trackId: string): boolean => trackOf(doc, trackId)?.locked ?? false;

export const timelineLength = (doc: Doc): number => doc.clips.reduce((n, c) => Math.max(n, clipEnd(c)), 0);

/** Clips of one track, left to right. */
export const clipsOn = (doc: Doc, trackId: string, exclude: ReadonlySet<string> = new Set()): TimelineClip[] =>
  doc.clips.filter((c) => c.track === trackId && !exclude.has(c.id)).sort((a, b) => a.start - b.start || a.id.localeCompare(b.id));

export function newId(doc: Doc, base: string): string {
  const used = new Set(doc.clips.map((c) => c.id));
  const stem = base.replace(/-\d+$/, "").slice(0, 56);
  for (let n = 2; ; n++) {
    const id = `${stem}-${n}`;
    if (!used.has(id)) return id;
  }
}

/** Frames of the asset a clip may play (unbounded for stills, captions and looping video). */
function sourceFrames(doc: Doc, c: TimelineClip): number {
  if (c.kind === "image" || c.kind === "caption" || c.loop) return Infinity;
  return (c.asset && doc.assets[c.asset]?.duration) || Infinity;
}
const usesSource = (c: TimelineClip) => c.kind === "video" || c.kind === "audio";

/** A scene is what the scene list and "swap visual" address. A clip that is cut or copied from a scene becomes a
 *  scene of its own, so no two clips ever share a scene id. */
function withNewScene(c: TimelineClip, among: readonly TimelineClip[]): TimelineClip {
  if (typeof c.meta["scene_id"] !== "number") return c;
  const top = among.reduce((n, x) => (typeof x.meta["scene_id"] === "number" ? Math.max(n, x.meta["scene_id"] as number) : n), 0);
  return { ...c, meta: { ...c.meta, scene_id: top + 1 } };
}

/** fades and a transition can never be longer than the clip */
function fit(c: TimelineClip): TimelineClip {
  const fade_out = Math.min(c.fade_out, c.duration);
  const fade_in = Math.min(c.fade_in, c.duration - fade_out);
  const transition_in = c.transition_in && c.transition_in.duration > c.duration ? { ...c.transition_in, duration: c.duration } : c.transition_in;
  return { ...c, fade_in, fade_out, transition_in };
}

const wordsIn = (words: TimelineClip["words"], from: number, to: number) => words.filter((w) => w.end > from && w.start < to);

// ------------------------------------------------------------------ move

export function moveClip(doc: Doc, id: string, to: { start: number; track?: string }): Result {
  const c = findClip(doc, id);
  if (!c) return refuse(doc, "That clip no longer exists.");
  const targetId = to.track ?? c.track;
  const target = trackOf(doc, targetId);
  if (!target) return refuse(doc, "That track does not exist.");
  if (!ACCEPTS[target.kind].includes(c.kind)) return refuse(doc, `A ${c.kind} clip cannot go on the ${target.kind} track “${target.name || target.id}”.`);
  if (target.locked || isLocked(doc, c.track)) return refuse(doc, "That track is locked.");

  const desired = Math.max(0, Math.round(to.start));
  const centre = desired + c.duration / 2;
  const others = clipsOn(doc, targetId, new Set([id]));
  // the free gap the clip is dropped into: between the neighbours on either side of its centre
  const next = others.find((o) => o.start + o.duration / 2 > centre);
  const prev = [...others].reverse().find((o) => o.start + o.duration / 2 <= centre);
  const lo = prev ? clipEnd(prev) : 0;
  const hi = next ? next.start : Infinity;
  if (hi - lo < c.duration) return refuse(doc, "There is not enough room for it there.");
  const start = Math.min(Math.max(desired, lo), hi - c.duration);
  if (start === c.start && targetId === c.track) return ok(doc, [id]);
  return ok(replaceClip(doc, { ...c, start, track: targetId }), [id]);
}

// ------------------------------------------------------------------ trim

export function trimClip(doc: Doc, id: string, edge: "start" | "end", frame: number): Result {
  const c = findClip(doc, id);
  if (!c) return refuse(doc, "That clip no longer exists.");
  if (isLocked(doc, c.track)) return refuse(doc, "That track is locked.");
  const f = Math.round(frame);
  const others = clipsOn(doc, c.track, new Set([id]));
  const prev = [...others].reverse().find((o) => clipEnd(o) <= c.start);
  const next = others.find((o) => o.start >= clipEnd(c));
  if (edge === "end") {
    const maxEnd = Math.min(next ? next.start : Infinity, c.start + (sourceFrames(doc, c) - (usesSource(c) ? c.in_point : 0)));
    const e = Math.min(Math.max(f, c.start + 1), maxEnd);
    if (e === clipEnd(c)) return ok(doc, [id]);
    return ok(replaceClip(doc, trimWords(fit({ ...c, duration: e - c.start }))), [id]);
  }
  const looping = c.loop && c.kind === "video";
  const minStart = Math.max(prev ? clipEnd(prev) : 0, usesSource(c) && !looping ? c.start - c.in_point : 0);
  const s = Math.min(Math.max(f, minStart), clipEnd(c) - 1);
  if (s === c.start) return ok(doc, [id]);
  const cut = s - c.start;
  return ok(replaceClip(doc, trimWords(fit({ ...c, start: s, duration: c.duration - cut, in_point: usesSource(c) ? wrapIn(doc, c, c.in_point + cut) : c.in_point,
    fade_in: cut > 0 ? 0 : c.fade_in, transition_in: cut > 0 ? null : c.transition_in }))), [id]);
}

/** a looping clip's in-point stays inside its media */
function wrapIn(doc: Doc, c: TimelineClip, v: number): number {
  const len = c.asset ? doc.assets[c.asset]?.duration : undefined;
  return c.loop && c.kind === "video" && len ? ((v % len) + len) % len : v;
}

/** a clip that shows only part of its recording carries only the words that are heard in it */
const trimWords = (c: TimelineClip): TimelineClip => (c.words.length ? { ...c, words: wordsIn(c.words, c.in_point, c.in_point + c.duration) } : c);

// ------------------------------------------------------------------ split / merge

function splitText(text: string, ratio: number): [string, string] | null {
  const tokens = text.trim().split(/\s+/);
  if (tokens.length < 2) return null;
  const k = Math.min(tokens.length - 1, Math.max(1, Math.round(tokens.length * ratio)));
  return [tokens.slice(0, k).join(" "), tokens.slice(k).join(" ")];
}

export function splitClip(doc: Doc, id: string, frame: number): Result {
  const c = findClip(doc, id);
  if (!c) return refuse(doc, "That clip no longer exists.");
  if (isLocked(doc, c.track)) return refuse(doc, "That track is locked.");
  const f = Math.round(frame);
  if (f <= c.start || f >= clipEnd(c)) return refuse(doc, "Put the playhead inside the clip to split it.");
  const cut = f - c.start;
  let leftText = c.text;
  let rightText = c.text;
  if (c.kind === "caption") {
    const parts = splitText(c.text ?? "", cut / c.duration);
    if (!parts) return refuse(doc, "A caption with a single word cannot be split.");
    [leftText, rightText] = parts;
  }
  const asset = c.asset ? doc.assets[c.asset] : undefined;
  let rightIn = usesSource(c) ? c.in_point + cut : 0;
  if (c.kind === "video" && c.loop && asset?.duration) rightIn %= asset.duration;
  const left = fit({ ...c, duration: cut, fade_out: 0, text: leftText });
  const right = fit({ ...withNewScene(c, doc.clips), id: newId(doc, c.id), start: f, duration: c.duration - cut, in_point: rightIn, fade_in: 0, transition_in: null, text: rightText });
  const leftW = c.words.length ? { ...left, words: wordsIn(c.words, c.in_point, c.in_point + cut) } : left;
  const rightW = c.words.length ? { ...right, words: wordsIn(c.words, c.in_point + cut, c.in_point + c.duration) } : right;
  const clips = doc.clips.flatMap((x) => (x.id === id ? [leftW, rightW] : [x]));
  return ok({ ...doc, clips }, [id, rightW.id]);
}

const sameLook = (a: TimelineClip, b: TimelineClip) =>
  a.volume === b.volume && a.loop === b.loop && JSON.stringify(a.transform) === JSON.stringify(b.transform) && JSON.stringify(a.effects) === JSON.stringify(b.effects);

export function mergeClips(doc: Doc, firstId: string, secondId: string): Result {
  const a = findClip(doc, firstId);
  const b = findClip(doc, secondId);
  if (!a || !b) return refuse(doc, "That clip no longer exists.");
  if (a.track !== b.track || a.kind !== b.kind || a.asset !== b.asset) return refuse(doc, "Only two pieces of the same media on the same track can be joined.");
  if (isLocked(doc, a.track)) return refuse(doc, "That track is locked.");
  if (clipEnd(a) !== b.start) return refuse(doc, "The two clips must touch.");
  if (!sameLook(a, b) || b.fade_in || a.fade_out || b.transition_in) return refuse(doc, "The two clips have different settings (volume, effects, fades), so they cannot be joined.");
  if (usesSource(a)) {
    const len = (a.asset && doc.assets[a.asset]?.duration) || 0;
    const expected = a.loop && len ? (a.in_point + a.duration) % len : a.in_point + a.duration;
    if (b.in_point !== expected) return refuse(doc, "The two clips are not consecutive parts of the same recording.");
  }
  let text = a.text;
  if (a.kind === "caption") {
    text = `${a.text ?? ""} ${b.text ?? ""}`.trim();
    if (text.length > MAX_TEXT) return refuse(doc, "The joined caption would be too long.");
  }
  const seen = new Set<string>();
  const words = [...a.words, ...b.words].filter((w) => {
    const key = `${w.start}:${w.end}:${w.text}`;
    return seen.has(key) ? false : (seen.add(key), true);
  });
  const merged = { ...a, duration: a.duration + b.duration, fade_out: b.fade_out, text, words };
  return ok({ ...doc, clips: doc.clips.filter((x) => x.id !== b.id).map((x) => (x.id === a.id ? merged : x)) }, [a.id]);
}

// ------------------------------------------------------------------ delete

/** "Lift": remove clips and leave the gap. */
export function deleteClips(doc: Doc, ids: readonly string[]): Result {
  const gone = new Set(ids.filter((id) => { const c = findClip(doc, id); return c && !isLocked(doc, c.track); }));
  if (gone.size === 0) return refuse(doc, ids.length ? "Those clips are on a locked track." : "Select a clip first.");
  return ok({ ...doc, clips: doc.clips.filter((c) => !gone.has(c.id)) }, []);
}

/** Words of narration, on the timeline: [{start, end}] in order, for every audio clip that carries words. */
function narrationWords(doc: Doc): { start: number; end: number }[] {
  const out: { start: number; end: number }[] = [];
  for (const c of doc.clips) {
    if (c.kind !== "audio" || !c.words.length) continue;
    for (const w of c.words) {
      if (w.end <= c.in_point || w.start >= c.in_point + c.duration) continue;
      out.push({ start: c.start + (w.start - c.in_point), end: c.start + (w.end - c.in_point) });
    }
  }
  return out.sort((x, y) => x.start - y.start);
}

/** Which words of a caption stay when only [from, to) of its time remains. Uses the narration's word times when
 *  they line up with the caption's words (the usual case), otherwise a proportional guess. */
function keepWords(text: string, c: TimelineClip, from: number, to: number, spoken: { start: number; end: number }[]): string {
  const tokens = text.trim().split(/\s+/).filter(Boolean);
  const inside = spoken.filter((w) => (w.start + w.end) / 2 >= c.start && (w.start + w.end) / 2 < clipEnd(c));
  const kept = tokens.filter((_, i) => {
    const centre = inside.length === tokens.length ? (inside[i]!.start + inside[i]!.end) / 2 : c.start + ((i + 0.5) / tokens.length) * c.duration;
    return centre >= from && centre < to;
  });
  return kept.join(" ");
}

/**
 * Cut the time [a, b) out of every unlocked track and close the gap ("ripple"). Clips inside it disappear, clips
 * that cross its edges are trimmed (or split in two when they span it), later clips move left by b - a. Captions
 * keep the words that are still spoken. Locked tracks are not touched.
 */
export function deleteRange(doc: Doc, a: number, b: number): Result {
  const from = Math.max(0, Math.round(a));
  const to = Math.round(b);
  if (to <= from) return refuse(doc, "Nothing to remove.");
  const gap = to - from;
  const spoken = narrationWords(doc);
  const clips: TimelineClip[] = [];
  let used = new Set(doc.clips.map((c) => c.id));
  const fresh = (base: string) => { const stem = base.replace(/-\d+$/, "").slice(0, 56); for (let n = 2; ; n++) { const id = `${stem}-${n}`; if (!used.has(id)) { used.add(id); return id; } } };
  for (const c of doc.clips) {
    if (isLocked(doc, c.track)) { clips.push(c); continue; }
    const s = c.start, e = clipEnd(c);
    if (e <= from) { clips.push(c); continue; }
    if (s >= to) { clips.push({ ...c, start: s - gap }); continue; }
    if (s >= from && e <= to) continue;                                         // entirely inside: gone
    const keepLeft = s < from ? { from: s, to: from } : null;
    const keepRight = e > to ? { from: to, to: e } : null;
    const piece = (range: { from: number; to: number }, start: number, isRight: boolean): TimelineClip | null => {
      const len = range.to - range.from;
      let text = c.text;
      if (c.kind === "caption") {
        text = keepWords(c.text ?? "", c, range.from, range.to, spoken);
        if (!text) return null;
      }
      const into = range.from - s;
      let inPoint = c.in_point;
      if (usesSource(c)) {
        inPoint = c.in_point + into;
        const total = c.asset ? doc.assets[c.asset]?.duration : undefined;
        if (c.kind === "video" && c.loop && total) inPoint %= total;
      }
      const base: TimelineClip = { ...c, start, duration: len, in_point: inPoint, text,
        fade_in: isRight || into > 0 ? 0 : c.fade_in, fade_out: !isRight && e > range.to ? 0 : c.fade_out,
        transition_in: into > 0 ? null : c.transition_in };
      return fit(c.words.length ? { ...base, words: wordsIn(c.words, inPoint, inPoint + len) } : base);
    };
    const left = keepLeft && piece(keepLeft, s, false);
    const right = keepRight && piece(keepRight, keepLeft ? from : from, true);
    if (left && right) clips.push(left, { ...withNewScene(right, [...doc.clips, ...clips]), id: fresh(c.id) });
    else if (left) clips.push(left);
    else if (right) clips.push(right);
  }
  used = new Set();
  return ok({ ...doc, clips }, []);
}

/** "Ripple delete": remove the clips and close the time they occupied on every unlocked track. */
export function rippleDelete(doc: Doc, ids: readonly string[]): Result {
  const chosen = ids.map((id) => findClip(doc, id)).filter((c): c is TimelineClip => !!c && !isLocked(doc, c.track));
  if (chosen.length === 0) return refuse(doc, ids.length ? "Those clips are on a locked track." : "Select a clip first.");
  // merge overlapping spans, then cut from the right so earlier positions stay valid
  const spans = chosen.map((c) => [c.start, clipEnd(c)] as [number, number]).sort((x, y) => x[0] - y[0]);
  const merged: [number, number][] = [];
  for (const sp of spans) {
    const last = merged[merged.length - 1];
    if (last && sp[0] <= last[1]) last[1] = Math.max(last[1], sp[1]);
    else merged.push([...sp]);
  }
  let current = doc;
  for (const [a, b] of merged.reverse()) current = deleteRange(current, a, b).doc;
  return ok(current, []);
}

// ------------------------------------------------------------------ duplicate / reorder

export function duplicateClip(doc: Doc, id: string): Result {
  const c = findClip(doc, id);
  if (!c) return refuse(doc, "That clip no longer exists.");
  if (isLocked(doc, c.track)) return refuse(doc, "That track is locked.");
  let at = clipEnd(c);
  for (const o of clipsOn(doc, c.track, new Set([id])).filter((x) => clipEnd(x) > at)) {
    if (o.start - at >= c.duration) break;
    at = Math.max(at, clipEnd(o));
  }
  const copy = { ...withNewScene(c, doc.clips), id: newId(doc, c.id), start: at };
  return ok({ ...doc, clips: [...doc.clips, copy] }, [copy.id]);
}

/** Swap a clip with its neighbour on the same track, staying inside the span both occupied. */
export function reorderClip(doc: Doc, id: string, direction: -1 | 1): Result {
  const c = findClip(doc, id);
  if (!c) return refuse(doc, "That clip no longer exists.");
  if (isLocked(doc, c.track)) return refuse(doc, "That track is locked.");
  const row = clipsOn(doc, c.track);
  const i = row.findIndex((x) => x.id === id);
  const other = row[i + direction];
  if (!other) return refuse(doc, direction < 0 ? "It is already the first clip." : "It is already the last clip.");
  const [first, second] = direction < 0 ? [other, c] : [c, other];
  const between = second.start - clipEnd(first);
  const movedSecond = { ...second, start: first.start };
  const movedFirst = { ...first, start: first.start + second.duration + between };
  return ok({ ...doc, clips: doc.clips.map((x) => (x.id === movedSecond.id ? movedSecond : x.id === movedFirst.id ? movedFirst : x)) }, [id]);
}

// ------------------------------------------------------------------ properties

export function setVolume(doc: Doc, id: string, volume: number): Result {
  const c = findClip(doc, id);
  if (!c || c.kind !== "audio") return refuse(doc, "Only audio clips have a volume.");
  if (isLocked(doc, c.track)) return refuse(doc, "That track is locked.");
  return ok(replaceClip(doc, { ...c, volume: Math.min(4, Math.max(0, Math.round(volume * 100) / 100)) }), [id]);
}

export function setFades(doc: Doc, id: string, fades: { fade_in?: number; fade_out?: number }): Result {
  const c = findClip(doc, id);
  if (!c || c.kind === "caption") return refuse(doc, "Captions have no fades.");
  if (isLocked(doc, c.track)) return refuse(doc, "That track is locked.");
  const clamp = (v: number) => Math.min(c.duration, Math.max(0, Math.round(v)));
  let fade_in = fades.fade_in === undefined ? c.fade_in : clamp(fades.fade_in);
  let fade_out = fades.fade_out === undefined ? c.fade_out : clamp(fades.fade_out);
  if (fade_in + fade_out > c.duration) (fades.fade_in !== undefined ? (fade_out = c.duration - fade_in) : (fade_in = c.duration - fade_out));
  return ok(replaceClip(doc, { ...c, fade_in, fade_out }), [id]);
}

export function setCaptionText(doc: Doc, id: string, text: string): Result {
  const c = findClip(doc, id);
  if (!c || c.kind !== "caption") return refuse(doc, "Only captions have text.");
  if (isLocked(doc, c.track)) return refuse(doc, "That track is locked.");
  // eslint-disable-next-line no-control-regex
  const clean = text.normalize("NFC").replace(/[\x00-\x1f\x7f]/g, " ").replace(/\s+/g, " ").trim();
  if (!clean) return refuse(doc, "A caption cannot be empty. Delete it instead.");
  if (clean.length > MAX_TEXT) return refuse(doc, `A caption can have at most ${MAX_TEXT} characters.`);
  return ok(replaceClip(doc, { ...c, text: clean }), [id]);
}

const MAX_TRACKS_PER_KIND = 6;

/** A new empty track; video tracks go on top of the existing ones. */
export function addTrack(doc: Doc, kind: "video" | "audio"): Result {
  const same = doc.tracks.filter((t) => t.kind === kind);
  if (same.length >= MAX_TRACKS_PER_KIND) return refuse(doc, `At most ${MAX_TRACKS_PER_KIND} ${kind} tracks.`);
  const letter = kind === "video" ? "V" : "A";
  const used = new Set(doc.tracks.map((t) => t.id));
  let n = same.length + 1;
  while (used.has(`${letter}${n}`)) n++;
  const track: TimelineTrack = { id: `${letter}${n}`, kind, name: `${kind === "video" ? "Video" : "Audio"} ${n}`, muted: false, locked: false, duck: false };
  return ok({ ...doc, tracks: [...doc.tracks, track] });
}

export function removeTrack(doc: Doc, trackId: string): Result {
  const t = trackOf(doc, trackId);
  if (!t) return refuse(doc, "That track does not exist.");
  if (t.kind === "caption") return refuse(doc, "The caption track cannot be removed.");
  if (doc.clips.some((c) => c.track === trackId)) return refuse(doc, "Move or delete the clips on this track first.");
  if (doc.tracks.filter((x) => x.kind === t.kind).length <= 1) return refuse(doc, `There must be at least one ${t.kind} track.`);
  return ok({ ...doc, tracks: doc.tracks.filter((x) => x.id !== trackId) });
}

export type TransitionType = "crossfade" | "dip" | "slide" | "zoom";
export type EffectType = "brightness" | "contrast" | "saturation" | "blur";

/** The transition into a picture clip (null removes it). It lasts at most as long as the clip. */
export function setTransition(doc: Doc, id: string, t: { type: TransitionType; duration: number } | null): Result {
  const c = findClip(doc, id);
  if (!c || (c.kind !== "video" && c.kind !== "image")) return refuse(doc, "Only pictures have transitions.");
  if (isLocked(doc, c.track)) return refuse(doc, "That track is locked.");
  if (!t) return ok(replaceClip(doc, { ...c, transition_in: null }), [id]);
  const duration = Math.max(1, Math.min(c.duration, Math.round(t.duration)));
  return ok(replaceClip(doc, fit({ ...c, transition_in: { type: t.type, duration } })), [id]);
}

/** Set (or, with 0, remove) a colour or blur effect of a picture clip. */
export function setEffect(doc: Doc, id: string, type: EffectType, value: number): Result {
  const c = findClip(doc, id);
  if (!c || (c.kind !== "video" && c.kind !== "image")) return refuse(doc, "Only pictures have effects.");
  if (isLocked(doc, c.track)) return refuse(doc, "That track is locked.");
  const v = Math.round(Math.min(type === "blur" ? 100 : 100, Math.max(type === "blur" ? 0 : -100, value)));
  const rest = c.effects.filter((e) => e.type !== type);
  return ok(replaceClip(doc, { ...c, effects: v === 0 ? rest : [...rest, { type, value: v }] }), [id]);
}

export interface Picture { opacity?: number; scale?: number; x?: number; y?: number }

/** Opacity, size and position of a picture clip (picture-in-picture). 1 = fills the frame; x/y are fractions of the frame. */
export function setPicture(doc: Doc, id: string, p: Picture): Result {
  const c = findClip(doc, id);
  if (!c || (c.kind !== "video" && c.kind !== "image")) return refuse(doc, "Only pictures have a size and position.");
  if (isLocked(doc, c.track)) return refuse(doc, "That track is locked.");
  const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Math.round(v * 1000) / 1000));
  const t = c.transform;
  const transform = { ...t,
    opacity: p.opacity === undefined ? t.opacity : clamp(p.opacity, 0, 1),
    scale: p.scale === undefined ? t.scale : clamp(p.scale, 0.05, 4),
    x: p.x === undefined ? t.x : clamp(p.x, -2, 2),
    y: p.y === undefined ? t.y : clamp(p.y, -2, 2) };
  return ok(replaceClip(doc, { ...c, transform }), [id]);
}

export function setTrackFlag(doc: Doc, trackId: string, flag: "muted" | "locked" | "duck", value: boolean): Result {
  const t = trackOf(doc, trackId);
  if (!t) return refuse(doc, "That track does not exist.");
  if (flag === "duck" && t.kind !== "audio") return refuse(doc, "Only audio tracks can be ducked.");
  return ok({ ...doc, tracks: doc.tracks.map((x) => (x.id === trackId ? { ...x, [flag]: value } : x)) });
}

// ------------------------------------------------------------------ snapping

/** Positions things snap to: 0, the end, the playhead, and the edges of every clip that is not being dragged. */
export function snapTargets(doc: Doc, exclude: ReadonlySet<string>, extra: readonly number[] = []): number[] {
  const set = new Set<number>([0, ...extra]);
  for (const c of doc.clips) if (!exclude.has(c.id)) { set.add(c.start); set.add(clipEnd(c)); }
  return [...set].sort((x, y) => x - y);
}

/** The smallest shift (within `tolerance` frames) that puts one of `edges` exactly on a target; null if none is close. */
export function snapShift(edges: readonly number[], targets: readonly number[], tolerance: number): { shift: number; target: number } | null {
  let best: { shift: number; target: number } | null = null;
  for (const e of edges) {
    for (const t of targets) {
      const d = t - e;
      if (Math.abs(d) <= tolerance && (best === null || Math.abs(d) < Math.abs(best.shift))) best = { shift: d, target: t };
    }
  }
  return best;
}

const PICTURE_SECONDS = 5;
const MAX_CLIP_SECONDS = 600;

/**
 * Put a media file on the timeline at `at`: a clip of its natural length (stills last 5 s) on the lowest track of the
 * right kind that is free there; when every such track is busy a new one is added on top, so the new clip lands over
 * what is already there. The asset joins the document's asset list in the same step.
 */
export function insertAsset(doc: Doc, given: TimelineAsset, at: number, title?: string): Result {
  const asset = doc.assets[given.id] ?? given; // a known asset is never replaced: other clips depend on its length
  const kind = asset.kind;
  const length = Math.max(1, Math.min(MAX_CLIP_SECONDS * doc.fps, kind === "image" ? PICTURE_SECONDS * doc.fps : asset.duration ?? PICTURE_SECONDS * doc.fps));
  const start = Math.max(0, Math.round(at));
  const accepts = kind === "audio" ? "audio" : "video";
  let work: Doc = { ...doc, assets: { ...doc.assets, [asset.id]: asset } };
  const free = (t: TimelineTrack) => !t.locked && clipsOn(work, t.id).every((c) => clipEnd(c) <= start || c.start >= start + length);
  let track = work.tracks.find((t) => t.kind === accepts && free(t));
  if (!track) {
    const added = addTrack(work, accepts);
    if (added.error) return refuse(doc, added.error);
    work = added.doc;
    track = work.tracks[work.tracks.length - 1]!;
  }
  const id = newId(work, kind === "audio" ? "audio-1" : kind === "image" ? "image-1" : "video-1");
  const clip: TimelineClip = {
    id, track: track.id, kind, asset: asset.id, start, duration: length, in_point: 0, loop: false, volume: 1, fade_in: 0, fade_out: 0,
    transform: { x: 0, y: 0, scale: 1, rotation: 0, opacity: 1, crop: [0, 0, 0, 0] }, effects: [], transition_in: null,
    text: null, words: [], meta: title ? { text: title } : {},
  };
  return ok({ ...work, clips: [...work.clips, clip] }, [id]);
}

export type SaveLike = "saved" | "dirty" | "saving" | "error" | "conflict";
