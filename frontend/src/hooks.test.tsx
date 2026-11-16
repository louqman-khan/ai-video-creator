import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api/client";
import type { Project } from "./api/types";
import { useProject } from "./hooks";

const P = (over: Partial<Project> = {}): Project => ({
  id: "a", name: "a", status: "running", stage: "plan", progress: 0.4, message: "", error: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", original_filename: "",
  language: null, aspect: "16:9", options: {}, video_ready: false, export_ready: false, export_aspect: null, ...over,
});

beforeEach(() => vi.restoreAllMocks());

describe("useProject", () => {
  it("polls while active and stops once the project is finished", async () => {
    const get = vi.spyOn(api, "getProject")
      .mockResolvedValueOnce(P({ progress: 0.2 }))
      .mockResolvedValueOnce(P({ progress: 0.7 }))
      .mockResolvedValue(P({ status: "done", progress: 1, video_ready: true }));
    const { result } = renderHook(() => useProject("a", 5));
    await waitFor(() => expect(result.current.project?.status).toBe("done"));
    const calls = get.mock.calls.length;
    await new Promise((r) => setTimeout(r, 60));
    expect(get.mock.calls.length).toBe(calls); // no more requests after "done"
    expect(calls).toBe(3);
  });

  it("does not retry a 404", async () => {
    const get = vi.spyOn(api, "getProject").mockRejectedValue(new ApiError("Project not found", 404));
    const { result } = renderHook(() => useProject("nope", 5));
    await waitFor(() => expect(result.current.error).toBe("Project not found"));
    await new Promise((r) => setTimeout(r, 80));
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("keeps trying after a temporary failure (network or 5xx) and recovers", async () => {
    const get = vi.spyOn(api, "getProject")
      .mockRejectedValueOnce(new ApiError("Cannot reach the server", 0))
      .mockRejectedValueOnce(new ApiError("Request failed (502)", 502))
      .mockResolvedValue(P({ status: "done", progress: 1 }));
    const { result } = renderHook(() => useProject("a", 3));
    await waitFor(() => expect(result.current.project?.status).toBe("done"), { timeout: 2000 });
    expect(get).toHaveBeenCalledTimes(3);
    expect(result.current.error).toBeNull();
  });

  it("stops polling when the component unmounts", async () => {
    const get = vi.spyOn(api, "getProject").mockResolvedValue(P());
    const { unmount } = renderHook(() => useProject("a", 5));
    await waitFor(() => expect(get).toHaveBeenCalled());
    unmount();
    const calls = get.mock.calls.length;
    await new Promise((r) => setTimeout(r, 60));
    expect(get.mock.calls.length).toBe(calls);
  });
});
