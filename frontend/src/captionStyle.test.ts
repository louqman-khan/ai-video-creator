import { describe, expect, it } from "vitest";
import { DEFAULT_STYLE, sameStyle, toForm, toPayload } from "./captionStyle";

describe("caption style helpers", () => {
  it("fills a partial stored style with defaults", () => {
    expect(toForm({ color: "#FFFF00" })).toEqual({ ...DEFAULT_STYLE, color: "#FFFF00" });
    expect(toForm({})).toEqual(DEFAULT_STYLE);
  });
  it("omits font and size when automatic, includes them when set", () => {
    expect(toPayload(DEFAULT_STYLE)).not.toHaveProperty("font");
    expect(toPayload(DEFAULT_STYLE)).not.toHaveProperty("size_pct");
    expect(toPayload({ ...DEFAULT_STYLE, font: "  Arial ", size_pct: 8 })).toMatchObject({ font: "Arial", size_pct: 8 });
    expect(toPayload({ ...DEFAULT_STYLE, font: "   " })).not.toHaveProperty("font");
  });
  it("compares styles ignoring unset/blank automatic fields", () => {
    expect(sameStyle(DEFAULT_STYLE, { ...DEFAULT_STYLE, font: "" })).toBe(true);
    expect(sameStyle(DEFAULT_STYLE, { ...DEFAULT_STYLE, bold: true })).toBe(false);
  });
});
