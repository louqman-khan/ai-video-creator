// The maths behind the on-canvas handles. A picture's box is its (cropped, resized) rectangle: centre, size and turn, in
// the pixels of the frame. It mirrors what the renderer does (`_geometry` in render.py): the crop keeps the remaining
// part where it was, the size is relative to the frame, the turn is about the centre of the visible piece.

import type { TimelineTransform } from "../api/types";
import { fixCrop, type Picture } from "./ops";

export interface Pt { x: number; y: number }
export interface Box { cx: number; cy: number; w: number; h: number; rot: number }
export type Edge = "l" | "t" | "r" | "b";

const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

export function layerBox(t: TimelineTransform, W: number, H: number): Box {
  const [l, tp, r, b] = t.crop;
  return {
    cx: W / 2 + t.x * W + ((l - r) / 2) * W * t.scale,
    cy: H / 2 + t.y * H + ((tp - b) / 2) * H * t.scale,
    w: W * (1 - l - r) * t.scale,
    h: H * (1 - tp - b) * t.scale,
    rot: t.rotation,
  };
}

/** A point in the box's own axes (origin at its centre, x along its width). */
export function toLocal(box: Box, p: Pt): Pt {
  const a = rad(-box.rot);
  const dx = p.x - box.cx;
  const dy = p.y - box.cy;
  return { x: dx * Math.cos(a) - dy * Math.sin(a), y: dx * Math.sin(a) + dy * Math.cos(a) };
}

/** Drag the whole picture by a pointer movement of (dx, dy) pixels. */
export function moveBy(t: TimelineTransform, dx: number, dy: number, W: number, H: number): Picture {
  return { x: t.x + dx / W, y: t.y + dy / H };
}

/** Drag a corner: the size follows the pointer's distance from the centre. */
export function scaleBy(t: TimelineTransform, box: Box, from: Pt, to: Pt): Picture {
  const d0 = Math.hypot(from.x - box.cx, from.y - box.cy);
  const d1 = Math.hypot(to.x - box.cx, to.y - box.cy);
  return d0 < 1 ? {} : { scale: t.scale * (d1 / d0) };
}

/** Drag the turn handle: the picture turns by the angle the pointer moved around the centre; near a quarter turn it snaps. */
export function rotateBy(t: TimelineTransform, box: Box, from: Pt, to: Pt): Picture {
  const a0 = Math.atan2(from.y - box.cy, from.x - box.cx);
  const a1 = Math.atan2(to.y - box.cy, to.x - box.cx);
  let r = t.rotation + deg(a1 - a0);
  r = ((r + 180) % 360 + 360) % 360 - 180;
  const snapped = Math.round(r / 90) * 90;
  if (Math.abs(r - snapped) < 3) r = snapped;
  return { rotation: Math.round(r * 10) / 10 };
}

/** Drag an edge in crop mode: the part of the picture beyond the pointer is hidden (or shown again). */
export function cropEdge(t: TimelineTransform, edge: Edge, deltaLocal: Pt, W: number, H: number): Picture {
  const [l, tp, r, b] = t.crop;
  const sw = W * t.scale;
  const sh = H * t.scale;
  const next: [number, number, number, number] = [l, tp, r, b];
  // the edge being dragged stops where 10 % of the picture is left; the opposite edge never moves
  const limit = (v: number, other: number) => Math.min(0.9 - other, Math.max(0, v));
  if (edge === "l") next[0] = limit(l + deltaLocal.x / sw, r);
  if (edge === "r") next[2] = limit(r - deltaLocal.x / sw, l);
  if (edge === "t") next[1] = limit(tp + deltaLocal.y / sh, b);
  if (edge === "b") next[3] = limit(b - deltaLocal.y / sh, tp);
  return { crop: fixCrop(next) };
}
