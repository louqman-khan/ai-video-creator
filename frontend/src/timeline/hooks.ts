import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { api } from "../api/client";
import type { FilmMeta, MediaView, Peaks, TimelineView } from "../api/types";
import { EditSession, type Saver } from "./session";

const messageOf = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

/** What the playhead needs from a player: an HTMLVideoElement, or the live preview engine. */
export interface Transport extends EventTarget {
  currentTime: number;
  readonly paused: boolean;
  play(): Promise<void>;
  pause(): void;
}

export interface PlayheadStore {
  get(): number;
  subscribe(listener: () => void): () => void;
}

/**
 * The playhead is the preview video's current time, in frames. It lives OUTSIDE React state: while playing it
 * changes 30-60 times a second, and only the small components that show it (the timecode, the line) may
 * re-render for that, never the clips. Both directions work: playing or scrubbing the video moves the playhead,
 * and `seek` moves the video. Without a video it still holds a position.
 */
export function usePlayhead(video: Transport | null, fps: number, durationFrames: number) {
  const store = useRef<(PlayheadStore & { set(f: number): void }) | null>(null);
  if (!store.current) {
    let value = 0;
    const listeners = new Set<() => void>();
    store.current = {
      get: () => value,
      subscribe: (l) => (listeners.add(l), () => void listeners.delete(l)),
      set: (f) => {
        if (f === value) return;
        value = f;
        listeners.forEach((l) => l());
      },
    };
  }
  const head = store.current;
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (!video) {
      setPlaying(false);
      return;
    }
    let raf = 0;
    const read = () => head.set(Math.round(video.currentTime * fps));
    const loop = () => {
      read();
      raf = requestAnimationFrame(loop);
    };
    const onPlay = () => {
      setPlaying(true);
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(loop);
    };
    const onStop = () => {
      setPlaying(false);
      cancelAnimationFrame(raf);
      read();
    };
    const events: [string, () => void][] = [["play", onPlay], ["pause", onStop], ["ended", onStop], ["seeked", read], ["timeupdate", read], ["loadedmetadata", read]];
    events.forEach(([e, h]) => video.addEventListener(e, h));
    read();
    if (!video.paused) onPlay();
    return () => {
      cancelAnimationFrame(raf);
      events.forEach(([e, h]) => video.removeEventListener(e, h));
    };
  }, [video, fps, head]);

  const last = Math.max(0, durationFrames - 1);
  const seek = useCallback(
    (target: number) => {
      const f = Math.min(last, Math.max(0, Math.round(target)));
      head.set(f);
      if (video) video.currentTime = f / fps;
    },
    [video, fps, last, head],
  );
  const togglePlay = useCallback(() => {
    if (!video) return;
    if (video.paused) void video.play().catch(() => undefined);
    else video.pause();
  }, [video]);

  return { head: head as PlayheadStore, playing, seek, togglePlay };
}

/** Subscribes the calling component (only) to the playhead. */
export function useFrame(head: PlayheadStore): number {
  return useSyncExternalStore(head.subscribe, head.get, head.get);
}

/** The timeline document plus the state of its prepared media (polled until everything is ready or failed). */
export function useTimelineData(projectId: string, version: string, enabled: boolean, pollMs = 1500) {
  const [timeline, setTimeline] = useState<TimelineView | null>(null);
  const [media, setMedia] = useState<Record<string, MediaView>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let live = true;
    api.getTimeline(projectId).then(
      (t) => live && (setTimeline(t), setError(null)),
      (e) => live && setError(messageOf(e)),
    );
    return () => {
      live = false;
    };
  }, [projectId, version, enabled]);

  const loaded = timeline !== null;
  useEffect(() => {
    if (!enabled || !loaded) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const list = await api.getMedia(projectId);
        if (!live) return;
        setMedia(Object.fromEntries(list.map((m) => [m.asset_id, m])));
        if (list.some((m) => m.status === "pending" || m.status === "processing")) timer = setTimeout(tick, pollMs);
      } catch {
        if (live) timer = setTimeout(tick, pollMs * 3); // a hiccup must not blank the timeline
      }
    };
    void tick();
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [projectId, version, enabled, loaded, pollMs]);

  const preparing = Object.values(media).filter((m) => m.status === "pending" || m.status === "processing").length;
  return { timeline, media, error, preparing };
}

/** Lazily fetches waveform peaks / filmstrip metadata for every asset once it is prepared (each at most once). */
export function useDerived(projectId: string, media: Record<string, MediaView>) {
  const [peaks, setPeaks] = useState<Record<string, Peaks>>({});
  const [film, setFilm] = useState<Record<string, FilmMeta>>({});
  const asked = useRef(new Set<string>());

  useEffect(() => {
    asked.current = new Set(); // a different project: start over
    setPeaks({});
    setFilm({});
  }, [projectId]);

  useEffect(() => {
    for (const m of Object.values(media)) {
      if (m.status !== "ready") continue;
      const need = (role: "peaks" | "film") => m.derived.includes(role) && !asked.current.has(`${role}:${m.asset_id}`);
      if (need("peaks")) {
        asked.current.add(`peaks:${m.asset_id}`);
        api.getPeaks(projectId, m.asset_id).then((p) => setPeaks((o) => ({ ...o, [m.asset_id]: p })), () => undefined);
      }
      if (need("film")) {
        asked.current.add(`film:${m.asset_id}`);
        api.getFilmMeta(projectId, m.asset_id).then((f) => setFilm((o) => ({ ...o, [m.asset_id]: f })), () => undefined);
      }
    }
  }, [projectId, media]);

  return { peaks, film };
}

/** One edit session per mounted timeline; components re-render on every change of its snapshot. */
export function useSession(initial: TimelineView, save: Saver) {
  const ref = useRef<EditSession | null>(null);
  if (!ref.current) ref.current = new EditSession(initial, save);
  const session = ref.current;
  const snap = useSyncExternalStore(session.subscribe, session.getSnapshot, session.getSnapshot);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (session.getSnapshot().status !== "saved") {
        void session.flush();
        e.preventDefault(); // ask before closing the tab while edits are not saved yet
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      window.removeEventListener("beforeunload", warn);
      void session.flush(); // leaving the editor saves what is pending
    };
  }, [session]);
  return { session, snap };
}
