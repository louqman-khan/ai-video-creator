import { describe, expect, it } from "vitest";
import type { TimelineClip } from "../api/types";
import * as ops from "./ops";
import { clipEnd, type Doc } from "./ops";

// ---- a small seeded random generator, so a failure can be reproduced from its seed
function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const base = (o: Partial<TimelineClip>): TimelineClip => ({
  id: "x", track: "v1", kind: "video", asset: null, start: 0, duration: 30, in_point: 0, loop: false, volume: 1,
  fade_in: 0, fade_out: 0, transform: { x: 0, y: 0, scale: 1, rotation: 0, opacity: 1, crop: [0, 0, 0, 0] },
  effects: [], transition_in: null, text: null, words: [], meta: {}, ...o,
});

const asset = (id: string, kind: "video" | "image" | "audio", duration: number | null) => ({
  id, kind, duration, width: 1920, height: 1080, source: "t", license: "CC0", author: "", title: id, attribution: "", attribution_required: false,
});

function sample(): Doc {
  const words = Array.from({ length: 40 }, (_, i) => ({ text: `w${i}`, start: i * 10, end: i * 10 + 8 }));
  return {
    fps: 30,
    tracks: [
      { id: "v1", kind: "video", name: "Video", muted: false, locked: false },
      { id: "a1", kind: "audio", name: "Voice", muted: false, locked: false },
      { id: "a2", kind: "audio", name: "Music", muted: false, locked: false },
      { id: "c1", kind: "caption", name: "Captions", muted: false, locked: false },
    ],
    assets: { v: asset("v", "video", 400), i: asset("i", "image", null), n: asset("n", "audio", 400), m: asset("m", "audio", 900) },
    caption_style: null,
    clips: [
      base({ id: "s1", kind: "video", asset: "v", start: 0, duration: 100, meta: { scene_id: 1 } }),
      base({ id: "s2", kind: "image", asset: "i", start: 100, duration: 120, meta: { scene_id: 2 } }),
      base({ id: "s3", kind: "video", asset: "v", start: 220, duration: 180, in_point: 20, loop: true, meta: { scene_id: 3 } }),
      base({ id: "voice", track: "a1", kind: "audio", asset: "n", start: 0, duration: 400, words }),
      base({ id: "music", track: "a2", kind: "audio", asset: "m", start: 20, duration: 300, volume: 0.3, fade_out: 30 }),
      ...Array.from({ length: 10 }, (_, i) => base({ id: `cap${i}`, track: "c1", kind: "caption", start: i * 40, duration: 40, text: `w${i * 4} w${i * 4 + 1} w${i * 4 + 2} w${i * 4 + 3}` })),
    ],
  };
}

