import type { Aspect, Asset, AvatarCorner, ExportEncoder, ExportPreset, Attribution, CaptionsView, CaptionStyle, FilmMeta, MediaView, Peaks, Project, Scene, TimelineAsset, TimelineView } from "./types";

/** Our own pages send this header on every request; the hosted server refuses state-changing requests without it (protection against other sites). */
export const CSRF_HEADERS = { "X-Requested-With": "avc" } as const;

/** The monthly allowance of a hosted account: a video costs credits by the length of its narration. */
export interface Credits {
  plan: string;
  monthly: number;
  used: number;
  remaining: number;
  resets_on: string;   // YYYY-MM-DD
  unlimited: boolean;
  minutes_per_credit: number;
  bonus?: number;   // credits given by the operator (they do not expire)
}

export interface AdminUser {
  id: string;
  email: string;
  role: "user" | "admin";
  verified: boolean;
  disabled: boolean;
  created_at: number;
  last_login: number | null;
  projects: number;
  storage_bytes: number;
  credits: Credits;
}

export interface Account {
  mode: "local" | "hosted";
  signups: "open" | "invite" | "closed";
  require_verification: boolean;
  user: { id: string; email: string | null; admin: boolean; verified?: boolean } | null;
  usage?: { credits?: Credits; projects: number; max_projects: number; storage_bytes: number; max_storage_bytes: number; max_exports_per_day: number };
}

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
    xhr.setRequestHeader("X-Requested-With", CSRF_HEADERS["X-Requested-With"]);
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
    res = await fetch(path, { ...init, headers: { ...CSRF_HEADERS, ...(init?.headers as Record<string, string> | undefined) } });
  } catch {
    throw new ApiError("Cannot reach the server. Is `avc serve` running?", 0);
  }
  if (res.status === 401 && !path.startsWith("/api/auth/")) window.dispatchEvent(new Event("avc:unauthorized")); // the session ended: the app sends the person to the log-in page
  if (!res.ok) throw new ApiError(await errorMessage(res), res.status);
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export interface SetupStatus {
  ffmpeg: boolean;
  keys: { gemini_api_key: boolean; pixabay_api_key: boolean };
  models: { whisper: boolean; whisper_model: string; rnnoise: boolean; clip: boolean; face?: boolean; voice?: boolean };
  whisper_sizes_mb: Record<string, number>;
  download: { running: boolean; message: string; error: string | null };
  data_dir: string | null;
}

