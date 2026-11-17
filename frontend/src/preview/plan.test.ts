import { describe, expect, it } from "vitest";
import type { TimelineClip } from "../api/types";
import type { Doc } from "../timeline/ops";
import { audioAt, audioGain, captionAt, DUCK_GAIN, duckFactor, kenBurnsZoom, layersAt, sourceSeconds } from "./plan";

const c = (o: Partial<TimelineClip>): TimelineClip => ({
  id: "x", track: "V1", kind: "video", asset: "v", start: 0, duration: 30, in_point: 0, loop: false, volume: 1, fade_in: 0, fade_out: 0,
  transform: { x: 0, y: 0, scale: 1, rotation: 0, opacity: 1, crop: [0, 0, 0, 0] }, effects: [], transition_in: null, text: null, words: [], meta: {}, ...o,
});
const asset = (id: string, kind: "video" | "image" | "audio", duration: number | null) => ({ id, kind, duration, width: 1, height: 1, source: "", license: "", author: "", title: "", attribution: "", attribution_required: false });
const doc = (clips: TimelineClip[], muted: string[] = []): Doc => ({
  fps: 30, caption_style: null,
  tracks: [
    { id: "V1", kind: "video", name: "", muted: muted.includes("V1"), locked: false },
    { id: "V2", kind: "video", name: "", muted: muted.includes("V2"), locked: false },
    { id: "A1", kind: "audio", name: "", muted: muted.includes("A1"), locked: false },
    { id: "C1", kind: "caption", name: "", muted: false, locked: false },
  ],
  assets: { v: asset("v", "video", 45), i: asset("i", "image", null), a: asset("a", "audio", 300) }, clips,
});

describe("live preview plan", () => {
  it("stacks layers in track order and hides muted tracks", () => {
    const d = doc([c({ id: "top", track: "V2" }), c({ id: "bottom", track: "V1" })]);
    expect(layersAt(d, 5).map((l) => l.clip.id)).toEqual(["bottom", "top"]);
    expect(layersAt(doc(d.clips, ["V2"]), 5).map((l) => l.clip.id)).toEqual(["bottom"]);
    expect(layersAt(d, 30)).toEqual([]);                                       // a clip ends before its end frame
  });
  it("maps timeline frames to source time, wrapping looped video", () => {
    const d = doc([c({ id: "a", start: 10, in_point: 20, loop: true, duration: 100 })]);
    expect(sourceSeconds(d, d.clips[0]!, 10)).toBeCloseTo(20 / 30);
    expect(sourceSeconds(d, d.clips[0]!, 40)).toBeCloseTo(((20 + 30) % 45) / 30);
  });
  it("Ken Burns grows linearly over the clip, for stills only", () => {
    const still = c({ kind: "image", asset: "i", duration: 100, effects: [{ type: "kenburns", value: 10 }] });
    expect(kenBurnsZoom(still, 0)).toBe(1);
    expect(kenBurnsZoom(still, 50)).toBeCloseTo(1.05);
    expect(kenBurnsZoom(c({ effects: [{ type: "kenburns", value: 10 }] }), 10)).toBe(1);
  });
  it("applies volume and linear fades", () => {
    const a = c({ kind: "audio", track: "A1", asset: "a", start: 0, duration: 100, volume: 0.5, fade_in: 10, fade_out: 20 });
    expect(audioGain(a, 0)).toBe(0);
    expect(audioGain(a, 5)).toBeCloseTo(0.25);
    expect(audioGain(a, 50)).toBe(0.5);
    expect(audioGain(a, 90)).toBeCloseTo(0.25);
    const d = doc([a]);
    expect(audioAt(d, 50)).toHaveLength(1);
    expect(audioAt(doc([a], ["A1"]), 50)).toHaveLength(0);
  });
  it("carries picture-in-picture size and position", () => {
    const d = doc([c({ id: "p", transform: { x: 0.3, y: -0.2, scale: 0.4, rotation: 0, opacity: 0.8, crop: [0, 0, 0, 0] } })]);
    const l = layersAt(d, 1)[0]!;
    expect([l.scale, l.x, l.y, l.opacity]).toEqual([0.4, 0.3, -0.2, 0.8]);
  });
  it("lowers a ducked track only while the narration's words are spoken", () => {
    const words = [{ text: "a", start: 30, end: 50 }];
    const d = doc([c({ id: "nar", track: "A1", kind: "audio", asset: "a", start: 0, duration: 200, words }), c({ id: "mus", track: "A2", kind: "audio", asset: "a", start: 0, duration: 200 })]);
    d.tracks.push({ id: "A2", kind: "audio", name: "", muted: false, locked: false, duck: true });
    const gain = (f: number) => audioAt(d, f).find((x) => x.clip.id === "mus")!.gain;
    expect(duckFactor(d, 40)).toBe(DUCK_GAIN);
    expect(gain(40)).toBe(DUCK_GAIN);
    expect(gain(120)).toBe(1);
    expect(audioAt(d, 40).find((x) => x.clip.id === "nar")!.gain).toBe(1);   // the narration itself is untouched
  });
  it("finds the caption under the playhead", () => {
    const d = doc([c({ id: "k", track: "C1", kind: "caption", asset: null, start: 10, duration: 20, text: "سلام" })]);
    expect(captionAt(d, 9)).toBeNull();
    expect(captionAt(d, 10)).toBe("سلام");
  });
});