// ---- the same rules as backend/app/timeline/validate.py
function problems(doc: Doc): string[] {
  const out: string[] = [];
  const ids = new Set<string>();
  if (new Set(doc.tracks.map((t) => t.id)).size !== doc.tracks.length) out.push("duplicate track id");
  for (const kind of ["video", "audio", "caption"]) if (!doc.tracks.some((t) => t.kind === kind)) out.push(`no ${kind} track`);
  const perTrack = new Map<string, TimelineClip[]>();
  const accepts: Record<string, string[]> = { video: ["video", "image"], audio: ["audio"], caption: ["caption"] };
  for (const c of doc.clips) {
    if (ids.has(c.id)) out.push(`duplicate id ${c.id}`);
    ids.add(c.id);
    const t = doc.tracks.find((x) => x.id === c.track);
    if (!t) out.push(`${c.id}: no track`);
    else if (!accepts[t.kind]!.includes(c.kind)) out.push(`${c.id}: wrong track kind`);
    else perTrack.set(c.track, [...(perTrack.get(c.track) ?? []), c]);
    for (const n of [c.start, c.duration, c.in_point, c.fade_in, c.fade_out]) if (!Number.isInteger(n)) out.push(`${c.id}: non-integer ${n}`);
    const [cl, ct, cr, cb] = c.transform.crop;
    if (cl + cr >= 1 || ct + cb >= 1 || Math.min(cl, ct, cr, cb) < 0) out.push(`${c.id}: crop leaves nothing`);
    if (c.transform.rotation < -360 || c.transform.rotation > 360 || c.transform.scale <= 0) out.push(`${c.id}: bad transform`);
    if (c.start < 0) out.push(`${c.id}: negative start`);
    if (c.duration < 1) out.push(`${c.id}: empty`);
    if (c.in_point < 0) out.push(`${c.id}: negative in_point`);
    if (c.fade_in + c.fade_out > c.duration) out.push(`${c.id}: fades too long`);
    if (c.transition_in && c.transition_in.duration > c.duration) out.push(`${c.id}: transition too long`);
    if (c.kind === "caption") {
      if (!c.text?.trim()) out.push(`${c.id}: empty caption`);
      continue;
    }
    const a = c.asset ? doc.assets[c.asset] : undefined;
    if (!a) { out.push(`${c.id}: unknown asset`); continue; }
    if (a.kind === "image") { if (c.in_point) out.push(`${c.id}: image in_point`); }
    else {
      const len = a.duration ?? 0;
      if (c.in_point >= len) out.push(`${c.id}: starts after media`);
      else if (!c.loop && c.in_point + c.duration > len) out.push(`${c.id}: past media end`);
    }
    if (c.kind !== "audio" && c.words.length) out.push(`${c.id}: words on non-audio`);
    for (const w of c.words) if (w.end < w.start) out.push(`${c.id}: bad word`);
  }
  const sceneIds = doc.clips.map((c) => c.meta["scene_id"]).filter((x) => x !== undefined);
  if (new Set(sceneIds).size !== sceneIds.length) out.push("two clips share a scene id");
  for (const [track, list] of perTrack) {
    const s = [...list].sort((a, b) => a.start - b.start);
    for (let i = 1; i < s.length; i++) if (s[i]!.start < clipEnd(s[i - 1]!)) out.push(`overlap ${s[i - 1]!.id}/${s[i]!.id} on ${track}`);
  }
  return out;
}

describe("sample document", () => {
  it("is valid", () => expect(problems(sample())).toEqual([]));
});

describe("move", () => {
  it("never overlaps: the clip stops at its neighbour", () => {
    const r = ops.moveClip(sample(), "s1", { start: 90 });
    expect(r.error).toBeUndefined();
    expect(problems(r.doc)).toEqual([]);
  });
  it("refuses a wrong track and a gap that is too small, without changing anything", () => {
    const d = sample();
    expect(ops.moveClip(d, "s1", { start: 0, track: "a1" }).doc).toBe(d);
    expect(ops.moveClip(d, "s1", { start: 0, track: "a1" }).error).toMatch(/cannot go on/);
  });
  it("refuses locked tracks", () => {
    const d = ops.setTrackFlag(sample(), "v1", "locked", true).doc;
    expect(ops.moveClip(d, "s1", { start: 5 }).error).toMatch(/locked/);
  });
});

describe("trim", () => {
  it("cannot extend past the media or into a neighbour", () => {
    const d = sample();
    const r = ops.trimClip(d, "s1", "end", 500);
    expect(problems(r.doc)).toEqual([]);
    expect(r.doc.clips.find((c) => c.id === "s1")!.duration).toBe(100); // s2 starts at 100
  });
  it("trimming the start moves the in-point and the words", () => {
    const d = sample();
    const r = ops.trimClip(d, "voice", "start", 100);
    const v = r.doc.clips.find((c) => c.id === "voice")!;
    expect([v.start, v.in_point, v.duration]).toEqual([100, 100, 300]);
    expect(v.words.every((w) => w.end > 100)).toBe(true);
    expect(problems(r.doc)).toEqual([]);
  });
});

describe("split and merge", () => {
  it("split then merge returns the original clip", () => {
    const d = sample();
    const s = ops.splitClip(d, "voice", 150);
    expect(s.error).toBeUndefined();
    expect(problems(s.doc)).toEqual([]);
    const [l, r] = s.ids!;
    const m = ops.mergeClips(s.doc, l!, r!);
    expect(m.error).toBeUndefined();
    expect(m.doc.clips.find((c) => c.id === "voice")).toEqual(d.clips.find((c) => c.id === "voice"));
  });
  it("splits a caption's words between the halves", () => {
    const r = ops.splitClip(sample(), "cap0", 20);
    const [a, b] = r.ids!.map((id) => r.doc.clips.find((c) => c.id === id)!);
    expect(`${a!.text} ${b!.text}`).toBe("w0 w1 w2 w3");
  });
  it("refuses to split outside the clip or merge clips that do not touch", () => {
    const d = sample();
    expect(ops.splitClip(d, "s1", 0).error).toBeDefined();
    expect(ops.mergeClips(d, "s1", "s3").error).toBeDefined();
  });
});