export const api = {
  adminUsers: () => request<AdminUser[]>("/api/admin/users"),
  adminGiveCredits: (id: string, amount: number) =>
    request<Credits>(`/api/admin/users/${encodeURIComponent(id)}/credits`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ amount }) }),
  adminSetDisabled: (id: string, disabled: boolean) =>
    request<{ id: string; disabled: boolean }>(`/api/admin/users/${encodeURIComponent(id)}/disabled`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ disabled }) }),
  setupStatus: () => request<SetupStatus>("/api/setup"),
  setupKeys: (body: { gemini_api_key?: string; pixabay_api_key?: string }) =>
    request<SetupStatus>("/api/setup/keys", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  setupModels: (body: { whisper?: string; clip: boolean; voice?: boolean }) =>
    request<SetupStatus>("/api/setup/models", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  account: () => request<Account>("/api/auth/me"),
  verifyCode: (email: string, code: string) =>
    request<{ message: string }>("/api/auth/verify-code", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, code }) }),
  resend: (email: string, lang: string) =>
    request<{ message: string }>("/api/auth/resend", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, lang }) }),
  signup: (body: { email: string; password: string; invite?: string; terms: boolean; lang?: string }) =>
    request<{ message: string }>("/api/auth/signup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  login: (body: { email: string; password: string }) =>
    request<unknown>("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  logout: () => request<unknown>("/api/auth/logout", { method: "POST" }),
  forgotPassword: (email: string, lang = "en") =>
    request<{ message: string }>("/api/auth/forgot", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, lang }) }),
  resetPassword: (token: string, password: string) =>
    request<{ message: string }>("/api/auth/reset", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token, password }) }),
  deleteAccount: (password: string) =>
    request<{ message: string }>("/api/auth/account", { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }) }),
  accountExportUrl: "/api/auth/export",
  health: () => request<{ ok: boolean; ffmpeg: boolean; hardware_encoder?: boolean; speech?: string[]; speech_paid?: boolean; limits: Limits }>("/api/health"),
  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: string) => request<Project>(`/api/projects/${encodeURIComponent(id)}`),
  deleteProject: (id: string) => request<void>(`/api/projects/${encodeURIComponent(id)}`, { method: "DELETE" }),
  getAttributions: (id: string) => request<Attribution[]>(`/api/projects/${encodeURIComponent(id)}/attributions`),
  /** The ready-to-paste credits text (same file the export ships with). */
  getCreditsText: async (id: string): Promise<string> => {
    let res: Response;
    try {
      res = await fetch(`/api/projects/${encodeURIComponent(id)}/credits`);
    } catch {
      throw new ApiError("Cannot reach the server. Is `avc serve` running?", 0);
    }
    if (!res.ok) throw new ApiError(await errorMessage(res), res.status);
    return res.text();
  },
  getTimeline: (id: string) => request<TimelineView>(`/api/projects/${encodeURIComponent(id)}/timeline`),
  /** Saves the edited timeline; the server answers 409 when it changed elsewhere, 422 when it is invalid. */
  saveTimeline: (id: string, body: { base_rev: number; aspect?: string; tracks: unknown[]; clips: unknown[]; caption_style: unknown }) =>
    request<TimelineView>(`/api/projects/${encodeURIComponent(id)}/timeline`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  /** Re-render the preview from the saved timeline (several requests while one runs are merged into one). */
  renderTimeline: (id: string) => request<Project>(`/api/projects/${encodeURIComponent(id)}/timeline/render`, { method: "POST" }),
  /** Stock media for the bin. The server keeps the download addresses; the browser only gets what it may show. */
  binSearch: (id: string, q: string, kind: "video" | "image" | "music" | "sound") =>
    request<Asset[]>(`/api/projects/${encodeURIComponent(id)}/bin/search?q=${encodeURIComponent(q)}&kind=${kind}`),
  /** Downloads an item the server offered into the project; answers with the asset as the timeline knows it. */
  binAdd: (id: string, assetId: string) =>
    request<TimelineAsset>(`/api/projects/${encodeURIComponent(id)}/bin/add`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ asset_id: assetId }),
    }),
  uploadMedia: (id: string, file: File, title: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("rights_confirmed", "true");
    form.append("title", title);
    return request<MediaView>(`/api/projects/${encodeURIComponent(id)}/media`, { method: "POST", body: form });
  },
  /** A suggestion for where the crop of a picture to the frame should be centred (looks at the picture; changes nothing). */
  suggestFocus: (id: string, asset: string) =>
    request<{ x: number; y: number; method?: "faces" | "saliency" }>(`/api/projects/${encodeURIComponent(id)}/media/focus?asset=${encodeURIComponent(asset)}`),
  getMedia: (id: string) => request<MediaView[]>(`/api/projects/${encodeURIComponent(id)}/media`),
  getPeaks: (id: string, asset: string) =>
    request<Peaks>(`/api/projects/${encodeURIComponent(id)}/media/peaks?asset=${encodeURIComponent(asset)}`),
  getFilmMeta: (id: string, asset: string) =>
    request<FilmMeta>(`/api/projects/${encodeURIComponent(id)}/media/film.json?asset=${encodeURIComponent(asset)}`),
  filmUrl: (id: string, asset: string) => `/api/projects/${encodeURIComponent(id)}/media/film?asset=${encodeURIComponent(asset)}`,
  mediaAudioUrl: (id: string, asset: string) => `/api/projects/${encodeURIComponent(id)}/media/audio?asset=${encodeURIComponent(asset)}`,
  mediaProxyUrl: (id: string, asset: string) => `/api/projects/${encodeURIComponent(id)}/media/proxy?asset=${encodeURIComponent(asset)}`,
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
        headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
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
  /** Full-quality (1080p) export in 16:9 or 9:16. Edits use the fast preview; this is the final step. */
  exportProject: (id: string, aspect: Aspect, preset: ExportPreset = "1080p", encoder: ExportEncoder = "software") =>
    request<Project>(`/api/projects/${encodeURIComponent(id)}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ aspect, preset, encoder }),
    }),
  /** About how many seconds an export takes on this computer (it learns from the exports already done). */
  exportEstimate: (id: string, aspect: Aspect, preset: ExportPreset, encoder: ExportEncoder) =>
    request<{ seconds: number; learned: boolean; video_seconds: number; width: number; height: number }>(
      `/api/projects/${encodeURIComponent(id)}/export/estimate?aspect=${aspect}&preset=${preset}&encoder=${encoder}`),
  /** Disk use by category and how much a clean-up could free. */
  storage: () => request<{ items: { key: string; label: string; bytes: number; reclaimable: number }[]; total: number; reclaimable: number }>("/api/storage"),
  /** Removes unused downloads, orphaned proxies and old render caches (never uploads, exports or timelines). */
  cleanStorage: () => request<{ freed: number; removed: number }>("/api/storage/clean?days=7&segments=true", { method: "POST" }),
  /** Characters that can speak the narration. */
  avatars: () => request<{ id: string; name: string; paid?: boolean }[]>("/api/avatars"),
  avatarThumbUrl: (avatarId: string) => `/api/avatars/${encodeURIComponent(avatarId)}/thumb`,
  /** Makes the avatar speak the project's narration and puts it on the timeline (a render follows). */
  addAvatar: (id: string, body: { avatar: string; corner: AvatarCorner; size: number }) =>
    request<Project>(`/api/projects/${encodeURIComponent(id)}/avatar`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  exportUrl: (id: string) => `/api/projects/${encodeURIComponent(id)}/export`,
  /** `version` changes when a render finishes, so the browser never plays an outdated copy. */
  videoUrl: (id: string, version?: string) =>
    `/api/projects/${encodeURIComponent(id)}/video${version ? `?v=${encodeURIComponent(version)}` : ""}`,
  creditsUrl: (id: string) => `/api/projects/${encodeURIComponent(id)}/credits`,
};
