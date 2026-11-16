import { useEffect, useState } from "react";
import { api } from "./api/client";
import { isActive, type Project } from "./api/types";
import { useProjects } from "./store/projects";

/** Loads one project and keeps polling while it is queued or running. */
export function useProject(id: string | undefined, intervalMs = 1500) {
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
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
        timer = setTimeout(tick, intervalMs * 3); // server hiccup: keep trying, slower
      }
    };
    void tick();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [id, intervalMs, upsert]);

  return { project, error };
}