describe("delete", () => {
  it("lift leaves the gap, ripple closes it on every track", () => {
    const lifted = ops.deleteClips(sample(), ["s2"]).doc;
    expect(lifted.clips.find((c) => c.id === "s3")!.start).toBe(220);
    const rip = ops.rippleDelete(sample(), ["s2"]).doc;
    expect(rip.clips.find((c) => c.id === "s3")!.start).toBe(100);
    expect(problems(rip)).toEqual([]);
  });
  it("deleting a time range keeps only the words still spoken in the captions", () => {
    const r = ops.deleteRange(sample(), 10, 30); // inside cap0 (w0 w1 w2 w3: words at 0,10,20,30)
    expect(problems(r.doc)).toEqual([]);
    const cap = r.doc.clips.filter((c) => c.track === "c1").sort((a, b) => a.start - b.start);
    expect(cap[0]!.text).toContain("w0");
  });
  it("leaves locked tracks alone", () => {
    const d = ops.setTrackFlag(sample(), "a1", "locked", true).doc;
    const r = ops.deleteRange(d, 50, 100).doc;
    expect(r.clips.find((c) => c.id === "voice")).toEqual(d.clips.find((c) => c.id === "voice"));
  });
});

describe("duplicate, reorder, properties", () => {
  it("duplicate sits in free space with a new id", () => {
    const r = ops.duplicateClip(sample(), "s1");
    expect(problems(r.doc)).toEqual([]);
    expect(r.doc.clips.length).toBe(sample().clips.length + 1);
  });
  it("reorder swaps neighbours and keeps the total span", () => {
    const d = sample();
    const r = ops.reorderClip(d, "s1", 1);
    expect(problems(r.doc)).toEqual([]);
    expect(r.doc.clips.find((c) => c.id === "s2")!.start).toBe(0);
    expect(ops.timelineLength(r.doc)).toBe(ops.timelineLength(d));
  });
  it("caption text is cleaned and may not be empty", () => {
    const d = sample();
    expect(ops.setCaptionText(d, "cap0", "   ").error).toBeDefined();
    expect(ops.setCaptionText(d, "cap0", "  hi\n there ").doc.clips.find((c) => c.id === "cap0")!.text).toBe("hi there");
  });
  it("volume and fades are clamped", () => {
    const d = sample();
    expect(ops.setVolume(d, "music", 99).doc.clips.find((c) => c.id === "music")!.volume).toBe(4);
    const f = ops.setFades(d, "music", { fade_in: 9999 }).doc.clips.find((c) => c.id === "music")!;
    expect(f.fade_in + f.fade_out).toBeLessThanOrEqual(f.duration);
  });
});

describe("tracks and pictures", () => {
  it("adds tracks with fresh ids (video on top), refuses beyond the limit, removes only empty ones", () => {
    let d = sample();
    d = ops.addTrack(d, "video").doc;
    expect(d.tracks.map((t) => t.id)).toContain("V2");
    expect(d.tracks[d.tracks.length - 1]!.id).toBe("V2");
    expect(ops.removeTrack(d, "v1").error).toMatch(/Move or delete/);
    expect(ops.removeTrack(d, "V2").doc.tracks.some((t) => t.id === "V2")).toBe(false);
    expect(ops.removeTrack(d, "c1").error).toMatch(/caption/);
    for (let i = 0; i < 10; i++) d = ops.addTrack(d, "audio").doc;
    expect(d.tracks.filter((t) => t.kind === "audio")).toHaveLength(6);
    expect(ops.addTrack(d, "audio").error).toMatch(/At most/);
  });
  it("the last track of a kind stays", () => {
    let d = ops.deleteClips(sample(), ["music", "voice"]).doc;
    d = ops.removeTrack(d, "a2").doc;
    expect(d.tracks.some((t) => t.id === "a2")).toBe(false);
    expect(ops.removeTrack(d, "a1").error).toMatch(/at least one/);
  });
  it("picture-in-picture settings are clamped, and only for pictures", () => {
    const d = sample();
    const t = ops.setPicture(d, "s1", { scale: 99, x: -9, opacity: 3 }).doc.clips.find((c) => c.id === "s1")!.transform;
    expect([t.scale, t.x, t.opacity]).toEqual([4, -2, 1]);
    expect(ops.setPicture(d, "voice", { scale: 0.5 }).error).toBeDefined();
  });
  it("only audio tracks can be ducked", () => {
    const d = sample();
    expect(ops.setTrackFlag(d, "a2", "duck", true).doc.tracks.find((x) => x.id === "a2")!.duck).toBe(true);
    expect(ops.setTrackFlag(d, "v1", "duck", true).error).toBeDefined();
  });
});

