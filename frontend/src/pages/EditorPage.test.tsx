import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { Project } from "../api/types";
import { useProjects } from "../store/projects";
import { EditorPage } from "./EditorPage";

const project = (over: Partial<Project> = {}): Project => ({
  id: "p1", name: "demo", status: "done", stage: "done", progress: 1, message: "", error: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:01Z", original_filename: "",
  language: "en", aspect: "16:9", options: {}, video_ready: true, export_ready: false, export_aspect: null, ...over,
});

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={["/projects/p1"]}>
      <Routes><Route path="/projects/:id" element={<EditorPage />} /></Routes>
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.restoreAllMocks();
  useProjects.setState({ projects: [], loading: false, error: null });
  vi.spyOn(api, "getScenes").mockResolvedValue([]);
  vi.spyOn(api, "getTimeline").mockResolvedValue({ rev: 1, fps: 30, aspect: "16:9", duration: 30, tracks: [], clips: [], assets: {}, caption_style: null });
  vi.spyOn(api, "getMedia").mockResolvedValue([]);
  vi.spyOn(api, "getCaptions").mockResolvedValue({ cues: [], edited: false, language: "en", style: {} });
});

describe("EditorPage", () => {
  it("plays the preview with a version in the URL so a re-render is never served from the browser cache", async () => {
    vi.spyOn(api, "getProject").mockResolvedValue(project({ updated_at: "2026-01-01T00:00:09Z" }));
    const { container } = renderPage();
    await screen.findByText(/Preview \(low resolution\)/);
    const video = container.querySelector("video")!;
    expect(video.getAttribute("src")).toBe("/api/projects/p1/video?v=2026-01-01T00%3A00%3A09Z");
  });

  it("keeps the same player element while a render is in progress (no reload on every progress update)", async () => {
    const get = vi.spyOn(api, "getProject")
      .mockResolvedValueOnce(project({ status: "running", progress: 0.2, updated_at: "t1" }))
      .mockResolvedValue(project({ status: "running", progress: 0.6, updated_at: "t2" }));
    const { container } = renderPage();
    await screen.findByText(/Preview \(low resolution\)/);
    const first = container.querySelector("video")!;
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(1), { timeout: 4000 });
    expect(container.querySelector("video")).toBe(first); // the very same DOM node
    expect(first.getAttribute("src")).toBe("/api/projects/p1/video?v=t1");   // it keeps its place until the render has finished
  });

  it("shows the export panel and hides the caption editor for projects made without captions", async () => {
    vi.spyOn(api, "getProject").mockResolvedValue(project({ options: { captions: false } }));
    renderPage();
    expect(await screen.findByRole("button", { name: "Export full quality" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Captions" })).not.toBeInTheDocument();
  });

  it("shows an error banner for a failed export without hiding the project", async () => {
    vi.spyOn(api, "getProject").mockResolvedValue(project({ error: "The export failed: disk full" }));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("disk full");
    expect(screen.getByText(/Preview \(low resolution\)/)).toBeInTheDocument();
  });

  it("explains an unknown project", async () => {
    vi.spyOn(api, "getProject").mockRejectedValue(Object.assign(new Error("Project not found"), { status: 404 }));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Project not found");
  });
});
