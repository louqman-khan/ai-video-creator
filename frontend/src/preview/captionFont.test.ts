import { describe, expect, it } from "vitest";
import { captionFontStack } from "./engine";

describe("live caption font", () => {
  it("uses the font chosen in the caption style first and keeps the Urdu defaults behind it", () => {
    expect(captionFontStack("Gulzar")).toBe('"Gulzar", "Noto Nastaliq Urdu", "Jameel Noori Nastaleeq", system-ui, sans-serif');
  });
  it("is the Urdu defaults when no font is chosen", () => {
    for (const none of [undefined, null, "", "   ", 42]) expect(captionFontStack(none)).toBe('"Noto Nastaliq Urdu", "Jameel Noori Nastaleeq", system-ui, sans-serif');
  });
  it("cannot be used to break out of the font string", () => {
    expect(captionFontStack('Evil"; color: red; {')).toBe('"Evil color: red", "Noto Nastaliq Urdu", "Jameel Noori Nastaleeq", system-ui, sans-serif');
  });
});
