import { useRef, useState, type PointerEvent } from "react";
import type { TimelineClip } from "../api/types";
import { cropEdge, layerBox, moveBy, rotateBy, scaleBy, toLocal, type Box, type Edge, type Pt } from "./frameGeometry";
import type { Picture } from "./ops";

interface Props {
  clip: TimelineClip;
  /** frame size in pixels (the canvas' own size) */
  width: number;
  height: number;
  cropMode: boolean;
  /** while dragging: what the picture would look like (null when the drag ends) */
  onDraft: (patch: Picture | null) => void;
  /** the drag ended: make it an edit */
  onCommit: (patch: Picture) => void;
}

type Mode = { kind: "move" } | { kind: "scale" } | { kind: "rotate" } | { kind: "crop"; edge: Edge };

/** Handles drawn over the live preview for the selected picture: drag it to move, a corner to resize, the round handle to turn it. */
export function CanvasHandles({ clip, width: W, height: H, cropMode, onDraft, onCommit }: Props) {
  const svg = useRef<SVGSVGElement>(null);
  const [live, setLive] = useState<Picture | null>(null);
  const t = { ...clip.transform, ...(live ?? {}) };
  const box = layerBox(t, W, H);

  const point = (e: PointerEvent): Pt => {
    const r = svg.current!.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * W, y: ((e.clientY - r.top) / r.height) * H };
  };

  const start = (mode: Mode) => (e: PointerEvent) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault();
    const from = point(e);
    const t0 = clip.transform;
    const box0: Box = layerBox(t0, W, H);
    const target = e.currentTarget as Element;
    target.setPointerCapture?.(e.pointerId);
    let last: Picture | null = null;
    const patchAt = (p: Pt): Picture => {
      switch (mode.kind) {
        case "move": return moveBy(t0, p.x - from.x, p.y - from.y, W, H);
        case "scale": return scaleBy(t0, box0, from, p);
        case "rotate": return rotateBy(t0, box0, from, p);
        case "crop": { const a = toLocal(box0, from); const b = toLocal(box0, p); return cropEdge(t0, mode.edge, { x: b.x - a.x, y: b.y - a.y }, W, H); }
      }
    };
    const move = (ev: globalThis.PointerEvent) => {
      const r = svg.current!.getBoundingClientRect();
      last = patchAt({ x: ((ev.clientX - r.left) / r.width) * W, y: ((ev.clientY - r.top) / r.height) * H });
      setLive(last);
      onDraft(last);
    };
    const up = () => {
      target.removeEventListener("pointermove", move as EventListener);
      target.removeEventListener("pointerup", up);
      target.removeEventListener("pointercancel", up);
      setLive(null);
      onDraft(null);
      if (last && Object.keys(last).length) onCommit(last);
    };
    target.addEventListener("pointermove", move as EventListener);
    target.addEventListener("pointerup", up);
    target.addEventListener("pointercancel", up);
  };

  const hw = box.w / 2;
  const hh = box.h / 2;
  const R = Math.max(7, W / 90); // handle size in frame pixels
  const corners: [number, number][] = [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]];
  const edges: { edge: Edge; x: number; y: number; w: number; h: number }[] = [
    { edge: "l", x: -hw - R / 2, y: -hh / 2, w: R, h: hh }, { edge: "r", x: hw - R / 2, y: -hh / 2, w: R, h: hh },
    { edge: "t", x: -hw / 2, y: -hh - R / 2, w: hw, h: R }, { edge: "b", x: -hw / 2, y: hh - R / 2, w: hw, h: R },
  ];
  return (
    <svg ref={svg} className="canvas-handles" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-label="Handles for the selected picture" role="group">
      <g transform={`translate(${box.cx} ${box.cy}) rotate(${box.rot})`}>
        <rect x={-hw} y={-hh} width={box.w} height={box.h} className="ch-box" onPointerDown={start({ kind: "move" })} data-handle="move" />
        {!cropMode && corners.map(([x, y], i) => (
          <rect key={i} x={x - R} y={y - R} width={2 * R} height={2 * R} className="ch-corner" data-handle="scale" onPointerDown={start({ kind: "scale" })} />
        ))}
        {!cropMode && (
          <>
            <line x1={0} y1={-hh} x2={0} y2={-hh - 4 * R} className="ch-stem" />
            <circle cx={0} cy={-hh - 4 * R} r={R} className="ch-rotate" data-handle="rotate" onPointerDown={start({ kind: "rotate" })} />
          </>
        )}
        {cropMode && edges.map((e) => (
          <rect key={e.edge} x={e.x} y={e.y} width={e.w} height={e.h} className="ch-edge" data-handle={`crop-${e.edge}`} onPointerDown={start({ kind: "crop", edge: e.edge })} />
        ))}
      </g>
    </svg>
  );
}
