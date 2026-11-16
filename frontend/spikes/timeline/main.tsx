// Spike for decision D4: can a DOM + pointer-events timeline (React + zustand) drag smoothly with
// hundreds of clips? Built the way the real one would be: memoised clips, snapping on every move.
// Not product code. Run: `npm run dev`, open /spikes/timeline/index.html?n=300
import { memo, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { create } from "zustand";

interface Clip { id: number; track: number; start: number; dur: number } // seconds
interface State {
  clips: Record<number, Clip>;
  pxPerSec: number;
  guide: number | null; // snap guide (seconds)
  move: (id: number, start: number) => void;
}

const params = new URLSearchParams(location.search);
const N = +(params.get("n") ?? 300), TRACKS = 8;

function seed(): Record<number, Clip> {
  const clips: Record<number, Clip> = {};
  let rnd = 12345; const r = () => ((rnd = (rnd * 1664525 + 1013904223) % 4294967296) / 4294967296);
  const cursor = new Array(TRACKS).fill(0);
  for (let i = 0; i < N; i++) {
    const track = i % TRACKS, dur = 1 + r() * 5;
    clips[i] = { id: i, track, start: cursor[track] + r() * 0.5, dur };
    cursor[track] = clips[i]!.start + dur;
  }
  return clips;
}

const SNAP_PX = 8;
const useTimeline = create<State>((set, get) => ({
  clips: seed(), pxPerSec: 60, guide: null,
  move: (id, start) => {
    const { clips, pxPerSec } = get();
    const c = clips[id]!;
    const tol = SNAP_PX / pxPerSec;
    let best = start, bestD = tol, guide: number | null = null;
    for (const o of Object.values(clips)) {            // snap start/end to every other clip's edges (O(n) per move)
      if (o.id === id) continue;
      for (const edge of [o.start, o.start + o.dur]) {
        for (const cand of [edge, edge - c.dur]) {
          const d = Math.abs(cand - start);
          if (d < bestD) { bestD = d; best = cand; guide = edge; }
        }
      }
    }
    set({ clips: { ...clips, [id]: { ...c, start: Math.max(0, best) } }, guide });
  },
}));

const ClipView = memo(function ClipView({ id }: { id: number }) {
  const clip = useTimeline((s) => s.clips[id]!);
  const pxPerSec = useTimeline((s) => s.pxPerSec);
  const onDown = (e: React.PointerEvent) => {
    e.preventDefault();
    const x0 = e.clientX, s0 = clip.start;
    let raf = 0, lastX = x0;
    const onMove = (ev: PointerEvent) => {
      lastX = ev.clientX;
      if (raf) return;                                   // at most one store update per frame
      raf = requestAnimationFrame(() => { raf = 0; useTimeline.getState().move(id, s0 + (lastX - x0) / pxPerSec); });
    };
    const onUp = () => { window.removeEventListener("pointermove", onMove); window.removeEventListener("pointerup", onUp); useTimeline.setState({ guide: null }); };
    window.addEventListener("pointermove", onMove); window.addEventListener("pointerup", onUp);
  };
  return (
    <div data-clip={id} onPointerDown={onDown}
      style={{ position: "absolute", top: clip.track * 40 + 4, height: 32, left: clip.start * pxPerSec, width: clip.dur * pxPerSec,
        background: `hsl(${(id * 37) % 360} 55% 55%)`, borderRadius: 4, fontSize: 11, color: "#fff", overflow: "hidden", cursor: "grab", userSelect: "none" }}>
      clip {id}
    </div>
  );
});

function App() {
  const ids = Object.keys(useTimeline.getState().clips).map(Number);
  const pxPerSec = useTimeline((s) => s.pxPerSec);
  const guide = useTimeline((s) => s.guide);
  useEffect(() => { (window as unknown as { ready: boolean }).ready = true; }, []);
  const end = Math.max(...Object.values(useTimeline.getState().clips).map((c) => c.start + c.dur));
  return (
    <div style={{ position: "relative", width: end * pxPerSec + 200, height: TRACKS * 40 + 30, marginTop: 30, background: "#222" }}>
      {Array.from({ length: Math.ceil(end / 5) }, (_, i) => (
        <div key={i} style={{ position: "absolute", left: i * 5 * pxPerSec, top: -24, fontSize: 10, color: "#888" }}>{i * 5}s</div>
      ))}
      {ids.map((id) => <ClipView key={id} id={id} />)}
      {guide !== null && <div style={{ position: "absolute", left: guide * pxPerSec, top: 0, bottom: 0, width: 1, background: "#ff0" }} />}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
