import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { api } from "../api/client";
import type { Aspect, FilmMeta, MediaView, Peaks, Project, TimelineAsset, TimelineClip, TimelineTrack, TimelineView } from "../api/types";
import { Filmstrip } from "./Filmstrip";
import { useDerived, useFrame, usePlayhead, useSession, useTimelineData, type PlayheadStore, type Transport } from "./hooks";
import { createPortal } from "react-dom";
import { CanvasHandles } from "./CanvasHandles";
import { Inspector } from "./Inspector";
import { CANVAS_SIZES } from "../preview/LivePreview";
import { MediaBin } from "./MediaBin";
import * as ops from "./ops";
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
  video: Transport | null;
  /** the document being edited, reported whenever it changes (the live preview draws it) */
  onDoc?: (doc: ops.Doc) => void;
  /** where to draw the picture handles (the element around the live preview); null when the live preview is not shown */
  overlayHost?: HTMLElement | null;
  /** the eyedropper: the colour of a clip's own picture at a point of the canvas (canvas pixels), "#rrggbb" or null */
  sampler?: ((clipId: string, x: number, y: number) => string | null) | null;
  /** the focus picker: the point of a clip's own picture (0..1) under a point of the canvas */
  focusSampler?: ((clipId: string, x: number, y: number) => { x: number; y: number } | null) | null;
  /** the preparation state of every asset, whenever it changes */
  onMedia?: (media: Record<string, MediaView>) => void;
  /** called with the project whenever an edit makes the server start (or queue) a new preview render */
  onProject?: (p: Project) => void;
}

const labelOf = (c: TimelineClip, a: TimelineAsset | undefined): string => {
  if (c.kind === "caption") return c.text ?? "";
  const scene = c.meta["text"];
  if (typeof scene === "string" && scene) return scene;
  return a?.title || c.id;
};

export function Timeline({ projectId, version, video, onProject, onDoc, onMedia, overlayHost, sampler, focusSampler }: Props) {
  const { timeline, media, error, preparing, refreshMedia } = useTimelineData(projectId, version, true);
  const { peaks, film } = useDerived(projectId, media);
  useEffect(() => { onMedia?.(media); }, [media, onMedia]);
  if (error && !timeline) return <p className="alert" role="alert">{error}</p>;   // once it is loaded, a failed refresh must not replace the editor
  if (!timeline) return <p className="muted">Loading the timeline…</p>;
  return <TimelineBody projectId={projectId} timeline={timeline} media={media} preparing={preparing} peaks={peaks} film={film} video={video} onProject={onProject} onDoc={onDoc} overlayHost={overlayHost} sampler={sampler} focusSampler={focusSampler} refreshMedia={refreshMedia} />;
}

interface BodyProps {
  projectId: string;
  timeline: TimelineView;
  media: Record<string, MediaView>;
  preparing: number;
  peaks: Record<string, Peaks>;
  film: Record<string, FilmMeta>;
  video: Transport | null;
  onDoc?: (doc: ops.Doc) => void;
  onProject?: (p: Project) => void;
  overlayHost?: HTMLElement | null;
  sampler?: ((clipId: string, x: number, y: number) => string | null) | null;
  focusSampler?: ((clipId: string, x: number, y: number) => { x: number; y: number } | null) | null;
  refreshMedia: () => void;
}