describe("transitions and effects", () => {
  const s = (d: Doc, id: string) => d.clips.find((c) => c.id === id)!;
  it("a transition is at most as long as its clip, can be removed, and only pictures have one", () => {
    const d = sample();
    expect(s(ops.setTransition(d, "s1", { type: "crossfade", duration: 9999 }).doc, "s1").transition_in).toEqual({ type: "crossfade", duration: 100 });
    const on = ops.setTransition(d, "s2", { type: "slide", duration: 20 }).doc;
    expect(s(ops.setTransition(on, "s2", null).doc, "s2").transition_in).toBeNull();
    expect(ops.setTransition(d, "voice", { type: "dip", duration: 5 }).error).toBeDefined();
  });
  it("trimming or splitting keeps a transition valid (never longer than the clip, only on the first piece)", () => {
    let d = ops.setTransition(sample(), "s1", { type: "dip", duration: 60 }).doc;
    d = ops.trimClip(d, "s1", "end", 30).doc;
    expect(s(d, "s1").transition_in!.duration).toBe(30);
    const sp = ops.splitClip(ops.setTransition(sample(), "s1", { type: "dip", duration: 60 }).doc, "s1", 50);
    expect(s(sp.doc, "s1").transition_in).not.toBeNull();
    expect(s(sp.doc, sp.ids![1]!).transition_in).toBeNull();
  });
  it("effects are clamped, replaced and removed with 0", () => {
    let d = ops.setEffect(sample(), "s1", "blur", 500).doc;
    expect(s(d, "s1").effects).toEqual([{ type: "blur", value: 100 }]);
    d = ops.setEffect(d, "s1", "brightness", -30).doc;
    d = ops.setEffect(d, "s1", "blur", 0).doc;
    expect(s(d, "s1").effects).toEqual([{ type: "brightness", value: -30 }]);
    expect(ops.setEffect(d, "voice", "blur", 5).error).toBeDefined();
  });
  it("pictures can fade now", () => {
    const f = ops.setFades(sample(), "s1", { fade_in: 20, fade_out: 5000 }).doc;
    expect(s(f, "s1").fade_in + s(f, "s1").fade_out).toBeLessThanOrEqual(100);
    expect(ops.setFades(sample(), "cap0", { fade_in: 3 }).error).toBeDefined();
  });
});

describe("focus", () => {
  const s = (d: Doc, id: string) => d.clips.find((c) => c.id === id)!;
  it("sets, rounds, clamps and clears the focus point, only for pictures", () => {
    let d = ops.setFocus(sample(), "s1", { x: 0.123456, y: 2 }).doc;
    expect(s(d, "s1").focus).toEqual([0.123, 1]);
    expect(s(ops.setFocus(d, "s1", null).doc, "s1").focus).toBeNull();
    expect(ops.setFocus(sample(), "voice", { x: 0.5, y: 0.5 }).error).toBeDefined();
    d = ops.splitClip(ops.setFocus(sample(), "s1", { x: 0.2, y: 0.4 }).doc, "s1", 50).doc;
    expect(d.clips.filter((c) => c.focus?.[0] === 0.2)).toHaveLength(2);                // both pieces keep it
  });
});

