import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { api } from "../api/client";
import type { FilmMeta, MediaView, Peaks, TimelineAsset, TimelineClip, TimelineTrack, TimelineView } from "../api/types";
import { Filmstrip } from "./Filmstrip";
import { useDerived, useFrame, usePlayhead, useTimelineData, type PlayheadStore } from "./hooks";
import {
  clampPps, displayOrder, fitPps, formatTimecode, frameToPx, isVisible, MAX_PPS, MIN_PPS, pxToFrame, rulerTicks, zoomScrollLeft,
} from "./layout";
import { Waveform } from "./Waveform";

const RULER_H = 30;
const LABEL_W = 132;
const ROW_H: Record<TimelineTrack["kind"], number> = { video: 56, audio: 48, caption: 30 };
const PAD_RIGHT = 120;

interface Props {
  projectId: string;
  /** changes whenever a render finished: the document is read again */
  version: string;
  /** the preview player, kept in sync with the playhead */
  video: HTMLVideoElement | null;
}

const labelOf = (c: TimelineClip, a: TimelineAsset | undefined): string => {
  if (c.kind === "caption") return c.text ?? "";
  const scene = c.meta["text"];
  if (typeof scene === "string" && scene) return scene;
  return a?.title || c.id;
};

export function Timeline({ projectId, version, video }: Props) {
  const { timeline, media, error, preparing } = useTimelineData(projectId, version, true);
  const { peaks, film } = useDerived(projectId, media);
  if (error) return <p className="alert" role="alert">{error}</p>;
  if (!timeline) return <p className="muted">Loading the timeline…</p>;
  return <TimelineBody projectId={projectId} timeline={timeline} media={media} preparing={preparing} peaks={peaks} film={film} video={video} />;
}

interface BodyProps {
  projectId: string;
  timeline: TimelineView;
  media: Record<string, MediaView>;
  preparing: number;
  peaks: Record<string, Peaks>;
  film: Record<string, FilmMeta>;
  video: HTMLVideoElement | null;
}

