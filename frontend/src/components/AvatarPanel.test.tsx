import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import type { Project } from "../api/types";
import { AvatarPanel } from "./AvatarPanel";

const project = (over: Partial<Project> = {}): Project => ({
  id: "p1", name: "demo", status: "done", stage: "done", progress: 1, message: "", error: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:01Z", original_filename: "",
  language: null, aspect: "16:9", options: {}, video_ready: true, export_ready: false, export_aspect: null, ...over,
});
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "avatars").mockResolvedValue([{ id: "sara", name: "Sara" }, { id: "ali", name: "Ali" }]);
});

describe("AvatarPanel", () => {
  it("lets the user pick an avatar, a corner and a size, and starts the job", async () => {
    const add = vi.spyOn(api, "addAvatar").mockResolvedValue(project({ status: "queued" }));
    const onStarted = vi.fn();
    render(<AvatarPanel project={project()} onStarted={onStarted} />);
    await userEvent.click(await screen.findByText("Talking avatar"));
    expect(screen.getAllByRole("radio")).toHaveLength(2);
    expect(screen.getByLabelText(/Sara/)).toBeChecked();                       // the first one is chosen
    await userEvent.click(screen.getByLabelText(/Ali/));
    await userEvent.selectOptions(screen.getByLabelText("Corner"), "top-left");
    await userEvent.click(screen.getByRole("button", { name: "Add avatar to the video" }));
    await waitFor(() => expect(add).toHaveBeenCalledWith("p1", { avatar: "ali", corner: "top-left", size: 0.3 }));
    expect(onStarted).toHaveBeenCalledWith(expect.objectContaining({ status: "queued" }));
  });
  it("is disabled while the project is processing and shows the server's problem", async () => {
    const { rerender } = render(<AvatarPanel project={project({ status: "running" })} onStarted={vi.fn()} />);
    await userEvent.click(await screen.findByText("Talking avatar"));
    expect(screen.getByRole("button", { name: "Add avatar to the video" })).toBeDisabled();
    vi.spyOn(api, "addAvatar").mockRejectedValue(new ApiError("The video is not ready yet", 409));
    rerender(<AvatarPanel project={project()} onStarted={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Add avatar to the video" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not ready");
  });
  it("shows nothing when no avatar is available", async () => {
    vi.spyOn(api, "avatars").mockResolvedValue([]);
    const { container } = render(<AvatarPanel project={project()} onStarted={vi.fn()} />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
