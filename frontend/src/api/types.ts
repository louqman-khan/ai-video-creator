// Mirrors backend `ProjectInfo` (backend/app/api/store.py).
export type ProjectStatus = "queued" | "running" | "done" | "failed";

export interface Project {
  id: string;
  name: string;
  status: ProjectStatus;
  stage: string;
  progress: number; // 0..1
  message: string;
  error: string | null;
  created_at: string;
  updated_at: string;
  original_filename: string;
  language: string | null;
  aspect: string;
  options: { captions?: boolean; [key: string]: unknown };
  video_ready: boolean; // a playable preview exists
  export_ready: boolean; // a full-quality export exists and matches the current edits
  export_aspect: string | null;
}

export const isActive = (p: Pick<Project, "status">): boolean =>
  p.status === "queued" || p.status === "running";

export interface Asset {
  id: string;
  source: string;
  kind: "video" | "image";
  thumb_url: string;
  page_url: string;
  title: string;
  width: number;
  height: number;
  duration: number | null;
  license: string;
  license_url: string;
  author: string;
  attribution: string;
  attribution_required: boolean;
}

export interface Scene {
  id: number;
  start: number;
  end: number;
  text: string;
  query_en: string;
  keywords: string[];
  preferred_kind: "video" | "image" | null;
  asset: Asset | null;
  has_thumb: boolean;
}

/** Mirrors backend `CaptionStyle`. font/size_pct unset = automatic (depends on the language). */
export interface CaptionStyle {
  font?: string | null;
  size_pct?: number | null;
  color: string;
  outline_color: string;
  outline_width: number;
  position: "bottom" | "center" | "top";
  margin_pct: number;
  bold: boolean;
  words_per_line: number;
  max_chars: number;
}

export interface Cue {
  id: number;
  start: number;
  end: number;
  text: string;
}

export interface CaptionsView {
  cues: Cue[];
  edited: boolean;
  language: string;
  style: Partial<CaptionStyle>;
}

/** One visual used by the project (once), with the scenes it appears in. */
export interface Attribution {
  asset: Asset;
  scenes: number[];
}

// ---- timeline document (mirrors backend/app/timeline/models.py; the browser never sees paths or URLs)
export interface TimelineTrack {
  id: string;
  kind: "video" | "audio" | "caption";
  name: string;
  muted: boolean;
  locked: boolean;
}

export interface TimelineClip {
  id: string;
  track: string;
  kind: "video" | "image" | "audio" | "caption";
  asset: string | null;
  start: number; // frames
  duration: number;
  in_point: number;
  loop: boolean;
  volume: number;
  fade_in: number;
  fade_out: number;
  text: string | null;
  words: { text: string; start: number; end: number }[];
  meta: Record<string, unknown>;
}

export interface TimelineAsset {
  id: string;
  kind: "video" | "image" | "audio";
  duration: number | null; // frames
  width: number;
  height: number;
  source: string;
  license: string;
  author: string;
  title: string;
  attribution: string;
  attribution_required: boolean;
}

export interface TimelineView {
  rev: number;
  fps: number;
  aspect: string;
  duration: number; // frames
  tracks: TimelineTrack[];
  clips: TimelineClip[];
  assets: Record<string, TimelineAsset>;
  caption_style: Record<string, unknown> | null;
}

export interface MediaView {
  asset_id: string;
  kind: string;
  title: string;
  status: "pending" | "processing" | "ready" | "failed";
  stage: string;
  error: string | null;
  uploaded: boolean;
  duration: number | null;
  width: number;
  height: number;
  derived: string[]; // proxy, audio, peaks, film
}

export interface Peaks {
  version: number;
  duration: number;
  rates: Record<string, number[]>; // peaks per second -> values 0..255
}

export interface FilmMeta {
  interval: number;
  count: number;
  thumb_width: number;
  thumb_height: number;
}