function TimelineBody({ projectId, timeline, media, preparing, peaks, film, video }: BodyProps) {
  const { fps, duration } = timeline;
  const { head, playing, seek, togglePlay } = usePlayhead(video, fps, duration);
  const scrollRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [pps, setPps] = useState(60);
  const [scrollLeft, setScrollLeft] = useState(0);
  const [viewport, setViewport] = useState(800);
  const [selected, setSelected] = useState<string | null>(null);
  const fitted = useRef(false);

  // measure the scroll area, and fit the whole timeline into it the first time we know the width
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const measure = () => {
      const w = el.clientWidth || 800;
      setViewport(w);
      if (!fitted.current) {
        fitted.current = true;
        setPps(fitPps(duration, fps, w - PAD_RIGHT));
      }
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [duration, fps]);

  const rafScroll = useRef(0);
  const onScroll = useCallback(() => {
    if (rafScroll.current) return;
    rafScroll.current = requestAnimationFrame(() => {
      rafScroll.current = 0;
      setScrollLeft(scrollRef.current?.scrollLeft ?? 0);
    });
  }, []);

  const zoomTo = useCallback(
    (next: number, anchorPx?: number) => {
      const el = scrollRef.current;
      const target = clampPps(next);
      if (!el) return setPps(target);
      const anchor = anchorPx ?? el.clientWidth / 2;
      const left = zoomScrollLeft(pps, target, el.scrollLeft, anchor);
      setPps(target);
      requestAnimationFrame(() => {
        el.scrollLeft = left;
        setScrollLeft(left);
      });
    },
    [pps],
  );

  // ctrl/cmd + wheel (and trackpad pinch) zooms around the pointer; a plain wheel scrolls as usual
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      zoomTo(pps * Math.exp(-e.deltaY * 0.01), e.clientX - el.getBoundingClientRect().left);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [pps, zoomTo]);

  const frameAt = useCallback(
    (clientX: number) => pxToFrame(clientX - (canvasRef.current?.getBoundingClientRect().left ?? 0), pps, fps),
    [pps, fps],
  );
  // stable, so memoised clips are not re-rendered by unrelated state (playing is no longer one of them anyway)
  const selectAt = useCallback((id: string, clientX: number) => { setSelected(id); seek(frameAt(clientX)); }, [seek, frameAt]);
  const scrub = useRef(false);
  const onSeekDown = (e: PointerEvent) => {
    if (e.button !== 0) return;
    scrub.current = true;
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    seek(frameAt(e.clientX));
  };
  const onSeekMove = (e: PointerEvent) => {
    if (scrub.current) seek(frameAt(e.clientX));
  };
  const onSeekUp = () => {
    scrub.current = false;
  };

  const onKey = (e: KeyboardEvent) => {
    const frame = head.get();
    const step = e.shiftKey ? fps : 1;
    const keys: Record<string, () => void> = {
      ArrowLeft: () => seek(frame - step), ArrowRight: () => seek(frame + step),
      Home: () => seek(0), End: () => seek(duration - 1),
      " ": togglePlay, "+": () => zoomTo(pps * 1.25), "=": () => zoomTo(pps * 1.25), "-": () => zoomTo(pps / 1.25),
      "0": () => zoomTo(fitPps(duration, fps, (scrollRef.current?.clientWidth ?? viewport) - PAD_RIGHT)),
    };
    const run = keys[e.key];
    if (run) {
      e.preventDefault();
      run();
    }
  };

  const order = useMemo(() => displayOrder(timeline.tracks), [timeline.tracks]);
  const byTrack = useMemo(() => {
    const m = new Map<string, TimelineClip[]>();
    for (const c of timeline.clips) (m.get(c.track) ?? m.set(c.track, []).get(c.track)!).push(c);
    return m;
  }, [timeline.clips]);
  const contentW = Math.max(viewport, frameToPx(duration, pps, fps)) + PAD_RIGHT;
  const chosen = selected ? timeline.clips.find((c) => c.id === selected) ?? null : null;

  const from = Math.max(0, (scrollLeft - 100) / pps);
  const to = (scrollLeft + viewport + 100) / pps;
  const ticks = useMemo(() => rulerTicks(pps, fps, from, to), [pps, fps, from, to]);
  const totalH = RULER_H + order.reduce((n, t) => n + ROW_H[t.kind], 0);

  return (
    <section className="tl" aria-label="Timeline">
      <div className="tl-toolbar">
        <button className="btn" type="button" onClick={togglePlay} disabled={!video} aria-label={playing ? "Pause" : "Play"}>{playing ? "❚❚" : "▶"}</button>
        {/* role=timer is not a live region: an <output> would make screen readers announce every frame */}
        <Timecode head={head} fps={fps} duration={duration} />
        <span className="tl-spacer" />
        {preparing > 0 && <span className="tl-chip" role="status">Preparing previews ({preparing} left)…</span>}
        <button className="btn" type="button" onClick={() => zoomTo(pps / 1.25)} aria-label="Zoom out">−</button>
        <input type="range" className="tl-zoom" aria-label="Zoom" min={Math.log(MIN_PPS)} max={Math.log(MAX_PPS)} step={0.01} value={Math.log(pps)}
          aria-valuetext={`${Math.round(pps)} pixels per second`} onChange={(e) => zoomTo(Math.exp(Number(e.target.value)))} />
        <button className="btn" type="button" onClick={() => zoomTo(pps * 1.25)} aria-label="Zoom in">+</button>
        <button className="btn" type="button" onClick={() => zoomTo(fitPps(duration, fps, (scrollRef.current?.clientWidth ?? viewport) - PAD_RIGHT))}>Fit</button>
      </div>

      <div className="tl-body" style={{ height: totalH }}>
        <div className="tl-labels" style={{ width: LABEL_W }}>
          <div style={{ height: RULER_H }} />
          {order.map((t) => (
            <div key={t.id} className={`tl-label${t.muted ? " tl-muted" : ""}`} style={{ height: ROW_H[t.kind] }}>
              <span className="tl-kind" aria-hidden="true">{t.kind === "video" ? "▣" : t.kind === "audio" ? "♪" : "T"}</span>
              <span className="tl-name">{t.name || t.id}</span>
              {t.muted && <span className="tl-tag">muted</span>}
              {t.locked && <span className="tl-tag">locked</span>}
            </div>
          ))}
        </div>

        <div className="tl-scroll" ref={scrollRef} onScroll={onScroll} tabIndex={0} onKeyDown={onKey}
          aria-label="Timeline tracks. Arrow keys move the playhead, space plays, plus and minus zoom, 0 fits.">
          <div className="tl-canvas" ref={canvasRef} style={{ width: contentW, height: totalH }}>
            <div className="tl-ruler" style={{ height: RULER_H }} onPointerDown={onSeekDown} onPointerMove={onSeekMove} onPointerUp={onSeekUp} aria-hidden="true">
              {ticks.map((t) => (
                <span key={t.sec} className={t.major ? "tl-tick tl-major" : "tl-tick"} style={{ left: t.sec * pps }}>
                  {t.label && <span className="tl-ticklabel">{t.label}</span>}
                </span>
              ))}
            </div>

            {order.map((t, i) => {
              const top = RULER_H + order.slice(0, i).reduce((n, x) => n + ROW_H[x.kind], 0);
              return (
                <div key={t.id} className={`tl-track tl-${t.kind}${t.muted ? " tl-muted" : ""}`} style={{ top, height: ROW_H[t.kind] }}
                  onPointerDown={onSeekDown} onPointerMove={onSeekMove} onPointerUp={onSeekUp} data-track={t.id}>
                  {(byTrack.get(t.id) ?? []).map((c) => {
                    const left = frameToPx(c.start, pps, fps);
                    const width = Math.max(2, frameToPx(c.duration, pps, fps));
                    if (!isVisible(left, width, scrollLeft, viewport, 600)) return null;
                    const asset = c.asset ? timeline.assets[c.asset] : undefined;
                    return (
                      <ClipView key={c.id} clip={c} asset={asset} label={labelOf(c, asset)} left={left} width={width} height={ROW_H[t.kind]}
                        selected={c.id === selected} onSelect={selectAt}
                        projectId={projectId} pps={pps} fps={fps} scrollLeft={scrollLeft} viewport={viewport}
                        media={asset ? media[asset.id] : undefined} peaks={asset ? peaks[asset.id] : undefined} film={asset ? film[asset.id] : undefined} />
                    );
                  })}
                </div>
              );
            })}

            <PlayheadLine head={head} pps={pps} fps={fps} height={totalH} playing={playing} scrollRef={scrollRef} onScrolled={setScrollLeft} />
          </div>
        </div>
      </div>

      {chosen ? <ClipInfo clip={chosen} asset={chosen.asset ? timeline.assets[chosen.asset] : undefined} fps={fps} /> : (
        <p className="muted small">Click the ruler or a track to move the playhead; click a clip to see what it is. Editing arrives in the next task.</p>
      )}
    </section>
  );
}

