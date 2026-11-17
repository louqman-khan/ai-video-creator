import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { MediaView, TimelineClip, TimelineView } from "../api/types";
import { useTimelineData } from "./hooks";
import { Timeline } from "./Timeline";

const clip = (over: Partial<TimelineClip> & Pick<TimelineClip, "id" | "track" | "kind" | "start" | "duration">): TimelineClip => ({
  asset: null, in_point: 0, loop: false, volume: 1, fade_in: 0, fade_out: 0, transform: { x: 0, y: 0, scale: 1, rotation: 0, opacity: 1, crop: [0, 0, 0, 0] },
  effects: [], transition_in: null, text: null, words: [], meta: {}, ...over,
});

const timeline = (over: Partial<TimelineView> = {}): TimelineView => ({
  rev: 1, fps: 30, aspect: "16:9", duration: 300,
  tracks: [
    { id: "V1", kind: "video", name: "Visuals", muted: false, locked: false },
    { id: "A1", kind: "audio", name: "Narration", muted: false, locked: false },
    { id: "C1", kind: "caption", name: "Captions", muted: false, locked: false },
  ],
  clips: [
    clip({ id: "scene-1", track: "V1", kind: "video", asset: "pix:1", start: 0, duration: 150, meta: { text: "first scene" }, loop: true }),
    clip({ id: "scene-2", track: "V1", kind: "image", asset: "pix:2", start: 150, duration: 150, meta: { text: "second scene" } }),
    clip({ id: "narration", track: "A1", kind: "audio", asset: "narration", start: 0, duration: 300 }),
    clip({ id: "cap-0", track: "C1", kind: "caption", start: 10, duration: 60, text: "پاکستان کے پہاڑ" }),
  ],
  assets: {
    "pix:1": { id: "pix:1", kind: "video", duration: 90, width: 1920, height: 1080, source: "pixabay", license: "Pixabay Content License", author: "bob", title: "", attribution: "", attribution_required: false },
    "pix:2": { id: "pix:2", kind: "image", duration: null, width: 1280, height: 720, source: "openverse", license: "CC BY 4.0", author: "Zed", title: "Old bridge", attribution: "", attribution_required: true },
    narration: { id: "narration", kind: "audio", duration: 300, width: 0, height: 0, source: "narration", license: "User-provided", author: "", title: "Narration", attribution: "", attribution_required: false },
  },
  caption_style: null, ...over,
});

const mediaItem = (id: string, derived: string[], status: MediaView["status"] = "ready"): MediaView => ({
  asset_id: id, kind: "video", title: id, status, stage: "", error: null, uploaded: false, duration: 10, width: 0, height: 0, derived,
});

const PEAKS = { version: 1, duration: 10, rates: { "100": Array.from({ length: 1000 }, (_, i) => (i * 7) % 256), "10": Array.from({ length: 100 }, (_, i) => (i * 13) % 256) } };

function fakeVideo(): HTMLVideoElement {
  const v = document.createElement("video");
  let t = 0;
  Object.defineProperty(v, "currentTime", { get: () => t, set: (x: number) => { t = x; }, configurable: true });
  Object.defineProperty(v, "paused", { get: () => true, configurable: true });
  v.play = vi.fn().mockResolvedValue(undefined);
  v.pause = vi.fn();
  return v;
}

const ctxStub = () => ({ setTransform: vi.fn(), clearRect: vi.fn(), fillRect: vi.fn(), fillStyle: "" });
let ctx: ReturnType<typeof ctxStub>;

beforeEach(() => {
  vi.restoreAllMocks();
  ctx = ctxStub();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation((() => ctx) as never);
  vi.spyOn(api, "getTimeline").mockResolvedValue(timeline());
  vi.spyOn(api, "getMedia").mockResolvedValue([mediaItem("pix:1", ["proxy", "film"]), mediaItem("pix:2", ["proxy"]), mediaItem("narration", ["audio", "peaks"])]);
  vi.spyOn(api, "getPeaks").mockResolvedValue(PEAKS);
  vi.spyOn(api, "getFilmMeta").mockResolvedValue({ interval: 0.5, count: 20, thumb_width: 160, thumb_height: 90 });
});

