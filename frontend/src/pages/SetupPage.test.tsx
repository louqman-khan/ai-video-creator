import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SetupPage } from "./SetupPage";

const status = (over = {}) => ({
  ffmpeg: true, keys: { gemini_api_key: false, pixabay_api_key: false },
  models: { whisper: false, whisper_model: "small", rnnoise: false, clip: false },
  whisper_sizes_mb: { tiny: 75, small: 465 }, download: { running: false, message: "", error: null }, data_dir: "/data", ...over,
});
const json = (b: unknown, code = 200) => new Response(JSON.stringify(b), { status: code, headers: { "Content-Type": "application/json" } });
afterEach(() => vi.restoreAllMocks());

describe("SetupPage", () => {
  it("saves keys without ever showing them and starts the download", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      if (String(url).endsWith("/keys")) return json(status({ keys: { gemini_api_key: true, pixabay_api_key: false } }));
      if (String(url).endsWith("/models")) return json(status({ download: { running: false, message: "", error: "Download failed: HTTP 503" } }));
      return json(status());
    });
    render(<MemoryRouter><SetupPage /></MemoryRouter>);
    const box = await screen.findByLabelText(/Gemini API key/);
    expect(box).toHaveAttribute("type", "password");
    await userEvent.type(box, "AIzaKEYKEYKEY1");
    await userEvent.click(screen.getByRole("button", { name: "Save keys" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Saved."));
    expect(screen.getByText(/A key is saved/)).toBeInTheDocument();
    const put = f.mock.calls.find((c) => String(c[0]).endsWith("/keys"))![1] as RequestInit;
    expect(put.body).toBe(JSON.stringify({ gemini_api_key: "AIzaKEYKEYKEY1" }));
    await userEvent.click(screen.getByRole("button", { name: "Download models" }));
    expect(await screen.findByText("Download failed: HTTP 503")).toBeInTheDocument();
  });
});
