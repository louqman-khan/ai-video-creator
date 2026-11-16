import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import type { Asset, Attribution, Project } from "../api/types";
import { CreditsPanel } from "./CreditsPanel";

const project = (over: Partial<Project> = {}): Project => ({
  id: "p1", name: "demo", status: "done", stage: "done", progress: 1, message: "", error: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:01Z", original_filename: "",
  language: null, aspect: "16:9", options: {}, video_ready: true, export_ready: false, export_aspect: null, ...over,
});
const asset = (id: string, over: Partial<Asset> = {}): Asset => ({
  id, source: "pixabay", kind: "video", thumb_url: "", page_url: "https://pixabay.com/videos/x/", title: "",
  width: 1920, height: 1080, duration: 10, license: "Pixabay Content License",
  license_url: "https://pixabay.com/service/license-summary/", author: "bob", attribution: "", attribution_required: false, ...over,
});
const item = (a: Asset, scenes: number[]): Attribution => ({ asset: a, scenes });

beforeEach(() => vi.restoreAllMocks());

describe("CreditsPanel", () => {
  it("lists each visual once with its scenes, author, source and license links", async () => {
    vi.spyOn(api, "getAttributions").mockResolvedValue([
      item(asset("pixabay:1"), [1, 3]),
      item(asset("openverse:2", { source: "openverse", kind: "image", title: "Old bridge", author: "Zed", license: "CC BY 4.0",
        license_url: "https://creativecommons.org/licenses/by/4.0/", page_url: "https://openverse.org/x", attribution_required: true }), [2]),
    ]);
    render(<CreditsPanel project={project()} />);
    expect(await screen.findByText("Scenes 1, 3")).toBeInTheDocument();
    expect(screen.getByText("Scene 2")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "pixabay" })).toHaveAttribute("href", "https://pixabay.com/videos/x/");
    expect(screen.getByRole("link", { name: "CC BY 4.0" })).toHaveAttribute("href", "https://creativecommons.org/licenses/by/4.0/");
    expect(screen.getByText("Old bridge")).toBeInTheDocument();
    expect(screen.getAllByText("Zed").length).toBeGreaterThan(0);
  });

  it("tells the user when a credit is legally required, and marks those visuals", async () => {
    vi.spyOn(api, "getAttributions").mockResolvedValue([
      item(asset("openverse:2", { license: "CC BY 4.0", attribution_required: true }), [2]),
      item(asset("pixabay:1"), [1]),
    ]);
    render(<CreditsPanel project={project()} />);
    expect(await screen.findByRole("note")).toHaveTextContent("1 of 2 visuals needs a credit");
    expect(screen.getAllByText("Credit required")).toHaveLength(1);
  });

  it("says so when nothing requires a credit", async () => {
    vi.spyOn(api, "getAttributions").mockResolvedValue([item(asset("pixabay:1"), [1])]);
    render(<CreditsPanel project={project()} />);
    expect(await screen.findByText(/None of these visuals legally require a credit/)).toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("handles a project without stock visuals", async () => {
    vi.spyOn(api, "getAttributions").mockResolvedValue([]);
    render(<CreditsPanel project={project()} />);
    expect(await screen.findByText(/nothing to credit/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Copy credits/ })).not.toBeInTheDocument();
  });

  it("never turns an unsafe URL into a link", async () => {
    vi.spyOn(api, "getAttributions").mockResolvedValue([
      item(asset("x:1", { page_url: "javascript:alert(1)", license_url: "data:text/html,x" }), [1]),
    ]);
    render(<CreditsPanel project={project()} />);
    await screen.findByText("Scene 1");
    expect(screen.queryByRole("link", { name: "pixabay" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Pixabay Content License" })).not.toBeInTheDocument();
    expect(screen.getByText(/License: Pixabay Content License/)).toBeInTheDocument(); // still shown, as plain text
  });

  it("copies the credits text to the clipboard", async () => {
    vi.spyOn(api, "getAttributions").mockResolvedValue([item(asset("pixabay:1"), [1])]);
    vi.spyOn(api, "getCreditsText").mockResolvedValue("Media credits\n- Video by bob");
    const write = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText: write }, configurable: true });
    render(<CreditsPanel project={project()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Copy credits text" }));
    await waitFor(() => expect(write).toHaveBeenCalledWith("Media credits\n- Video by bob"));
    expect(await screen.findByRole("button", { name: "Copied ✓" })).toBeInTheDocument();
  });

  it("falls back to a selectable text box when the browser blocks the clipboard", async () => {
    vi.spyOn(api, "getAttributions").mockResolvedValue([item(asset("pixabay:1"), [1])]);
    vi.spyOn(api, "getCreditsText").mockResolvedValue("Media credits\n- Video by bob");
    Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) }, configurable: true });
    render(<CreditsPanel project={project()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Copy credits text" }));
    expect(await screen.findByDisplayValue(/Video by bob/)).toHaveAttribute("readonly");
  });

  it("offers the text file download and shows load errors", async () => {
    vi.spyOn(api, "getAttributions").mockResolvedValueOnce([item(asset("pixabay:1"), [1])]);
    const { unmount } = render(<CreditsPanel project={project()} />);
    expect(await screen.findByRole("link", { name: "Download credits.txt" })).toHaveAttribute("href", "/api/projects/p1/credits");
    unmount();
    vi.spyOn(api, "getAttributions").mockRejectedValueOnce(new ApiError("The scenes are not ready yet", 409));
    render(<CreditsPanel project={project()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("not ready yet");
  });

  it("does not load while the project is processing", async () => {
    const get = vi.spyOn(api, "getAttributions").mockResolvedValue([]);
    render(<CreditsPanel project={project({ status: "running" })} />);
    await new Promise((r) => setTimeout(r, 20));
    expect(get).not.toHaveBeenCalled();
  });
});