function TimelineBody({ projectId, timeline, media, preparing, peaks, film, video, onProject, onDoc, overlayHost, sampler, focusSampler, refreshMedia }: BodyProps) {
  const { session, snap } = useSession(timeline, (body) => api.saveTimeline(projectId, body));
  const doc = snap.doc;
  const fps = doc.fps;
  const [draft, setDraft] = useState<{ id: string; patch: ops.Picture } | null>(null);   // a handle is being dragged
  const [cropMode, setCropMode] = useState(false);
  const [picking, setPicking] = useState(false);   // the eyedropper waits for a click on the preview
  const [pickingFocus, setPickingFocus] = useState(false);   // the focus picker waits for a click on the preview
  const shownDoc = useMemo(() => (draft ? ops.setPicture(doc, draft.id, draft.patch).doc : doc), [doc, draft]);
  useEffect(() => { onDoc?.(shownDoc); }, [shownDoc, onDoc]);
  const duration = Math.max(1, ops.timelineLength(doc));
  const onProjectRef = useRef(onProject);
  onProjectRef.current = onProject;
  // every successful save asks for a new preview (the server merges requests that arrive during a render)
  useEffect(() => {
    session.onSaved = () => void api.renderTimeline(projectId).then((p) => onProjectRef.current?.(p), () => undefined);
  }, [session, projectId]);
  // a newer document from the server (e.g. after a visual was swapped) replaces ours only when we have no edits of our own
  useEffect(() => {
    if (timeline.rev > session.getSnapshot().rev && session.clean) session.reset(timeline);
  }, [timeline, session]);
  const { head, playing, seek, togglePlay } = usePlayhead(video, fps, duration);
  const scrollRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [pps, setPps] = useState(60);
  const [scrollLeft, setScrollLeft] = useState(0);
  const [viewport, setViewport] = useState(800);
  const [selected, setSelected] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [drag, setDrag] = useState<TimelineClip | null>(null); // the clip as it would be if dropped now
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
  const orderRef = useRef<TimelineTrack[]>([]);
  const live = useRef({ doc, pps, fps });
  live.current = { doc, pps, fps };
  const run = useCallback((r: ops.Result) => {
    const err = session.apply(r);
    setNotice(err);
    if (!err && r.ids) setSelected(r.ids[0] ?? null);
    scrollRef.current?.focus({ preventScroll: true }); // a removed or replaced clip must not take the keyboard focus with it
  }, [session]);

  /** Press on a clip (move) or on one of its edges (trim). A press without movement only selects and seeks. */
  const onGrab = useCallback((e: PointerEvent, id: string, mode: "move" | "start" | "end") => {
    if (e.button !== 0) return;
    e.stopPropagation();
    const L = live.current;
    const clip = L.doc.clips.find((c) => c.id === id);
    setSelected(id);
    setNotice(null);
    seek(frameAt(e.clientX));
    if (!clip) return;
    const x0 = e.clientX;
    const y0 = e.clientY;
    const tol = Math.max(1, Math.round((8 / L.pps) * L.fps)); // snap within 8 pixels
    const targets = ops.snapTargets(L.doc, new Set([id]), [head.get()]);
    const snap1 = (edges: number[]) => ops.snapShift(edges, targets, tol)?.shift ?? 0;
    let moved = false;
    let result: ops.Result | null = null;
    const trackAt = (clientY: number): string => {
      const top = (canvasRef.current?.getBoundingClientRect().top ?? 0) + RULER_H;
      let y = clientY - top;
      for (const t of orderRef.current) {
        if (y < ROW_H[t.kind]) return t.id;
        y -= ROW_H[t.kind];
      }
      return clip.track;
    };
    const onMove = (ev: globalThis.PointerEvent) => {
      if (!moved && Math.abs(ev.clientX - x0) < 3 && Math.abs(ev.clientY - y0) < 3) return;
      moved = true;
      const dx = Math.round(((ev.clientX - x0) / L.pps) * L.fps);
      if (mode === "move") {
        let start = clip.start + dx;
        start += snap1([start, start + clip.duration]);
        result = ops.moveClip(L.doc, id, { start, track: trackAt(ev.clientY) });
        if (result.error) result = ops.moveClip(L.doc, id, { start, track: clip.track });
      } else {
        let f = (mode === "start" ? clip.start : clip.start + clip.duration) + dx;
        f += snap1([f]);
        result = ops.trimClip(L.doc, id, mode, f);
      }
      setDrag(result.error ? null : result.doc.clips.find((c) => c.id === id) ?? null);
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      setDrag(null);
      if (moved && result) run({ ...result, ids: result.ids });
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  }, [seek, frameAt, head, run]);
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
    const mod = e.metaKey || e.ctrlKey;
    const k = e.key.toLowerCase();
    const editing: [boolean, () => void][] = [
      [mod && k === "z" && !e.shiftKey, () => session.undo()],
      [(mod && k === "z" && e.shiftKey) || (mod && k === "y"), () => session.redo()],
      [mod && k === "d", () => selected && run(ops.duplicateClip(doc, selected))],
      [e.altKey && !mod && (e.key === "ArrowLeft" || e.key === "ArrowRight"), () => nudge((e.key === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? fps : 1))],
      [!mod && !e.altKey && (e.key === "[" || e.key === "]"), () => selectNeighbour(e.key === "]" ? 1 : -1)],
      [e.key === "Escape" && !!selected, () => { setSelected(null); setNotice("Nothing selected."); }],
      [!mod && k === "s", splitAtPlayhead],
      [!mod && (e.key === "Delete" || e.key === "Backspace") && !e.shiftKey, () => removeSelected(false)],
      [!mod && (e.key === "Delete" || e.key === "Backspace") && e.shiftKey, () => removeSelected(true)],
    ];
    const hit = editing.find(([on]) => on);
    if (hit) {
      e.preventDefault();
      hit[1]();
      return;
    }
    const keys: Record<string, () => void> = {
      ArrowLeft: () => seek(frame - step), ArrowRight: () => seek(frame + step),
      Home: () => seek(0), End: () => seek(duration - 1),
      " ": togglePlay, "+": () => zoomTo(pps * 1.25), "=": () => zoomTo(pps * 1.25), "-": () => zoomTo(pps / 1.25),
      "0": () => zoomTo(fitPps(duration, fps, (scrollRef.current?.clientWidth ?? viewport) - PAD_RIGHT)),
    };
    const act = keys[e.key];
    if (act) {
      e.preventDefault();
      act();
    }
  };

  const splitAtPlayhead = () => {
    const f = head.get();
    const targets = selected ? [selected] : doc.clips.filter((c) => c.start < f && f < ops.clipEnd(c) && !ops.isLocked(doc, c.track)).map((c) => c.id);
    if (targets.length === 0) return setNotice("Put the playhead on a clip to split it.");
    let d = doc;
    const ids: string[] = [];
    for (const id of targets) {
      const r = ops.splitClip(d, id, f);
      if (r.error) { if (selected) return setNotice(r.error); continue; }
      d = r.doc;
      ids.push(...(r.ids ?? []));
    }
    run({ doc: d, ids: ids.length ? [ids[ids.length - 1]!] : [] });
  };
  const removeSelected = (ripple: boolean) => {
    if (!selected) return setNotice("Select a clip first.");
    run(ripple ? ops.rippleDelete(doc, [selected]) : ops.deleteClips(doc, [selected]));
  };
  /** keyboard: move the selected clip by `frames` (it stops at its neighbours) */
  const nudge = (frames: number) => {
    const c = selected ? doc.clips.find((x) => x.id === selected) : undefined;
    if (!c) return setNotice("Select a clip first (press ] to select the next one).");
    run(ops.moveClip(doc, c.id, { start: c.start + frames }));
  };
  /** keyboard: select the previous / next clip (top track first, left to right) and put the playhead at its start */
  const selectNeighbour = (dir: 1 | -1) => {
    const rank = new Map(displayOrder(doc.tracks).map((t, i) => [t.id, i]));
    const all = [...doc.clips].sort((a, b) => (rank.get(a.track) ?? 0) - (rank.get(b.track) ?? 0) || a.start - b.start);
    if (all.length === 0) return;
    const i = all.findIndex((c) => c.id === selected);
    const next = all[(i + dir + all.length) % all.length]!;
    setSelected(next.id);
    seek(next.start);
    const asset = next.asset ? doc.assets[next.asset] : undefined;
    setNotice(`Selected ${labelOf(next, asset) || next.kind} (${next.kind}, track ${doc.tracks.find((t) => t.id === next.track)?.name || next.track}), starts at ${formatTimecode(next.start, fps)}.`);
  };
  const toggleTrack = (id: string, flag: "muted" | "locked" | "duck", value: boolean) => run(ops.setTrackFlag(doc, id, flag, value));

  const order = useMemo(() => displayOrder(doc.tracks), [doc.tracks]);
  orderRef.current = order;
  const shown = useMemo(() => (drag ? doc.clips.map((c) => (c.id === drag.id ? drag : c)) : doc.clips), [doc.clips, drag]);
  const byTrack = useMemo(() => {
    const m = new Map<string, TimelineClip[]>();
    for (const c of shown) (m.get(c.track) ?? m.set(c.track, []).get(c.track)!).push(c);
    return m;
  }, [shown]);
  const contentW = Math.max(viewport, frameToPx(duration, pps, fps)) + PAD_RIGHT;
  const chosen = selected ? doc.clips.find((c) => c.id === selected) ?? null : null;

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
        <span className="tl-group" role="group" aria-label="Edit">
          <button className="btn" type="button" onClick={() => session.undo()} disabled={!snap.canUndo} aria-label="Undo" title="Undo (Ctrl/⌘+Z)">↶</button>
          <button className="btn" type="button" onClick={() => session.redo()} disabled={!snap.canRedo} aria-label="Redo" title="Redo (Ctrl/⌘+Shift+Z)">↷</button>
          <button className="btn" type="button" onClick={splitAtPlayhead} title="Split at the playhead (S)">Split</button>
          <button className="btn" type="button" onClick={() => removeSelected(false)} disabled={!selected} title="Delete the clip and leave a gap (Delete)">Delete</button>
          <button className="btn" type="button" onClick={() => removeSelected(true)} disabled={!selected} title="Delete and close the gap on every track (Shift+Delete)">Ripple delete</button>
          <button className="btn" type="button" onClick={() => selected && run(ops.duplicateClip(doc, selected))} disabled={!selected} title="Duplicate (Ctrl/⌘+D)">Duplicate</button>
          <label className="tl-fmt">Frame <select aria-label="Frame shape" value={doc.aspect ?? "16:9"} onChange={(e) => run(ops.setAspect(doc, e.target.value as Aspect))}>
            {ops.ASPECTS.map((a) => <option key={a} value={a}>{a}</option>)}
          </select></label>
          <label className="tl-fmt">Pictures <select aria-label="Pictures that do not match the frame" value={fitOfAll(doc)} onChange={(e) => e.target.value && run(ops.setFitAll(doc, e.target.value as "fill" | "fit" | "blur"))}>
            <option value="">(mixed)</option><option value="fill">Fill</option><option value="fit">Fit with bars</option><option value="blur">Fit over blur</option>
          </select></label>
          <button className="btn" type="button" onClick={() => run(ops.addTrack(doc, "video"))}>+ Video track</button>
          <button className="btn" type="button" onClick={() => run(ops.addTrack(doc, "audio"))}>+ Audio track</button>
        </span>
        <SaveChip status={snap.status} message={snap.message}
          onReload={() => void api.getTimeline(projectId).then((v) => session.reset(v), (er) => setNotice(er instanceof Error ? er.message : "Reload failed"))}
          onKeepMine={() => void api.getTimeline(projectId).then((v) => session.keepMine(v.rev), (er) => setNotice(er instanceof Error ? er.message : "Could not check the other version"))} />
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
              <button type="button" className="tl-tbtn" aria-pressed={t.muted} aria-label={`Mute ${t.name || t.id}`} title="Mute" onClick={() => toggleTrack(t.id, "muted", !t.muted)}>{t.muted ? "🔇" : "🔊"}</button>
              {t.kind === "audio" && <button type="button" className="tl-tbtn" aria-pressed={!!t.duck} aria-label={`Duck ${t.name || t.id}`} title="Lower this track while the other audio tracks speak (for music under narration)" onClick={() => toggleTrack(t.id, "duck", !t.duck)}>{t.duck ? "⤓" : "–"}</button>}
              {t.kind !== "caption" && !doc.clips.some((c) => c.track === t.id) && <button type="button" className="tl-tbtn" aria-label={`Remove ${t.name || t.id}`} title="Remove this empty track" onClick={() => run(ops.removeTrack(doc, t.id))}>×</button>}
              <button type="button" className="tl-tbtn" aria-pressed={t.locked} aria-label={`Lock ${t.name || t.id}`} title="Lock" onClick={() => toggleTrack(t.id, "locked", !t.locked)}>{t.locked ? "🔒" : "🔓"}</button>
            </div>
          ))}
        </div>

        <div className="tl-scroll" ref={scrollRef} onScroll={onScroll} tabIndex={0} onKeyDown={onKey}
          aria-label="Timeline tracks. Arrow keys move the playhead, space plays, plus and minus zoom, 0 fits. Square brackets select the previous or next clip, Alt and arrow keys move it, S splits, Delete removes.">
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
                    const asset = c.asset ? doc.assets[c.asset] : undefined;
                    return (
                      <ClipView key={c.id} clip={c} asset={asset} label={labelOf(c, asset)} left={left} width={width} height={ROW_H[t.kind]}
                        selected={c.id === selected} onGrab={onGrab}
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

      <p className="small tl-notice" role="status">{notice}</p>
      <MediaBin projectId={projectId} doc={doc} media={media} onInsert={(a, title) => run(ops.insertAsset(doc, a, head.get(), title))}
        onAdded={refreshMedia} onNotice={setNotice} />
      {chosen && <Inspector clip={chosen} doc={doc} onApply={run} cropMode={cropMode} onCropMode={overlayHost ? setCropMode : undefined}
        picking={picking} onPick={overlayHost && sampler ? (on) => { setPicking(on); if (on) setPickingFocus(false); } : undefined}
        pickingFocus={pickingFocus} onPickFocus={overlayHost && focusSampler ? (on) => { setPickingFocus(on); if (on) setPicking(false); } : undefined}
        onSuggestFocus={chosen && chosen.asset && (chosen.kind === "video" || chosen.kind === "image") ? () => void api.suggestFocus(projectId, chosen.asset!).then((f) => run(ops.setFocus(doc, chosen.id, f)), (er) => setNotice(er instanceof Error ? er.message : "No suggestion")) : undefined} />}
      {overlayHost && focusSampler && pickingFocus && chosen && createPortal(
        <div className="pick-layer" role="button" aria-label="Click the part of the picture that must stay in view" tabIndex={0}
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const [W, H] = CANVAS_SIZES[doc.aspect ?? "16:9"] ?? CANVAS_SIZES["16:9"]!;
            const f = focusSampler(chosen.id, ((e.clientX - r.left) / r.width) * W, ((e.clientY - r.top) / r.height) * H);
            setPickingFocus(false);
            if (f) run(ops.setFocus(doc, chosen.id, f));
            else setNotice("The focus only applies to a picture that fills the frame (Fit: fill) and is not zoomed by Ken Burns.");
          }} onKeyDown={(e) => e.key === "Escape" && setPickingFocus(false)} />,
        overlayHost,
      )}
      {overlayHost && sampler && picking && chosen && createPortal(
        <div className="pick-layer" role="button" aria-label="Click the colour to remove" tabIndex={0}
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const [W, H] = CANVAS_SIZES[doc.aspect ?? "16:9"] ?? CANVAS_SIZES["16:9"]!;
            const hex = sampler(chosen.id, ((e.clientX - r.left) / r.width) * W, ((e.clientY - r.top) / r.height) * H);
            setPicking(false);
            if (hex) run(ops.setKey(doc, chosen.id, { color: hex }));
            else setNotice("There is no picture of this clip at that point.");
          }} onKeyDown={(e) => e.key === "Escape" && setPicking(false)} />,
        overlayHost,
      )}
      {overlayHost && !picking && !pickingFocus && chosen && (chosen.kind === "video" || chosen.kind === "image") && createPortal(
        <CanvasHandles clip={chosen} width={(CANVAS_SIZES[doc.aspect ?? "16:9"] ?? CANVAS_SIZES["16:9"]!)[0]} height={(CANVAS_SIZES[doc.aspect ?? "16:9"] ?? CANVAS_SIZES["16:9"]!)[1]}
          cropMode={cropMode} onDraft={(patch) => setDraft(patch ? { id: chosen.id, patch } : null)} onCommit={(patch) => run(ops.setPicture(doc, chosen.id, patch))} />,
        overlayHost,
      )}
      {chosen ? <ClipInfo clip={chosen} asset={chosen.asset ? doc.assets[chosen.asset] : undefined} fps={fps} /> : (
        <p className="muted small">Click the ruler or a track to move the playhead. Drag a clip to move it, drag its edges to trim, press S to split at the playhead, Delete to remove, Ctrl/⌘+Z to undo.</p>
      )}
    </section>
  );
}