describe("green screen", () => {
  const s = (d: Doc, id: string) => d.clips.find((c) => c.id === id)!;
  it("turns on with defaults, changes one thing at a time, clamps, and turns off", () => {
    let d = ops.setKey(sample(), "s1", {}).doc;
    expect(s(d, "s1").key).toEqual({ color: "#00ff00", similarity: 0.15, blend: 0.1, despill: true });
    d = ops.setKey(d, "s1", { color: "#0000FF", similarity: 9, despill: false }).doc;
    expect(s(d, "s1").key).toEqual({ color: "#0000ff", similarity: 0.5, blend: 0.1, despill: false });
    expect(s(ops.setKey(d, "s1", { color: "not a colour" }).doc, "s1").key!.color).toBe("#0000ff");
    expect(s(ops.setKey(d, "s1", null).doc, "s1").key).toBeNull();
    expect(ops.setKey(sample(), "voice", {}).error).toBeDefined();
  });
  it("is kept when a clip is split", () => {
    const d = ops.setKey(sample(), "s1", { color: "#00ff00" }).doc;
    const sp = ops.splitClip(d, "s1", 50);
    expect(s(sp.doc, sp.ids![1]!).key).toEqual(s(d, "s1").key);
  });
});

describe("insertAsset", () => {
  const song = { ...asset("song", "audio", 450), title: "Calm" };
  const photo = asset("photo", "image", null);
  const clip = (d: Doc, id: string) => d.clips.find((c) => c.id === id)!;
  it("puts audio on the first free audio track, or a new one when the narration is in the way", () => {
    const r = ops.insertAsset(sample(), song, 100, "Calm");
    expect(problems(r.doc)).toEqual([]);
    expect(clip(r.doc, r.ids![0]!).track).not.toBe("a1");
    const d = ops.deleteClips(sample(), ["music"]).doc;      // a2 is free now
    const again = ops.insertAsset(d, song, 0);
    expect(clip(again.doc, again.ids![0]!).track).toBe("a2");
    expect(r.doc.assets["song"]).toBeDefined();
    expect(clip(r.doc, r.ids![0]!).duration).toBe(450);
  });
  it("a picture over a busy video track lands on a new track above it; stills last five seconds", () => {
    const r = ops.insertAsset(sample(), photo, 10);
    expect(problems(r.doc)).toEqual([]);
    const c = clip(r.doc, r.ids![0]!);
    expect([c.duration, c.start, c.kind]).toEqual([150, 10, "image"]);
    expect(r.doc.tracks.filter((t) => t.kind === "video")).toHaveLength(2);
    expect(c.track).toBe(r.doc.tracks[r.doc.tracks.length - 1]!.id);
  });
  it("uses a free gap on an existing track", () => {
    const d = ops.deleteClips(sample(), ["s2"]).doc;          // 100..220 is free
    const r = ops.insertAsset(d, { ...asset("p2", "video", 100) }, 100);
    expect(clip(r.doc, r.ids![0]!).track).toBe("v1");
    expect(r.doc.tracks.filter((t) => t.kind === "video")).toHaveLength(1);
  });
});

describe("frame shape, fit, crop and turn", () => {
  const s = (d: Doc, id: string) => d.clips.find((c) => c.id === id)!;
  it("changes the frame shape and reframes all pictures in one step", () => {
    let d = ops.setAspect(sample(), "9:16").doc;
    expect(d.aspect).toBe("9:16");
    d = ops.setFitAll(d, "blur").doc;
    expect(s(d, "s1").fit).toBe("blur");
    expect(s(d, "voice").fit).toBeUndefined();                                    // only pictures
    expect(ops.setFitAll(d, "blur").doc).toBe(d);                                 // nothing to do: the same document
    const locked = ops.setFitAll(ops.setTrackFlag(sample(), "v1", "locked", true).doc, "fit").doc;
    expect(s(locked, "s1").fit).toBeUndefined();                                  // a locked track is left alone
  });
  it("a crop always leaves some picture and a turn stays within a full circle", () => {
    const t = (p: ops.Picture) => s(ops.setPicture(sample(), "s1", p).doc, "s1").transform;
    expect(t({ crop: [0.9, 0.9, 0.9, 0.9] }).crop.every((v) => v <= 0.45)).toBe(true);
    expect(t({ crop: [-1, 2, 0, 0] }).crop).toEqual([0, 0.9, 0, 0]);
    expect(t({ rotation: 200 }).rotation).toBe(-160);
    expect(t({ rotation: -540 }).rotation).toBe(-180);
  });
  it("crop and turn survive splitting (both pieces keep the framing)", () => {
    const d = ops.setPicture(sample(), "s1", { rotation: 30, crop: [0.1, 0, 0, 0.2] }).doc;
    const sp = ops.splitClip(d, "s1", 50);
    expect(s(sp.doc, sp.ids![1]!).transform.crop).toEqual([0.1, 0, 0, 0.2]);
    expect(s(sp.doc, sp.ids![1]!).transform.rotation).toBe(30);
  });
});

