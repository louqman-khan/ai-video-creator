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

/**
 * A real caption frame from the server, re-requested (debounced) whenever the text or style
 * changes. Older requests are cancelled so a slow one can never overwrite a newer picture.
 */
export function useCaptionPreview(
  projectId: string,
  request: { cue_id: number; text: string; style: import("./api/types").CaptionStyle } | null,
  debounceMs = 400,
) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = request ? JSON.stringify(request) : "";

  useEffect(() => {
    if (!request || !request.text.trim()) {
      setError(request ? "Type some text to preview." : null);
      setLoading(false);
      return;
    }
    const ctl = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const blob = await api.previewCaption(projectId, request, ctl.signal);
        if (ctl.signal.aborted) return;
        setUrl((old) => {
          if (old) URL.revokeObjectURL(old);
          return URL.createObjectURL(blob);
        });
        setError(null);
      } catch (e) {
        if (ctl.signal.aborted) return;
        setError(e instanceof Error ? e.message : "Preview failed");
      } finally {
        if (!ctl.signal.aborted) setLoading(false);
      }
    }, debounceMs);
    return () => {
      clearTimeout(timer);
      ctl.abort();
    };
    // `key` captures the whole request
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, key, debounceMs]);

  useEffect(() => () => setUrl((old) => (old && URL.revokeObjectURL(old), null)), []);
  return { url, loading, error };
}
