import { describe, expect, it } from "vitest";
import { DEFAULT_LIMITS } from "./api/client";
import { buildForm, DEFAULT_VALUES, formatSize, validateAudioFile, validateScript } from "./newProject";

const file = (name: string, bytes = 1000) => new File([new Uint8Array(bytes)], name);

describe("validateAudioFile", () => {
  it("accepts supported audio, case-insensitively", () => {
    expect(validateAudioFile(file("talk.mp3"), DEFAULT_LIMITS)).toBeNull();
    expect(validateAudioFile(file("TALK.M4A"), DEFAULT_LIMITS)).toBeNull();
  });
  it("rejects other types, missing extensions, empty and oversized files", () => {
    expect(validateAudioFile(file("notes.txt"), DEFAULT_LIMITS)).toMatch(/not a supported audio file/);
    expect(validateAudioFile(file("noextension"), DEFAULT_LIMITS)).toMatch(/not a supported/);
    expect(validateAudioFile(file("a.mp3", 0), DEFAULT_LIMITS)).toMatch(/empty/);
    const small = { ...DEFAULT_LIMITS, max_upload_mb: 1 };
    expect(validateAudioFile(file("a.mp3", 2 * 1024 * 1024), small)).toMatch(/limit is 1 MB/);
  });
  it("uses the limits the server reported", () => {
    const only = { ...DEFAULT_LIMITS, extensions: [".wav"] };
    expect(validateAudioFile(file("a.mp3"), only)).not.toBeNull();
    expect(validateAudioFile(file("a.wav"), only)).toBeNull();
  });
});

describe("validateScript / formatSize", () => {
  it("limits script length", () => {
    expect(validateScript("x".repeat(10), DEFAULT_LIMITS)).toBeNull();
    expect(validateScript("x".repeat(DEFAULT_LIMITS.max_script_chars + 1), DEFAULT_LIMITS)).toMatch(/too long/);
  });
  it("formats sizes", () => {
    expect(formatSize(500)).toBe("1 KB");
    expect(formatSize(3 * 1024)).toBe("3 KB");
    expect(formatSize(5.5 * 1024 * 1024)).toBe("5.5 MB");
  });
});

describe("buildForm", () => {
  it("sends the fields the API expects, booleans as strings", () => {
    const f = buildForm(file("a.mp3"), { ...DEFAULT_VALUES, language: "ur", aspect: "9:16", removeSilence: true, clean: false });
    expect(f.get("language")).toBe("ur");
    expect(f.get("aspect")).toBe("9:16");
    expect(f.get("remove_silence")).toBe("true");
    expect(f.get("clean")).toBe("false");
    expect(f.get("normalize")).toBe("true");
    expect(f.get("captions")).toBe("true");
    expect((f.get("file") as File).name).toBe("a.mp3");
  });
  it("omits empty name and script, keeps Urdu script text exactly", () => {
    const empty = buildForm(file("a.mp3"), { ...DEFAULT_VALUES, name: "  ", script: "   " });
    expect(empty.has("name")).toBe(false);
    expect(empty.has("script")).toBe(false);
    const urdu = "پاکستان کے پہاڑ۔";
    const f = buildForm(file("a.mp3"), { ...DEFAULT_VALUES, name: " دوست ", script: urdu });
    expect(f.get("script")).toBe(urdu);
    expect(f.get("name")).toBe("دوست");
  });
});
