import { useEffect, useRef } from "react";
import { api } from "../api/client";
import type { Doc } from "../timeline/ops";
import { LiveEngine } from "./engine";

interface Props {
  projectId: string;
  doc: Doc;
  aspect: string;
  /** the engine, once it exists (null again when this component goes away) */
  onEngine: (e: LiveEngine | null) => void;
}

/** The instant preview: the timeline drawn from the proxy files, without waiting for a render. */
export function LivePreview({ projectId, doc, aspect, onEngine }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const engine = useRef<LiveEngine | null>(null);
  const first = useRef(doc);
  const portrait = aspect === "9:16";

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const e = new LiveEngine(canvas, {
      video: (a) => api.mediaProxyUrl(projectId, a),
      image: (a) => api.mediaProxyUrl(projectId, a),
      audio: (a) => api.mediaAudioUrl(projectId, a),
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

  useEffect(() => { engine.current?.setDoc(doc); }, [doc]);

  return (
    <canvas ref={ref} className="player live-canvas" width={portrait ? 540 : 960} height={portrait ? 960 : 540}
      aria-label="Live preview of the timeline" role="img" />
  );
}
