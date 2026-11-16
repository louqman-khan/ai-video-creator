import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import { DEFAULT_LIMITS } from "../api/client";
import type { Project } from "../api/types";
import { useProjects } from "../store/projects";
import { NewProjectPage } from "./NewProjectPage";

const PROJECT: Project = {
  id: "abc", name: "talk", status: "queued", stage: "", progress: 0, message: "", error: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", original_filename: "talk.mp3",
  language: null, aspect: "16:9", video_ready: false,
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/new"]}>
      <Routes>
        <Route path="/new" element={<NewProjectPage />} />
        <Route path="/projects/:id" element={<p>EDITOR PAGE</p>} />
        <Route path="/" element={<p>HOME</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

const audio = (name = "talk.mp3") => new File([new Uint8Array(2048)], name, { type: "audio/mpeg" });

beforeEach(() => {
  useProjects.setState({ projects: [], loading: false, error: null });
  vi.restoreAllMocks();
  vi.spyOn(client.api, "health").mockResolvedValue({ ok: true, ffmpeg: true, limits: DEFAULT_LIMITS });
});

describe("NewProjectPage", () => {
  it("keeps the button disabled until a valid audio file is chosen", async () => {
    renderPage();
    const button = screen.getByRole("button", { name: "Create video" });
    expect(button).toBeDisabled();
    await userEvent.upload(screen.getByLabelText(/Narration audio/), audio());
    expect(await screen.findByText("talk.mp3")).toBeInTheDocument();
    expect(button).toBeEnabled();
  });

  it("rejects an unsupported file with a message and no selection", async () => {
    renderPage();
    // applyAccept off: a user can still drop/pick any file in some browsers
    await userEvent.upload(screen.getByLabelText(/Narration audio/), audio("notes.txt"), { applyAccept: false });
    expect(await screen.findByRole("alert")).toHaveTextContent("not a supported audio file");
    expect(screen.getByRole("button", { name: "Create video" })).toBeDisabled();
  });

  it("uploads the form, shows progress, then opens the project", async () => {
    let send: ((p: Project) => void) | undefined;
    const spy = vi.spyOn(client, "uploadProject").mockImplementation((_form, onProgress) => {
      onProgress(0.4);
      return { promise: new Promise<Project>((r) => (send = r)), abort: vi.fn() };
    });
    renderPage();
    await userEvent.upload(screen.getByLabelText(/Narration audio/), audio());
    await userEvent.selectOptions(screen.getByLabelText("Language"), "ur");
    await userEvent.selectOptions(screen.getByLabelText("Video format"), "9:16");
    await userEvent.click(screen.getByRole("button", { name: "Create video" }));

    expect(await screen.findByText("Uploading 40%")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Upload progress" })).toHaveAttribute("aria-valuenow", "40");
    expect(screen.getByLabelText("Language")).toBeDisabled(); // no edits mid-upload
    const form = spy.mock.calls[0]![0] as FormData;
    expect([form.get("language"), form.get("aspect")]).toEqual(["ur", "9:16"]);

    send!(PROJECT);
    expect(await screen.findByText("EDITOR PAGE")).toBeInTheDocument();
    expect(useProjects.getState().projects.map((p) => p.id)).toEqual(["abc"]);
  });

  it("shows the server's error and lets the user try again", async () => {
    // created when called, so the component attaches its handler before the rejection happens
    vi.spyOn(client, "uploadProject").mockImplementation(() => ({
      promise: Promise.reject(new client.ApiError("Audio is longer than 30 minutes", 413)),
      abort: vi.fn(),
    }));
    renderPage();
    await userEvent.upload(screen.getByLabelText(/Narration audio/), audio());
    await userEvent.click(screen.getByRole("button", { name: "Create video" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("longer than 30 minutes");
    await waitFor(() => expect(screen.getByRole("button", { name: "Create video" })).toBeEnabled());
  });

  it("cancel aborts the running upload", async () => {
    const abort = vi.fn();
    vi.spyOn(client, "uploadProject").mockReturnValue({ promise: new Promise(() => undefined), abort });
    renderPage();
    await userEvent.upload(screen.getByLabelText(/Narration audio/), audio());
    await userEvent.click(screen.getByRole("button", { name: "Create video" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(abort).toHaveBeenCalled();
  });

  it("uses the limits reported by the server", async () => {
    vi.spyOn(client.api, "health").mockResolvedValue({
      ok: true, ffmpeg: true, limits: { ...DEFAULT_LIMITS, extensions: [".wav"], max_upload_mb: 5 },
    });
    renderPage();
    expect(await screen.findByText(/up to 5 MB/)).toBeInTheDocument();
    await userEvent.upload(screen.getByLabelText(/Narration audio/), audio("talk.mp3"), { applyAccept: false });
    expect(await screen.findByRole("alert")).toHaveTextContent("not a supported audio file");
  });
});
