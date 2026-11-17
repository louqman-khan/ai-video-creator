import { useEffect, useRef } from "react";
import { api } from "../api/client";
import type { MediaView } from "../api/types";
import type { Doc } from "../timeline/ops";
import { LiveEngine } from "./engine";

/** Same sizes as the renderer's preview (`PREVIEW_SIZES`). */
export const CANVAS_SIZES: Record<string, [number, number]> = { "16:9": [960, 540], "9:16": [540, 960], "1:1": [540, 540], "4:5": [560, 700] };

interface Props {
  projectId: string;
  doc: Doc;
  aspect: string;
  /** preparation state of every asset: files that are not ready are not requested */
  media: Record<string, MediaView>;
  /** the engine, once it exists (null again when this component goes away) */
  onEngine: (e: LiveEngine | null) => void;
}

/** The instant preview: the timeline drawn from the proxy files, without waiting for a render. */
export function LivePreview({ projectId, doc, aspect, media, onEngine }: Props) {
  const mediaRef = useRef(media);
  mediaRef.current = media;
  const ref = useRef<HTMLCanvasElement>(null);
  const engine = useRef<LiveEngine | null>(null);
  const first = useRef(doc);
  const [width, height] = CANVAS_SIZES[aspect] ?? CANVAS_SIZES["16:9"]!;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const e = new LiveEngine(canvas, {
      video: (a) => (mediaRef.current[a]?.derived.includes("proxy") ? api.mediaProxyUrl(projectId, a) : null),
      image: (a) => (mediaRef.current[a]?.derived.includes("proxy") ? api.mediaProxyUrl(projectId, a) : null),
      audio: (a) => (mediaRef.current[a]?.derived.includes("audio") ? api.mediaAudioUrl(projectId, a) : null),
    }, first.current);
    engine.current = e;
    (canvas as HTMLCanvasElement & { __engine?: LiveEngine }).__engine = e; // lets the browser tests drive and measure it
    onEngine(e);
    return () => {
      onEngine(null);
      e.dispose();
      engine.current = null;
    };
  }, [projectId, onEngine]);

  useEffect(() => { engine.current?.setDoc(doc); }, [doc, width, height]);
  useEffect(() => { engine.current?.refresh(); }, [media]);

  return (
    <canvas ref={ref} className="player live-canvas" width={width} height={height}
      aria-label="Live preview of the timeline" role="img" />
  );
}