describe("snapping", () => {
  it("snaps to the nearest target within tolerance only", () => {
    expect(ops.snapShift([98], [0, 100, 220], 4)).toEqual({ shift: 2, target: 100 });
    expect(ops.snapShift([90], [0, 100, 220], 4)).toBeNull();
  });
});

describe("random operation sequences (property test)", () => {
  it("every operation sequence keeps the document valid, and a refusal changes nothing", () => {
    for (let seed = 1; seed <= 400; seed++) {
      const rand = rng(seed);
      const pick = <T,>(xs: T[]): T => xs[Math.floor(rand() * xs.length)]!;
      let doc = sample();
      const log: string[] = [];
      for (let step = 0; step < 80; step++) {
        const ids = doc.clips.map((c) => c.id);
        const id = pick(ids);
        const frame = Math.floor(rand() * (ops.timelineLength(doc) + 40));
        const which = Math.floor(rand() * 18);
        let r: ops.Result;
        let name: string;
        switch (which) {
          case 0: name = `move ${id} ${frame}`; r = ops.moveClip(doc, id, { start: frame }); break;
          case 1: name = `moveTrack ${id} ${frame}`; r = ops.moveClip(doc, id, { start: frame, track: pick(doc.tracks).id }); break;
          case 2: name = `trimS ${id} ${frame}`; r = ops.trimClip(doc, id, "start", frame); break;
          case 3: name = `trimE ${id} ${frame}`; r = ops.trimClip(doc, id, "end", frame); break;
          case 4: case 5: name = `split ${id} ${frame}`; r = ops.splitClip(doc, id, frame); break;
          case 6: {
            const next = doc.clips.find((c) => c.track === doc.clips.find((x) => x.id === id)!.track && c.start === clipEnd(doc.clips.find((x) => x.id === id)!));
            name = `merge ${id} ${next?.id}`; r = next ? ops.mergeClips(doc, id, next.id) : { doc, error: "none" }; break;
          }
          case 7: name = `delete ${id}`; r = ops.deleteClips(doc, [id]); break;
          case 8: name = `ripple ${id}`; r = ops.rippleDelete(doc, [id]); break;
          case 9: name = `range ${frame}`; r = ops.deleteRange(doc, frame, frame + 1 + Math.floor(rand() * 80)); break;
          case 10: name = `dup ${id}`; r = ops.duplicateClip(doc, id); break;
          case 11: name = `reorder ${id}`; r = ops.reorderClip(doc, id, rand() < 0.5 ? -1 : 1); break;
          case 11 + 5: name = `insert`; r = ops.insertAsset(doc, asset("v", rand() < 0.5 ? "video" : "audio", 200 + Math.floor(rand() * 300)), frame); break;
          case 17: name = `transition ${id}`; r = rand() < 0.2 ? ops.setTransition(doc, id, null) : ops.setTransition(doc, id, { type: pick(["crossfade", "dip", "slide", "zoom"] as const), duration: 1 + Math.floor(rand() * 200) }); break;
          case 12: name = `addTrack`; r = ops.addTrack(doc, rand() < 0.5 ? "video" : "audio"); break;
          case 13: name = `removeTrack`; r = ops.removeTrack(doc, pick(doc.tracks).id); break;
          case 14: name = `picture ${id}`; r = ops.setPicture(doc, id, { scale: rand() * 3, x: rand() * 6 - 3, y: rand() * 6 - 3, opacity: rand(), rotation: rand() * 800 - 400, crop: [rand(), rand(), rand(), rand()] }); break;
          default: name = `lock`; r = ops.setTrackFlag(doc, pick(doc.tracks).id, "locked", rand() < 0.2); break;
        }
        log.push(name);
        if (r.error) expect(r.doc, `seed ${seed}: refused "${name}" must not change the document`).toBe(doc);
        const p = problems(r.doc);
        expect(p, `seed ${seed} after ${log.slice(-6).join(" | ")}`).toEqual([]);
        doc = r.doc;
        if (doc.clips.length === 0) break;
      }
    }
  }, 60000);
});
