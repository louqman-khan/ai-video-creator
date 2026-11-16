import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { Project } from "../api/types";
import { useProjects } from "../store/projects";
import { ProjectsPage } from "./ProjectsPage";

const P = (id: string, over: Partial<Project> = {}): Project => ({
  id, name: `Project ${id}`, status: "done", stage: "done", progress: 1, message: "", error: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  original_filename: "", language: "ur", aspect: "16:9", options: {}, video_ready: true, export_ready: false, export_aspect: null, ...over,
});

const renderPage = () => render(<MemoryRouter><ProjectsPage /></MemoryRouter>);

beforeEach(() => {
  useProjects.setState({ projects: [], loading: false, error: null });
  vi.restoreAllMocks();
});

describe("ProjectsPage", () => {
  it("shows an empty state", async () => {
    vi.spyOn(api, "listProjects").mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText(/No projects yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New project" })).toHaveAttribute("href", "/new");
  });

  it("lists projects with status, progress for running ones, and errors for failed ones", async () => {
    vi.spyOn(api, "listProjects").mockResolvedValue([
      P("a"),
      P("b", { status: "running", progress: 0.5, message: "Finding visuals 1/2", video_ready: false }),
      P("c", { status: "failed", error: "Gemini request failed", video_ready: false }),
    ]);
    renderPage();
    expect(await screen.findByText("Project a")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("Working")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Project b progress" })).toHaveAttribute("aria-valuenow", "50");
    expect(screen.getByText("Finding visuals 1/2")).toBeInTheDocument();
    expect(screen.getByText("Gemini request failed")).toBeInTheDocument();
    // a running project cannot be deleted
    const deletes = screen.getAllByRole("button", { name: "Delete" });
    expect(deletes.map((b) => (b as HTMLButtonElement).disabled)).toEqual([false, true, false]);
  });

  it("shows server errors instead of an empty list", async () => {
    vi.spyOn(api, "listProjects").mockRejectedValue(new Error("Cannot reach the server. Is `avc serve` running?"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("avc serve");
    expect(screen.queryByText(/No projects yet/)).not.toBeInTheDocument();
  });

  it("asks for confirmation before deleting", async () => {
    vi.spyOn(api, "listProjects").mockResolvedValue([P("a")]);
    const del = vi.spyOn(api, "deleteProject").mockResolvedValue(undefined);
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderPage();
    const button = await screen.findByRole("button", { name: "Delete" });
    await userEvent.click(button);
    expect(del).not.toHaveBeenCalled();
    await userEvent.click(button);
    await waitFor(() => expect(del).toHaveBeenCalledWith("a"));
    expect(confirm).toHaveBeenCalledTimes(2);
  });
});
