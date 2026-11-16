import { describe, expect, it } from "vitest";
import { formatTime, safeHref } from "./format";

describe("formatTime", () => {
  it("formats minutes and tenths", () => {
    expect(formatTime(0)).toBe("0:00.0");
    expect(formatTime(4.25)).toBe("0:04.3");
    expect(formatTime(83.4)).toBe("1:23.4");
    expect(formatTime(600)).toBe("10:00.0");
    expect(formatTime(-3)).toBe("0:00.0");
  });
});

describe("safeHref", () => {
  it("allows http(s) only", () => {
    expect(safeHref("https://pixabay.com/videos/id-1/")).toBe("https://pixabay.com/videos/id-1/");
    expect(safeHref("http://example.org/a")).toBe("http://example.org/a");
  });
  it("refuses script, data, file and garbage URLs", () => {
    for (const bad of ["javascript:alert(1)", "data:text/html,<script>1</script>", "file:///etc/passwd", "not a url", ""]) {
      expect(safeHref(bad)).toBeUndefined();
    }
  });
});
