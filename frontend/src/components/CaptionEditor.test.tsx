import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import type { CaptionsView, Project } from "../api/types";
import { CaptionEditor } from "./CaptionEditor";

const project = (over: Partial<Project> = {}): Project => ({
  id: "p1", name: "demo", status: "done", stage: "done", progress: 1, message: "", error: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:01Z", original_filename: "",
  language: "ur", aspect: "16:9", options: {}, video_ready: true, export_ready: false, export_aspect: null, ...over,
});
const captions = (over: Partial<CaptionsView> = {}): CaptionsView => ({
  cues: [
    { id: 0, start: 0, end: 2.5, text: "پاکستان کے پہاڑ" },
    { id: 1, start: 2.5, end: 5, text: "second caption" },
  ],
  edited: false, language: "ur", style: {}, ...over,
});
const jpeg = () => new Blob(["x"], { type: "image/jpeg" });

beforeEach(() => {
  vi.restoreAllMocks();
  URL.createObjectURL = vi.fn(() => "blob:preview");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(api, "getCaptions").mockResolvedValue(captions());
  vi.spyOn(api, "previewCaption").mockResolvedValue(jpeg());
});

const renderEditor = (props: Partial<Parameters<typeof CaptionEditor>[0]> = {}) =>
  render(<CaptionEditor project={project()} onChanged={vi.fn()} previewDebounceMs={0} {...props} />);

