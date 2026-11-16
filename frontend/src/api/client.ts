import type { Asset, CaptionsView, CaptionStyle, Project, Scene } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** FastAPI errors: {detail: "text"} or {detail: [{msg, loc}, ...]} (validation). */
export function messageFromBody(status: number, text: string): string {
  try {
    const d = JSON.parse(text)?.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d[0]?.msg) return d.map((x: { msg: string }) => x.msg).join("; ");
  } catch {
    /* not JSON */
  }
  return `Request failed (${status})`;
}

const errorMessage = async (res: Response) => messageFromBody(res.status, await res.text());

export interface Limits {
  max_upload_mb: number;
  max_audio_minutes: number;
  max_script_chars: number;
  extensions: string[];
}

/** Used until the server answers, and if it cannot be reached. Mirrors the backend defaults. */
export const DEFAULT_LIMITS: Limits = {
  max_upload_mb: 200,
  max_audio_minutes: 30,
  max_script_chars: 100_000,
  extensions: [".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"],
};

/** fetch() has no upload progress, so uploads use XMLHttpRequest. */
export function uploadProject(
  form: FormData,
  onProgress: (fraction: number) => void,
): { promise: Promise<Project>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<Project>((resolve, reject) => {
    xhr.open("POST", "/api/projects");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as Project);
        } catch {
          reject(new ApiError("The server sent an unreadable answer", xhr.status));
        }
      } else reject(new ApiError(messageFromBody(xhr.status, xhr.responseText), xhr.status));
    };
    xhr.onerror = () => reject(new ApiError("Cannot reach the server. Is `avc serve` running?", 0));
    xhr.onabort = () => reject(new ApiError("Upload cancelled", 0));
    xhr.send(form);
  });
  return { promise, abort: () => xhr.abort() };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError("Cannot reach the server. Is `avc serve` running?", 0);
  }
  if (!res.ok) throw new ApiError(await errorMessage(res), res.status);
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  health: () => request<{ ok: boolean; ffmpeg: boolean; limits: Limits }>("/api/health"),
  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: string) => request<Project>(`/api/projects/${encodeURIComponent(id)}`),
  deleteProject: (id: string) => request<void>(`/api/projects/${encodeURIComponent(id)}`, { method: "DELETE" }),
  getScenes: (id: string) => request<Scene[]>(`/api/projects/${encodeURIComponent(id)}/scenes`),
  getCandidates: (id: string, sceneId: number, query: string) =>
    request<Asset[]>(
      `/api/projects/${encodeURIComponent(id)}/scenes/${sceneId}/candidates?query=${encodeURIComponent(query)}`,
    ),
  /** Only the id of a visual the server offered is sent: never a URL. */
  swapVisual: (id: string, sceneId: number, assetId: string) =>
    request<Project>(`/api/projects/${encodeURIComponent(id)}/scenes/${sceneId}/swap`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ asset_id: assetId }),
    }),
  /** `version` (the asset id) busts the browser cache when a visual is swapped. */
  thumbUrl: (id: string, sceneId: number, version: string) =>
    `/api/projects/${encodeURIComponent(id)}/scenes/${sceneId}/thumb?v=${encodeURIComponent(version)}`,
  getCaptions: (id: string) => request<CaptionsView>(`/api/projects/${encodeURIComponent(id)}/captions`),
  /** Send only what the user changed: `cues` (id + new text) and/or `style`. Starts a re-render. */
  updateCaptions: (id: string, body: { cues?: { id: number; text: string }[]; style?: CaptionStyle }) =>
    request<Project>(`/api/projects/${encodeURIComponent(id)}/captions`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  resetCaptions: (id: string) =>
    request<Project>(`/api/projects/${encodeURIComponent(id)}/captions`, { method: "DELETE" }),
  /** A real frame rendered by the server (same engine as the final video). */
  previewCaption: async (
    id: string,
    body: { cue_id: number; text: string; style: CaptionStyle },
    signal?: AbortSignal,
  ): Promise<Blob> => {
    let res: Response;
    try {
      res = await fetch(`/api/projects/${encodeURIComponent(id)}/captions/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal,
      });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") throw e;
      throw new ApiError("Cannot reach the server. Is `avc serve` running?", 0);
    }
    if (!res.ok) throw new ApiError(await errorMessage(res), res.status);
    return res.blob();
  },
  videoUrl: (id: string) => `/api/projects/${encodeURIComponent(id)}/video`,
  creditsUrl: (id: string) => `/api/projects/${encodeURIComponent(id)}/credits`,
};
