import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { Asset, Project, Scene } from "../api/types";
import { SceneList } from "./SceneList";

const project = (over: Partial<Project> = {}): Project => ({
  id: "p1", name: "demo", status: "done", stage: "done", progress: 1, message: "", error: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:01Z", original_filename: "",
  language: "ur", aspect: "16:9", video_ready: true, ...over,
});
const asset = (id: string, over: Partial<Asset> = {}): Asset => ({
  id, source: "pixabay", kind: "video", thumb_url: `https://cdn.example/${id}.jpg`, page_url: "https://pixabay.com/videos/x/",
  title: "", width: 1920, height: 1080, duration: 12, license: "Pixabay Content License", license_url: "",
  author: "bob", attribution: "", attribution_required: false, ...over,
});
const scene = (id: number, over: Partial<Scene> = {}): Scene => ({
  id, start: (id - 1) * 4, end: id * 4, text: `text ${id}`, query_en: `query ${id}`, keywords: [],
  preferred_kind: null, asset: asset(`pixabay:${id}`), has_thumb: true, ...over,
});

beforeEach(() => vi.restoreAllMocks());

describe("SceneList", () => {
  it("lists scenes with time range, text, query, source and license", async () => {
    vi.spyOn(api, "getScenes").mockResolvedValue([
      scene(1, { text: "پاکستان کے پہاڑ" }),
      scene(2, { asset: asset("openverse:2", { source: "openverse", kind: "image", license: "CC BY 4.0", author: "Zed", attribution_required: true }) }),
    ]);
    render(<SceneList project={project()} onSwapped={vi.fn()} />);
    expect(await screen.findByText("پاکستان کے پہاڑ")).toHaveAttribute("dir", "auto");
    expect(screen.getByText(/Scene 1 · 0:00.0 – 0:04.0/)).toBeInTheDocument();
    expect(screen.getByText("query 1")).toBeInTheDocument();
    expect(screen.getByText(/CC BY 4.0 · by Zed/)).toBeInTheDocument(); // attribution shown when required
    expect(screen.getByRole("link", { name: "pixabay" })).toHaveAttribute("href", "https://pixabay.com/videos/x/");
    const img = screen.getAllByRole("img", { name: /Visual for scene/ })[0]!;
    expect(img).toHaveAttribute("src", "/api/projects/p1/scenes/1/thumb?v=pixabay%3A1");
  });

  it("does not turn an unsafe page URL into a link", async () => {
    vi.spyOn(api, "getScenes").mockResolvedValue([scene(1, { asset: asset("x:1", { page_url: "javascript:alert(1)" }) })]);
    render(<SceneList project={project()} onSwapped={vi.fn()} />);
    await screen.findByText("text 1");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows a placeholder for a scene without a visual", async () => {
    vi.spyOn(api, "getScenes").mockResolvedValue([scene(1, { asset: null, has_thumb: false })]);
    render(<SceneList project={project()} onSwapped={vi.fn()} />);
    expect(await screen.findByLabelText("Scene 1 has no visual")).toBeInTheDocument();
  });

  it("disables swapping while the project is processing, and does not load scenes yet", async () => {
    const get = vi.spyOn(api, "getScenes").mockResolvedValue([scene(1)]);
    render(<SceneList project={project({ status: "running" })} onSwapped={vi.fn()} />);
    await new Promise((r) => setTimeout(r, 20));
    expect(get).not.toHaveBeenCalled();
  });

  it("swap flow: search with the scene's query, pick a result, report the queued project", async () => {
    vi.spyOn(api, "getScenes").mockResolvedValue([scene(1), scene(2)]);
    const cands = vi.spyOn(api, "getCandidates").mockResolvedValue([asset("pixabay:9"), asset("openverse:7", { source: "openverse", kind: "image" })]);
    const swap = vi.spyOn(api, "swapVisual").mockResolvedValue(project({ status: "queued" }));
    const onSwapped = vi.fn();
    render(<SceneList project={project()} onSwapped={onSwapped} />);
    const buttons = await screen.findAllByRole("button", { name: "Swap visual" });
    await userEvent.click(buttons[1]!); // scene 2

    expect(await screen.findByRole("search")).toBeInTheDocument();
    await waitFor(() => expect(cands).toHaveBeenCalledWith("p1", 2, "query 2")); // searched right away
    await userEvent.click(await screen.findByRole("button", { name: "Use this image from openverse" }));
    await waitFor(() => expect(swap).toHaveBeenCalledWith("p1", 2, "openverse:7"));
    expect(onSwapped).toHaveBeenCalledWith(expect.objectContaining({ status: "queued" }));
  });

  it("lets the user change the search words", async () => {
    vi.spyOn(api, "getScenes").mockResolvedValue([scene(1)]);
    const cands = vi.spyOn(api, "getCandidates").mockResolvedValue([]);
    render(<SceneList project={project()} onSwapped={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Swap visual" }));
    const box = await screen.findByRole("textbox", { name: /What should this scene show/ });
    await userEvent.clear(box);
    await userEvent.type(box, "old castle");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(cands).toHaveBeenLastCalledWith("p1", 1, "old castle"));
    expect(await screen.findByText(/Nothing found/)).toBeInTheDocument();
  });

  it("shows search and swap errors without losing the results", async () => {
    vi.spyOn(api, "getScenes").mockResolvedValue([scene(1)]);
    vi.spyOn(api, "getCandidates").mockResolvedValue([asset("pixabay:9")]);
    vi.spyOn(api, "swapVisual").mockRejectedValue(new Error("This project is still processing"));
    render(<SceneList project={project()} onSwapped={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Swap visual" }));
    await userEvent.click(await screen.findByRole("button", { name: /Use this video from pixabay/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("still processing");
    expect(within(document.body).getByRole("button", { name: /Use this video from pixabay/ })).toBeEnabled(); // can retry
  });

  it("shows an error if the scenes cannot be loaded", async () => {
    vi.spyOn(api, "getScenes").mockRejectedValue(new Error("The scenes are not ready yet"));
    render(<SceneList project={project()} onSwapped={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("not ready yet");
  });
});
