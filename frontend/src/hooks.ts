import { useEffect, useState } from "react";
import { api, ApiError } from "./api/client";
import { isActive, type Project } from "./api/types";
import { useProjects } from "./store/projects";

/** Loads one project and keeps polling while it is queued or running. */
export function useProject(id: string | undefined, intervalMs = 1500) {
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0); // bump to start polling again (e.g. after a swap)
  const upsert = useProjects((s) => s.upsert);

  useEffect(() => {
    if (!id) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const p = await api.getProject(id);
        if (stopped) return;
        setProject(p);
        setError(null);
        upsert(p);
        if (isActive(p)) timer = setTimeout(tick, intervalMs);
      } catch (e) {
        if (stopped) return;
        setError(e instanceof Error ? e.message : "Something went wrong");
        // a 4xx (e.g. 404: no such project) is permanent: retrying would only spam the server.
        // Network failures and 5xx are temporary: keep trying, more slowly.
        const permanent = e instanceof ApiError && e.status >= 400 && e.status < 500;
        if (!permanent) timer = setTimeout(tick, intervalMs * 3);
      }
    };
    void tick();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [id, intervalMs, upsert, nonce]);

  return { project, error, refresh: () => setNonce((n) => n + 1) };
}
