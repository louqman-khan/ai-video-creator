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
  video_ready: boolean;
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
