import { describe, expect, it } from "vitest";
import {
  clampPps, displayOrder, filmSlots, fitPps, formatTimecode, frameToPx, isVisible, MAX_PPS, MIN_PPS, peakColumns, peakRate,
  pxToFrame, rulerTicks, visibleSeconds, zoomScrollLeft,
} from "./layout";

describe("frames and pixels", () => {
  it("converts both ways and round-trips", () => {
    expect(frameToPx(30, 60, 30)).toBe(60);            // 1 s at 60 px/s
    expect(pxToFrame(60, 60, 30)).toBe(30);
    for (const f of [0, 1, 17, 359, 5400]) expect(pxToFrame(frameToPx(f, 137, 30), 137, 30)).toBe(f);
  });
  it("clamps the zoom", () => {
    expect(clampPps(0)).toBe(MIN_PPS);
    expect(clampPps(1e6)).toBe(MAX_PPS);
    expect(clampPps(50)).toBe(50);
  });
  it("fits the whole timeline into the viewport", () => {
    expect(fitPps(300, 30, 1000)).toBe(100);           // 10 s in 1000 px
    expect(fitPps(30 * 3600, 30, 1000)).toBe(MIN_PPS); // an hour can not fit: stays at the minimum
    expect(fitPps(0, 30, 1000)).toBe(60);              // empty timeline: a sane default
    expect(fitPps(300, 30, 0)).toBe(60);
  });
});

describe("timecode", () => {
  it("shows minutes:seconds:frames", () => {
    expect(formatTimecode(0, 30)).toBe("00:00:00");
    expect(formatTimecode(75, 30)).toBe("00:02:15");
    expect(formatTimecode(30 * 61 + 4, 30)).toBe("01:01:04");
    expect(formatTimecode(30 * 3600 + 30 * 62, 30)).toBe("1:01:02:00");
    expect(formatTimecode(-5, 30)).toBe("00:00:00");
    expect(formatTimecode(24, 24)).toBe("00:01:00");   // other frame rates roll over at their own fps
  });
});

describe("zoom anchoring", () => {
  it("keeps the time under the cursor fixed", () => {
    const [oldPps, newPps, scroll, anchor] = [60, 120, 300, 200];
    const timeBefore = (scroll + anchor) / oldPps;
    const newScroll = zoomScrollLeft(oldPps, newPps, scroll, anchor);
    expect((newScroll + anchor) / newPps).toBeCloseTo(timeBefore, 9);
  });
  it("never scrolls to a negative position", () => {
    expect(zoomScrollLeft(100, 10, 0, 500)).toBe(0);
  });
  it("reports the visible time range and clip visibility with a margin", () => {
    expect(visibleSeconds(120, 600, 60)).toEqual({ from: 2, to: 12 });
    expect(isVisible(0, 100, 1000, 500)).toBe(false);
    expect(isVisible(800, 100, 1000, 500)).toBe(true);   // just inside the margin
    expect(isVisible(1400, 100, 1000, 500)).toBe(true);
    expect(isVisible(5000, 100, 1000, 500)).toBe(false);
  });
});

describe("ruler", () => {
  it("never puts major labels closer than 90 px", () => {
    for (const pps of [4, 10, 33, 60, 150, 400, 800]) {
      const majors = rulerTicks(pps, 30, 0, 600).filter((t) => t.major);
      const gaps = majors.slice(1).map((t, i) => (t.sec - majors[i]!.sec) * pps);
      expect(Math.min(...gaps), `pps=${pps}`).toBeGreaterThanOrEqual(89.9);
    }
  });
  it("labels majors as minutes:seconds and lands them on whole steps", () => {
    const majors = rulerTicks(60, 30, 0, 130).filter((t) => t.major);
    expect(majors.map((t) => t.label).slice(0, 4)).toEqual(["0:00", "0:02", "0:04", "0:06"]);   // 2 s steps at 60 px/s
    expect(majors.find((t) => t.sec === 120)?.label).toBe("2:00");
  });
  it("uses fractions of a second when zoomed far in, and one tick per frame once frames are wide", () => {
    const fine = rulerTicks(800, 30, 0, 2);
    expect(fine.find((t) => t.major && t.sec > 0)?.label).toMatch(/^\d:\d\d\.\d$/);
    const spacing = fine[2]!.sec - fine[1]!.sec;
    expect(spacing).toBeCloseTo(1 / 30, 9);                                                       // 26 px per frame: every frame ticks
    const coarse = rulerTicks(60, 30, 0, 5);
    expect(coarse[2]!.sec - coarse[1]!.sec).toBeGreaterThan(1 / 30);
  });
  it("only generates ticks for the requested range", () => {
    const t = rulerTicks(60, 30, 100, 110);
    expect(t.length).toBeLessThan(120);
    expect(t[0]!.sec).toBeLessThanOrEqual(100);
    expect(t[t.length - 1]!.sec).toBeGreaterThanOrEqual(110);
  });
});

