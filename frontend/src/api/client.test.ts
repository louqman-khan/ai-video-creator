import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./client";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.restoreAllMocks());

describe("api client", () => {
  it("returns parsed JSON and encodes ids in URLs", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ id: "a" }));
    await api.getProject("a/b ?");
    expect(f).toHaveBeenCalledWith("/api/projects/a%2Fb%20%3F", undefined);
  });

  it("turns FastAPI string and validation errors into readable messages", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json({ detail: "Unsupported file type '.txt'" }, 415));
    await expect(api.listProjects()).rejects.toMatchObject({ message: "Unsupported file type '.txt'", status: 415 });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json({ detail: [{ msg: "bad a" }, { msg: "bad b" }] }, 422));
    await expect(api.listProjects()).rejects.toThrow("bad a; bad b");
  });

  it("falls back to a generic message for non-JSON errors", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("<html>oops</html>", { status: 502 }));
    await expect(api.listProjects()).rejects.toThrow("Request failed (502)");
  });

  it("explains when the server is not running", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const err = await api.listProjects().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toMatch(/avc serve/);
    expect(err.status).toBe(0);
  });

  it("handles 204 (delete) without a body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
    await expect(api.deleteProject("x")).resolves.toBeUndefined();
  });
});