/** The only things that change on every frame while playing: kept tiny and subscribed to the playhead store. */
function Timecode({ head, fps, duration }: { head: PlayheadStore; fps: number; duration: number }) {
  const frame = useFrame(head);
  // role=timer is not a live region: an <output> would make screen readers announce every frame
  return (
    <div className="tl-timecode" role="timer" aria-live="off" aria-label="Playhead position">
      {formatTimecode(frame, fps)} <span className="muted">/ {formatTimecode(duration, fps)}</span>
    </div>
  );
}

function PlayheadLine({ head, pps, fps, height, playing, scrollRef, onScrolled }: {
  head: PlayheadStore; pps: number; fps: number; height: number; playing: boolean;
  scrollRef: React.RefObject<HTMLDivElement | null>; onScrolled: (left: number) => void;
}) {
  const x = frameToPx(useFrame(head), pps, fps);
  useEffect(() => {  // while playing, keep the playhead on screen
    const el = scrollRef.current;
    if (!playing || !el) return;
    if (x > el.scrollLeft + el.clientWidth - 40 || x < el.scrollLeft) {
      el.scrollLeft = Math.max(0, x - 80);
      onScrolled(el.scrollLeft);
    }
  }, [playing, x, scrollRef, onScrolled]);
  return <div className="tl-playhead" style={{ left: x, height }} aria-hidden="true"><span className="tl-playhead-head" /></div>;
}