describe("waveform columns", () => {
  const peaks = [0, 10, 20, 255, 30, 0, 0, 5]; // 4 peaks per second -> 2 s
  it("takes the maximum under each column", () => {
    expect(peakColumns(peaks, 4, 0, 2, 2)).toEqual([255, 30]);   // columns cover peaks 0-3 and 4-7
    expect(peakColumns(peaks, 4, 0, 2, 8)).toEqual(peaks);
  });
  it("handles ranges outside the data and degenerate input", () => {
    expect(peakColumns(peaks, 4, 5, 6, 4)).toEqual([0, 0, 0, 0]);
    expect(peakColumns(peaks, 4, 1, 1, 4)).toEqual([0, 0, 0, 0]);
    expect(peakColumns(peaks, 4, 0, 2, 0)).toEqual([]);
    expect(peakColumns([], 100, 0, 1, 3)).toEqual([0, 0, 0]);
  });
  it("picks the fine level only when zoomed in", () => {
    expect(peakRate(20)).toBe("10");
    expect(peakRate(40)).toBe("100");
  });
});

describe("filmstrip", () => {
  const base = { clipLeftPx: 0, clipWidthPx: 400, inPointSec: 0, pps: 100, interval: 0.5, count: 20, tilePx: 80, scrollLeft: 0, viewportPx: 1000 };
  it("fills a clip with fixed-width tiles, each showing the nearest thumbnail", () => {
    const slots = filmSlots(base);
    expect(slots).toHaveLength(5);                                          // 400 px / 80 px
    expect(slots.map((s) => s.x)).toEqual([0, 80, 160, 240, 320]);
    expect(slots.map((s) => s.index)).toEqual([0, 2, 3, 5, 6]);              // slot k is at k*0.8 s: round(t / 0.5), 0.8 -> 2, 1.6 -> 3, ...
  });
  it("starts from the in-point of the clip and never runs past the sprite", () => {
    const slots = filmSlots({ ...base, inPointSec: 8, clipWidthPx: 800 });
    expect(slots[0]!.index).toBe(16);
    expect(Math.max(...slots.map((s) => s.index))).toBe(19);                 // clamped to count - 1
  });
  it("only produces tiles near the viewport", () => {
    const slots = filmSlots({ ...base, clipWidthPx: 100_000, scrollLeft: 50_000, viewportPx: 800, clipLeftPx: 0 });
    expect(slots.length).toBeLessThan(25);
    expect(slots[0]!.x).toBeGreaterThan(49_000);
  });
  it("returns nothing when there is nothing to draw", () => {
    expect(filmSlots({ ...base, count: 0 })).toEqual([]);
    expect(filmSlots({ ...base, tilePx: 0 })).toEqual([]);
  });
});

describe("track order", () => {
  it("draws captions first, then pictures with the top layer first, then audio", () => {
    const tracks = [
      { id: "V1", kind: "video" }, { id: "V2", kind: "video" }, { id: "A1", kind: "audio" },
      { id: "A2", kind: "audio" }, { id: "C1", kind: "caption" },
    ];
    expect(displayOrder(tracks).map((t) => t.id)).toEqual(["C1", "V2", "V1", "A1", "A2"]);
  });
});
