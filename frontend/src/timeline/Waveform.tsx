import { useEffect, useRef } from "react";
import type { Peaks } from "../api/types";
import { peakColumns, peakRate } from "./layout";

interface Props {
  peaks: Peaks;
  inSec: number; // where in the audio file this clip starts
  clipLeftPx: number;
  clipWidthPx: number;
  pps: number;
  scrollLeft: number;
  viewportPx: number;
  height: number;
  gain: number; // the clip's volume: drawn so a quiet clip looks quiet
}

/** Draws only the part of the clip that is on screen (a canvas as wide as a 30-minute clip would be unusable). */
export function Waveform({ peaks, inSec, clipLeftPx, clipWidthPx, pps, scrollLeft, viewportPx, height, gain }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const x0 = Math.max(0, Math.floor(scrollLeft - clipLeftPx - 200));
  const x1 = Math.min(Math.ceil(clipWidthPx), Math.ceil(scrollLeft + viewportPx - clipLeftPx + 200));
  const width = Math.max(1, Math.min(x1 - x0, 4096));

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext?.("2d");
    if (!canvas || !ctx) return;
    const dpr = typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const values = peaks.rates[peakRate(pps)] ?? [];
    const rate = Number(peakRate(pps));
    const cols = peakColumns(values, rate, inSec + x0 / pps, inSec + (x0 + width) / pps, width);
    const mid = height / 2;
    ctx.fillStyle = "rgba(255,255,255,0.8)";
    for (let i = 0; i < cols.length; i++) {
      const h = Math.max(cols[i]! > 0 ? 1 : 0, (cols[i]! / 255) * Math.min(1, gain) * mid);
      if (h > 0) ctx.fillRect(i, mid - h, 1, h * 2);
    }
  }, [peaks, inSec, x0, width, pps, height, gain]);

  return <canvas ref={ref} className="tl-wave" style={{ left: x0, width, height }} aria-hidden="true" />;
}
