import type { Project } from "./types";

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
async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    const d = body?.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d[0]?.msg) return d.map((x: { msg: string }) => x.msg).join("; ");
  } catch {
    /* not JSON */
  }
  return `Request failed (${res.status})`;
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
  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: string) => request<Project>(`/api/projects/${encodeURIComponent(id)}`),
  createProject: (form: FormData) => request<Project>("/api/projects", { method: "POST", body: form }),
  deleteProject: (id: string) => request<void>(`/api/projects/${encodeURIComponent(id)}`, { method: "DELETE" }),
  videoUrl: (id: string) => `/api/projects/${encodeURIComponent(id)}/video`,
  creditsUrl: (id: string) => `/api/projects/${encodeURIComponent(id)}/credits`,
};
