import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import type { Project } from "../api/types";
import { ExportPanel } from "./ExportPanel";

const project = (over: Partial<Project> = {}): Project => ({
  id: "p1", name: "demo", status: "done", stage: "done", progress: 1, message: "", error: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:01Z", original_filename: "",
  language: null, aspect: "16:9", options: {}, video_ready: true, export_ready: false, export_aspect: null, ...over,
});

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "health").mockResolvedValue({ ok: true, ffmpeg: true, hardware_encoder: true, limits: {} as never });
  vi.spyOn(api, "exportEstimate").mockResolvedValue({ seconds: 42, learned: false, video_seconds: 12, width: 1920, height: 1080 });
});

describe("ExportPanel", () => {
  it("offers an export and no download when nothing was exported", () => {
    render(<ExportPanel project={project()} onStarted={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Export full quality" })).toBeEnabled();
    expect(screen.queryByRole("link", { name: "Download" })).not.toBeInTheDocument();
    expect(screen.getByText(/No export yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Media credits" })).toHaveAttribute("href", "/api/projects/p1/credits");
  });

  it("starts an export in the project's format by default", async () => {
    const onStarted = vi.fn();
    const start = vi.spyOn(api, "exportProject").mockResolvedValue(project({ status: "queued" }));
    render(<ExportPanel project={project({ aspect: "9:16" })} onStarted={onStarted} />);
    expect(screen.getByLabelText("Format")).toHaveValue("9:16");
    await userEvent.click(screen.getByRole("button", { name: "Export full quality" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith("p1", "9:16", "1080p", "software"));
    expect(onStarted).toHaveBeenCalledWith(expect.objectContaining({ status: "queued" }));
  });

  it("lets the user pick the other format, with a warning about cropping", async () => {
    const start = vi.spyOn(api, "exportProject").mockResolvedValue(project({ status: "queued" }));
    render(<ExportPanel project={project()} onStarted={vi.fn()} />);
    expect(screen.queryByText(/centre-crop/)).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Format"), "9:16");
    expect(screen.getByText(/centre-crop/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Export full quality" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith("p1", "9:16", "1080p", "software"));
  });

  it("shows the download link and format once the export is ready", () => {
    render(<ExportPanel project={project({ export_ready: true, export_aspect: "9:16" })} onStarted={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("9:16, 1080p");
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute("href", "/api/projects/p1/export");
    expect(screen.getByRole("button", { name: "Export again" })).toBeEnabled();
    expect(screen.queryByText(/No export yet/)).not.toBeInTheDocument();
  });

  it("is disabled while the project is processing", () => {
    render(<ExportPanel project={project({ status: "running" })} onStarted={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Export full quality" })).toBeDisabled();
    expect(screen.getByLabelText("Format")).toBeDisabled();
  });

  it("shows the server's error and allows another attempt", async () => {
    vi.spyOn(api, "exportProject").mockRejectedValue(new ApiError("This project is still processing", 409));
    render(<ExportPanel project={project()} onStarted={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Export full quality" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("still processing");
    expect(screen.getByRole("button", { name: "Export full quality" })).toBeEnabled();
  });

  it("offers sizes and the fast encoder (only when this computer has one) and shows a time estimate", async () => {
    const start = vi.spyOn(api, "exportProject").mockResolvedValue(project({ status: "queued" }));
    render(<ExportPanel project={project()} onStarted={vi.fn()} />);
    expect(await screen.findByLabelText("Time estimate")).toHaveTextContent("About 42 seconds");
    await userEvent.selectOptions(screen.getByLabelText("Size"), "4k");
    expect(api.exportEstimate).toHaveBeenLastCalledWith("p1", "16:9", "4k", "software");
    expect(screen.getByLabelText("Format")).toHaveDisplayValue(/3840×2160/);
    await screen.findByRole("option", { name: /Fast/ });
    await userEvent.selectOptions(screen.getByLabelText("Encoder"), "hardware");
    await userEvent.click(screen.getByRole("button", { name: "Export full quality" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith("p1", "16:9", "4k", "hardware"));
  });

  it("hides the fast encoder when the computer has none", async () => {
    vi.spyOn(api, "health").mockResolvedValue({ ok: true, ffmpeg: true, hardware_encoder: false, limits: {} as never });
    render(<ExportPanel project={project()} onStarted={vi.fn()} />);
    await screen.findByLabelText("Time estimate");
    expect(screen.queryByRole("option", { name: /Fast/ })).not.toBeInTheDocument();
  });

  it("says what a finished export was made with", () => {
    render(<ExportPanel project={project({ export_ready: true, export_aspect: "1:1", export_preset: "720p", export_encoder: "hardware" })} onStarted={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("1:1, 720p, hardware encoder");
  });
});