const open = async (video: HTMLVideoElement | null = fakeVideo()) => {
  const r = render(<Timeline projectId="p1" version="v1" video={video} />);
  await screen.findByRole("region", { name: "Timeline" });
  return { ...r, video };
};

describe("Timeline", () => {
  it("draws tracks in editor order with their clips and labels", async () => {
    await open();
    const rows = [...document.querySelectorAll("[data-track]")].map((el) => el.getAttribute("data-track"));
    expect(rows).toEqual(["C1", "V1", "A1"]);                                    // captions on top, pictures, then audio
    expect(screen.getByText("Visuals")).toBeInTheDocument();
    expect(screen.getByText("first scene")).toBeInTheDocument();
    expect(screen.getByText("second scene")).toBeInTheDocument();                // a scene is labelled with what is said in it
  });

  it("shows right-to-left captions as text, with automatic direction", async () => {
    await open();
    const label = screen.getByText("پاکستان کے پہاڑ");
    expect(label).toHaveAttribute("dir", "auto");
  });

  it("marks a muted track and a looping clip", async () => {
    vi.spyOn(api, "getTimeline").mockResolvedValue(timeline({ tracks: timeline().tracks.map((t) => (t.id === "A1" ? { ...t, muted: true } : t)) }));
    await open();
    expect(screen.getByText("muted")).toBeInTheDocument();
    expect(screen.getByTitle("This video repeats to fill the clip")).toBeInTheDocument();
  });

  it("shows the time under the playhead and follows the video", async () => {
    const { video } = await open();
    expect(screen.getByLabelText("Playhead position")).toHaveTextContent("00:00:00 / 00:10:00");
    act(() => { (video as HTMLVideoElement).currentTime = 2.5; video!.dispatchEvent(new Event("seeked")); });
    await waitFor(() => expect(screen.getByLabelText("Playhead position")).toHaveTextContent("00:02:15"));   // 75 frames
  });

  it("clicking the ruler moves the video (and a drag keeps scrubbing)", async () => {
    const { video } = await open();
    const ruler = document.querySelector(".tl-ruler")!;
    fireEvent.pointerDown(ruler, { clientX: 340, button: 0, pointerId: 1 });
    // an 800 px view minus the 120 px margin fits 10 s: 68 px/s, so 340 px = 5 s = frame 150
    expect(video!.currentTime).toBeCloseTo(5, 5);
    fireEvent.pointerMove(ruler, { clientX: 680, pointerId: 1 });
    expect(video!.currentTime).toBeCloseTo(10 - 1 / 30, 3);                      // clamped to the last frame
    fireEvent.pointerUp(ruler, { pointerId: 1 });
    fireEvent.pointerMove(ruler, { clientX: 68, pointerId: 1 });
    expect(video!.currentTime).toBeCloseTo(10 - 1 / 30, 3);                      // released: no more scrubbing
  });

  it("clicking an empty part of a track also seeks", async () => {
    const { video } = await open();
    fireEvent.pointerDown(document.querySelector('[data-track="C1"]')!, { clientX: 204, button: 0, pointerId: 1 });   // 3 s
    expect(video!.currentTime).toBeCloseTo(3, 5);
  });

  it("keyboard: arrows step a frame (shift: a second), Home/End jump, space plays", async () => {
    const { video } = await open();
    const area = screen.getByLabelText(/Timeline tracks/);
    area.focus();
    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    expect(video!.currentTime).toBeCloseTo(2 / 30, 5);
    await userEvent.keyboard("{Shift>}{ArrowRight}{/Shift}");
    expect(video!.currentTime).toBeCloseTo(2 / 30 + 1, 5);
    await userEvent.keyboard("{ArrowLeft}");
    expect(video!.currentTime).toBeCloseTo(1 + 1 / 30, 5);
    await userEvent.keyboard("{End}");
    expect(video!.currentTime).toBeCloseTo(299 / 30, 5);
    await userEvent.keyboard("{Home}");
    expect(video!.currentTime).toBe(0);
    await userEvent.keyboard("{ArrowLeft}");
    expect(video!.currentTime).toBe(0);                                            // never before the start
    await userEvent.keyboard(" ");
    expect(video!.play).toHaveBeenCalled();
  });

  it("zoom buttons, slider and Fit change the timeline's width", async () => {
    await open();
    const canvas = () => document.querySelector(".tl-canvas") as HTMLElement;
    const fitted = parseFloat(canvas().style.width);
    await userEvent.click(screen.getByLabelText("Zoom in"));
    await waitFor(() => expect(parseFloat(canvas().style.width)).toBeGreaterThan(fitted));
    await userEvent.click(screen.getByLabelText("Zoom in"));
    const zoomed = parseFloat(canvas().style.width);
    await userEvent.click(screen.getByLabelText("Zoom out"));
    await waitFor(() => expect(parseFloat(canvas().style.width)).toBeLessThan(zoomed));
    await userEvent.click(screen.getByRole("button", { name: "Fit" }));
    await waitFor(() => expect(parseFloat(canvas().style.width)).toBeCloseTo(fitted, 0));
    fireEvent.change(screen.getByLabelText("Zoom"), { target: { value: String(Math.log(400)) } });
    await waitFor(() => expect(parseFloat(canvas().style.width)).toBeGreaterThan(zoomed));
  });

  it("ctrl + wheel zooms, a plain wheel does not", async () => {
    await open();
    const area = screen.getByLabelText(/Timeline tracks/);
    const canvas = () => parseFloat((document.querySelector(".tl-canvas") as HTMLElement).style.width);
    const w0 = canvas();
    fireEvent.wheel(area, { deltaY: -100 });
    expect(canvas()).toBe(w0);
    fireEvent.wheel(area, { deltaY: -100, ctrlKey: true });
    await waitFor(() => expect(canvas()).toBeGreaterThan(w0));
  });

  it("selecting a clip shows what it is, including the credit that is required", async () => {
    const { video } = await open();
    expect(screen.queryByLabelText("Selected clip")).not.toBeInTheDocument();
    const second = document.querySelector('[data-clip="scene-2"]')!;
    fireEvent.pointerDown(second, { clientX: 400, button: 0, pointerId: 1 });
    const info = screen.getByLabelText("Selected clip");
    expect(within(info).getByText("second scene")).toBeInTheDocument();
    expect(info).toHaveTextContent("image");
    expect(info).toHaveTextContent("CC BY 4.0 · by Zed");                          // attribution shown when required
    expect(second).toHaveAttribute("aria-pressed", "true");
    expect(video!.currentTime).toBeGreaterThan(4);                                   // clicking a clip also moves the playhead there
    fireEvent.pointerDown(document.querySelector('[data-clip="scene-1"]')!, { clientX: 100, button: 0, pointerId: 1 });
    expect(within(screen.getByLabelText("Selected clip")).getByText("first scene")).toBeInTheDocument();
    expect(screen.getByLabelText("Selected clip")).toHaveTextContent("(repeats)");
  });

  it("clips have accessible names with their timing", async () => {
    await open();
    expect(screen.getByRole("button", { name: /first scene, video clip, starts 00:00:00, lasts 00:05:00/ })).toBeInTheDocument();
  });

  it("draws a waveform for audio once its peaks are ready, and nothing before", async () => {
    vi.spyOn(api, "getMedia").mockResolvedValue([mediaItem("narration", [], "processing")]);
    const { unmount } = await open();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Preparing previews (1 left)"));
    expect(document.querySelectorAll("canvas")).toHaveLength(0);
    unmount();
    ctx.fillRect.mockClear();
    vi.spyOn(api, "getMedia").mockResolvedValue([mediaItem("narration", ["audio", "peaks"])]);
    await open();
    await waitFor(() => expect(document.querySelectorAll("canvas")).toHaveLength(1));
    await waitFor(() => expect(ctx.fillRect).toHaveBeenCalled());
    expect(api.getPeaks).toHaveBeenCalledWith("p1", "narration");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows filmstrip thumbnails for prepared video and the picture for stills", async () => {
    await open();
    await waitFor(() => expect(document.querySelectorAll(".tl-tile").length).toBeGreaterThan(0));
    const tile = document.querySelector(".tl-tile") as HTMLElement;
    expect(tile.style.backgroundImage).toContain("/api/projects/p1/media/film?asset=pix%3A1");
    const still = document.querySelector('[data-clip="scene-2"] .tl-image') as HTMLElement;
    expect(still.style.backgroundImage).toContain("/api/projects/p1/media/proxy?asset=pix%3A2");
  });

  it("only builds what is on screen, however many clips there are", async () => {
    const many: TimelineClip[] = Array.from({ length: 600 }, (_, i) => clip({ id: `c${i}`, track: "C1", kind: "caption", start: i * 30, duration: 24, text: `caption ${i}` }));
    vi.spyOn(api, "getTimeline").mockResolvedValue(timeline({ duration: 600 * 30, clips: many }));
    vi.spyOn(api, "getMedia").mockResolvedValue([]);
    await open();
    // the whole 10-minute timeline is fitted into the view, so zoom in and scroll far away: still only a handful exist
    await userEvent.click(screen.getByLabelText("Zoom in"));
    for (let i = 0; i < 8; i++) await userEvent.click(screen.getByLabelText("Zoom in"));
    const area = screen.getByLabelText(/Timeline tracks/);
    area.scrollLeft = 20000;
    fireEvent.scroll(area);
    await waitFor(() => expect(document.querySelectorAll("[data-clip]").length).toBeLessThan(80));
    expect(document.querySelectorAll("[data-clip]").length).toBeGreaterThan(0);
  });

  it("explains errors and the loading state", async () => {
    vi.spyOn(api, "getTimeline").mockRejectedValue(new Error("The project is not ready yet"));
    render(<Timeline projectId="p1" version="v1" video={null} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("not ready yet");
  });

  it("works without a player (it keeps its own position)", async () => {
    await open(null);
    expect(screen.getByRole("button", { name: "Play" })).toBeDisabled();
    const area = screen.getByLabelText(/Timeline tracks/);
    area.focus();
    await userEvent.keyboard("{ArrowRight}{ArrowRight}{ArrowRight}");
    expect(screen.getByLabelText("Playhead position")).toHaveTextContent("00:00:03");
  });
});

describe("useTimelineData", () => {
  it("polls the media until everything is prepared, then stops", async () => {
    const get = vi.spyOn(api, "getMedia")
      .mockResolvedValueOnce([mediaItem("a", [], "processing")])
      .mockResolvedValueOnce([mediaItem("a", [], "processing")])
      .mockResolvedValue([mediaItem("a", ["proxy"], "ready")]);
    const { result } = renderHook(() => useTimelineData("p1", "v1", true, 5));
    await waitFor(() => expect(result.current.media["a"]?.status).toBe("ready"));
    const calls = get.mock.calls.length;
    expect(result.current.preparing).toBe(0);
    await new Promise((r) => setTimeout(r, 60));
    expect(get.mock.calls.length).toBe(calls);
  });

  it("reloads the document when the version changes, and does nothing while disabled", async () => {
    const t = vi.spyOn(api, "getTimeline");
    const { rerender } = renderHook(({ v, on }) => useTimelineData("p1", v, on, 5), { initialProps: { v: "1", on: false } });
    await new Promise((r) => setTimeout(r, 20));
    expect(t).not.toHaveBeenCalled();
    rerender({ v: "1", on: true });
    await waitFor(() => expect(t).toHaveBeenCalledTimes(1));
    rerender({ v: "2", on: true });
    await waitFor(() => expect(t).toHaveBeenCalledTimes(2));
  });
});
