import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { Project } from "../api/types";
import { useProjects } from "./projects";

const P = (id: string, over: Partial<Project> = {}): Project => ({
  id, name: id, status: "done", stage: "done", progress: 1, message: "", error: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  original_filename: "", language: null, aspect: "16:9", video_ready: true, ...over,
});

beforeEach(() => {
  useProjects.setState({ projects: [], loading: false, error: null });
  vi.restoreAllMocks();
});

describe("projects store", () => {
  it("loads projects", async () => {
    vi.spyOn(api, "listProjects").mockResolvedValue([P("a"), P("b")]);
    await useProjects.getState().load();
    expect(useProjects.getState().projects.map((p) => p.id)).toEqual(["a", "b"]);
    expect(useProjects.getState().error).toBeNull();
  });

  it("keeps the old list and records the error when loading fails", async () => {
    useProjects.setState({ projects: [P("a")] });
    vi.spyOn(api, "listProjects").mockRejectedValue(new Error("boom"));
    await useProjects.getState().load();
    expect(useProjects.getState().projects).toHaveLength(1);
    expect(useProjects.getState().error).toBe("boom");
    expect(useProjects.getState().loading).toBe(false);
  });

  it("upsert replaces in place or adds to the front", () => {
    useProjects.setState({ projects: [P("a", { progress: 0.1 })] });
    useProjects.getState().upsert(P("a", { progress: 0.9 }));
    useProjects.getState().upsert(P("c"));
    expect(useProjects.getState().projects.map((p) => [p.id, p.progress])).toEqual([["c", 1], ["a", 0.9]]);
  });

  it("removes only after the server accepted the delete", async () => {
    useProjects.setState({ projects: [P("a"), P("b")] });
    vi.spyOn(api, "deleteProject").mockRejectedValueOnce(new Error("still processing"));
    await useProjects.getState().remove("a");
    expect(useProjects.getState().projects).toHaveLength(2);
    expect(useProjects.getState().error).toBe("still processing");
    vi.spyOn(api, "deleteProject").mockResolvedValueOnce(undefined);
    await useProjects.getState().remove("a");
    expect(useProjects.getState().projects.map((p) => p.id)).toEqual(["b"]);
  });
});