/** the `fit` every picture shares, or "" when they differ */
function fitOfAll(doc: ops.Doc): string {
  const fits = new Set(doc.clips.filter((c) => c.kind === "video" || c.kind === "image").map((c) => c.fit ?? "fill"));
  return fits.size === 1 ? [...fits][0]! : "";
}

function SaveChip({ status, message, onReload, onKeepMine }: { status: ops.SaveLike; message: string | null; onReload: () => void; onKeepMine: () => void }) {
  const text = { saved: "All changes saved", dirty: "Unsaved changes…", saving: "Saving…", error: `Could not save (${message ?? "error"}). Trying again…`, conflict: message ?? "Changed elsewhere" }[status];
  return (
    <span className={`tl-chip tl-save tl-save-${status}`} role="status">
      {text}
      {status === "conflict" && (
        <>
          <button className="btn" type="button" onClick={onKeepMine} title="Your edits become the new version; what the other window saved is replaced">Keep my edits</button>
          <button className="btn" type="button" onClick={onReload} title="Load what the other window saved; your unsaved edits are lost">Discard my edits and reload</button>
        </>
      )}
    </span>
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
  onGrab: (e: PointerEvent, id: string, mode: "move" | "start" | "end") => void; projectId: string; pps: number; fps: number; scrollLeft: number; viewport: number;
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
      onPointerDown={(e) => p.onGrab(e, c.id, "move")}
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
      {!tiny && <span className="tl-handle tl-handle-start" aria-hidden="true" onPointerDown={(e) => p.onGrab(e, c.id, "start")} />}
      {!tiny && <span className="tl-handle tl-handle-end" aria-hidden="true" onPointerDown={(e) => p.onGrab(e, c.id, "end")} />}
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
