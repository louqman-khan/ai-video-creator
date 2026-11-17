// Pure layout maths for the timeline (no DOM): frames <-> pixels, ruler ticks, zoom anchoring, waveform columns.
// Everything is in integer FRAMES on the document side; "pps" is the zoom in pixels per second.

export const MIN_PPS = 4;
export const MAX_PPS = 800;

export const clampPps = (v: number): number => Math.min(MAX_PPS, Math.max(MIN_PPS, v));
export const frameToPx = (frame: number, pps: number, fps: number): number => (frame * pps) / fps;
export const pxToFrame = (px: number, pps: number, fps: number): number => Math.round((px * fps) / pps);

/** 75 frames at 30 fps -> "00:02:15" (minutes:seconds:frames); one hour or more -> "1:00:02:15". */
export function formatTimecode(frame: number, fps: number): string {
  const f = Math.max(0, Math.round(frame));
  const total = Math.floor(f / fps);
  const ff = f - total * fps;
  const s = total % 60;
  const m = Math.floor(total / 60) % 60;
  const h = Math.floor(total / 3600);
  const two = (n: number) => String(n).padStart(2, "0");
  return `${h > 0 ? `${h}:` : ""}${two(m)}:${two(s)}:${two(ff)}`;
}

/** The zoom at which the whole timeline fits the viewport. */
export function fitPps(durationFrames: number, fps: number, viewportPx: number): number {
  const seconds = durationFrames / fps;
  return seconds > 0 && viewportPx > 0 ? clampPps(viewportPx / seconds) : 60;
}

/** New scrollLeft after a zoom, keeping the time under `anchorPx` (a position inside the viewport) fixed. */
export function zoomScrollLeft(oldPps: number, newPps: number, scrollLeft: number, anchorPx: number): number {
  return Math.max(0, ((scrollLeft + anchorPx) * newPps) / oldPps - anchorPx);
}

export const visibleSeconds = (scrollLeft: number, viewportPx: number, pps: number) => ({
  from: scrollLeft / pps,
  to: (scrollLeft + viewportPx) / pps,
});

export function isVisible(left: number, width: number, scrollLeft: number, viewportPx: number, margin = 240): boolean {
  return left + width >= scrollLeft - margin && left <= scrollLeft + viewportPx + margin;
}

export interface Tick {
  sec: number;
  major: boolean;
  label: string | null;
}

const NICE_STEPS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600];
const MAJOR_MIN_PX = 90; // never closer than this
const MINOR_MIN_PX = 9;

function rulerLabel(sec: number, step: number): string {
  const m = Math.floor(sec / 60);
  const s = sec - m * 60;
  const secs = step < 1 ? s.toFixed(1).padStart(4, "0") : String(Math.round(s)).padStart(2, "0");
  return `${m}:${secs}`;
}

/** Ticks covering [fromSec, toSec]: majors with labels at a "nice" spacing, minors between them, and
 *  one tick per frame once frames are far enough apart to tell. */
export function rulerTicks(pps: number, fps: number, fromSec: number, toSec: number): Tick[] {
  const step = NICE_STEPS.find((s) => s * pps >= MAJOR_MIN_PX) ?? NICE_STEPS[NICE_STEPS.length - 1]!;
  const frameTicks = pps / fps >= MINOR_MIN_PX;
  const minorStep = frameTicks ? 1 / fps : [5, 4, 2].map((d) => step / d).find((m) => m * pps >= MINOR_MIN_PX) ?? step;
  const ticks: Tick[] = [];
  const first = Math.max(0, Math.floor(fromSec / minorStep) - 1);
  const last = Math.ceil(toSec / minorStep) + 1;
  for (let i = first; i <= last; i++) {
    const sec = i * minorStep;
    const onMajor = Math.abs(sec / step - Math.round(sec / step)) < 1e-6;
    ticks.push({ sec, major: onMajor, label: onMajor ? rulerLabel(Math.round(sec / step) * step, step) : null });
  }
  return ticks;
}

/** Peaks (0-255, `rate` per second) -> one value per pixel column across [startSec, endSec]. */
export function peakColumns(peaks: number[], rate: number, startSec: number, endSec: number, columns: number): number[] {
  const out = new Array<number>(Math.max(0, columns)).fill(0);
  if (columns <= 0 || endSec <= startSec) return out;
  const perCol = ((endSec - startSec) * rate) / columns;
  for (let i = 0; i < columns; i++) {
    const a = Math.floor(startSec * rate + i * perCol);
    const b = Math.max(a + 1, Math.ceil(startSec * rate + (i + 1) * perCol));
    let max = 0;
    for (let k = Math.max(0, a); k < Math.min(peaks.length, b); k++) if (peaks[k]! > max) max = peaks[k]!;
    out[i] = max;
  }
  return out;
}

/** Which peak resolution to use at this zoom: the fine one once a second is wide enough to need it. */
export const peakRate = (pps: number): "100" | "10" => (pps >= 40 ? "100" : "10");

/** Filmstrip: thumbnails are drawn at a fixed pixel width; slot k shows the thumbnail nearest to its time. */
export function filmSlots(args: {
  clipLeftPx: number; clipWidthPx: number; inPointSec: number; pps: number;
  interval: number; count: number; tilePx: number; scrollLeft: number; viewportPx: number;
}): { x: number; index: number }[] {
  const { clipLeftPx, clipWidthPx, inPointSec, pps, interval, count, tilePx, scrollLeft, viewportPx } = args;
  if (tilePx <= 0 || count <= 0) return [];
  const from = Math.max(0, Math.floor((scrollLeft - clipLeftPx - 240) / tilePx));
  const to = Math.min(Math.ceil(clipWidthPx / tilePx), Math.ceil((scrollLeft + viewportPx - clipLeftPx + 240) / tilePx));
  const slots: { x: number; index: number }[] = [];
  for (let k = from; k < to; k++) {
    const t = inPointSec + (k * tilePx) / pps;
    slots.push({ x: k * tilePx, index: Math.min(count - 1, Math.max(0, Math.round(t / interval))) });
  }
  return slots;
}

/** Order in which tracks are drawn: captions on top, then pictures (top layer first), then audio. */
export function displayOrder<T extends { kind: string }>(tracks: T[]): T[] {
  return [
    ...tracks.filter((t) => t.kind === "caption"),
    ...tracks.filter((t) => t.kind === "video").reverse(),
    ...tracks.filter((t) => t.kind === "audio"),
  ];
}