describe("CaptionEditor", () => {
  it("marks cues the recogniser was unsure about and can show only those", async () => {
    vi.spyOn(api, "getCaptions").mockResolvedValue(captions({ cues: [
      { id: 0, start: 0, end: 2.5, text: "sure caption", confidence: 0.95 },
      { id: 1, start: 2.5, end: 5, text: "doubtful caption", confidence: 0.31 },
    ] }));
    renderEditor();
    await screen.findByDisplayValue("doubtful caption");
    expect(screen.getAllByText(/please check/)).toHaveLength(1);
    await userEvent.click(screen.getByLabelText(/Show only the 1 cue to check/));
    expect(screen.queryByDisplayValue("sure caption")).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("doubtful caption")).toBeInTheDocument();
  });


  it("lists the captions with time ranges and shows a server-rendered preview of the first one", async () => {
    renderEditor();
    expect(await screen.findByDisplayValue("پاکستان کے پہاڑ")).toHaveAttribute("dir", "auto");
    expect(screen.getByText("0:00.0 – 0:02.5")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByAltText("Caption preview")).toHaveAttribute("src", "blob:preview"));
    expect(api.previewCaption).toHaveBeenCalledWith(
      "p1", expect.objectContaining({ cue_id: 0, text: "پاکستان کے پہاڑ", style: expect.objectContaining({ color: "#FFFFFF" }) }), expect.anything(),
    );
    expect(screen.getByRole("button", { name: "Apply and re-render" })).toBeDisabled(); // nothing changed yet
  });

  it("text edit: marks the caption, previews the new text, and sends every id with its text on Apply", async () => {
    const onChanged = vi.fn();
    const update = vi.spyOn(api, "updateCaptions").mockResolvedValue(project({ status: "queued" }));
    renderEditor({ onChanged });
    const box = await screen.findByDisplayValue("second caption");
    await userEvent.clear(box);
    await userEvent.type(box, "fixed text");
    expect(screen.getByText(/2.5.*· edited/)).toBeInTheDocument();
    await waitFor(() => expect(api.previewCaption).toHaveBeenLastCalledWith("p1", expect.objectContaining({ cue_id: 1, text: "fixed text" }), expect.anything()));
    await userEvent.click(screen.getByRole("button", { name: "Apply and re-render" }));
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
    expect(update.mock.calls[0]![1]).toEqual({ cues: [{ id: 0, text: "پاکستان کے پہاڑ" }, { id: 1, text: "fixed text" }] }); // no style
    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ status: "queued" }));
  });

  it("style-only change sends just the style, and previews it live", async () => {
    const update = vi.spyOn(api, "updateCaptions").mockResolvedValue(project({ status: "queued" }));
    renderEditor();
    await screen.findByDisplayValue("second caption");
    fireEvent.change(screen.getByLabelText("Text colour"), { target: { value: "#ffff00" } });
    await userEvent.selectOptions(screen.getByLabelText("Position"), "top");
    await waitFor(() => expect(api.previewCaption).toHaveBeenLastCalledWith("p1", expect.objectContaining({ style: expect.objectContaining({ color: "#FFFF00", position: "top" }) }), expect.anything()));
    await userEvent.click(screen.getByRole("button", { name: "Apply and re-render" }));
    await waitFor(() => expect(update).toHaveBeenCalled());
    const body = update.mock.calls[0]![1];
    expect(body.cues).toBeUndefined();
    expect(body.style).toMatchObject({ color: "#FFFF00", position: "top" });
  });

  it("clicking into another caption previews that caption", async () => {
    renderEditor();
    await userEvent.click(await screen.findByDisplayValue("second caption"));
    await waitFor(() => expect(api.previewCaption).toHaveBeenLastCalledWith("p1", expect.objectContaining({ cue_id: 1 }), expect.anything()));
  });

  it("cancels an outdated preview request when a newer one starts", async () => {
    const signals: AbortSignal[] = [];
    vi.spyOn(api, "previewCaption").mockImplementation((_id, _b, signal) => {
      signals.push(signal!);
      return new Promise(() => undefined); // never answers
    });
    renderEditor();
    const box = await screen.findByDisplayValue("second caption");
    await waitFor(() => expect(signals.length).toBe(1));
    await userEvent.type(box, "!"); // focusing selects caption 2 (request 2), then the typed text (request 3)
    await waitFor(() => expect(signals.length).toBe(3));
    expect(signals.slice(0, -1).every((x) => x.aborted)).toBe(true); // every outdated request was cancelled
    expect(signals[signals.length - 1]!.aborted).toBe(false);          // only the newest stays alive
  });

  it("Undo changes restores the original text and disables Apply", async () => {
    renderEditor();
    const box = await screen.findByDisplayValue("second caption");
    await userEvent.type(box, " more");
    expect(screen.getByRole("button", { name: "Apply and re-render" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Undo changes" }));
    expect(screen.getByDisplayValue("second caption")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply and re-render" })).toBeDisabled();
  });

  it("after edits, words-per-line is locked and Reset is offered (with confirmation)", async () => {
    vi.spyOn(api, "getCaptions").mockResolvedValue(captions({ edited: true }));
    const reset = vi.spyOn(api, "resetCaptions").mockResolvedValue(project({ status: "queued" }));
    vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderEditor();
    await screen.findByDisplayValue("second caption");
    expect(screen.getByLabelText("Words per line")).toBeDisabled();
    const button = screen.getByRole("button", { name: "Reset text edits" });
    await userEvent.click(button);
    expect(reset).not.toHaveBeenCalled();
    await userEvent.click(button);
    await waitFor(() => expect(reset).toHaveBeenCalledWith("p1"));
  });

  it("does not offer Reset for unedited captions and keeps words-per-line editable", async () => {
    renderEditor();
    await screen.findByDisplayValue("second caption");
    expect(screen.queryByRole("button", { name: "Reset text edits" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Words per line")).toBeEnabled();
  });

  it("is read-only while the project is processing", async () => {
    renderEditor({ project: project({ status: "running" }) });
    await new Promise((r) => setTimeout(r, 20));
    expect(api.getCaptions).not.toHaveBeenCalled(); // not loaded until the project is done
  });

  it("shows the server's message if Apply fails, and lets the user try again", async () => {
    vi.spyOn(api, "updateCaptions").mockRejectedValue(new ApiError("The captions changed since you opened the editor. Reload the page.", 409));
    renderEditor();
    await userEvent.type(await screen.findByDisplayValue("second caption"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Apply and re-render" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Reload the page");
    expect(screen.getByRole("button", { name: "Apply and re-render" })).toBeEnabled();
  });

  it("shows load errors and preview errors", async () => {
    vi.spyOn(api, "getCaptions").mockRejectedValueOnce(new Error("The captions are not ready yet"));
    const { unmount } = renderEditor();
    expect(await screen.findByRole("alert")).toHaveTextContent("not ready yet");
    unmount();
    vi.spyOn(api, "getCaptions").mockResolvedValue(captions());
    vi.spyOn(api, "previewCaption").mockRejectedValue(new ApiError("The preview could not be rendered", 500));
    renderEditor();
    expect(await screen.findByText("The preview could not be rendered")).toBeInTheDocument();
  });

  it("an emptied caption cannot be previewed but the rest of the editor keeps working", async () => {
    renderEditor();
    const box = await screen.findByDisplayValue("second caption");
    await userEvent.clear(box);
    expect(await screen.findByText("Type some text to preview.")).toBeInTheDocument();
  });
});
