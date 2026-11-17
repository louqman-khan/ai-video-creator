import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { StoragePanel } from "./StoragePanel";

const usage = (reclaimable: number) => ({
  items: [{ key: "stock", label: "Downloaded stock media", bytes: 300e6, reclaimable }, { key: "projects", label: "Projects", bytes: 70e6, reclaimable: 0 }],
  total: 370e6, reclaimable,
});
beforeEach(() => vi.restoreAllMocks());

describe("StoragePanel", () => {
  it("shows the use and frees space on request", async () => {
    const storage = vi.spyOn(api, "storage").mockResolvedValueOnce(usage(20e6)).mockResolvedValue(usage(0));
    const clean = vi.spyOn(api, "cleanStorage").mockResolvedValue({ freed: 20e6, removed: 3 });
    render(<StoragePanel />);
    expect(await screen.findByText(/370 MB used, 20 MB can be freed/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Free up space" }));
    await waitFor(() => expect(clean).toHaveBeenCalled());
    expect(await screen.findByText("Freed 20 MB.")).toBeInTheDocument();
    expect(storage).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "Free up space" })).toBeDisabled();       // nothing left to free
  });
  it("shows nothing when the server cannot be asked", async () => {
    vi.spyOn(api, "storage").mockRejectedValue(new Error("down"));
    const { container } = render(<StoragePanel />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