interface ClipProps {
  clip: TimelineClip; asset: TimelineAsset | undefined; label: string; left: number; width: number; height: number; selected: boolean;
  onSelect: (id: string, clientX: number) => void; projectId: string; pps: number; fps: number; scrollLeft: number; viewport: number;
  media: MediaView | undefined; peaks: Peaks | undefined; film: FilmMeta | undefined;
}

const ClipView = memo(function ClipView(p: ClipProps) {
  const { clip: c, asset, label, left, width, height, media, peaks, film } = p;
  const inSec = c.in_point / p.fps;
  const scroll = p.scrollLeft;
  const tiny = width < 8; // too narrow to see anything inside: just the coloured block
  return (
    <div
      className={`tl-clip tl-clip-${c.kind}${p.selected ? " tl-selected" : ""}`}
      style={{ left, width }}
      role="button" tabIndex={-1} aria-pressed={p.selected}
      aria-label={`${label || c.kind}, ${c.kind} clip, starts ${formatTimecode(c.start, p.fps)}, lasts ${formatTimecode(c.duration, p.fps)}`}
      data-clip={c.id}
      onPointerDown={(e) => { e.stopPropagation(); p.onSelect(c.id, e.clientX); }}
    >
      {!tiny && c.kind === "video" && media?.derived.includes("film") && film && (
        <Filmstrip url={api.filmUrl(p.projectId, asset!.id)} meta={film} inSec={inSec} clipLeftPx={left} clipWidthPx={width} pps={p.pps}
          scrollLeft={scroll} viewportPx={p.viewport} height={height - 2} />
      )}
      {!tiny && c.kind === "image" && media?.derived.includes("proxy") && (
        <span className="tl-image" aria-hidden="true" style={{ backgroundImage: `url("${api.mediaProxyUrl(p.projectId, asset!.id)}")`, backgroundSize: `auto ${height - 2}px` }} />
      )}
      {!tiny && c.kind === "audio" && peaks && (
        <Waveform peaks={peaks} inSec={inSec} clipLeftPx={left} clipWidthPx={width} pps={p.pps} scrollLeft={scroll} viewportPx={p.viewport}
          height={height - 2} gain={c.volume} />
      )}
      {!tiny && <span className="tl-cliplabel" dir="auto">{label}</span>}
      {!tiny && c.loop && <span className="tl-tag tl-loop" title="This video repeats to fill the clip">⟳</span>}
    </div>
  );
});

function ClipInfo({ clip: c, asset, fps }: { clip: TimelineClip; asset: TimelineAsset | undefined; fps: number }) {
  const tc = (f: number) => formatTimecode(f, fps);
  return (
    <dl className="tl-info" aria-label="Selected clip">
      <div><dt>Clip</dt><dd dir="auto">{labelOf(c, asset)}</dd></div>
      <div><dt>Type</dt><dd>{c.kind}</dd></div>
      <div><dt>Start</dt><dd>{tc(c.start)}</dd></div>
      <div><dt>Length</dt><dd>{tc(c.duration)}</dd></div>
      {c.kind !== "caption" && c.kind !== "image" && <div><dt>From source</dt><dd>{tc(c.in_point)}{c.loop ? " (repeats)" : ""}</dd></div>}
      {c.kind === "audio" && <div><dt>Volume</dt><dd>{Math.round(c.volume * 100)}%</dd></div>}
      {asset && <div><dt>Media</dt><dd dir="auto">{asset.title || asset.id} · {asset.source || "–"} · {asset.license}{asset.attribution_required && asset.author ? ` · by ${asset.author}` : ""}</dd></div>}
    </dl>
  );
}
