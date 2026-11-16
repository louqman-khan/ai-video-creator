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
