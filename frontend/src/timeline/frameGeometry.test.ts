import { describe, expect, it } from "vitest";
import type { TimelineTransform } from "../api/types";
import { cropEdge, layerBox, moveBy, rotateBy, scaleBy, toLocal } from "./frameGeometry";

const T = (o: Partial<TimelineTransform> = {}): TimelineTransform => ({ x: 0, y: 0, scale: 1, rotation: 0, opacity: 1, crop: [0, 0, 0, 0], ...o });
const W = 960;
const H = 540;

describe("frame geometry", () => {
  it("a default picture fills the frame; size and position follow the transform", () => {
    expect(layerBox(T(), W, H)).toEqual({ cx: 480, cy: 270, w: 960, h: 540, rot: 0 });
    expect(layerBox(T({ scale: 0.5, x: 0.25, y: -0.1 }), W, H)).toEqual({ cx: 720, cy: 216, w: 480, h: 270, rot: 0 });
  });
  it("a cropped picture keeps the remaining part where it was (its centre moves, its size shrinks)", () => {
    const b = layerBox(T({ crop: [0.25, 0, 0, 0] }), W, H);
    expect(b).toMatchObject({ cx: 480 + 0.125 * 960, w: 720, h: 540 });
    expect(b.cx - b.w / 2).toBeCloseTo(240);                                     // its left edge is the old 25 % line
  });
  it("moves, scales and turns by what the pointer does", () => {
    expect(moveBy(T(), 96, -54, W, H)).toEqual({ x: 0.1, y: -0.1 });
    const box = layerBox(T({ scale: 0.5 }), W, H);
    expect(scaleBy(T({ scale: 0.5 }), box, { x: 720, y: 270 }, { x: 960, y: 270 }).scale).toBeCloseTo(0.5 * (480 / 240));
    expect(rotateBy(T(), box, { x: 480, y: 0 }, { x: 960, y: 270 }).rotation).toBe(90);                 // a quarter turn snaps
    expect(rotateBy(T(), box, { x: 480, y: 0 }, { x: 800, y: 30 }).rotation).toBeCloseTo(53.1, 0);     // otherwise it is exact
  });
  it("points are converted into the turned box's own axes", () => {
    const box = { cx: 100, cy: 100, w: 50, h: 20, rot: 90 };
    const p = toLocal(box, { x: 100, y: 130 });                                  // 30 below the centre = 30 along the box's width after a quarter turn
    expect(p.x).toBeCloseTo(30);
    expect(p.y).toBeCloseTo(0);
  });
  it("dragging a crop edge hides what is beyond it, never more than 90 %", () => {
    expect(cropEdge(T(), "l", { x: 96, y: 0 }, W, H).crop).toEqual([0.1, 0, 0, 0]);
    expect(cropEdge(T({ crop: [0, 0, 0.5, 0] }), "r", { x: 96, y: 0 }, W, H).crop).toEqual([0, 0, 0.4, 0]);   // dragging the right edge to the right shows more
    expect(cropEdge(T({ crop: [0, 0, 0.8, 0] }), "l", { x: 960, y: 0 }, W, H).crop).toEqual([0.1, 0, 0.8, 0]);   // stops at 10 % left; the other edge stays
    expect(cropEdge(T({ scale: 0.5 }), "t", { x: 0, y: 27 }, W, H).crop).toEqual([0, 0.1, 0, 0]);          // relative to the picture's own size
  });
});
