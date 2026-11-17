import { describe, expect, it } from "vitest";
import { despill, hexToRgb, keyAlpha, keyImageData, rgbToHex, spillChannel } from "./chromakey";

const green = { color: "#00ff00", similarity: 0.15, blend: 0.1, despill: false };

describe("chroma key maths (measured against ffmpeg's chromakey / despill)", () => {
  it("keeps what is far from the key colour and removes what is close", () => {
    expect(keyAlpha(0, 255, 0, green)).toBe(0);
    expect(keyAlpha(30, 230, 30, green)).toBe(0);
    expect(keyAlpha(255, 0, 0, green)).toBe(1);
    expect(keyAlpha(0, 0, 255, green)).toBe(1);
  });
  it("blends in the soft edge like ffmpeg does (grey is 45/255 opaque at match 0.15, soft edge 0.1)", () => {
    expect(keyAlpha(128, 128, 128, green)).toBeCloseTo(45 / 255, 1);
    expect(keyAlpha(128, 128, 128, { ...green, blend: 0 })).toBe(1);        // a hard edge is all or nothing
    expect(keyAlpha(100, 200, 100, { ...green, blend: 0 })).toBe(0);        // (ffmpeg: transparent)
  });
  it("works for a blue screen", () => {
    const blue = { ...green, color: "#0000ff" };
    expect(keyAlpha(0, 0, 255, blue)).toBe(0);
    expect(keyAlpha(0, 255, 0, blue)).toBe(1);
  });
  it("despill limits the key's channel to the mean of the other two", () => {
    expect(despill(200, 230, 100, "green")).toEqual([200, 150, 100]);
    expect(despill(100, 150, 200, "green")).toEqual([100, 150, 200]);       // nothing to remove
    expect(despill(50, 100, 200, "blue")).toEqual([50, 100, 75]);
    expect(spillChannel("#00ff00")).toBe("green");
    expect(spillChannel("#2020ff")).toBe("blue");
    expect(spillChannel("#ff0000")).toBeNull();                              // only green and blue screens
  });
  it("keys a whole image in place", () => {
    const px = new Uint8ClampedArray([0, 255, 0, 255, 255, 0, 0, 255, 200, 230, 100, 255]);
    keyImageData(px, { ...green, despill: true });
    expect([px[3], px[7]]).toEqual([0, 255]);                               // green gone, red kept
    expect(px[9]).toBe(150);                                                 // the tinted pixel lost its green spill
  });
  it("hex helpers round trip", () => {
    expect(hexToRgb("#1e90ff")).toEqual([30, 144, 255]);
    expect(rgbToHex(30, 144, 255)).toBe("#1e90ff");
  });
});
