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
